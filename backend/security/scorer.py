"""
backend/security/scorer.py
----------------------------
§7.5 スコアリングと通知判定。

risk_score = behavior_score + context_score + persistence_score
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from .output_validator import ValidatedOutput
from .trigger_judge import TriggerEvent


@dataclass
class ScoringResult:
    risk_score: int
    behavior_score: int
    context_score: int
    persistence_score: int
    action: str   # "notify" | "discard"
    label: str
    reason: str


class Scorer:
    """
    §7.5 スコアリングコンポーネント。

    各スコアの上限:
      behavior_score  : 0-60
      context_score   : 0-25
      persistence_score: 0-15
      risk_score      : 0-100
    """

    def __init__(
        self,
        threshold: int = 70,
        behavior_scores: dict[str, int] | None = None,
        night_start_hour: int = 22,
        night_end_hour: int = 6,
        twilight1_start: int = 18,
        twilight1_end: int = 22,
        twilight2_start: int = 5,
        twilight2_end: int = 7,
        recent_event_window_hours: int = 24,
    ):
        self._threshold = threshold
        self._behavior_scores: dict[str, int] = behavior_scores or {
            "forced_entry_attempt": 60,
            "vandalism": 50,
            "tampering": 45,
            "peering": 30,
            "approach_fast": 25,
            "circling": 15,
            "stay_near_vehicle": 10,
            "unknown_behavior": 5,
        }
        self._night_start = night_start_hour
        self._night_end = night_end_hour
        self._tw1_start = twilight1_start
        self._tw1_end = twilight1_end
        self._tw2_start = twilight2_start
        self._tw2_end = twilight2_end
        self._recent_window = recent_event_window_hours

        # 過去イベントのタイムスタンプ (epoch sec)
        self._event_history: list[float] = []

    # ------------------------------------------------------------------

    def calculate(
        self,
        vlm_output: ValidatedOutput,
        trigger: TriggerEvent,
        now: datetime | None = None,
    ) -> ScoringResult:
        if now is None:
            now = datetime.now()

        b = self._behavior_score(vlm_output.label)
        c = self._context_score(now)
        p = self._persistence_score(trigger.stay_duration_sec, trigger.repeat_count)
        total = min(b + c + p, 100)
        action = "notify" if total >= self._threshold else "discard"

        # 通知時はイベント履歴に追加
        if action == "notify":
            self._event_history.append(time.time())
            self._purge_old_events()

        return ScoringResult(
            risk_score=total,
            behavior_score=b,
            context_score=c,
            persistence_score=p,
            action=action,
            label=vlm_output.label,
            reason=vlm_output.reason,
        )

    def update_config(
        self,
        threshold: int | None = None,
        behavior_scores: dict[str, int] | None = None,
    ) -> None:
        if threshold is not None:
            self._threshold = threshold
        if behavior_scores is not None:
            self._behavior_scores.update(behavior_scores)

    # ------------------------------------------------------------------

    def _behavior_score(self, label: str) -> int:
        return self._behavior_scores.get(label, 5)

    def _context_score(self, now: datetime) -> int:
        score = 0
        h = now.hour

        # 夜間帯 (22:00〜05:59) と薄暮帯は排他; 夜間優先
        def in_night(h: int) -> bool:
            if self._night_start > self._night_end:
                # 日をまたぐ (例: 22-6)
                return h >= self._night_start or h < self._night_end
            return self._night_start <= h < self._night_end

        def in_twilight(h: int) -> bool:
            tw1 = self._tw1_start <= h < self._tw1_end
            tw2 = self._tw2_start <= h < self._tw2_end
            return tw1 or tw2

        if in_night(h):
            score += 15
        elif in_twilight(h):
            score += 5

        # 過去24h以内に不審イベントがあれば +10
        if self._has_recent_event():
            score += 10

        return min(score, 25)

    def _persistence_score(self, stay_sec: float, repeat_count: int) -> int:
        # 滞在時間加算
        if stay_sec < 5:
            time_score = 0
        elif stay_sec < 10:
            time_score = 3
        elif stay_sec < 30:
            time_score = 7
        else:
            time_score = 10

        # 反復回数加算
        if repeat_count == 0:
            repeat_score = 0
        elif repeat_count <= 2:
            repeat_score = 3
        else:
            repeat_score = 5

        return min(time_score + repeat_score, 15)

    def _has_recent_event(self) -> bool:
        self._purge_old_events()
        return len(self._event_history) > 0

    def _purge_old_events(self) -> None:
        cutoff = time.time() - self._recent_window * 3600
        self._event_history = [t for t in self._event_history if t >= cutoff]
