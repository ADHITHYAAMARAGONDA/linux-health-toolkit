#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="${LOG_DIR:-/var/log/myapp}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [[ ! -d "$LOG_DIR" ]]; then
  echo "Log directory not found: $LOG_DIR" >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  find "$LOG_DIR" -type f -name '*.log' -mtime +"$RETENTION_DAYS" -print
else
  find "$LOG_DIR" -type f -name '*.log' -mtime +"$RETENTION_DAYS" -print -delete
fi
