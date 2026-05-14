"""
backend/schemas/security_models.py
------------------------------------
セキュリティ検知エンドポイント用 Pydantic スキーマ。
"""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel


# ---- 検出 ----

class SecurityDetection(BaseModel):
    track_id: int
    class_id: int
    class_name: str          # "person" | "vehicle"
    bbox: List[float]        # [x1, y1, x2, y2]
    confidence: float
    owner_excluded: bool


class SecurityDistance(BaseModel):
    person_track_id: int
    vehicle_track_id: int
    distance_m: Optional[float]  # None = 算出不能


# ---- トリガー ----

class TriggerEventSchema(BaseModel):
    person_track_id: int
    vehicle_track_id: int
    distance_m: float
    stay_duration_sec: float
    triggered_at: int        # epoch ms
    repeat_count: int


class ActiveConditionSchema(BaseModel):
    person_track_id: int
    vehicle_track_id: int
    stay_sec: float
    triggered: bool


# ---- VLM 出力 ----

class ValidatedOutputSchema(BaseModel):
    label: str
    reason: str
    is_fallback: bool
    raw_output: str


# ---- スコアリング ----

class ScoringResultSchema(BaseModel):
    risk_score: int
    behavior_score: int
    context_score: int
    persistence_score: int
    action: Literal["notify", "discard"]
    label: str
    reason: str


# ---- レイテンシ計測 ----

class LatencyInfoSchema(BaseModel):
    trigger_at_ms: int      # トリガー成立時刻 (epoch ms)
    submitted_at_ms: int    # VLM キュー投入時刻 (epoch ms)
    vlm_start_ms: int       # VLM 推論開始時刻 (epoch ms)
    vlm_end_ms: int         # VLM 推論完了時刻 (epoch ms)
    scoring_at_ms: int      # スコアリング完了時刻 (epoch ms)
    queue_wait_ms: int      # キュー待機時間 (ms)
    vlm_latency_ms: int     # VLM 推論時間 (ms)
    total_latency_ms: int   # トリガー〜スコアリング合計時間 (ms)


# ---- パイプライン状態 (SSE ペイロード) ----

class SecurityPipelineStateResponse(BaseModel):
    timestamp_ms: int
    detections: List[SecurityDetection]
    distances: List[SecurityDistance]
    active_conditions: List[ActiveConditionSchema]
    active_triggers: List[TriggerEventSchema]
    owner_candidates: List[int]
    latest_vlm: Optional[ValidatedOutputSchema]
    latest_scoring: Optional[ScoringResultSchema]
    latest_latency: Optional[LatencyInfoSchema]
    scoring_history: List[ScoringResultSchema]
    annotated_image: Optional[str]   # base64 JPEG (デバッグ表示用)
    latest_offline: Optional["OfflineResultSchema"] = None  # オフライン解析最新結果


# ---- 設定 ----

class SecurityConfigResponse(BaseModel):
    threshold: int
    distance_threshold_m: float
    stay_duration_sec: float


class SecurityConfigRequest(BaseModel):
    threshold: Optional[int] = None
    distance_threshold_m: Optional[float] = None
    stay_duration_sec: Optional[float] = None


# ---- オフライン解析結果 (デバッグビュー届け) ----

class OfflineResultSchema(BaseModel):
    source: str                          # "image" | "video"
    annotated_image: Optional[str]       # base64 JPEG
    detections: List[SecurityDetection]
    distances: List[SecurityDistance]
    vlm_result: Optional[ValidatedOutputSchema]
    scoring: Optional[ScoringResultSchema]
    # 動画用追加フィールド
    job_id: Optional[str] = None
    timestamp_sec: Optional[float] = None
    frame_id: Optional[int] = None
    total_events: Optional[int] = None   # 動画: 検知済みイベント数


# ---- 静止画解析 ----

class SecurityImageAnalysisResponse(BaseModel):
    annotated_image: str                    # base64 JPEG
    detections: List[SecurityDetection]
    distances: List[SecurityDistance]
    vlm_result: Optional[ValidatedOutputSchema]
    scoring: Optional[ScoringResultSchema]


# ---- 動画解析ジョブ ----

class SecurityVideoJobResponse(BaseModel):
    job_id: str
    status: str


class SecurityVideoJobStatusResponse(BaseModel):
    job_id: str
    status: str    # queued | processing | done | error
    progress: int  # 0-100
    error: Optional[str] = None


class SecurityVideoEventSchema(BaseModel):
    frame_id: int
    timestamp_sec: float
    trigger: TriggerEventSchema
    vlm_result: ValidatedOutputSchema
    scoring: ScoringResultSchema
    annotated_image: Optional[str]          # base64 JPEG


class SecurityVideoJobResultResponse(BaseModel):
    job_id: str
    status: str
    events: List[SecurityVideoEventSchema]
    total_frames_processed: int
    notify_count: int
    error: Optional[str] = None
