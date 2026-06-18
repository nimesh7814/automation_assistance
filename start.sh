#!/usr/bin/env bash
set -eu

base_log_dir="${LOG_DIR:-/app/logs}"
mkdir -p "$base_log_dir/api" "$base_log_dir/ui"
export LOG_ROOT="${LOG_ROOT:-$base_log_dir}"

cd /app/api
LOG_DIR="$base_log_dir/api" uvicorn main:app --host 0.0.0.0 --port 8000 &
api_pid="$!"

cd /app/ui
LOG_DIR="$base_log_dir/ui" streamlit run app.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --server.maxUploadSize=200 \
  --server.headless=true &
ui_pid="$!"

cd /app/logger
uvicorn app:app --host 0.0.0.0 --port 8888 &
logger_pid="$!"

trap 'kill "$api_pid" "$ui_pid" "$logger_pid" 2>/dev/null || true' INT TERM

wait -n "$api_pid" "$ui_pid" "$logger_pid"
exit_code="$?"
kill "$api_pid" "$ui_pid" "$logger_pid" 2>/dev/null || true
exit "$exit_code"
