#!/usr/bin/env bash
# Elysium one-time development setup.
# - installs frontend dependencies (pnpm)
# - creates the AI engine virtualenv and installs it in editable mode
#
# Prerequisites: Node 20+, pnpm, Python 3.11+, Rust (for `pnpm tauri dev`).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
ENGINE_DIR="$REPO_ROOT/ai-engine"
VENV_DIR="$ENGINE_DIR/.venv"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- prerequisite checks ----------------------------------------------------
command -v node >/dev/null 2>&1 || fail "Node.js not found (Node 20+ required)"
command -v pnpm >/dev/null 2>&1 || fail "pnpm not found (https://pnpm.io/installation)"

PYTHON_BIN="${PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "python3 not found (Python 3.11+ required)"

if ! command -v cargo >/dev/null 2>&1; then
  warn "Rust toolchain not found — needed for 'pnpm tauri dev' (https://rustup.rs)"
fi

# --- frontend ---------------------------------------------------------------
if [ -f "$FRONTEND_DIR/package.json" ]; then
  info "Installing frontend dependencies"
  pnpm --dir "$FRONTEND_DIR" install
else
  warn "frontend/package.json not found — skipping frontend install"
fi

# --- AI engine --------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  info "Creating Python virtualenv at ai-engine/.venv"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$VENV_DIR/Scripts/python.exe" # Windows (Git Bash)

info "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip >/dev/null

if [ -f "$ENGINE_DIR/pyproject.toml" ]; then
  info "Installing elysium_engine (editable, with dev extras if defined)"
  "$VENV_PY" -m pip install -e "$ENGINE_DIR[dev]" 2>/dev/null \
    || "$VENV_PY" -m pip install -e "$ENGINE_DIR"
elif [ -f "$ENGINE_DIR/requirements.txt" ]; then
  info "Installing ai-engine requirements"
  "$VENV_PY" -m pip install -r "$ENGINE_DIR/requirements.txt"
else
  warn "ai-engine has no pyproject.toml or requirements.txt yet — skipping install"
fi

info "Setup complete."
echo
echo "Next steps:"
echo "  scripts/dev.sh        # engine + frontend dev servers (browser mode)"
echo "  pnpm tauri dev                  # full desktop app, from the repo root"
