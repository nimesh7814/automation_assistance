#!/usr/bin/env bash
set -eu

mkdir -p "${LOG_DIR:-/app/logs}"

cd /app/api
uvicorn main:app --host 0.0.0.0 --port 8000 &
api_pid="$!"

cd /app/ui
streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.maxUploadSize=200 \
  --server.headless=true &
ui_pid="$!"

trap 'kill "$api_pid" "$ui_pid" 2>/dev/null || true' INT TERM

wait -n "$api_pid" "$ui_pid"
exit_code="$?"
kill "$api_pid" "$ui_pid" 2>/dev/null || true
exit "$exit_code"
