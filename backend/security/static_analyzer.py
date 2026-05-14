"""
backend/security/static_analyzer.py
--------------------------------------
オフライン解析エンジン。

画像 (1 フレーム) または動画ファイルを入力とし、
セキュリティ検知ロジックをオフラインで実行する。

ライブカメラ用の SecurityPipeline とは独立したインスタンスを使用し、
tracker の状態やスコアリング履歴が干渉しないようにする。
"""

from __future__ import annotations

import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO

from .continuous_processor import (
    DetectionItem,
    DistanceItem,
    FrameData,
    _bbox_bottom_center,
    _pixel_distance,
)
from .output_validator import ValidatedOutput, validate_vlm_output
from .owner_exclusion import OwnerExclusionJudge
from .scorer import Scorer, ScoringResult
from .trigger_judge import TriggerEvent, TriggerJudge


# --------------------------------------------------------------------------
# 結果データクラス
# --------------------------------------------------------------------------

@dataclass
class SecurityImageResult:
    annotated_image: np.ndarray
    detections: list[DetectionItem]
    distances: list[DistanceItem]
    vlm_result: ValidatedOutput | None
    scoring: ScoringResult | None


@dataclass
class SecurityVideoEvent:
    frame_id: int
    timestamp_sec: float
    trigger: TriggerEvent
    vlm_result: ValidatedOutput
    scoring: ScoringResult
    annotated_frame: np.ndarray | None


@dataclass
class SecurityVideoJob:
    job_id: str
    status: str = "queued"       # queued | processing | done | error
    progress: int = 0            # 0-100
    events: list[SecurityVideoEvent] = field(default_factory=list)
    total_frames_processed: int = 0
    notify_count: int = 0
    error: str | None = None


# --------------------------------------------------------------------------
# メインクラス
# --------------------------------------------------------------------------

class SecurityStaticAnalyzer:
    """
    画像・動画ファイルに対してセキュリティ検知ロジックを実行する。

    ライブパイプラインとは独立した YOLO インスタンスを使用するため、
    tracker 状態の干渉が発生しない。
    """

    def __init__(self, model_name: str, vlm_analyzer, cfg: dict):
        print("[SecurityStaticAnalyzer] Loading dedicated offline YOLO model...")
        self._yolo = YOLO(model_name)
        self._vlm = vlm_analyzer
        self._cfg = cfg

        det = cfg.get("detection", {})
        scr = cfg.get("scoring", {})
        bsc = cfg.get("behavior_scores", {})
        self._prompt = cfg.get("vlm_prompt_template", "")
        self._person_classes = set(det.get("target_classes", {}).get("person", [0]))
        self._vehicle_classes = set(det.get("target_classes", {}).get("vehicle", [2, 3, 5, 7]))
        self._security_classes = list(self._person_classes | self._vehicle_classes)
        self._confidence_min = det.get("confidence_min", 0.5)
        self._pixels_per_meter: float | None = det.get("pixels_per_meter")

        # pixels_per_meter 未設定時はピクセル閾値を使う
        trg = cfg.get("trigger", {})
        self._dist_threshold = (
            trg.get("distance_threshold_m", 3.0)
            if self._pixels_per_meter
            else trg.get("distance_threshold_px", 200)
        )
        self._stay_duration = trg.get("stay_duration_sec", 2.0)

        self._scorer = Scorer(
            threshold=scr.get("threshold", 70),
            behavior_scores=bsc if bsc else None,
            night_start_hour=scr.get("night_start_hour", 22),
            night_end_hour=scr.get("night_end_hour", 6),
            twilight1_start=scr.get("twilight1_start_hour", 18),
            twilight1_end=scr.get("twilight1_end_hour", 22),
            twilight2_start=scr.get("twilight2_start_hour", 5),
            twilight2_end=scr.get("twilight2_end_hour", 7),
            recent_event_window_hours=scr.get("recent_event_window_hours", 24),
        )

        self._jobs: dict[str, SecurityVideoJob] = {}
        self._jobs_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 画像解析
    # ------------------------------------------------------------------

    def analyze_image(self, frame: np.ndarray) -> SecurityImageResult:
        """
        単一フレームを解析して結果を返す。
        トリガー判定は行わず、person が検出された場合は VLM を直接実行する。
        """
        annotated, detections, distances = self._detect_frame_once(
            frame, frame_id=0, timestamp_ms=int(time.time() * 1000)
        )

        has_person = any(d.class_name == "person" for d in detections)
        vlm_result = None
        scoring = None

        if has_person:
            raw = self._run_vlm(frame)
            vlm_result = validate_vlm_output(raw)
            dummy_trigger = TriggerEvent(
                person_track_id=0,
                vehicle_track_id=0,
                distance_m=0.0,
                stay_duration_sec=0.0,
                triggered_at=int(time.time() * 1000),
                repeat_count=0,
            )
            scoring = self._scorer.calculate(vlm_result, dummy_trigger)

        return SecurityImageResult(
            annotated_image=annotated,
            detections=detections,
            distances=distances,
            vlm_result=vlm_result,
            scoring=scoring,
        )

    # ------------------------------------------------------------------
    # 動画解析（非同期ジョブ）
    # ------------------------------------------------------------------

    def create_video_job(self) -> str:
        job_id = str(uuid.uuid4())[:8]
        with self._jobs_lock:
            self._jobs[job_id] = SecurityVideoJob(job_id=job_id)
        return job_id

    def start_video_job(
        self,
        job_id: str,
        video_path: str,
        target_fps: float = 10.0,
        result_callback=None,
    ) -> None:
        """バックグラウンドスレッドで動画解析を開始する。

        result_callback: callable(SecurityVideoEvent) | None
            各トリガーイベント発火時に呼び出されるコールバック。
            SecurityService が SSE スロットをリアルタイム更新するのに使用。
        """
        t = threading.Thread(
            target=self._process_video,
            args=(job_id, video_path, target_fps, result_callback),
            daemon=True,
            name=f"sec-video-{job_id}",
        )
        t.start()

    def get_job(self, job_id: str) -> SecurityVideoJob | None:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # 内部: 動画処理ループ
    # ------------------------------------------------------------------

    def _process_video(
        self, job_id: str, video_path: str, target_fps: float, result_callback=None
    ) -> None:
        job = self.get_job(job_id)
        if job is None:
            return

        job.status = "processing"

        # ビデオタイムスタンプを時刻として使う (オフライン精度のため)
        current_vtime: list[float] = [0.0]
        time_fn = lambda: current_vtime[0]  # noqa: E731

        own_judge = OwnerExclusionJudge(
            proximity_threshold_m=self._cfg.get("owner_exclusion", {}).get("proximity_threshold_m", 1.5),
            detection_window_sec=self._cfg.get("owner_exclusion", {}).get("detection_window_sec", 10.0),
            exclusion_duration_sec=self._cfg.get("owner_exclusion", {}).get("exclusion_duration_sec", 300.0),
            time_fn=time_fn,
        )
        trg_judge = TriggerJudge(
            distance_threshold_m=self._dist_threshold,
            stay_duration_sec=self._stay_duration,
            time_fn=time_fn,
        )

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                job.status = "error"
                job.error = "Failed to open video file"
                return

            video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            step = max(1, round(video_fps / target_fps))
            estimated_steps = max(1, total_frames // step)

            frame_idx = 0
            processed = 0

            while True:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp_sec = frame_idx / video_fps
                current_vtime[0] = timestamp_sec
                timestamp_ms = int(timestamp_sec * 1000)

                fd = self._build_frame_data(frame, frame_idx, timestamp_ms)
                fd = own_judge.update(fd)
                new_triggers = trg_judge.update(fd)

                for trig in new_triggers:
                    raw = self._run_vlm(frame)
                    vlm_out = validate_vlm_output(raw)
                    scoring = self._scorer.calculate(
                        vlm_out, trig, now=datetime.fromtimestamp(timestamp_sec + time.time() - timestamp_sec)
                    )
                    job.events.append(SecurityVideoEvent(
                        frame_id=frame_idx,
                        timestamp_sec=round(timestamp_sec, 3),
                        trigger=trig,
                        vlm_result=vlm_out,
                        scoring=scoring,
                        annotated_frame=fd.annotated_frame,
                    ))
                    if scoring.action == "notify":
                        job.notify_count += 1
                    # コールバックでデバッグビューをリアルタイム更新
                    if result_callback is not None:
                        try:
                            result_callback(job.events[-1], job_id, len(job.events))
                        except Exception:
                            pass

                processed += 1
                job.total_frames_processed = processed
                if total_frames > 0:
                    job.progress = min(int(processed / estimated_steps * 100), 99)

                frame_idx += step

            cap.release()
            job.progress = 100
            job.status = "done"

        except Exception as exc:
            job.status = "error"
            job.error = str(exc)
        finally:
            try:
                os.unlink(video_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # 内部: フレーム検出ヘルパー (画像用: tracking state なし)
    # ------------------------------------------------------------------

    def _detect_frame_once(
        self, frame: np.ndarray, frame_id: int, timestamp_ms: int
    ) -> tuple[np.ndarray, list[DetectionItem], list[DistanceItem]]:
        """tracker state を持ち越さない単一フレーム検出。"""
        results = self._yolo(frame, classes=self._security_classes, verbose=False)
        annotated = results[0].plot()
        detections, distances = self._parse_results(results, frame_id, timestamp_ms, use_track_id=False)
        return annotated, detections, distances

    # ------------------------------------------------------------------
    # 内部: フレーム検出ヘルパー (動画用: ByteTrack)
    # ------------------------------------------------------------------

    def _build_frame_data(
        self, frame: np.ndarray, frame_idx: int, timestamp_ms: int
    ) -> FrameData:
        """ByteTrack を使った検出 + FrameData 構築。"""
        results = self._yolo.track(
            frame,
            classes=self._security_classes,
            tracker="bytetrack.yaml",
            persist=True,
            verbose=False,
        )
        annotated = results[0].plot()
        detections, distances = self._parse_results(results, frame_idx, timestamp_ms, use_track_id=True)
        return FrameData(
            frame_id=frame_idx,
            timestamp_ms=timestamp_ms,
            detections=detections,
            distances=distances,
            raw_frame=frame,
            annotated_frame=annotated,
        )

    def _parse_results(
        self,
        results,
        frame_id: int,
        timestamp_ms: int,
        use_track_id: bool,
    ) -> tuple[list[DetectionItem], list[DistanceItem]]:
        detections: list[DetectionItem] = []
        boxes = results[0].boxes

        if boxes is None:
            return detections, []

        has_ids = use_track_id and boxes.id is not None

        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i])
            conf = float(boxes.conf[i])
            if conf < self._confidence_min:
                continue
            if cls_id in self._person_classes:
                cls_name = "person"
            elif cls_id in self._vehicle_classes:
                cls_name = "vehicle"
            else:
                continue

            tid = int(boxes.id[i]) if has_ids else (frame_id * 1000 + i)
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()
            detections.append(DetectionItem(
                track_id=tid,
                class_id=cls_id,
                class_name=cls_name,
                bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                confidence=round(conf, 4),
                owner_excluded=False,
            ))

        persons = [d for d in detections if d.class_name == "person"]
        vehicles = [d for d in detections if d.class_name == "vehicle"]
        distances: list[DistanceItem] = []
        for p in persons:
            for v in vehicles:
                try:
                    pc = _bbox_bottom_center(p.bbox)
                    vc = _bbox_bottom_center(v.bbox)
                    px_dist = _pixel_distance(pc, vc)
                    dist_m = (
                        px_dist / self._pixels_per_meter
                        if self._pixels_per_meter
                        else px_dist
                    )
                    distances.append(DistanceItem(
                        person_track_id=p.track_id,
                        vehicle_track_id=v.track_id,
                        distance_m=round(dist_m, 3),
                    ))
                except Exception:
                    distances.append(DistanceItem(
                        person_track_id=p.track_id,
                        vehicle_track_id=v.track_id,
                        distance_m=None,
                    ))
        return detections, distances

    # ------------------------------------------------------------------
    # 内部: VLM 同期呼び出し
    # ------------------------------------------------------------------

    def _run_vlm(self, frame: np.ndarray) -> str:
        try:
            model = self._vlm._model
            if model is None:
                return '{"label": "unknown_behavior", "reason": "VLM model not loaded"}'
            pil = Image.fromarray(frame[..., ::-1])  # BGR → RGB
            result = model.infer(pil, self._prompt)
            return result or '{"label": "unknown_behavior", "reason": "empty response"}'
        except Exception as exc:
            return f'{{"label": "unknown_behavior", "reason": "infer error: {exc}"}}'
