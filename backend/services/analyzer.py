"""
backend/services/analyzer.py
------------------------------
VLMAnalyzer と YoloDetector のシングルトンラッパー。
アプリケーション全体で単一インスタンスを共有する。
"""

from __future__ import annotations

import sys
import os

# プロジェクトルートを Python パスに追加
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from vlm_analyzer import VLMAnalyzer
from yolo_detector import YoloDetector
from models import MODEL_REGISTRY

AVAILABLE_MODELS = list(MODEL_REGISTRY.keys())

# YOLO 検出モードの定義（mode_name -> classes）
YOLO_MODES: dict[str, list[int] | None] = {
    "Person":    [0],
    "Vehicles":  [2, 3, 5, 7],
    "Animals":   [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
    "Furniture": [56, 57, 58, 59, 60, 61, 62, 72],
    "All":       None,
}


class AnalyzerService:
    """アプリケーション全体で共有する解析サービス。"""

    def __init__(self):
        self._detector = YoloDetector(model_name="yolov8n.pt", target_classes=[0])
        self._analyzer = VLMAnalyzer(model_id=AVAILABLE_MODELS[0])
        self._analyzer.start()

        self._yolo_mode = "Person"
        self._yolo_classes = [0]

    # ---- VLM ----

    @property
    def analyzer(self) -> VLMAnalyzer:
        return self._analyzer

    def get_model_status(self) -> dict:
        status_raw = self._analyzer.state.get("status", "")
        if "Loading" in status_raw or "Switching" in status_raw:
            status = "loading"
        elif "Error" in status_raw:
            status = "error"
        else:
            status = "loaded"
        return {"model_id": self._analyzer.model_id, "status": status}

    def switch_model(self, model_id: str) -> None:
        self._analyzer.set_model(model_id)

    # ---- Prompt ----

    def get_prompt(self) -> str:
        return self._analyzer.state.get("current_prompt", "")

    def set_prompt(self, prompt: str) -> None:
        self._analyzer.set_prompt(prompt)

    # ---- YOLO ----

    @property
    def detector(self) -> YoloDetector:
        return self._detector

    def get_yolo_classes(self) -> dict:
        return {"mode": self._yolo_mode, "classes": self._yolo_classes}

    def set_yolo_classes(self, mode: str, classes: list[int]) -> None:
        self._yolo_mode = mode
        self._yolo_classes = classes
        effective = classes if classes else None
        if effective is None:
            self._detector.set_classes(list(range(80)))
        else:
            self._detector.set_classes(effective)


# モジュールレベルのシングルトン（アプリ起動時に一度だけ生成）
_service: AnalyzerService | None = None


def get_analyzer_service() -> AnalyzerService:
    global _service
    if _service is None:
        _service = AnalyzerService()
    return _service
