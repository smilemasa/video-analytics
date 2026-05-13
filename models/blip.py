"""
models/blip.py
--------------
Salesforce BLIP (blip-vqa-base) の VLM 実装。
"""

from __future__ import annotations

from PIL import Image
from .base import VLMBase


class BlipModel(VLMBase):
    MODEL_ID = "Salesforce/blip-vqa-base"

    def __init__(self, device=None):
        super().__init__(device)
        self.processor = None

    def load(self) -> None:
        from transformers import BlipProcessor, BlipForQuestionAnswering

        self.processor = BlipProcessor.from_pretrained(self.MODEL_ID)
        self.model = BlipForQuestionAnswering.from_pretrained(
            self.MODEL_ID
        ).to(self.device)
        self.model.eval()

    def infer(self, image: Image.Image, prompt: str) -> str:
        inputs = self.processor(image, prompt, return_tensors="pt").to(self.device)
        out = self.model.generate(**inputs, max_new_tokens=50)
        return self.processor.decode(out[0], skip_special_tokens=True)

    def unload(self) -> None:
        if self.processor is not None:
            del self.processor
            self.processor = None
        super().unload()
