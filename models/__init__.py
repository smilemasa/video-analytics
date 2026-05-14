"""
models/__init__.py
------------------
VLMモデルのレジストリ。

新しいモデルを追加する手順:
    1. models/ 配下に新しい .py ファイルを作成し、VLMBase を継承したクラスを実装する。
    2. このファイルの MODEL_REGISTRY にエントリを追加する。
    以上。vlm_analyzer.py や main.py への変更は不要。
"""

from .qwen_vl import QwenVL2BModel, QwenVL3BModel

# model_id (str) -> VLMBase サブクラス のマッピング
MODEL_REGISTRY: dict[str, type] = {
    QwenVL2BModel.MODEL_ID: QwenVL2BModel,
    QwenVL3BModel.MODEL_ID: QwenVL3BModel,
}

__all__ = ["MODEL_REGISTRY"]
