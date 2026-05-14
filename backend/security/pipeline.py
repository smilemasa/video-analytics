"""
backend/security/pipeline.py
------------------------------
セキュリティ検知パイプライン統括。

各コンポーネントを順に呼び出し、デバッグ用の PipelineState を保持する。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import yaml

from .continuous_processor import ContinuousProcessor, FrameData
from .owner_exclusion import OwnerExclusionJudge
from .trigger_judge import TriggerJudge, TriggerEvent
from .vlm_security_analyzer import VLMSecurityAnalyzer
from .vlm_security_analyzer import LatencyInfo
from .output_validator import ValidatedOutput
from .scorer import Scorer, ScoringResult

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "security.yaml",
)


def _load_config() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# デバッグ状態
# --------------------------------------------------------------------------

@dataclass
class PipelineState:
    """フロントエンドデバッグビュー向けに全ステージの最新状態を保持する。"""
    timestamp_ms: int = 0
    frame_data: FrameData | None = None
    active_conditions: list[dict] = field(default_factory=list)  # TriggerJudge の監視中ペア
    active_triggers: list[TriggerEvent] = field(default_factory=list)  # 今フレームで成立
    owner_candidates: list[int] = field(default_factory=list)
    latest_vlm_output: ValidatedOutput | None = None
    latest_scoring: ScoringResult | None = None
    latest_trigger_for_vlm: TriggerEvent | None = None
    latest_latency: LatencyInfo | None = None
    # スコアリング履歴（直近10件）
    scoring_history: list[ScoringResult] = field(default_factory=list)


# --------------------------------------------------------------------------
# パイプライン
# --------------------------------------------------------------------------

class SecurityPipeline:
    """
    SecurityPipeline.process_frame(frame) を呼び出すだけで全コンポーネントが動作する。
    """

    HISTORY_MAX = 10

    def __init__(self, detector, vlm_analyzer):
        cfg = _load_config()

        det_cfg = cfg.get("detection", {})
        trg_cfg = cfg.get("trigger", {})
        own_cfg = cfg.get("owner_exclusion", {})
        scr_cfg = cfg.get("scoring", {})
        bscore  = cfg.get("behavior_scores", {})
        prompt  = cfg.get("vlm_prompt_template", "")

        person_classes  = det_cfg.get("target_classes", {}).get("person", [0])
        vehicle_classes = det_cfg.get("target_classes", {}).get("vehicle", [2, 3, 5, 7])

        pixels_per_meter = det_cfg.get("pixels_per_meter")

        self._processor = ContinuousProcessor(
            detector=detector,
            target_fps=det_cfg.get("fps", 10),
            confidence_min=det_cfg.get("confidence_min", 0.5),
            person_classes=person_classes,
            vehicle_classes=vehicle_classes,
            pixels_per_meter=pixels_per_meter,
        )
        self._owner_judge = OwnerExclusionJudge(
            proximity_threshold_m=own_cfg.get("proximity_threshold_m", 1.5),
            detection_window_sec=own_cfg.get("detection_window_sec", 10.0),
            exclusion_duration_sec=own_cfg.get("exclusion_duration_sec", 300.0),
        )
        # pixels_per_meter 未設定時はピクセル閾値を使う
        _dist_threshold = (
            trg_cfg.get("distance_threshold_m", 3.0)
            if pixels_per_meter
            else trg_cfg.get("distance_threshold_px", 200)
        )
        self._trigger_judge = TriggerJudge(
            distance_threshold_m=_dist_threshold,
            stay_duration_sec=trg_cfg.get("stay_duration_sec", 2.0),
        )
        self._vlm_analyzer = VLMSecurityAnalyzer(
            vlm_analyzer=vlm_analyzer,
            prompt_template=prompt,
        )
        self._scorer = Scorer(
            threshold=scr_cfg.get("threshold", 70),
            behavior_scores=bscore if bscore else None,
            night_start_hour=scr_cfg.get("night_start_hour", 22),
            night_end_hour=scr_cfg.get("night_end_hour", 6),
            twilight1_start=scr_cfg.get("twilight1_start_hour", 18),
            twilight1_end=scr_cfg.get("twilight1_end_hour", 22),
            twilight2_start=scr_cfg.get("twilight2_start_hour", 5),
            twilight2_end=scr_cfg.get("twilight2_end_hour", 7),
            recent_event_window_hours=scr_cfg.get("recent_event_window_hours", 24),
        )
        self._vlm_analyzer.start()

        self._state = PipelineState()
        self._state_lock = threading.Lock()

        # VLM 結果のポーリング: スコアリングはトリガー発火後の非同期結果を受け取る
        self._pending_trigger: TriggerEvent | None = None

    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray) -> PipelineState:
        """メインループから毎フレーム呼び出す。"""
        if not self._processor.should_process():
            return self.get_state()

        frame_data = self._processor.process(frame)
        if frame_data is None:
            return self.get_state()  # スキップ

        # オーナー除外
        frame_data = self._owner_judge.update(frame_data)

        # トリガー判定
        new_triggers = self._trigger_judge.update(frame_data)
        active_conds = self._trigger_judge.get_active_triggers()

        # トリガー成立 → VLM へ投入
        for trig in new_triggers:
            if frame_data.raw_frame is not None:
                self._vlm_analyzer.submit(frame_data.raw_frame, trig)

        # VLM 結果受取 → スコアリング
        vlm_result, vlm_trigger, vlm_latency = self._vlm_analyzer.get_latest_result()
        scoring = None
        if vlm_result is not None and vlm_trigger is not None:
            # まだスコアリング済みでない場合のみ処理
            prev_scoring = self._state.latest_scoring
            if (prev_scoring is None or
                    vlm_trigger.triggered_at != getattr(self._state.latest_trigger_for_vlm, "triggered_at", None)):
                scoring = self._scorer.calculate(vlm_result, vlm_trigger)
                if vlm_latency is not None:
                    vlm_latency.scoring_at_ms = int(time.time() * 1000)

        with self._state_lock:
            self._state.timestamp_ms = frame_data.timestamp_ms
            self._state.frame_data = frame_data
            self._state.active_conditions = active_conds
            self._state.active_triggers = new_triggers
            self._state.owner_candidates = self._owner_judge.get_excluded_track_ids()
            self._state.latest_vlm_output = vlm_result
            if vlm_trigger is not None:
                self._state.latest_trigger_for_vlm = vlm_trigger
            if scoring is not None:
                self._state.latest_scoring = scoring
                self._state.latest_latency = vlm_latency
                self._state.scoring_history.append(scoring)
                if len(self._state.scoring_history) > self.HISTORY_MAX:
                    self._state.scoring_history.pop(0)

        return self.get_state()

    def get_state(self) -> PipelineState:
        with self._state_lock:
            return self._state

    def stop(self) -> None:
        self._vlm_analyzer.stop()

    # ------------------------------------------------------------------
    # 設定更新

    def update_config(
        self,
        threshold: int | None = None,
        distance_threshold_m: float | None = None,
        stay_duration_sec: float | None = None,
    ) -> None:
        if threshold is not None:
            self._scorer.update_config(threshold=threshold)
        if distance_threshold_m is not None:
            self._trigger_judge._dist_threshold = distance_threshold_m
        if stay_duration_sec is not None:
            self._trigger_judge._stay_duration = stay_duration_sec

    def get_config(self) -> dict:
        return {
            "threshold": self._scorer._threshold,
            "distance_threshold_m": self._trigger_judge._dist_threshold,
            "stay_duration_sec": self._trigger_judge._stay_duration,
        }
