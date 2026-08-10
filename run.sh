#!/usr/bin/env bash
# One-command launcher: sets up a virtualenv on first run, installs
# dependencies, starts the server, and opens it in your browser.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/app"
VENV_DIR="$SCRIPT_DIR/.venv"
URL="http://127.0.0.1:5055"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Setting up virtual environment (first run only)..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet -r "$APP_DIR/requirements.txt"

echo "Starting Internet Diagnostic Monitor at $URL"
echo "Press Ctrl+C to stop."

if command -v open >/dev/null 2>&1; then
  ( sleep 1 && open "$URL" ) &
fi

cd "$APP_DIR"
exec python3 server.py
