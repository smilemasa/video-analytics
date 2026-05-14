"""
backend/main.py
----------------
FastAPI エントリポイント。
起動コマンド: uvicorn backend.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import system, settings, static, live, security

app = FastAPI(title="Video Analytics API", version="1.0.0")

# CORS 設定（開発環境用: 全オリジン許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(system.router)
app.include_router(settings.router)
app.include_router(static.router)
app.include_router(live.router)
app.include_router(security.router)
