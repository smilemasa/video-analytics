"""
backend/routers/settings.py
-----------------------------
GET  /api/settings/model
POST /api/settings/model
GET  /api/settings/yolo-classes
POST /api/settings/yolo-classes
GET  /api/settings/prompt
PUT  /api/settings/prompt
"""

from fastapi import APIRouter, Depends, HTTPException
from backend.schemas.models import (
    ModelStatusResponse,
    ModelSwitchRequest,
    YoloClassesResponse,
    YoloClassesRequest,
    PromptResponse,
    PromptRequest,
)
from backend.services.analyzer import AnalyzerService, get_analyzer_service, AVAILABLE_MODELS

router = APIRouter(prefix="/api/settings")


# ---- Model ----

@router.get("/model", response_model=ModelStatusResponse)
async def get_model(svc: AnalyzerService = Depends(get_analyzer_service)):
    return svc.get_model_status()


@router.post("/model", response_model=ModelStatusResponse)
async def switch_model(
    req: ModelSwitchRequest,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    if req.model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model_id: {req.model_id}")
    svc.switch_model(req.model_id)
    return {"model_id": req.model_id, "status": "loading"}


# ---- YOLO classes ----

@router.get("/yolo-classes", response_model=YoloClassesResponse)
async def get_yolo_classes(svc: AnalyzerService = Depends(get_analyzer_service)):
    return svc.get_yolo_classes()


@router.post("/yolo-classes", response_model=YoloClassesResponse)
async def set_yolo_classes(
    req: YoloClassesRequest,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    svc.set_yolo_classes(req.mode, req.classes)
    return {"mode": req.mode, "classes": req.classes}


# ---- Prompt ----

@router.get("/prompt", response_model=PromptResponse)
async def get_prompt(svc: AnalyzerService = Depends(get_analyzer_service)):
    return {"prompt": svc.get_prompt()}


@router.put("/prompt", response_model=PromptResponse)
async def set_prompt(
    req: PromptRequest,
    svc: AnalyzerService = Depends(get_analyzer_service),
):
    svc.set_prompt(req.prompt)
    return {"prompt": svc.get_prompt()}
