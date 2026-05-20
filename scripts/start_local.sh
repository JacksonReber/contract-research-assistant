#!/usr/bin/env bash
# Start backend (uvicorn :8000) + frontend (vite :3000) for local dev.
# Usage: ./scripts/start_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env.local ]; then
  echo "No .env.local found — copy .env.example and fill in DATABRICKS_HOST + DATABRICKS_TOKEN"
  exit 1
fi

set -a; source .env.local; set +a

# Backend
uv run uvicorn server.start_server:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
trap "kill $BACKEND_PID 2>/dev/null || true" EXIT

# Frontend
cd client
if [ ! -d node_modules ]; then npm install --silent; fi
npm run dev
