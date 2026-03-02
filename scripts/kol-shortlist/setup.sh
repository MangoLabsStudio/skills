#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/scripts" && pwd)"

echo "Creating venv at $SCRIPT_DIR/venv ..."
python3 -m venv "$SCRIPT_DIR/venv"

echo "Installing dependencies ..."
"$SCRIPT_DIR/venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

echo "Done. Set your API key:"
echo "  export APIDANCE_API_KEY=your_key_here"
