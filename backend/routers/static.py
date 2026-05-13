"""
backend/routers/static.py
--------------------------
POST /api/static/image
POST /api/static/video
GET  /api/static/video/{job_id}/status
GET  /api/static/video/{job_id}/result
"""

from __future__ import annotations

import base64
import os
import tempfile

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image

from backend.schemas.models import (
    Detection,
    FrameResult,
    ImageAnalysisResponse,
    VideoJobResponse,
    VideoJobResultResponse,
    VideoJobStatusResponse,
)
from backend.services.analyzer import AnalyzerService, get_analyzer_service
from backend.services.job_manager import JobManager, get_job_manager

router = APIRouter(prefix="/api/static")

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg"}
_ALLOWED_VIDEO_TYPES = {"video/mp4", "video/avi", "video/quicktime", "video/x-msvideo"}


# ---- Image ----

@router.post("/image", response_model=ImageAnalysisResponse)
async def analyze_image(
    file: UploadFile = File(...),
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    data = await file.read()
    if len(data) > 50 * 1024 * 1024:  # 50 MB limit
        raise HTTPException(status_code=413, detail="File too large")

    # バイト列 → OpenCV フレーム
    import numpy as np
    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Failed to decode image")

    # YOLO 検出
    annotated, results = svc.detector.detect(frame)

    detections: list[Detection] = []
    for box in results[0].boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        label = svc.detector.model.names.get(cls_id, str(cls_id))
        detections.append(
            Detection(
                class_id=cls_id,
                label=label,
                confidence=round(conf, 4),
                bbox=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            )
        )

    # VLM 解析（同期）
    vlm_result = ""
    if svc.analyzer._model is not None:
        try:
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            prompt_ja = svc.get_prompt()
            try:
                prompt_en = svc.analyzer.translator_ja_en.translate(prompt_ja)
            except Exception:
                prompt_en = prompt_ja
            answer_en = svc.analyzer._model.infer(img, prompt_en)
            try:
                vlm_result = svc.analyzer.translator_en_ja.translate(answer_en)
            except Exception:
                vlm_result = answer_en
        except Exception as e:
            vlm_result = f"[Error] {e}"

    # アノテーション済み画像を base64 に変換
    _, buf = cv2.imencode(".jpg", annotated)
    img_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

    return ImageAnalysisResponse(
        annotated_image=img_b64,
        detections=detections,
        vlm_result=vlm_result,
        detection_count=len(detections),
    )


# ---- Video ----

@router.post("/video", status_code=202, response_model=VideoJobResponse)
async def submit_video(
    file: UploadFile = File(...),
    svc: AnalyzerService = Depends(get_analyzer_service),
    jm: JobManager = Depends(get_job_manager),
):
    if file.content_type not in _ALLOWED_VIDEO_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported video type")

    data = await file.read()
    if len(data) > 500 * 1024 * 1024:  # 500 MB limit
        raise HTTPException(status_code=413, detail="File too large")

    # 一時ファイルに保存
    suffix = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()

    job_id = jm.create_job()
    jm.start_video_processing(
        job_id=job_id,
        video_path=tmp.name,
        detector=svc.detector,
        analyzer=svc.analyzer,
    )

    return VideoJobResponse(job_id=job_id, status="queued")


@router.get("/video/{job_id}/status", response_model=VideoJobStatusResponse)
async def get_video_status(
    job_id: str,
    jm: JobManager = Depends(get_job_manager),
):
    job = jm.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return VideoJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
    )


@router.get("/video/{job_id}/result", response_model=VideoJobResultResponse)
async def get_video_result(
    job_id: str,
    jm: JobManager = Depends(get_job_manager),
):
    job = jm.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    frames = [FrameResult(**f) for f in job.frames]
    return VideoJobResultResponse(
        job_id=job.job_id,
        status=job.status,
        frames=frames,
    )
