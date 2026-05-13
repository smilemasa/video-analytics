"""
backend/services/job_manager.py
---------------------------------
動画解析ジョブの管理。
バックグラウンドスレッドで動画を処理し、進捗と結果を保持する。
"""

from __future__ import annotations

import base64
import threading
import time
import uuid
from typing import Any

import cv2
import numpy as np
from PIL import Image


class VideoJob:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status: str = "queued"  # queued | processing | done | error
        self.progress: int = 0
        self.frames: list[dict] = []
        self.error: str | None = None


class JobManager:
    def __init__(self):
        self._jobs: dict[str, VideoJob] = {}
        self._lock = threading.Lock()

    def create_job(self) -> str:
        job_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._jobs[job_id] = VideoJob(job_id)
        return job_id

    def get_job(self, job_id: str) -> VideoJob | None:
        return self._jobs.get(job_id)

    def start_video_processing(
        self,
        job_id: str,
        video_path: str,
        detector,
        analyzer,
        frame_interval: float = 1.0,
    ) -> None:
        """バックグラウンドスレッドで動画を解析する。"""
        t = threading.Thread(
            target=self._process_video,
            args=(job_id, video_path, detector, analyzer, frame_interval),
            daemon=True,
        )
        t.start()

    def _process_video(
        self,
        job_id: str,
        video_path: str,
        detector,
        analyzer,
        frame_interval: float,
    ) -> None:
        job = self._jobs[job_id]
        job.status = "processing"

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                job.status = "error"
                job.error = "Failed to open video file"
                return

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            step = max(1, int(fps * frame_interval))

            frame_idx = 0
            processed = 0

            while True:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break

                timestamp = frame_idx / fps

                # YOLO 検出
                annotated, results = detector.detect(frame)

                # 検出結果の整形
                detections = []
                for box in results[0].boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    label = detector.model.names.get(cls_id, str(cls_id))
                    detections.append({
                        "class_id": cls_id,
                        "label": label,
                        "confidence": round(conf, 4),
                        "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                    })

                # VLM 解析（同期推論：ワーカースレッドは使わない）
                vlm_result = ""
                if analyzer._model is not None:
                    try:
                        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        prompt_ja = analyzer.state.get("current_prompt", "Describe this image.")
                        try:
                            prompt_en = analyzer.translator_ja_en.translate(prompt_ja)
                        except Exception:
                            prompt_en = prompt_ja
                        answer_en = analyzer._model.infer(img, prompt_en)
                        try:
                            vlm_result = analyzer.translator_en_ja.translate(answer_en)
                        except Exception:
                            vlm_result = answer_en
                    except Exception as e:
                        vlm_result = f"[Error] {e}"

                # アノテーション済み画像を base64 に変換
                _, buf = cv2.imencode(".jpg", annotated)
                img_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

                job.frames.append({
                    "timestamp": round(timestamp, 3),
                    "annotated_image": img_b64,
                    "detections": detections,
                    "vlm_result": vlm_result,
                })

                processed += 1
                frame_idx += step
                if total_frames > 0:
                    job.progress = min(99, int(frame_idx / total_frames * 100))

            cap.release()
            job.progress = 100
            job.status = "done"

        except Exception as e:
            job.status = "error"
            job.error = str(e)


# モジュールレベルのシングルトン
_job_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
