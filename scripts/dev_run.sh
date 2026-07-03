#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SNVR_DEVICE="${SNVR_DEVICE:-auto}"
export SNVR_DB_PATH="${SNVR_DB_PATH:-./data/snvr.db}"
export SNVR_SNAPSHOT_DIR="${SNVR_SNAPSHOT_DIR:-./data/snapshots}"
export SNVR_MODEL_DIR="${SNVR_MODEL_DIR:-./config/models}"
mkdir -p "$SNVR_SNAPSHOT_DIR" "$SNVR_MODEL_DIR" "$(dirname "$SNVR_DB_PATH")"
exec python -m uvicorn app.main:app --host "${SNVR_HOST:-0.0.0.0}" --port "${SNVR_PORT:-8080}" --reload
