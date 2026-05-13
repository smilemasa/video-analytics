"""
vlm_analyzer.py
---------------
VLM推論のオーケストレーター。

モデル固有のロード・推論ロジックはすべて models/ 配下に委譲し、
このクラスはキュー管理・スレッド制御・翻訳のみを担当する。
"""

import threading
import queue
import time

import cv2
import torch
from PIL import Image
from deep_translator import GoogleTranslator

from models import MODEL_REGISTRY


class VLMAnalyzer:
    def __init__(self, model_id: str = "vikhyatk/moondream2", device: str | None = None):
        """
        VLM（Vision-Language Model）による画像解析クラス。
        バックグラウンドスレッドで重い推論タスクを実行します。
        """
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self.model_id = model_id
        self._model = None  # 現在ロード済みの VLMBase インスタンス

        self.frame_queue = queue.Queue(maxsize=1)
        self.state = {
            "result_text": "VLM: Waiting for frame...",
            "status": "Waiting",
            "current_prompt": "画像を説明してください。",
            "is_running": False,
            "current_frame": None,
            "needs_reload": False,
        }
        self.thread = None

        # 翻訳用インスタンス
        self.translator_ja_en = GoogleTranslator(source="ja", target="en")
        self.translator_en_ja = GoogleTranslator(source="en", target="ja")

        self._load_model()

    # ------------------------------------------------------------------
    # モデル管理
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """モデルレジストリを使ってモデルをロードする。"""
        self.state["status"] = f"Loading {self.model_id}..."
        print(f"[*] Loading {self.model_id} on {self.device}... This might take a while.")

        # 既存モデルの解放
        if self._model is not None:
            self._model.unload()
            self._model = None

        model_cls = MODEL_REGISTRY.get(self.model_id)
        if model_cls is None:
            print(f"[!] Unknown model_id: {self.model_id}")
            self.state["status"] = "Error: Unknown Model"
            return

        try:
            self._model = model_cls(device=self.device)
            self._model.load()
            self.state["status"] = "Waiting"
            print(f"[*] Model loaded: {self.model_id}")
        except Exception as e:
            print(f"[!] Error loading model {self.model_id}: {e}")
            self.state["status"] = "Error Loading Model"
            self._model = None

    def set_model(self, model_id: str) -> None:
        """VLMモデルを動的に変更する（ワーカースレッド側で非同期リロード）。"""
        if model_id != self.model_id:
            self.model_id = model_id
            self.state["status"] = f"Switching to {model_id}..."
            self.state["needs_reload"] = True

    # ------------------------------------------------------------------
    # スレッド制御
    # ------------------------------------------------------------------

    def start(self) -> None:
        """ワーカースレッドを開始する。"""
        self.state["is_running"] = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """ワーカースレッドの停止を要求し、終了を待機する。"""
        self.state["is_running"] = False
        if self.thread:
            self.thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # フレーム入力 / 結果取得
    # ------------------------------------------------------------------

    def push_frame(self, frame) -> None:
        """最新フレームをキューに送る（古いフレームは破棄）。"""
        if self.frame_queue.full():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
        self.frame_queue.put(frame.copy())

    def get_latest_result(self) -> str:
        """現在の解析結果テキストを取得する。"""
        return self.state["result_text"]

    def get_status(self) -> tuple[str, str]:
        """VLMの現在のステータスとプロンプトを取得する。"""
        return self.state["status"], self.state["current_prompt"]

    def set_prompt(self, prompt: str) -> None:
        """VLMのプロンプトを動的に更新する。"""
        if prompt.strip():
            self.state["current_prompt"] = prompt.strip()

    def get_queue_size(self) -> int:
        """現在キューに溜まっているフレーム数を取得する。"""
        return self.frame_queue.qsize()

    def get_current_frame(self):
        """現在解析中のフレームを取得する。"""
        return self.state.get("current_frame")

    # ------------------------------------------------------------------
    # ワーカー処理（内部）
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """キューからフレームを取り出し、VLMモデルで推論するワーカー。"""
        while self.state["is_running"]:

            # モデル切替リクエストの処理
            if self.state.get("needs_reload", False):
                self._load_model()
                self.state["needs_reload"] = False
                continue

            try:
                if self.frame_queue.empty():
                    self.state["status"] = "Waiting"
                    self.state["current_frame"] = None

                frame = self.frame_queue.get(timeout=1.0)
                if frame is None:
                    continue

                self.state["current_frame"] = frame
                start_time = time.time()

                # 日本語プロンプト → 英語に翻訳
                self.state["status"] = "Translating Prompt..."
                prompt_ja = self.state["current_prompt"]
                try:
                    prompt_en = self.translator_ja_en.translate(prompt_ja)
                except Exception as e:
                    print(f"[!] Translation error (Prompt): {e}")
                    prompt_en = prompt_ja

                # モデルがロードされていない場合はスキップ
                if self._model is None:
                    self.state["result_text"] = "[Error] Model failed to load. Check console."
                    self.state["status"] = "Error Loading Model"
                    continue

                # 推論（モデル固有の処理は _model.infer() に委譲）
                self.state["status"] = "Analyzing..."
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                answer_en = self._model.infer(image, prompt_en)

                # 英語結果 → 日本語に翻訳
                self.state["status"] = "Translating Result..."
                try:
                    answer_ja = self.translator_en_ja.translate(answer_en)
                except Exception as e:
                    print(f"[!] Translation error (Result): {e}")
                    answer_ja = answer_en

                process_time = time.time() - start_time
                self.state["result_text"] = f"Action: {answer_ja} ({process_time:.1f}s)"
                self.state["status"] = "Done"

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[!] VLM Error: {e}")
                self.state["status"] = "Error"
