"""
backend/routers/system.py
--------------------------
GET /api/health
GET /api/models
"""

from fastapi import APIRouter
from backend.schemas.models import HealthResponse, ModelsResponse
from backend.services.analyzer import AVAILABLE_MODELS

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}


@router.get("/api/models", response_model=ModelsResponse)
async def list_models():
    return {"models": AVAILABLE_MODELS}
