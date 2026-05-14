"""
backend/security/owner_exclusion.py
-------------------------------------
§7.2.1 オーナー除外判定コンポーネント。

車両到着後に降車した人物をオーナー候補として除外する。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .continuous_processor import FrameData, DetectionItem


@dataclass
class _VehicleEntry:
    track_id: int
    arrived_at: float       # monotonic time
    bbox: list[float]


class OwnerExclusionJudge:
    """
    条件:
      O1: 車両が新規に監視エリアへ進入
      O2: O1 成立後 detection_window_sec 以内に近傍から人物が出現
      O3: 人物の初期位置が車両近傍 (proximity_threshold_m 以内)

    O1∧O2∧O3 を満たす person track_id を owner_candidate として除外する。
    除外は exclusion_duration_sec 後に自動解除される。
    """

    def __init__(
        self,
        proximity_threshold_m: float = 1.5,
        detection_window_sec: float = 10.0,
        exclusion_duration_sec: float = 300.0,
        time_fn=None,
    ):
        self._proximity_threshold = proximity_threshold_m
        self._detection_window = detection_window_sec
        self._exclusion_duration = exclusion_duration_sec
        self._time_fn = time_fn or time.monotonic

        self._known_vehicle_ids: set[int] = set()
        self._new_vehicles: dict[int, _VehicleEntry] = {}  # track_id -> entry (O1 監視中)
        self._owner_candidates: dict[int, float] = {}      # person_track_id -> expire_time

    # ------------------------------------------------------------------

    def update(self, frame_data: FrameData) -> FrameData:
        """
        detections の owner_excluded フラグを更新して返す。
        FrameData の detections リストは in-place で変更する。
        """
        now = self._time_fn()
        self._expire_old_entries(now)

        vehicles = [d for d in frame_data.detections if d.class_name == "vehicle"]
        persons  = [d for d in frame_data.detections if d.class_name == "person"]

        # O1: 新規車両検出
        for v in vehicles:
            if v.track_id not in self._known_vehicle_ids:
                self._known_vehicle_ids.add(v.track_id)
                self._new_vehicles[v.track_id] = _VehicleEntry(
                    track_id=v.track_id,
                    arrived_at=now,
                    bbox=v.bbox,
                )

        # O2 + O3: 新規車両近傍に出現した人物をオーナー候補へ
        for p in persons:
            if p.track_id in self._owner_candidates:
                continue  # 既に除外中
            for vid, ventry in list(self._new_vehicles.items()):
                if now - ventry.arrived_at > self._detection_window:
                    continue  # 検出ウィンドウ外
                dist = self._bbox_distance(p.bbox, ventry.bbox)
                if dist <= self._proximity_threshold:
                    # O2∧O3 成立 → オーナー候補に追加
                    expire = now + self._exclusion_duration
                    self._owner_candidates[p.track_id] = expire

        # フラグ付与
        for d in frame_data.detections:
            if d.class_name == "person" and d.track_id in self._owner_candidates:
                d.owner_excluded = True

        return frame_data

    def get_excluded_track_ids(self) -> list[int]:
        now = self._time_fn()
        return [tid for tid, exp in self._owner_candidates.items() if exp > now]

    # ------------------------------------------------------------------

    def _expire_old_entries(self, now: float) -> None:
        # 除外期限切れを削除
        expired = [tid for tid, exp in self._owner_candidates.items() if exp <= now]
        for tid in expired:
            del self._owner_candidates[tid]

        # 車両の検出ウィンドウ切れ
        expired_v = [
            vid for vid, e in self._new_vehicles.items()
            if now - e.arrived_at > self._detection_window
        ]
        for vid in expired_v:
            del self._new_vehicles[vid]

    @staticmethod
    def _bbox_distance(bbox_a: list[float], bbox_b: list[float]) -> float:
        """底辺中心点間距離 (ピクセル / メートル共通)。"""
        import math
        ax = (bbox_a[0] + bbox_a[2]) / 2.0
        ay = bbox_a[3]
        bx = (bbox_b[0] + bbox_b[2]) / 2.0
        by = bbox_b[3]
        return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
