"""
backend/routers/live.py
------------------------
WebSocket /ws/live
GET  /api/live/camera/status
POST /api/live/camera/start
POST /api/live/camera/stop
GET  /api/live/camera/stream  (SSE)
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import time
from typing import AsyncGenerator

import cv2
import numpy as np
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from PIL import Image

from backend.schemas.models import (
    CameraStartRequest,
    CameraStartResponse,
    CameraStatusResponse,
    CameraStopResponse,
)
from backend.services.analyzer import AnalyzerService, get_analyzer_service

router = APIRouter()


# ---- サーバーカメラ状態管理 ----

class CameraManager:
    def __init__(self):
        self.active = False
        self.camera_index = 0
        self.fps = 30
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest_frame: bytes | None = None  # JPEG bytes
        self._latest_detections: list = []
        self._latest_vlm: str = ""
        self._stop_event = threading.Event()

    def start(self, camera_index: int, svc: AnalyzerService) -> None:
        with self._lock:
            if self.active:
                return
            self._stop_event.clear()
            self.camera_index = camera_index
            self.active = True

        self._thread = threading.Thread(
            target=self._capture_loop, args=(camera_index, svc), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self.active = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def get_latest(self) -> tuple[bytes | None, list, str]:
        return self._latest_frame, self._latest_detections, self._latest_vlm

    def _capture_loop(self, camera_index: int, svc: AnalyzerService) -> None:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            self.active = False
            return

        interval = 1.0 / self.fps

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            annotated, results = svc.detector.detect(frame)

            detections = []
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                label = svc.detector.model.names.get(cls_id, str(cls_id))
                detections.append({
                    "class_id": cls_id,
                    "label": label,
                    "confidence": round(conf, 4),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                })

            _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
            self._latest_frame = buf.tobytes()
            self._latest_detections = detections

            # VLM 結果は非同期ワーカーが更新したものを利用
            svc.analyzer.push_frame(frame)
            self._latest_vlm = svc.analyzer.get_latest_result()

            time.sleep(interval)

        cap.release()
        self.active = False


_camera_manager = CameraManager()


# ---- Camera endpoints ----

@router.get("/api/live/camera/status", response_model=CameraStatusResponse)
async def camera_status():
    m = _camera_manager
    if m.active:
        return CameraStatusResponse(active=True, camera_index=m.camera_index, fps=m.fps)
    return CameraStatusResponse(active=False)


@router.post("/api/live/camera/start", response_model=CameraStartResponse)
async def camera_start(
    req: CameraStartRequest,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    _camera_manager.start(req.camera_index, svc)
    return CameraStartResponse(active=True, camera_index=req.camera_index)


@router.post("/api/live/camera/stop", response_model=CameraStopResponse)
async def camera_stop():
    _camera_manager.stop()
    return CameraStopResponse(active=False)


# ---- SSE stream ----

@router.get("/api/live/camera/stream")
async def camera_stream(svc: AnalyzerService = Depends(get_analyzer_service)):
    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            frame_bytes, detections, vlm = _camera_manager.get_latest()
            if frame_bytes:
                img_b64 = base64.b64encode(frame_bytes).decode("utf-8")
                payload = json.dumps({
                    "annotated_image": img_b64,
                    "detections": detections,
                    "vlm_result": vlm,
                })
                yield f"data: {payload}\n\n"
            await asyncio.sleep(1.0 / 15)  # ~15 fps

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- WebSocket /ws/live ----

@router.websocket("/ws/live")
async def websocket_live(
    websocket: WebSocket,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    await websocket.accept()
    frame_times: list[float] = []

    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)

            frame_b64 = data.get("frame", "")
            if not frame_b64:
                continue

            # base64 デコード → OpenCV フレーム
            img_bytes = base64.b64decode(frame_b64)
            nparr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            # YOLO 検出
            annotated, results = svc.detector.detect(frame)

            detections = []
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                label = svc.detector.model.names.get(cls_id, str(cls_id))
                detections.append({
                    "class_id": cls_id,
                    "label": label,
                    "confidence": round(conf, 4),
                    "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                })

            # VLM (非同期ワーカー経由)
            svc.analyzer.push_frame(frame)
            vlm_result = svc.analyzer.get_latest_result()

            # FPS 計算
            now = time.time()
            frame_times.append(now)
            frame_times = [t for t in frame_times if now - t < 5.0]
            fps = len(frame_times) / 5.0 if len(frame_times) > 1 else 0.0

            # アノテーション済み画像を base64 に変換
            _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
            img_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")

            await websocket.send_text(json.dumps({
                "annotated_image": img_b64,
                "detections": detections,
                "vlm_result": vlm_result,
                "fps": round(fps, 1),
            }))

    except WebSocketDisconnect:
        pass
