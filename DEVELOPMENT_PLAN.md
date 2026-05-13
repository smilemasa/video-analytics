# Video Analytics — 開発計画

## API 仕様

### 1. システム管理

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/health` | ヘルスチェック |
| `GET` | `/api/models` | 利用可能なVLMモデル一覧 |

#### `GET /api/health`

```json
// Response 200
{
  "status": "ok"
}
```

#### `GET /api/models`

```json
// Response 200
{
  "models": [
    "vikhyatk/moondream2",
    "Salesforce/blip-image-captioning-large",
    "Qwen/Qwen2-VL-2B-Instruct"
  ]
}
```

---

### 2. 設定管理

| Method | Endpoint | 説明 |
|--------|----------|------|
| `GET` | `/api/settings/model` | 現在ロード中のモデルを取得 |
| `POST` | `/api/settings/model` | VLMモデルの切り替え |
| `GET` | `/api/settings/yolo-classes` | 現在のYOLO検出クラスを取得 |
| `POST` | `/api/settings/yolo-classes` | YOLO検出クラスの設定 |
| `GET` | `/api/settings/prompt` | 現在のプロンプトを取得 |
| `PUT` | `/api/settings/prompt` | VLM解析プロンプトの変更 |

#### `GET /api/settings/model`

```json
// Response 200
{
  "model_id": "vikhyatk/moondream2",
  "status": "loaded"  // "loaded" | "loading" | "error"
}
```

#### `POST /api/settings/model`

```json
// Request
{ "model_id": "Salesforce/blip-image-captioning-large" }

// Response 200
{ "model_id": "Salesforce/blip-image-captioning-large", "status": "loading" }
```

#### `GET /api/settings/yolo-classes`

```json
// Response 200
{
  "mode": "Person",
  "classes": [0]
}
```

#### `POST /api/settings/yolo-classes`

```json
// Request
{ "mode": "Vehicles", "classes": [2, 3, 5, 7] }

// Response 200
{ "mode": "Vehicles", "classes": [2, 3, 5, 7] }
```

#### `GET /api/settings/prompt`

```json
// Response 200
{ "prompt": "画像を説明してください。" }
```

#### `PUT /api/settings/prompt`

```json
// Request
{ "prompt": "この画像に映っている人数を教えてください。" }

// Response 200
{ "prompt": "この画像に映っている人数を教えてください。" }
```

---

### 3. 静的解析

| Method | Endpoint | 説明 |
|--------|----------|------|
| `POST` | `/api/static/image` | 画像アップロード → YOLO+VLM解析 |
| `POST` | `/api/static/video` | 動画アップロード → バックグラウンドジョブ登録 |
| `GET` | `/api/static/video/{job_id}/status` | 動画解析ジョブの進捗確認 |
| `GET` | `/api/static/video/{job_id}/result` | 動画解析結果取得 |

#### `POST /api/static/image`

```
// Request: multipart/form-data
file: <画像ファイル> (jpg/png)

// Response 200
{
  "annotated_image": "<base64エンコードされた解析済み画像>",
  "detections": [
    { "class_id": 0, "label": "person", "confidence": 0.92, "bbox": [x1, y1, x2, y2] }
  ],
  "vlm_result": "画像には3人の人物が映っています。",
  "detection_count": 1
}
```

#### `POST /api/static/video`

```
// Request: multipart/form-data
file: <動画ファイル> (mp4/avi/mov)

// Response 202
{
  "job_id": "abc123",
  "status": "queued"
}
```

#### `GET /api/static/video/{job_id}/status`

```json
// Response 200
{
  "job_id": "abc123",
  "status": "processing",  // "queued" | "processing" | "done" | "error"
  "progress": 45           // 0〜100 (%)
}
```

#### `GET /api/static/video/{job_id}/result`

```json
// Response 200
{
  "job_id": "abc123",
  "status": "done",
  "frames": [
    {
      "timestamp": 1.0,
      "annotated_image": "<base64>",
      "detections": [...],
      "vlm_result": "..."
    }
  ]
}
```

---

### 4. ライブ解析

| Method | Endpoint | 説明 |
|--------|----------|------|
| `WebSocket` | `/ws/live` | ブラウザ→フレーム送信、サーバー→解析結果返却 |
| `GET` | `/api/live/camera/status` | サーバーカメラの状態確認 |
| `POST` | `/api/live/camera/start` | サーバーカメラ起動 |
| `POST` | `/api/live/camera/stop` | サーバーカメラ停止 |
| `GET` | `/api/live/camera/stream` | SSEでサーバーカメラ映像+解析結果ストリーム |

#### `WebSocket /ws/live`

```
// Client → Server (binary or base64 JPEG フレーム)
{ "frame": "<base64 JPEG>" }

// Server → Client
{
  "annotated_image": "<base64 JPEG>",
  "detections": [...],
  "vlm_result": "...",
  "fps": 15.2
}
```

#### `GET /api/live/camera/status`

```json
// Response 200
{
  "active": true,
  "camera_index": 0,
  "fps": 30
}
```

#### `POST /api/live/camera/start`

```json
// Request
{ "camera_index": 0 }

// Response 200
{ "active": true, "camera_index": 0 }
```

#### `POST /api/live/camera/stop`

```json
// Response 200
{ "active": false }
```

#### `GET /api/live/camera/stream`

```
// Response: text/event-stream (SSE)
data: { "annotated_image": "<base64 JPEG>", "detections": [...], "vlm_result": "..." }
data: { ... }
...
```

---

## 作業計画

### Phase 1: FastAPI バックエンド構築

#### 1-0. API Doc・ディレクトリ構成

- [ ] API仕様書の作成（`openapi.yaml`）
- [ ] `backend/` ディレクトリ構成の作成

  ```
  backend/
  ├── main.py            # FastAPI エントリポイント
  ├── routers/
  │   ├── __init__.py
  │   ├── system.py      # /api/health, /api/models
  │   ├── settings.py    # /api/settings/*
  │   ├── static.py      # /api/static/*
  │   └── live.py        # /api/live/*, /ws/live
  ├── services/
  │   ├── __init__.py
  │   ├── analyzer.py    # VLMAnalyzer ラッパー
  │   └── job_manager.py # 動画ジョブ管理
  └── schemas/
      ├── __init__.py
      └── models.py      # Pydantic スキーマ定義
  ```

#### 1-1. システム管理 API

- [ ] `GET /api/health`
- [ ] `GET /api/models`

#### 1-2. 設定管理 API

- [ ] `GET /api/settings/model`
- [ ] `POST /api/settings/model`
- [ ] `GET /api/settings/yolo-classes`
- [ ] `POST /api/settings/yolo-classes`
- [ ] `GET /api/settings/prompt`
- [ ] `PUT /api/settings/prompt`

#### 1-3. 静的解析 API

- [ ] `POST /api/static/image`
- [ ] `POST /api/static/video`
- [ ] `GET /api/static/video/{job_id}/status`
- [ ] `GET /api/static/video/{job_id}/result`

#### 1-4. ライブ解析 API

- [ ] `WebSocket /ws/live`
- [ ] `GET /api/live/camera/status`
- [ ] `POST /api/live/camera/start`
- [ ] `POST /api/live/camera/stop`
- [ ] `GET /api/live/camera/stream`

#### 1-5. 共通設定

- [ ] CORS 設定
- [ ] FastAPI 依存関係インストール（`fastapi`, `uvicorn`, `python-multipart`）

#### ✅ Phase 1 動作確認チェック

- [ ] `uvicorn backend.main:app --reload` でサーバー起動確認
- [ ] Swagger UI（`http://localhost:8000/docs`）が表示される
- [ ] `GET /api/health` → `{"status": "ok"}` が返る
- [ ] `GET /api/models` → モデル一覧が返る
- [ ] `GET /api/settings/model` → 現在のモデルが返る
- [ ] `POST /api/settings/model` → モデル切り替えが反映される
- [ ] `GET /api/settings/yolo-classes` → 現在のクラスが返る
- [ ] `POST /api/settings/yolo-classes` → クラス変更が反映される
- [ ] `GET /api/settings/prompt` / `PUT /api/settings/prompt` → プロンプト取得・更新できる
- [ ] `POST /api/static/image` → 画像をアップロードし、bounding box付き画像とVLM結果が返る
- [ ] `POST /api/static/video` → 動画をアップロードし、`job_id` が返る
- [ ] `GET /api/static/video/{job_id}/status` → 進捗が取得できる
- [ ] `GET /api/static/video/{job_id}/result` → 完了後に結果が取得できる
- [ ] `WebSocket /ws/live` → フレームを送信し、解析結果が返ってくる
- [ ] `POST /api/live/camera/start` → サーバーカメラが起動する
- [ ] `GET /api/live/camera/stream` → SSEでフレームが流れてくる
- [ ] `POST /api/live/camera/stop` → サーバーカメラが停止する

---

### Phase 2: React フロントエンド構築

#### 2-1. プロジェクト初期化

- [ ] Vite + React + TypeScript プロジェクト作成
- [ ] axios / react-query などの依存関係インストール
- [ ] ルーティング設定（react-router-dom）

#### 2-2. 共通コンポーネント

- [ ] ヘッダー・ナビゲーション
- [ ] モデル切り替えUI（`/api/settings/model`）
- [ ] YOLOクラス選択UI（`/api/settings/yolo-classes`）
- [ ] プロンプト入力UI（`/api/settings/prompt`）

#### 2-3. 静的解析ページ

- [ ] 画像ドラッグ&ドロップアップロード
- [ ] 動画アップロード + 進捗バー
- [ ] 解析結果画像表示（bounding box付き）
- [ ] VLMテキスト結果表示

#### 2-4. ライブ解析ページ

- [ ] ブラウザWebカメラ取得（WebSocket送信）
- [ ] サーバーカメラストリーム表示（SSE受信）
- [ ] リアルタイム解析結果オーバーレイ表示

#### ✅ Phase 2 動作確認チェック

- [ ] React アプリが `http://localhost:5173` で起動する
- [ ] ヘッダーのモデル切り替えでVLMモデルが変更できる
- [ ] YOLOクラス選択が反映される
- [ ] プロンプトを変更して保存できる
- [ ] 静的解析ページ：画像をアップロードし、bounding box付き画像が表示される
- [ ] 静的解析ページ：VLMテキスト結果が表示される
- [ ] 静的解析ページ：動画をアップロードし、進捗バーが動作する
- [ ] 静的解析ページ：動画解析完了後に結果が表示される
- [ ] ライブ解析ページ：ブラウザWebカメラが起動し、解析結果がオーバーレイ表示される
- [ ] ライブ解析ページ：サーバーカメラのSSEストリームが表示される

---

### Phase 3: 統合・動作確認

- [ ] バックエンド・フロントエンドの疎通確認
- [ ] エラーハンドリング整備（ローディング・エラー表示）
- [ ] レスポンスタイム確認・調整

#### ✅ Phase 3 動作確認チェック

- [ ] フロントエンドからバックエンドへの全APIリクエストが正常に通る
- [ ] ネットワークエラー時にUI上でエラーメッセージが表示される
- [ ] モデルロード中にローディングインジケーターが表示される
- [ ] 静的解析の画像・動画アップロードがE2Eで正常動作する
- [ ] ライブ解析（WebSocket/SSE）がE2Eで正常動作する
- [ ] ページリロード後も設定（モデル・クラス・プロンプト）が維持される
