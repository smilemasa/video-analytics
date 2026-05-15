"""
backend/routers/live.py
------------------------
WebSocket /ws/live          … ブラウザカメラ (既存)
GET  /api/live/camera/status
POST /api/live/camera/start  … USB / RTSP / ONVIF
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
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse

import sys
import glob
from backend.schemas.models import (
    CameraStartRequest,
    CameraStartResponse,
    CameraStatusResponse,
    CameraStopResponse,
    CameraListResponse,
    CameraInfo,
)
from backend.services.analyzer import AnalyzerService, get_analyzer_service

router = APIRouter()


# ---- ONVIF ヘルパー ----

def _resolve_onvif_rtsp(
    host: str,
    port: int,
    user: str,
    password: str,
    profile_index: int,
) -> str:
    """ONVIF カメラに接続し RTSP ストリーム URI を返す。"""
    try:
        from onvif import ONVIFCamera  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "ONVIF サポートには onvif-zeep パッケージが必要です: "
            "pip install onvif-zeep"
        ) from exc

    cam = ONVIFCamera(host, port, user, password)
    media = cam.create_media_service()
    profiles = media.GetProfiles()
    if not profiles:
        raise RuntimeError("ONVIF プロファイルが見つかりません")
    idx = min(profile_index, len(profiles) - 1)
    token = profiles[idx].token
    stream_setup = {
        "StreamSetup": {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        },
        "ProfileToken": token,
    }
    stream_uri = media.GetStreamUri(stream_setup)
    rtsp_url: str = stream_uri.Uri
    # 認証情報を URL に埋め込む (rtsp://user:pass@host/...)
    if user and password and "@" not in rtsp_url:
        rtsp_url = rtsp_url.replace("rtsp://", f"rtsp://{user}:{password}@", 1)
    return rtsp_url


# ---- サーバーカメラ状態管理 ----

class CameraManager:
    def __init__(self):
        self.active = False
        self.fps = 15
        self.source_type: str = "usb"
        self.source_label: str = ""
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest_frame: bytes | None = None
        self._latest_detections: list = []
        self._latest_vlm: str = ""
        self._stop_event = threading.Event()
        self._error: str | None = None

    # --- public API ---

    def start(self, req: CameraStartRequest, svc: AnalyzerService) -> None:
        with self._lock:
            if self.active:
                return
            self._stop_event.clear()
            self._error = None
            self.active = True
            self.source_type = req.source_type

        try:
            capture_src: int | str
            if req.source_type == "usb":
                capture_src = req.camera_index
                self.source_label = f"USB カメラ #{req.camera_index}"
            elif req.source_type == "rtsp":
                if not req.rtsp_url:
                    raise ValueError("RTSP URL が指定されていません")
                capture_src = req.rtsp_url
                self.source_label = req.rtsp_url
            elif req.source_type == "onvif":
                if not req.onvif_host:
                    raise ValueError("ONVIF ホストが指定されていません")
                capture_src = _resolve_onvif_rtsp(
                    req.onvif_host,
                    req.onvif_port,
                    req.onvif_user or "",
                    req.onvif_password or "",
                    req.onvif_profile,
                )
                self.source_label = f"ONVIF {req.onvif_host} (→ {capture_src})"
            else:
                raise ValueError(f"不明な source_type: {req.source_type}")
        except Exception as exc:
            with self._lock:
                self.active = False
                self._error = str(exc)
            raise

        self._thread = threading.Thread(
            target=self._capture_loop, args=(capture_src, svc), daemon=True
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

    @property
    def error(self) -> str | None:
        return self._error

    # --- 内部キャプチャループ ---

    def _capture_loop(self, src: int | str, svc: AnalyzerService) -> None:
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            with self._lock:
                self.active = False
                self._error = f"カメラを開けませんでした: {src}"
            return

        interval = 1.0 / self.fps
        
        # SecurityService にもフレームを流すため取得
        from backend.services.security_service import get_security_service
        sec_svc = get_security_service()

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

            svc.analyzer.push_frame(frame)
            self._latest_vlm = svc.analyzer.get_latest_result()
            
            # Security Dashboard 向けに Security Pipeline にもフレームを投入
            sec_svc.process_frame(frame)

            time.sleep(interval)

        cap.release()
        with self._lock:
            self.active = False


_camera_manager = CameraManager()


# ---- Camera endpoints ----

@router.get("/api/live/camera/list", response_model=CameraListResponse)
async def camera_list():
    cameras = []
    if sys.platform.startswith("linux"):
        devices = glob.glob("/dev/video*")
        for dev in sorted(devices):
            try:
                idx = int(dev.replace("/dev/video", ""))
                # We do not try to open them via cv2 here because it can cause crashes or warnings.
                # Just listing `/dev/video*` is usually enough on Linux to show available devices.
                cameras.append(CameraInfo(index=idx, label=f"USB Camera {idx} ({dev})"))
            except ValueError:
                pass
    else:
        for i in range(4):
            cameras.append(CameraInfo(index=i, label=f"Camera {i}"))
    
    # Also add "Default (0)" just in case
    if not cameras:
        cameras.append(CameraInfo(index=0, label="Default Camera 0"))

    return CameraListResponse(cameras=cameras)


@router.get("/api/live/camera/status", response_model=CameraStatusResponse)
async def camera_status():
    m = _camera_manager
    if m.active:
        return CameraStatusResponse(
            active=True,
            source_type=m.source_type,
            source_label=m.source_label,
            fps=m.fps,
        )
    return CameraStatusResponse(active=False)


@router.post("/api/live/camera/start", response_model=CameraStartResponse)
async def camera_start(
    req: CameraStartRequest,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    _camera_manager.start(req, svc)
    # Wait briefly to catch immediate open errors
    await asyncio.sleep(0.5)
    if _camera_manager.error:
        raise HTTPException(status_code=400, detail=_camera_manager.error)
        
    return CameraStartResponse(
        active=True,
        source_type=_camera_manager.source_type,
        source_label=_camera_manager.source_label,
    )


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


# ---- WebSocket /ws/live (ブラウザカメラ) ----

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
