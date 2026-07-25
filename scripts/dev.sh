#!/usr/bin/env bash
# Elysium development loop *without* the desktop shell:
# starts the AI engine (from its venv) and the frontend dev server, so UI and
# API work can iterate in a plain browser.
#
# NOTE: for the full desktop experience run `pnpm tauri dev` (from frontend/,
# or `cargo tauri dev` from src-tauri/). The Tauri app spawns and supervises
# its OWN engine sidecar with a fresh token — do not run this script at the
# same time on the same port.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/ai-engine"
FRONTEND_DIR="$REPO_ROOT/frontend"
VENV_DIR="$ENGINE_DIR/.venv"

ELYSIUM_PORT="${ELYSIUM_PORT:-8721}"
# Dev-only token; the desktop app generates a random one per session.
ELYSIUM_TOKEN="${ELYSIUM_TOKEN:-$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')}"

fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$VENV_DIR/Scripts/python.exe" # Windows (Git Bash)
[ -x "$VENV_PY" ] || fail "ai-engine/.venv not found — run scripts/setup.sh first"

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  info "Shutting down"
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

info "Starting AI engine on 127.0.0.1:$ELYSIUM_PORT"
info "ELYSIUM_TOKEN=$ELYSIUM_TOKEN"
(
  cd "$ENGINE_DIR"
  ELYSIUM_TOKEN="$ELYSIUM_TOKEN" ELYSIUM_PORT="$ELYSIUM_PORT" \
    exec "$VENV_PY" -m elysium_engine
) &
PIDS+=("$!")

if [ -f "$FRONTEND_DIR/package.json" ]; then
  info "Starting frontend dev server (pnpm dev)"
  (
    cd "$FRONTEND_DIR"
    VITE_ELYSIUM_PORT="$ELYSIUM_PORT" VITE_ELYSIUM_TOKEN="$ELYSIUM_TOKEN" \
      exec pnpm dev
  ) &
  PIDS+=("$!")
else
  info "frontend/package.json not found — engine only"
fi

echo
echo "Engine:   http://127.0.0.1:$ELYSIUM_PORT  (Authorization: Bearer \$ELYSIUM_TOKEN)"
echo "Frontend: see the Vite output above (usually http://localhost:1420)"
echo "Desktop:  run 'pnpm tauri dev' instead for the real app shell."
echo "Press Ctrl-C to stop."

wait
