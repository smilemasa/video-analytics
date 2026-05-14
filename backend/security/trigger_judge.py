"""
backend/security/trigger_judge.py
-----------------------------------
§7.2 トリガー判定コンポーネント。

条件 A: person-vehicle 距離 ≤ distance_threshold_m
条件 B: 同一 track_id が条件Aを stay_duration_sec 以上継続
A∧B 成立 → TriggerEvent を生成する。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .continuous_processor import FrameData, DistanceItem


@dataclass
class TriggerEvent:
    person_track_id: int
    vehicle_track_id: int
    distance_m: float
    stay_duration_sec: float
    triggered_at: int       # epoch timestamp_ms
    repeat_count: int       # 同一 person_track_id での再トリガー回数


# (person_track_id, vehicle_track_id) のペア状態
@dataclass
class _TrackState:
    condition_a_since: float | None = None   # 条件A最初の成立時刻 (monotonic)
    triggered: bool = False                  # 現フレームでトリガー済みか


class TriggerJudge:
    """
    FrameData を受け取り、トリガー成立したイベント一覧を返す。

    time_fn: 時刻取得関数。デフォルトは time.monotonic。
             オフライン動画解析時はビデオタイムスタンプを返す関数を渡す。
    """

    def __init__(
        self,
        distance_threshold_m: float = 3.0,
        stay_duration_sec: float = 2.0,
        time_fn=None,
    ):
        self._dist_threshold = distance_threshold_m
        self._stay_duration = stay_duration_sec
        self._time_fn = time_fn or time.monotonic

        # (person_tid, vehicle_tid) -> _TrackState
        self._states: dict[tuple[int, int], _TrackState] = {}
        # person_track_id -> 過去のトリガー回数
        self._trigger_counts: dict[int, int] = {}

    # ------------------------------------------------------------------

    def update(self, frame_data: FrameData) -> list[TriggerEvent]:
        """
        frame_data を評価し、今フレームで新たに成立したトリガーイベントを返す。
        owner_excluded フラグが True の person はスキップする。
        """
        now = self._time_fn()
        events: list[TriggerEvent] = []

        # 現フレームで有効なペアキーを収集
        active_keys: set[tuple[int, int]] = set()

        excluded_ids = {
            d.track_id for d in frame_data.detections
            if d.class_name == "person" and d.owner_excluded
        }

        for dist in frame_data.distances:
            p_tid = dist.person_track_id
            if p_tid in excluded_ids:
                continue
            if dist.distance_m is None:
                continue  # 算出不能 → スキップ

            v_tid = dist.vehicle_track_id
            key = (p_tid, v_tid)
            active_keys.add(key)

            cond_a = dist.distance_m <= self._dist_threshold

            state = self._states.setdefault(key, _TrackState())

            if cond_a:
                if state.condition_a_since is None:
                    state.condition_a_since = now
                elapsed = now - state.condition_a_since
                cond_b = elapsed >= self._stay_duration
                if cond_b and not state.triggered:
                    state.triggered = True
                    repeat = self._trigger_counts.get(p_tid, 0)
                    self._trigger_counts[p_tid] = repeat + 1
                    events.append(TriggerEvent(
                        person_track_id=p_tid,
                        vehicle_track_id=v_tid,
                        distance_m=dist.distance_m,
                        stay_duration_sec=round(elapsed, 2),
                        triggered_at=frame_data.timestamp_ms,
                        repeat_count=repeat,
                    ))
            else:
                # 条件A 不成立 → リセット
                state.condition_a_since = None
                state.triggered = False

        # 現フレームに存在しないペアの状態をリセット
        for key in list(self._states.keys()):
            if key not in active_keys:
                del self._states[key]

        return events

    def get_active_triggers(self) -> list[dict]:
        """現在条件A が成立中 (滞在中) のペア情報を返す (デバッグ用)。"""
        now = self._time_fn()
        result = []
        for (p_tid, v_tid), state in self._states.items():
            if state.condition_a_since is not None:
                result.append({
                    "person_track_id": p_tid,
                    "vehicle_track_id": v_tid,
                    "stay_sec": round(now - state.condition_a_since, 2),
                    "triggered": state.triggered,
                })
        return result
