#!/usr/bin/env bash
# start.sh — バックエンド + フロントエンドを起動する開発用スクリプト
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# プロキシから localhost / 127.0.0.1 を除外
export NO_PROXY="localhost,127.0.0.1"
export no_proxy="localhost,127.0.0.1"

# venv をアクティベート (存在する場合)
if [ -f "$ROOT/venv/bin/activate" ]; then
  source "$ROOT/venv/bin/activate"
fi

echo "==> Starting FastAPI backend on http://localhost:8000 ..."
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "==> Starting React frontend on http://localhost:5173 ..."
cd "$ROOT/frontend" && npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend : http://localhost:8000"
echo "  Swagger : http://localhost:8000/docs"
echo "  Frontend: http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop all processes."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
