# 車両周辺セキュリティ検知 — 実装計画

## 1. 現状のコードベース分析

### 1.1 既存アーキテクチャ

```
video-analytics-master/
├── yolo_detector.py        # YOLOv8 検出（model()呼び出し、person クラスのみ）
├── vlm_analyzer.py         # VLMオーケストレーター（キュー+スレッド制御）
├── models/                 # VLMモデル実装（Moondream / BLIP / Qwen-VL）
└── backend/
    ├── main.py             # FastAPI エントリポイント
    ├── routers/
    │   ├── live.py         # カメラ管理・SSE・WebSocket
    │   ├── settings.py     # モデル切り替え・YOLOクラス設定
    │   ├── static.py       # 静的画像/動画解析
    │   └── system.py       # ヘルスチェック
    ├── schemas/models.py   # Pydantic スキーマ
    └── services/analyzer.py # VLMAnalyzer + YoloDetector シングルトン
```

### 1.2 既存コードの再利用方針

| 既存コード | 再利用方針 |
|---|---|
| `YoloDetector.detect()` | 変更なし（既存ユースケースを維持） |
| `YoloDetector` クラス | `detect_and_track()` メソッドを**追加**（`model.track()` + ByteTrack） |
| `VLMAnalyzer` | 変更なし。セキュリティ専用の軽量ラッパーを**新規作成**して呼び出す |
| `AnalyzerService` | 変更なし。`SecurityService` が独立して動作する |
| FastAPI `backend/main.py` | セキュリティルーターの**登録を追加**するのみ |
| フロントエンド `App.tsx` | セキュリティページへのナビゲーション**リンクを追加** |

---

## 2. 実装対象の全体像

### 2.1 追加するファイル構成

```
video-analytics-master/
├── config/
│   └── security.yaml               # [新規] セキュリティ設定（閾値・スコア・時間帯）
├── backend/
│   ├── security/                   # [新規] セキュリティ検知エンジン
│   │   ├── __init__.py
│   │   ├── continuous_processor.py # §7.1 常時処理（YOLO+ByteTrack+距離算出）
│   │   ├── owner_exclusion.py      # §7.2.1 オーナー除外判定
│   │   ├── trigger_judge.py        # §7.2 トリガー判定
│   │   ├── vlm_security_analyzer.py# §7.3 VLMオンデマンド解析
│   │   ├── output_validator.py     # §7.4 出力バリデーション
│   │   ├── scorer.py               # §7.5 スコアリング
│   │   └── pipeline.py             # パイプライン統括・デバッグ状態管理
│   ├── routers/
│   │   └── security.py             # [新規] セキュリティ API エンドポイント
│   ├── schemas/
│   │   └── security_models.py      # [新規] セキュリティ用 Pydantic スキーマ
│   └── services/
│       └── security_service.py     # [新規] SecurityService シングルトン
└── frontend/src/
    ├── pages/
    │   └── SecurityPage.tsx        # [新規] デバッグビューページ
    └── components/
        └── SecurityDebugPanel.tsx  # [新規] パイプライン状態パネル
```

### 2.2 変更するファイル

| ファイル | 変更内容 |
|---|---|
| `yolo_detector.py` | `detect_and_track()` メソッド追加 |
| `backend/main.py` | `security` ルーター登録を追加 |
| `frontend/src/App.tsx` | 「セキュリティ」ナビリンク追加 |
| `frontend/src/api.ts` | セキュリティ用型定義を追加 |

---

## 3. 実装フェーズ

### Phase 1: バックエンド — セキュリティ検知エンジン

#### Task 1-1: `yolo_detector.py` — トラッキング対応

**実装内容:**  
`detect_and_track(frame)` メソッドを追加する。内部で `model.track(frame, tracker="bytetrack.yaml")` を呼び出し、`track_id` を含む検出結果を返す。既存の `detect()` は変更しない。

**出力形式:**

```python
[
    {
        "track_id": int,          # ByteTrack が付与する追跡ID
        "class_id": int,          # 0=person, 2/3/5/7=vehicle
        "class_name": str,        # "person" | "vehicle"
        "bbox": [x1, y1, x2, y2],
        "confidence": float,
        "owner_excluded": False   # 初期値
    }
]
```

---

#### Task 1-2: `config/security.yaml` — 設定ファイル

**実装内容:**  
スコア閾値・距離閾値・時間帯・ラベル定義等を外部管理する YAML ファイルを作成する。

```yaml
detection:
  fps: 10
  confidence_min: 0.5
  target_classes:
    person: [0]
    vehicle: [2, 3, 5, 7]

trigger:
  distance_threshold_m: 3.0
  stay_duration_sec: 2.0

owner_exclusion:
  proximity_threshold_m: 1.5
  detection_window_sec: 10.0
  exclusion_duration_sec: 300.0

scoring:
  threshold: 70
  night_hours: [22, 5]     # 22:00〜05:59
  twilight_hours: [[18, 21], [5, 6]]  # 薄暮帯

behavior_scores:
  forced_entry_attempt: 60
  vandalism: 50
  tampering: 45
  peering: 30
  approach_fast: 25
  circling: 15
  stay_near_vehicle: 10
  unknown_behavior: 5

labels:
  - forced_entry_attempt
  - vandalism
  - tampering
  - peering
  - approach_fast
  - circling
  - stay_near_vehicle
  - unknown_behavior
```

---

#### Task 1-3: `backend/security/continuous_processor.py` — 常時処理 (§7.1)

**責務:**

- 10fps でフレームを処理（入力が10fps未満の場合は全フレームを処理）
- `detect_and_track()` を呼び出し person / vehicle を検出
- `distances` を算出: 各 person-vehicle ペアのバウンディングボックス底辺中心点間距離（ピクセル値。実運用ではキャリブレーション行列でメートル換算。初期実装はピクセル距離のみ）
- §7.1.5 の出力スキーマに準拠した `FrameData` データクラスを後段へ渡す

**入出力:**

```python
# 出力: FrameData
@dataclass
class FrameData:
    frame_id: int
    timestamp_ms: int
    detections: list[Detection]   # track_id, class, bbox, confidence, owner_excluded
    distances: list[Distance]     # person_track_id, vehicle_track_id, distance_m
    raw_frame: np.ndarray         # アノテーション前の生フレーム（デバッグ用）
    annotated_frame: np.ndarray   # YOLO アノテーション済みフレーム
```

**処理周期制御:**  
100ms 上限を超えたフレームはスキップし、バッファ蓄積を行わない。

---

#### Task 1-4: `backend/security/owner_exclusion.py` — オーナー除外判定 (§7.2.1)

**責務:**

- 新規車両進入（O1）を監視
- 所定時間内に車両近傍から出現した人物（O2）を検出
- 軌跡が車両ドア近傍から連続移動しているか確認（O3）
- 除外対象の `track_id` を `owner_excluded=True` にフラグ付けする

**状態管理:**

```python
class OwnerExclusionJudge:
    _known_vehicles: dict[int, VehicleEntry]   # track_id -> 到着時刻等
    _owner_candidates: dict[int, float]        # person_track_id -> 除外期限タイムスタンプ

    def update(self, frame_data: FrameData) -> FrameData:
        """detections の owner_excluded フラグを更新して返す。"""
```

---

#### Task 1-5: `backend/security/trigger_judge.py` — トリガー判定 (§7.2)

**責務:**

- 条件A: person-vehicle 距離 ≤ `distance_threshold_m`
- 条件B: 同一 `track_id` が条件Aを `stay_duration_sec` 以上継続
- A and B が成立 → トリガーイベントを生成

```python
@dataclass
class TriggerEvent:
    person_track_id: int
    vehicle_track_id: int
    distance_m: float
    stay_duration_sec: float
    triggered_at: int  # timestamp_ms
    repeat_count: int  # 同一トラックIDの再トリガー回数
```

---

#### Task 1-6: `backend/security/vlm_security_analyzer.py` — VLMオンデマンド解析 (§7.3)

**責務:**

- トリガーイベント受信時のみ VLM を起動（常時起動禁止）
- 1スレッドの `queue.Queue(maxsize=N)` でキュー管理
- §7.3.1 のプロンプトテンプレートを `security.yaml` から読み込み
- 既存 `VLMAnalyzer._model.infer()` を呼び出す（モデル再ロード不要）

**注意:**  
`VLMAnalyzer` の `frame_queue` は通常解析用のため共有しない。`_model.infer()` を直接呼ぶラッパーとして実装する。

---

#### Task 1-7: `backend/security/output_validator.py` — 出力バリデーション (§7.4)

**責務:**

- VLM 生出力を JSON パース
- `label` フィールドが標準ラベル一覧に含まれるか検証
- 不正値・パース失敗 → `label="unknown_behavior"`, `is_fallback=True`

```python
@dataclass
class ValidatedOutput:
    label: str
    reason: str
    is_fallback: bool
    raw_output: str
```

---

#### Task 1-8: `backend/security/scorer.py` — スコアリング (§7.5)

**責務:**

- `behavior_score`: ラベル別固定値（`security.yaml` から取得）
- `context_score`: 時刻から夜間/薄暮帯を判定 + 過去24h以内の不審イベント有無
- `persistence_score`: 滞在時間加算 + 反復回数加算（上限15点）
- `risk_score = behavior_score + context_score + persistence_score`
- 閾値比較 → `action: "notify" | "discard"`

```python
@dataclass
class ScoringResult:
    risk_score: int
    behavior_score: int
    context_score: int
    persistence_score: int
    action: str   # "notify" | "discard"
    label: str
    reason: str
```

---

#### Task 1-9: `backend/security/pipeline.py` — パイプライン統括

**責務:**

- 各コンポーネントを順に呼び出す `SecurityPipeline.process_frame(frame)` を提供
- **デバッグ用**: 各ステージの最新状態を `pipeline_state` として保持
- `pipeline_state` はフロントエンドへ SSE で配信するために `SecurityService` が参照する

```python
class PipelineState:
    """デバッグビュー向けに全ステージの最新状態を保持する。"""
    timestamp_ms: int
    frame_data: FrameData | None         # 常時処理出力
    active_triggers: list[TriggerEvent]  # 現在成立中のトリガー
    latest_vlm_output: ValidatedOutput | None
    latest_scoring: ScoringResult | None
    owner_candidates: list[int]          # 除外中の track_id 一覧
```

---

#### Task 1-10: `backend/schemas/security_models.py` — Pydantic スキーマ

セキュリティエンドポイントの Request / Response 型を定義する。

```python
class SecurityPipelineStateResponse(BaseModel):
    timestamp_ms: int
    detections: list[SecurityDetection]
    distances: list[SecurityDistance]
    active_triggers: list[TriggerEventSchema]
    owner_candidates: list[int]
    latest_vlm: ValidatedOutputSchema | None
    latest_scoring: ScoringResultSchema | None
    annotated_image: str | None   # base64 (デバッグ表示用)

class SecurityConfigResponse(BaseModel):
    threshold: int
    distance_threshold_m: float
    stay_duration_sec: float

class SecurityConfigRequest(BaseModel):
    threshold: int | None
    distance_threshold_m: float | None
    stay_duration_sec: float | None
```

---

#### Task 1-11: `backend/services/security_service.py` — シングルトンサービス

- `SecurityPipeline` を保持し `process_frame()` を呼び出す
- `pipeline_state` を参照し SSE 配信用データに変換する

---

#### Task 1-12: `backend/routers/security.py` — API エンドポイント

| Method | Endpoint | 説明 |
|---|---|---|
| `GET` | `/api/security/status` | パイプライン状態（最新1件） |
| `GET` | `/api/security/debug/stream` | SSE: リアルタイムデバッグデータ配信 |
| `GET` | `/api/security/config` | 現在の設定取得 |
| `PUT` | `/api/security/config` | 設定更新（閾値・距離等） |

**SSE ペイロード（15fps）:**  
`SecurityPipelineStateResponse` を JSON シリアライズして配信。アノテーション済みフレームの base64 を含む。

---

#### Task 1-13: `backend/main.py` — ルーター登録

```python
from backend.routers import security
app.include_router(security.router)
```

---

### Phase 2: フロントエンド — デバッグビュー

#### Task 2-1: `frontend/src/api.ts` — セキュリティ型定義追加

```typescript
export type SecurityLabel =
  | "forced_entry_attempt" | "vandalism" | "tampering" | "peering"
  | "approach_fast" | "circling" | "stay_near_vehicle" | "unknown_behavior";

export interface SecurityDetection {
  track_id: number;
  class_name: "person" | "vehicle";
  bbox: [number, number, number, number];
  confidence: number;
  owner_excluded: boolean;
}

export interface TriggerEvent {
  person_track_id: number;
  vehicle_track_id: number;
  distance_m: number;
  stay_duration_sec: number;
  repeat_count: number;
}

export interface ValidatedOutput {
  label: SecurityLabel;
  reason: string;
  is_fallback: boolean;
  raw_output: string;
}

export interface ScoringResult {
  risk_score: number;
  behavior_score: number;
  context_score: number;
  persistence_score: number;
  action: "notify" | "discard";
  label: SecurityLabel;
  reason: string;
}

export interface SecurityPipelineState {
  timestamp_ms: number;
  detections: SecurityDetection[];
  distances: Array<{ person_track_id: number; vehicle_track_id: number; distance_m: number }>;
  active_triggers: TriggerEvent[];
  owner_candidates: number[];
  latest_vlm: ValidatedOutput | null;
  latest_scoring: ScoringResult | null;
  annotated_image: string | null;
}

export interface SecurityConfig {
  threshold: number;
  distance_threshold_m: number;
  stay_duration_sec: number;
}

export const getSecurityConfig = () => api.get<SecurityConfig>("/api/security/config");
export const updateSecurityConfig = (cfg: Partial<SecurityConfig>) =>
  api.put<SecurityConfig>("/api/security/config", cfg);
```

---

#### Task 2-2: `frontend/src/components/SecurityDebugPanel.tsx` — デバッグパネル

**表示要素:**

| セクション | 表示内容 |
|---|---|
| 検知レイヤー | アノテーション済みフレーム（人: 黄枠、車: 青枠、除外: グレー） + 距離ライン |
| 検出リスト | track_id / クラス / 信頼度 / オーナー除外フラグ |
| トリガー状態 | 条件A（距離）/ 条件B（滞在時間）の充足状況、成立中トリガー一覧 |
| VLM解析結果 | ラベル / 根拠文 / is_fallback フラグ / 生出力（折りたたみ） |
| リスクスコア | スコアメーター（0-100）、behavior / context / persistence 内訳、action バッジ |
| イベントログ | 直近10件のスコアリング結果（タイムスタンプ付き） |

---

#### Task 2-3: `frontend/src/pages/SecurityPage.tsx` — セキュリティデバッグページ

**実装方針:**

- `useEffect` で `EventSource("/api/security/debug/stream")` を購読
- 受信した `SecurityPipelineState` を各表示コンポーネントへ渡す
- カメラ入力はサーバーカメラ（既存の `CameraManager`）を再利用
- 設定パネル: threshold / distance / duration を変更できる入力フォーム

**ページ構成（2カラム）:**

```
┌────────────────────────┬────────────────────────┐
│  アノテーション映像     │  スコアリング結果       │
│  (SSE 画像ストリーム)   │  リスクスコアメーター   │
├────────────────────────┼────────────────────────┤
│  検出リスト            │  VLM 解析パネル         │
│  トリガー状態          │  イベントログ           │
├────────────────────────┴────────────────────────┤
│  設定パネル (閾値・距離・滞在時間)               │
└─────────────────────────────────────────────────┘
```

---

#### Task 2-4: `frontend/src/App.tsx` — ナビゲーション追加

```tsx
<NavLink to="/security" style={({ isActive }) => linkStyle(isActive)}>
  セキュリティ
</NavLink>
// ...
<Route path="/security" element={<SecurityPage />} />
```

---

## 4. データフロー（実装後）

```
カメラ入力
  │
  ▼ (既存 CameraManager._capture_loop または WebSocket)
  │
  ▼ SecurityService.process_frame(frame)
  │
  ├─ ContinuousProcessor.process()
  │    └─ YoloDetector.detect_and_track()  [person + vehicle + ByteTrack]
  │    └─ 距離算出 (bbox bottom-center ユークリッド距離)
  │
  ├─ OwnerExclusionJudge.update()
  │    └─ owner_excluded フラグ付与
  │
  ├─ TriggerJudge.update()
  │    └─ 条件 A∧B → TriggerEvent 生成
  │
  ├─ [トリガー成立時のみ] VLMSecurityAnalyzer.submit()
  │    └─ キュー → 1スレッドで VLMBase.infer() 実行
  │    └─ OutputValidator.validate()
  │    └─ Scorer.calculate()
  │
  └─ PipelineState 更新
       │
       ▼ SSE /api/security/debug/stream
       │
       ▼ フロントエンド SecurityPage
```

---

## 5. 実装順序と依存関係

```
[1] config/security.yaml
    ↓
[2] yolo_detector.py (detect_and_track 追加)
    ↓
[3] backend/security/continuous_processor.py
[4] backend/security/owner_exclusion.py
[5] backend/security/trigger_judge.py
[6] backend/security/output_validator.py
[7] backend/security/scorer.py
    ↓
[8] backend/security/vlm_security_analyzer.py
    ↓
[9] backend/security/pipeline.py
[10] backend/security/__init__.py
    ↓
[11] backend/schemas/security_models.py
[12] backend/services/security_service.py
[13] backend/routers/security.py
[14] backend/main.py (router 登録)
    ↓
[15] frontend/src/api.ts (型追加)
[16] frontend/src/components/SecurityDebugPanel.tsx
[17] frontend/src/pages/SecurityPage.tsx
[18] frontend/src/App.tsx (ナビ追加)
```

---

## 6. 未確定事項（仕様書 §10 より）

以下は仕様書で「今後の確定事項」とされており、初期実装では近似値またはプレースホルダーで対応する。

| 項目 | 初期実装での対応 |
|---|---|
| 距離算出: カメラキャリブレーション行列 | ピクセル距離のみ。設定値でスケーリング係数を持ちメートル換算できる構造にするが、キャリブレーション値は `null` で距離 = ピクセル値のまま |
| VLM入力クリップ長・フレーム抽出間隔 | トリガー直前の単一フレームを入力（後でクリップ対応に拡張可能な設計） |
| オーナー除外の時間窓 | `security.yaml` の `detection_window_sec: 10.0` / `exclusion_duration_sec: 300.0` をデフォルトとし、実績データで調整 |
| behavior_score / 閾値の運用値調整方針 | `security.yaml` で変更可能にし、フロントエンド設定パネルからも更新可能にする |

---

## 7. チェックリスト

### Phase 1 — バックエンド

- [x] Task 1-1: `yolo_detector.py` — `detect_and_track()` 追加
- [x] Task 1-2: `config/security.yaml` 作成
- [x] Task 1-3: `continuous_processor.py`
- [x] Task 1-4: `owner_exclusion.py`
- [x] Task 1-5: `trigger_judge.py`
- [x] Task 1-6: `vlm_security_analyzer.py`
- [x] Task 1-7: `output_validator.py`
- [x] Task 1-8: `scorer.py`
- [x] Task 1-9: `pipeline.py`
- [x] Task 1-10: `backend/security/__init__.py`
- [x] Task 1-11: `backend/schemas/security_models.py`
- [x] Task 1-12: `backend/services/security_service.py`
- [x] Task 1-13: `backend/routers/security.py`
- [x] Task 1-14: `backend/main.py` ルーター登録

### Phase 2 — フロントエンド

- [x] Task 2-1: `api.ts` セキュリティ型追加
- [x] Task 2-2: `SecurityDebugPanel.tsx`
- [x] Task 2-3: `SecurityPage.tsx`
- [x] Task 2-4: `App.tsx` ナビ追加
