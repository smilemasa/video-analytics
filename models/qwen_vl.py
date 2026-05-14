"""
models/qwen_vl.py
-----------------
Qwen2.5-VL (Qwen/Qwen2.5-VL-3B-Instruct) の VLM 実装。

Note: PIL Image を直接 processor に渡す方式を採用。
      base64 + qwen-vl-utils 経由だとトークン/フィーチャー不一致エラーが
      発生するため、transformers 5.x の推奨 API を使用する。
"""

from __future__ import annotations

from PIL import Image
from .base import VLMBase


class QwenVL3BModel(VLMBase):
    MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"

class QwenVL2BModel(QwenVL3BModel):
    MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct"

    def __init__(self, device=None):
        super().__init__(device)
        self.processor = None

    def load(self) -> None:
        from transformers import AutoProcessor, AutoModelForImageTextToText

        self.processor = AutoProcessor.from_pretrained(self.MODEL_ID)
        self.model = AutoModelForImageTextToText.from_pretrained(
            self.MODEL_ID,
            torch_dtype="auto",
            device_map="auto",
        )
        self.model.eval()

    def infer(self, image: Image.Image, prompt: str) -> str:
        # PIL Image を直接 content に渡す（base64 変換 / qwen-vl-utils 不要）
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        # apply_chat_template でテキスト側を組み立てる
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # processor に PIL Image と text を直接渡す
        inputs = self.processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt",
        ).to(self.model.device)

        generated_ids = self.model.generate(**inputs, max_new_tokens=128)
        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        return self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]

    def unload(self) -> None:
        if self.processor is not None:
            del self.processor
            self.processor = None
        super().unload()
