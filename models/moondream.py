"""
models/moondream.py
-------------------
Moondream2 (vikhyatk/moondream2) の VLM 実装。

transformers >= 4.47 で発生する
  'HfMoondream' object has no attribute 'all_tied_weights_keys'
エラーを回避するため、transformers==4.46.x に固定して使用する。
"""

from __future__ import annotations

from PIL import Image
from .base import VLMBase


class MoondreamModel(VLMBase):
    MODEL_ID = "vikhyatk/moondream2"

    def __init__(self, device=None):
        super().__init__(device)
        self.tokenizer = None

    def load(self) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.MODEL_ID, trust_remote_code=True
        )
        model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID, trust_remote_code=True
        )

        # Patch: transformers >= 4.47 expects this attribute on the model config
        # during tie_weights(); moondream2's custom HfMoondream class doesn't define it.
        if not hasattr(model, "all_tied_weights_keys"):
            model.all_tied_weights_keys = []

        self.model = model.to(self.device)
        self.model.eval()

    def infer(self, image: Image.Image, prompt: str) -> str:
        enc_image = self.model.encode_image(image)
        return self.model.answer_question(enc_image, prompt, self.tokenizer)

    def unload(self) -> None:
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        super().unload()
