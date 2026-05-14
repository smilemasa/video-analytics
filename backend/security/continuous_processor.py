"""
backend/security/continuous_processor.py
-----------------------------------------
§7.1 常時処理: YOLO+ByteTrack によるフレーム毎の検出・距離算出。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np


# --------------------------------------------------------------------------
# データクラス
# --------------------------------------------------------------------------

@dataclass
class DetectionItem:
    track_id: int
    class_id: int
    class_name: str            # "person" | "vehicle" (or raw COCO name)
    bbox: list[float]          # [x1, y1, x2, y2]
    confidence: float
    owner_excluded: bool = False


@dataclass
class DistanceItem:
    person_track_id: int
    vehicle_track_id: int
    distance_m: float | None   # None = 算出不能 (信頼度不足等)


@dataclass
class FrameData:
    frame_id: int
    timestamp_ms: int
    detections: list[DetectionItem] = field(default_factory=list)
    distances: list[DistanceItem] = field(default_factory=list)
    raw_frame: np.ndarray | None = None      # 生フレーム（デバッグ用）
    annotated_frame: np.ndarray | None = None  # YOLO アノテーション済み


# --------------------------------------------------------------------------
# ヘルパー
# --------------------------------------------------------------------------

def _bbox_bottom_center(bbox: list[float]) -> tuple[float, float]:
    """バウンディングボックス底辺中心点を返す。"""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


def _pixel_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# --------------------------------------------------------------------------
# メインクラス
# --------------------------------------------------------------------------

class ContinuousProcessor:
    """
    §7.1 常時処理コンポーネント。

    process(frame) を呼び出すたびに YOLO トラッキングを実行し、
    FrameData を返す。

    処理周期制御:
      - target_fps に基づき 1フレームあたりの上限時間 (1/fps) を設ける。
      - 処理が上限 (100ms) を超えた場合はフレームをスキップする（呼び出し側が制御）。

    距離算出:
      - pixels_per_meter が設定されていればメートル換算。
      - None の場合はピクセル距離をそのまま distance_m に格納する。
    """

    LATENCY_LIMIT_SEC = 0.1  # 100ms

    def __init__(
        self,
        detector,
        target_fps: int = 10,
        confidence_min: float = 0.5,
        person_classes: list[int] | None = None,
        vehicle_classes: list[int] | None = None,
        pixels_per_meter: float | None = None,
    ):
        self._detector = detector
        self._target_fps = target_fps
        self._interval = 1.0 / target_fps
        self._confidence_min = confidence_min
        self._person_classes = set(person_classes or [0])
        self._vehicle_classes = set(vehicle_classes or [2, 3, 5, 7])
        self._pixels_per_meter = pixels_per_meter

        self._frame_id = 0
        self._last_process_time: float = 0.0

    # ------------------------------------------------------------------

    def should_process(self) -> bool:
        """10fps に満たない場合は全フレーム処理。超える場合は間引き。"""
        now = time.monotonic()
        return (now - self._last_process_time) >= self._interval

    def process(self, frame: np.ndarray) -> FrameData | None:
        """
        フレームを処理して FrameData を返す。
        処理時間が LATENCY_LIMIT_SEC を超えた場合は None を返しスキップ扱いにする。
        """
        t_start = time.monotonic()
        self._last_process_time = t_start
        self._frame_id += 1

        security_classes = list(self._person_classes | self._vehicle_classes)

        try:
            annotated, track_list = self._detector.detect_and_track(
                frame, security_classes=security_classes
            )
        except Exception as exc:
            print(f"[ContinuousProcessor] detect_and_track error: {exc}")
            return None

        elapsed = time.monotonic() - t_start
        if elapsed > self.LATENCY_LIMIT_SEC:
            return None  # 上限超過 → スキップ

        timestamp_ms = int(time.time() * 1000)

        detections: list[DetectionItem] = []
        for t in track_list:
            if t["confidence"] < self._confidence_min:
                continue
            cls_id = t["class_id"]
            if cls_id in self._person_classes:
                cls_name = "person"
            elif cls_id in self._vehicle_classes:
                cls_name = "vehicle"
            else:
                continue  # 対象外クラスは除外

            detections.append(DetectionItem(
                track_id=t["track_id"],
                class_id=cls_id,
                class_name=cls_name,
                bbox=t["bbox"],
                confidence=t["confidence"],
                owner_excluded=False,
            ))

        distances = self._calc_distances(detections)

        return FrameData(
            frame_id=self._frame_id,
            timestamp_ms=timestamp_ms,
            detections=detections,
            distances=distances,
            raw_frame=frame,
            annotated_frame=annotated,
        )

    # ------------------------------------------------------------------

    def _calc_distances(self, detections: list[DetectionItem]) -> list[DistanceItem]:
        persons = [d for d in detections if d.class_name == "person"]
        vehicles = [d for d in detections if d.class_name == "vehicle"]

        result: list[DistanceItem] = []
        for p in persons:
            for v in vehicles:
                try:
                    pc = _bbox_bottom_center(p.bbox)
                    vc = _bbox_bottom_center(v.bbox)
                    px_dist = _pixel_distance(pc, vc)
                    if self._pixels_per_meter is not None and self._pixels_per_meter > 0:
                        dist_m = px_dist / self._pixels_per_meter
                    else:
                        dist_m = px_dist  # キャリブ未設定: ピクセル距離をそのまま使用
                    result.append(DistanceItem(
                        person_track_id=p.track_id,
                        vehicle_track_id=v.track_id,
                        distance_m=round(dist_m, 3),
                    ))
                except Exception:
                    result.append(DistanceItem(
                        person_track_id=p.track_id,
                        vehicle_track_id=v.track_id,
                        distance_m=None,
                    ))
        return result
