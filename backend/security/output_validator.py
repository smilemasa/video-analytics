"""
backend/security/output_validator.py
--------------------------------------
§7.4 VLM 出力バリデーション。

VLM 生出力を受け取り、JSON パース → ラベル検証 → フォールバック処理を行う。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


FALLBACK_LABEL = "unknown_behavior"

STANDARD_LABELS: frozenset[str] = frozenset([
    "forced_entry_attempt",
    "vandalism",
    "tampering",
    "peering",
    "approach_fast",
    "circling",
    "stay_near_vehicle",
    "unknown_behavior",
])


@dataclass
class ValidatedOutput:
    label: str
    reason: str
    is_fallback: bool
    raw_output: str


def validate_vlm_output(raw: str) -> ValidatedOutput:
    """
    §7.4.2 バリデーションアルゴリズム。

    1. JSON パース失敗 → is_fallback=True, label=unknown_behavior
    2. label が標準ラベル外   → is_fallback=True, label=unknown_behavior
    3. 正常                   → is_fallback=False, label をそのまま採用
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ValidatedOutput(
            label=FALLBACK_LABEL,
            reason="",
            is_fallback=True,
            raw_output=raw,
        )

    label = parsed.get("label", "")
    reason = parsed.get("reason", "")

    if label not in STANDARD_LABELS:
        return ValidatedOutput(
            label=FALLBACK_LABEL,
            reason=str(reason),
            is_fallback=True,
            raw_output=raw,
        )

    return ValidatedOutput(
        label=label,
        reason=str(reason),
        is_fallback=False,
        raw_output=raw,
    )
