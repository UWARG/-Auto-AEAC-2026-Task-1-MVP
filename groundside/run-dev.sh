#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BLUE=$'\033[1;34m'
GREEN=$'\033[1;32m'
YELLOW=$'\033[1;33m'
RESET=$'\033[0m'

kill_tree() {
  local pid="$1"
  local child

  if command -v pgrep >/dev/null 2>&1; then
    while IFS= read -r child; do
      [[ -n "$child" ]] && kill_tree "$child"
    done < <(pgrep -P "$pid" 2>/dev/null || true)
  fi

  kill -TERM "$pid" 2>/dev/null || true
}

pick_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
    return
  fi

  local candidates=(
    "$ROOT_DIR/venv/bin/python"
    "$ROOT_DIR/../venv/bin/python"
  )

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return
    fi
  done

  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return
  fi

  if command -v python >/dev/null 2>&1; then
    printf '%s\n' "python"
    return
  fi

  printf 'No Python interpreter found.\n' >&2
  exit 1
}

prefix_logs() {
  local label="$1"
  local color="$2"

  awk -v label="$label" -v color="$color" -v reset="$RESET" '
    {
      printf "%s[%s]%s %s\n", color, label, reset, $0
      fflush()
    }
  '
}

PYTHON_BIN="$(pick_python)"

if ! command -v pnpm >/dev/null 2>&1; then
  printf 'pnpm is required but was not found in PATH.\n' >&2
  exit 1
fi

printf '%s[info]%s backend:  http://127.0.0.1:5001\n' "$YELLOW" "$RESET"
printf '%s[info]%s frontend: http://127.0.0.1:5173\n' "$YELLOW" "$RESET"
printf '%s[info]%s press Ctrl+C to stop both services\n' "$YELLOW" "$RESET"

cleanup() {
  local exit_code=$?
  trap - HUP INT TERM EXIT

  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill_tree "$BACKEND_PID"
  fi

  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill_tree "$FRONTEND_PID"
  fi

  sleep 0.2

  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill -KILL "$BACKEND_PID" 2>/dev/null || true
  fi

  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill -KILL "$FRONTEND_PID" 2>/dev/null || true
  fi

  wait 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup HUP INT TERM EXIT

(
  cd "$BACKEND_DIR"
  "$PYTHON_BIN" app.py 2>&1 | prefix_logs "backend" "$BLUE"
) &
BACKEND_PID=$!

(
  cd "$FRONTEND_DIR"
  pnpm dev 2>&1 | prefix_logs "frontend" "$GREEN"
) &
FRONTEND_PID=$!

backend_reported_dead=0
frontend_reported_dead=0

while true; do
  if [[ "$backend_reported_dead" -eq 0 ]] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    backend_reported_dead=1
    printf '%s[warn]%s backend process exited; script will keep running until Ctrl+C.\n' "$YELLOW" "$RESET"
  fi

  if [[ "$frontend_reported_dead" -eq 0 ]] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    frontend_reported_dead=1
    printf '%s[warn]%s frontend process exited; script will keep running until Ctrl+C.\n' "$YELLOW" "$RESET"
  fi

  sleep 1
done
