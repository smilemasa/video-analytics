"""
backend/security/vlm_security_analyzer.py
-------------------------------------------
§7.3 VLMオンデマンド解析ラッパー。

トリガーイベント受信時のみ VLM を起動する。
1スレッドのキューで順次処理し、常時起動を禁止する。
既存 VLMAnalyzer のモデルインスタンス (_model.infer) を直接利用する。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from .output_validator import ValidatedOutput, validate_vlm_output
from .trigger_judge import TriggerEvent


@dataclass
class LatencyInfo:
    """検出トリガーから最終判定までの各ステージの計測時刻（epoch ms）。"""
    trigger_at_ms: int       # TriggerEvent が成立した時刻
    submitted_at_ms: int     # VLM キューへ投入した時刻
    vlm_start_ms: int        # VLM 推論開始時刻
    vlm_end_ms: int          # VLM 推論完了時刻
    scoring_at_ms: int = 0   # スコアリング完了時刻（pipeline で更新）

    @property
    def queue_wait_ms(self) -> int:
        """キュー待機時間（ms）。"""
        return self.vlm_start_ms - self.submitted_at_ms

    @property
    def vlm_latency_ms(self) -> int:
        """VLM 推論時間（ms）。"""
        return self.vlm_end_ms - self.vlm_start_ms

    @property
    def total_latency_ms(self) -> int:
        """トリガー成立〜スコアリング完了までの合計時間（ms）。"""
        end = self.scoring_at_ms if self.scoring_at_ms > 0 else self.vlm_end_ms
        return end - self.trigger_at_ms


@dataclass
class _AnalysisRequest:
    frame: np.ndarray
    trigger: TriggerEvent
    submitted_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class VLMSecurityAnalyzer:
    """
    トリガー成立時のみ VLM を起動するオンデマンド解析クラス。

    使い方:
        analyzer = VLMSecurityAnalyzer(vlm_analyzer_instance, prompt)
        analyzer.start()
        analyzer.submit(frame, trigger_event)   # トリガー成立時
        result = analyzer.get_latest_result()   # ValidatedOutput | None
    """

    QUEUE_MAX = 5
    TIMEOUT_SEC = 30.0

    def __init__(self, vlm_analyzer, prompt_template: str):
        """
        Args:
            vlm_analyzer: 既存の VLMAnalyzer インスタンス (models._model.infer を持つ)
            prompt_template: security.yaml から読み込んだプロンプトテンプレート
        """
        self._vlm = vlm_analyzer
        self._prompt = prompt_template

        self._queue: queue.Queue[_AnalysisRequest] = queue.Queue(maxsize=self.QUEUE_MAX)
        self._latest_result: ValidatedOutput | None = None
        self._latest_trigger: TriggerEvent | None = None
        self._latest_latency: LatencyInfo | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="vlm-security")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        # ダミーを積んでブロック解除
        try:
            self._queue.put_nowait(None)  # type: ignore[arg-type]
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def submit(self, frame: np.ndarray, trigger: TriggerEvent) -> None:
        """トリガー成立時にフレームをキューへ投入する。満杯の場合は古いものを破棄。"""
        submitted_at_ms = int(time.time() * 1000)
        req = _AnalysisRequest(frame=frame.copy(), trigger=trigger, submitted_at_ms=submitted_at_ms)
        try:
            self._queue.put_nowait(req)
        except queue.Full:
            # キュー満杯: 古いリクエストを1件破棄して再投入
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(req)
            except queue.Full:
                pass

    def get_latest_result(self) -> tuple[ValidatedOutput | None, TriggerEvent | None, LatencyInfo | None]:
        with self._lock:
            return self._latest_result, self._latest_trigger, self._latest_latency

    def update_prompt(self, prompt: str) -> None:
        self._prompt = prompt

    # ------------------------------------------------------------------

    def _worker(self) -> None:
        while self._running:
            try:
                req = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if req is None:
                break

            vlm_start_ms = int(time.time() * 1000)
            raw = self._infer(req.frame)
            vlm_end_ms = int(time.time() * 1000)
            validated = validate_vlm_output(raw)
            latency = LatencyInfo(
                trigger_at_ms=req.trigger.triggered_at,
                submitted_at_ms=req.submitted_at_ms,
                vlm_start_ms=vlm_start_ms,
                vlm_end_ms=vlm_end_ms,
            )
            with self._lock:
                self._latest_result = validated
                self._latest_trigger = req.trigger
                self._latest_latency = latency

    def _infer(self, frame: np.ndarray) -> str:
        """フレームを PIL 変換し VLM に問い合わせる。"""
        try:
            pil_img = Image.fromarray(frame[..., ::-1])  # BGR → RGB
            model = self._vlm._model
            if model is None:
                return '{"label": "unknown_behavior", "reason": "VLM model not loaded"}'
            raw = model.infer(pil_img, self._prompt)
            return raw if raw else '{"label": "unknown_behavior", "reason": "empty response"}'
        except Exception as exc:
            return f'{{"label": "unknown_behavior", "reason": "infer error: {exc}"}}'
