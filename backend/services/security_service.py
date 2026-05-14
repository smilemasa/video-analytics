"""
backend/services/security_service.py
--------------------------------------
SecurityPipeline のシングルトンラッパー。
AnalyzerService から VLMAnalyzer を借用する。
"""

from __future__ import annotations

import base64
import os
import threading

import cv2
import numpy as np
import yaml

from backend.security import SecurityPipeline, PipelineState
from backend.security.static_analyzer import (
    SecurityStaticAnalyzer,
    SecurityImageResult,
    SecurityVideoJob,
)
from backend.schemas.security_models import (
    SecurityPipelineStateResponse,
    SecurityDetection,
    SecurityDistance,
    TriggerEventSchema,
    ActiveConditionSchema,
    ValidatedOutputSchema,
    ScoringResultSchema,
    LatencyInfoSchema,
    OfflineResultSchema,
    SecurityConfigResponse,
    SecurityImageAnalysisResponse,
    SecurityVideoJobStatusResponse,
    SecurityVideoJobResultResponse,
    SecurityVideoEventSchema,
)

_CFG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "security.yaml",
)


def _load_cfg() -> dict:
    with open(_CFG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class SecurityService:
    """アプリケーション全体で共有するセキュリティ検知サービス。"""

    def __init__(self, detector, vlm_analyzer):
        self._pipeline = SecurityPipeline(detector=detector, vlm_analyzer=vlm_analyzer)
        self._static_analyzer = SecurityStaticAnalyzer(
            model_name="yolov8n.pt",
            vlm_analyzer=vlm_analyzer,
            cfg=_load_cfg(),
        )
        # オフライン解析結果を SSE ストリームに乗せるためのスロット
        self._latest_offline: OfflineResultSchema | None = None
        self._offline_lock = threading.Lock()

    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray) -> PipelineState:
        return self._pipeline.process_frame(frame)

    def get_state(self) -> PipelineState:
        return self._pipeline.get_state()

    def get_config(self) -> SecurityConfigResponse:
        cfg = self._pipeline.get_config()
        return SecurityConfigResponse(**cfg)

    def update_config(
        self,
        threshold: int | None = None,
        distance_threshold_m: float | None = None,
        stay_duration_sec: float | None = None,
    ) -> SecurityConfigResponse:
        self._pipeline.update_config(
            threshold=threshold,
            distance_threshold_m=distance_threshold_m,
            stay_duration_sec=stay_duration_sec,
        )
        return self.get_config()

    def stop(self) -> None:
        self._pipeline.stop()

    # ------------------------------------------------------------------
    # 静止画解析

    def analyze_image(self, frame: np.ndarray) -> SecurityImageAnalysisResponse:
        result = self._static_analyzer.analyze_image(frame)
        # デバッグビュー用にオフラインスロットを更新
        with self._offline_lock:
            self._latest_offline = self._build_offline_from_image_result(result)
        return self._image_result_to_response(result)

    def _image_result_to_response(self, r: SecurityImageResult) -> SecurityImageAnalysisResponse:
        _, buf = cv2.imencode(".jpg", r.annotated_image, [cv2.IMWRITE_JPEG_QUALITY, 75])
        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        detections = [
            SecurityDetection(
                track_id=d.track_id, class_id=d.class_id, class_name=d.class_name,
                bbox=d.bbox, confidence=d.confidence, owner_excluded=d.owner_excluded,
            )
            for d in r.detections
        ]
        distances = [
            SecurityDistance(
                person_track_id=di.person_track_id,
                vehicle_track_id=di.vehicle_track_id,
                distance_m=di.distance_m,
            )
            for di in r.distances
        ]
        vlm = None
        if r.vlm_result:
            v = r.vlm_result
            vlm = ValidatedOutputSchema(label=v.label, reason=v.reason, is_fallback=v.is_fallback, raw_output=v.raw_output)
        scoring = None
        if r.scoring:
            s = r.scoring
            scoring = ScoringResultSchema(
                risk_score=s.risk_score, behavior_score=s.behavior_score,
                context_score=s.context_score, persistence_score=s.persistence_score,
                action=s.action, label=s.label, reason=s.reason,  # type: ignore[arg-type]
            )
        return SecurityImageAnalysisResponse(
            annotated_image=b64, detections=detections, distances=distances,
            vlm_result=vlm, scoring=scoring,
        )

    # ------------------------------------------------------------------
    # 動画解析ジョブ

    def create_video_job(self) -> str:
        return self._static_analyzer.create_video_job()

    def start_video_job(self, job_id: str, video_path: str) -> None:
        def _video_event_callback(event, jid: str, total_events: int):
            """SecurityVideoEvent 発火時にオフラインスロットを更新する。"""
            with self._offline_lock:
                self._latest_offline = self._build_offline_from_video_event(
                    event, jid, total_events
                )

        self._static_analyzer.start_video_job(
            job_id, video_path, result_callback=_video_event_callback
        )

    def get_video_job_status(self, job_id: str) -> SecurityVideoJobStatusResponse:
        job = self._static_analyzer.get_job(job_id)
        if job is None:
            return SecurityVideoJobStatusResponse(job_id=job_id, status="not_found", progress=0)
        return SecurityVideoJobStatusResponse(
            job_id=job.job_id, status=job.status, progress=job.progress, error=job.error
        )

    def get_video_job_result(self, job_id: str) -> SecurityVideoJobResultResponse:
        job = self._static_analyzer.get_job(job_id)
        if job is None:
            return SecurityVideoJobResultResponse(
                job_id=job_id, status="not_found", events=[],
                total_frames_processed=0, notify_count=0,
            )
        events = []
        for ev in job.events:
            t = ev.trigger
            v = ev.vlm_result
            s = ev.scoring
            ann_b64 = None
            if ev.annotated_frame is not None:
                _, buf = cv2.imencode(".jpg", ev.annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                ann_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
            events.append(SecurityVideoEventSchema(
                frame_id=ev.frame_id,
                timestamp_sec=ev.timestamp_sec,
                trigger=TriggerEventSchema(
                    person_track_id=t.person_track_id, vehicle_track_id=t.vehicle_track_id,
                    distance_m=t.distance_m, stay_duration_sec=t.stay_duration_sec,
                    triggered_at=t.triggered_at, repeat_count=t.repeat_count,
                ),
                vlm_result=ValidatedOutputSchema(
                    label=v.label, reason=v.reason, is_fallback=v.is_fallback, raw_output=v.raw_output,
                ),
                scoring=ScoringResultSchema(
                    risk_score=s.risk_score, behavior_score=s.behavior_score,
                    context_score=s.context_score, persistence_score=s.persistence_score,
                    action=s.action, label=s.label, reason=s.reason,  # type: ignore[arg-type]
                ),
                annotated_image=ann_b64,
            ))
        return SecurityVideoJobResultResponse(
            job_id=job.job_id, status=job.status, events=events,
            total_frames_processed=job.total_frames_processed,
            notify_count=job.notify_count, error=job.error,
        )

    # ------------------------------------------------------------------
    # オフライン結果ビルダー

    def _build_offline_from_image_result(self, r: SecurityImageResult) -> OfflineResultSchema:
        """SecurityImageResult → OfflineResultSchema"""
        ann_b64 = None
        if r.annotated_image is not None:
            _, buf = cv2.imencode(".jpg", r.annotated_image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            ann_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        detections = [
            SecurityDetection(
                track_id=d.track_id, class_id=d.class_id, class_name=d.class_name,
                bbox=d.bbox, confidence=d.confidence, owner_excluded=d.owner_excluded,
            )
            for d in r.detections
        ]
        distances = [
            SecurityDistance(
                person_track_id=di.person_track_id,
                vehicle_track_id=di.vehicle_track_id,
                distance_m=di.distance_m,
            )
            for di in r.distances
        ]
        vlm = None
        if r.vlm_result:
            v = r.vlm_result
            vlm = ValidatedOutputSchema(label=v.label, reason=v.reason, is_fallback=v.is_fallback, raw_output=v.raw_output)
        scoring = None
        if r.scoring:
            s = r.scoring
            scoring = ScoringResultSchema(
                risk_score=s.risk_score, behavior_score=s.behavior_score,
                context_score=s.context_score, persistence_score=s.persistence_score,
                action=s.action, label=s.label, reason=s.reason,  # type: ignore[arg-type]
            )
        return OfflineResultSchema(
            source="image",
            annotated_image=ann_b64,
            detections=detections,
            distances=distances,
            vlm_result=vlm,
            scoring=scoring,
        )

    def _build_offline_from_video_event(self, ev, job_id: str, total_events: int) -> OfflineResultSchema:
        """SecurityVideoEvent → OfflineResultSchema"""
        ann_b64 = None
        if ev.annotated_frame is not None:
            _, buf = cv2.imencode(".jpg", ev.annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            ann_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        t = ev.trigger
        v = ev.vlm_result
        s = ev.scoring
        return OfflineResultSchema(
            source="video",
            job_id=job_id,
            annotated_image=ann_b64,
            detections=[],  # フレーム内の全検出は trigger に湬約されるため省略
            distances=[SecurityDistance(
                person_track_id=t.person_track_id,
                vehicle_track_id=t.vehicle_track_id,
                distance_m=t.distance_m,
            )],
            vlm_result=ValidatedOutputSchema(
                label=v.label, reason=v.reason, is_fallback=v.is_fallback, raw_output=v.raw_output
            ) if v else None,
            scoring=ScoringResultSchema(
                risk_score=s.risk_score, behavior_score=s.behavior_score,
                context_score=s.context_score, persistence_score=s.persistence_score,
                action=s.action, label=s.label, reason=s.reason,  # type: ignore[arg-type]
            ) if s else None,
            timestamp_sec=ev.timestamp_sec,
            frame_id=ev.frame_id,
            total_events=total_events,
        )

    # ------------------------------------------------------------------

    def to_response(self, state: PipelineState) -> SecurityPipelineStateResponse:
        """PipelineState → Pydantic レスポンスモデルへ変換。"""
        fd = state.frame_data

        detections = []
        distances = []
        annotated_b64 = None

        if fd is not None:
            for d in fd.detections:
                detections.append(SecurityDetection(
                    track_id=d.track_id,
                    class_id=d.class_id,
                    class_name=d.class_name,
                    bbox=d.bbox,
                    confidence=d.confidence,
                    owner_excluded=d.owner_excluded,
                ))
            for dist in fd.distances:
                distances.append(SecurityDistance(
                    person_track_id=dist.person_track_id,
                    vehicle_track_id=dist.vehicle_track_id,
                    distance_m=dist.distance_m,
                ))
            if fd.annotated_frame is not None:
                _, buf = cv2.imencode(".jpg", fd.annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                annotated_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

        active_conditions = [
            ActiveConditionSchema(**c) for c in state.active_conditions
        ]
        active_triggers = [
            TriggerEventSchema(
                person_track_id=t.person_track_id,
                vehicle_track_id=t.vehicle_track_id,
                distance_m=t.distance_m,
                stay_duration_sec=t.stay_duration_sec,
                triggered_at=t.triggered_at,
                repeat_count=t.repeat_count,
            )
            for t in state.active_triggers
        ]

        latest_vlm = None
        if state.latest_vlm_output is not None:
            v = state.latest_vlm_output
            latest_vlm = ValidatedOutputSchema(
                label=v.label,
                reason=v.reason,
                is_fallback=v.is_fallback,
                raw_output=v.raw_output,
            )

        latest_scoring = None
        if state.latest_scoring is not None:
            s = state.latest_scoring
            latest_scoring = ScoringResultSchema(
                risk_score=s.risk_score,
                behavior_score=s.behavior_score,
                context_score=s.context_score,
                persistence_score=s.persistence_score,
                action=s.action,  # type: ignore[arg-type]
                label=s.label,
                reason=s.reason,
            )

        scoring_history = [
            ScoringResultSchema(
                risk_score=s.risk_score,
                behavior_score=s.behavior_score,
                context_score=s.context_score,
                persistence_score=s.persistence_score,
                action=s.action,  # type: ignore[arg-type]
                label=s.label,
                reason=s.reason,
            )
            for s in state.scoring_history
        ]

        return SecurityPipelineStateResponse(
            timestamp_ms=state.timestamp_ms,
            detections=detections,
            distances=distances,
            active_conditions=active_conditions,
            active_triggers=active_triggers,
            owner_candidates=state.owner_candidates,
            latest_vlm=latest_vlm,
            latest_scoring=latest_scoring,
            latest_latency=(
                LatencyInfoSchema(
                    trigger_at_ms=state.latest_latency.trigger_at_ms,
                    submitted_at_ms=state.latest_latency.submitted_at_ms,
                    vlm_start_ms=state.latest_latency.vlm_start_ms,
                    vlm_end_ms=state.latest_latency.vlm_end_ms,
                    scoring_at_ms=state.latest_latency.scoring_at_ms,
                    queue_wait_ms=state.latest_latency.queue_wait_ms,
                    vlm_latency_ms=state.latest_latency.vlm_latency_ms,
                    total_latency_ms=state.latest_latency.total_latency_ms,
                )
                if state.latest_latency is not None else None
            ),
            scoring_history=scoring_history,
            annotated_image=annotated_b64,
            latest_offline=self._latest_offline,
        )


# --------------------------------------------------------------------------
# シングルトン

_security_service: SecurityService | None = None


def get_security_service() -> SecurityService:
    global _security_service
    if _security_service is None:
        from backend.services.analyzer import get_analyzer_service
        svc = get_analyzer_service()
        _security_service = SecurityService(
            detector=svc.detector,
            vlm_analyzer=svc.analyzer,
        )
    return _security_service
