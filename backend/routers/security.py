"""
backend/routers/security.py
-----------------------------
セキュリティ検知 API エンドポイント。

ライブ:
  GET  /api/security/status          … 最新パイプライン状態 (1件)
  GET  /api/security/debug/stream    … SSE リアルタイムデバッグ配信
  GET  /api/security/config          … 設定取得
  PUT  /api/security/config          … 設定更新

オフライン解析:
  POST /api/security/analyze/image                       … 静止画解析（同期）
  POST /api/security/analyze/video                       … 動画解析ジョブ登録
  GET  /api/security/analyze/video/{job_id}/status       … ジョブ状態
  GET  /api/security/analyze/video/{job_id}/result       … ジョブ結果
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import numpy as np
import cv2
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from backend.schemas.security_models import (
    SecurityPipelineStateResponse,
    SecurityConfigResponse,
    SecurityConfigRequest,
    SecurityImageAnalysisResponse,
    SecurityVideoJobResponse,
    SecurityVideoJobStatusResponse,
    SecurityVideoJobResultResponse,
)
from backend.services.security_service import SecurityService, get_security_service

router = APIRouter()

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg"}
_ALLOWED_VIDEO_TYPES = {"video/mp4", "video/avi", "video/quicktime", "video/x-msvideo"}
_MAX_FILE_BYTES = 200 * 1024 * 1024  # 200 MB


# ---- ライブ: 最新状態 ----

@router.get("/api/security/status", response_model=SecurityPipelineStateResponse)
async def security_status(svc: SecurityService = Depends(get_security_service)):
    state = svc.get_state()
    return svc.to_response(state)


# ---- ライブ: SSE デバッグストリーム ----

@router.get("/api/security/debug/stream")
async def security_debug_stream(svc: SecurityService = Depends(get_security_service)):
    async def event_generator():
        while True:
            state = svc.get_state()
            payload = svc.to_response(state).model_dump_json()
            yield f"data: {payload}\n\n"
            await asyncio.sleep(1.0 / 15)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- 設定 ----

@router.get("/api/security/config", response_model=SecurityConfigResponse)
async def get_config(svc: SecurityService = Depends(get_security_service)):
    return svc.get_config()


@router.put("/api/security/config", response_model=SecurityConfigResponse)
async def update_config(
    req: SecurityConfigRequest,
    svc: SecurityService = Depends(get_security_service),
):
    return svc.update_config(
        threshold=req.threshold,
        distance_threshold_m=req.distance_threshold_m,
        stay_duration_sec=req.stay_duration_sec,
    )


# ---- オフライン: 静止画解析 ----

@router.post("/api/security/analyze/image", response_model=SecurityImageAnalysisResponse)
async def analyze_image(
    file: UploadFile = File(...),
    svc: SecurityService = Depends(get_security_service),
):
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    nparr = np.frombuffer(data, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Failed to decode image")

    return svc.analyze_image(frame)


# ---- オフライン: 動画解析ジョブ ----

@router.post("/api/security/analyze/video", response_model=SecurityVideoJobResponse)
async def analyze_video(
    file: UploadFile = File(...),
    svc: SecurityService = Depends(get_security_service),
):
    if file.content_type not in _ALLOWED_VIDEO_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported video type")

    data = await file.read()
    if len(data) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    suffix = os.path.splitext(file.filename or ".mp4")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    job_id = svc.create_video_job()
    svc.start_video_job(job_id, tmp_path)
    return SecurityVideoJobResponse(job_id=job_id, status="queued")


@router.get("/api/security/analyze/video/{job_id}/status", response_model=SecurityVideoJobStatusResponse)
async def video_job_status(
    job_id: str,
    svc: SecurityService = Depends(get_security_service),
):
    return svc.get_video_job_status(job_id)


@router.get("/api/security/analyze/video/{job_id}/result", response_model=SecurityVideoJobResultResponse)
async def video_job_result(
    job_id: str,
    svc: SecurityService = Depends(get_security_service),
):
    result = svc.get_video_job_result(job_id)
    if result.status == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    return result
