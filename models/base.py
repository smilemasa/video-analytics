"""
models/base.py
--------------
VLMモデルの抽象基底クラス。
全てのモデル実装はこのクラスを継承し、load() と infer() を実装する。
"""

from __future__ import annotations

import torch
from abc import ABC, abstractmethod
from PIL import Image


class VLMBase(ABC):
    """VLMモデルの共通インターフェース。"""

    # サブクラスで定義: HuggingFace の model_id 文字列
    MODEL_ID: str = ""

    def __init__(self, device: str | None = None):
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self.model = None

    # ------------------------------------------------------------------
    # 必須メソッド（サブクラスで実装）
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self) -> None:
        """モデルのロード処理。self.model 等を初期化する。"""
        ...

    @abstractmethod
    def infer(self, image: Image.Image, prompt: str) -> str:
        """
        画像とプロンプトを受け取り、推論結果の文字列を返す。

        Args:
            image: PIL.Image (RGB)
            prompt: 英語に翻訳済みのプロンプト文字列

        Returns:
            推論結果の英語テキスト
        """
        ...

    # ------------------------------------------------------------------
    # 共通メソッド（必要に応じてオーバーライド可）
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """モデルをメモリから解放する。"""
        if self.model is not None:
            del self.model
            self.model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
