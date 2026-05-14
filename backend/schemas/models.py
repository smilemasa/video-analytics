"""
backend/schemas/models.py
--------------------------
Pydantic スキーマ定義。
"""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel


# ---- System ----

class HealthResponse(BaseModel):
    status: str


class ModelsResponse(BaseModel):
    models: List[str]


# ---- Settings ----

class ModelStatusResponse(BaseModel):
    model_id: str
    status: str  # "loaded" | "loading" | "error"


class ModelSwitchRequest(BaseModel):
    model_id: str


class YoloClassesResponse(BaseModel):
    mode: str
    classes: List[int]


class YoloClassesRequest(BaseModel):
    mode: str
    classes: List[int]


class PromptResponse(BaseModel):
    prompt: str


class PromptRequest(BaseModel):
    prompt: str


# ---- Static ----

class Detection(BaseModel):
    class_id: int
    label: str
    confidence: float
    bbox: List[float]  # [x1, y1, x2, y2]


class ImageAnalysisResponse(BaseModel):
    annotated_image: str  # base64
    detections: List[Detection]
    vlm_result: str
    detection_count: int


class VideoJobResponse(BaseModel):
    job_id: str
    status: str


class VideoJobStatusResponse(BaseModel):
    job_id: str
    status: str  # "queued" | "processing" | "done" | "error"
    progress: int  # 0-100


class FrameResult(BaseModel):
    timestamp: float
    annotated_image: str  # base64
    detections: List[Detection]
    vlm_result: str


class VideoJobResultResponse(BaseModel):
    job_id: str
    status: str
    frames: List[FrameResult]


# ---- Live ----

class CameraStatusResponse(BaseModel):
    active: bool
    source_type: Optional[str] = None   # "usb" | "rtsp" | "onvif"
    source_label: Optional[str] = None  # 表示用ラベル
    fps: Optional[int] = None


class CameraStartRequest(BaseModel):
    source_type: Literal["usb", "rtsp", "onvif"] = "usb"
    # USB
    camera_index: int = 0
    # RTSP
    rtsp_url: Optional[str] = None
    # ONVIF
    onvif_host: Optional[str] = None
    onvif_port: int = 80
    onvif_user: Optional[str] = None
    onvif_password: Optional[str] = None
    onvif_profile: int = 0


class CameraStartResponse(BaseModel):
    active: bool
    source_type: str
    source_label: str


class CameraStopResponse(BaseModel):
    active: bool
