#!/usr/bin/env bash
# Start the trip dashboard. Creates the venv and installs deps on first run.
set -euo pipefail
cd "$(dirname "$0")"

PY=./.venv/bin/python
PORT="${PORT:-8000}"

if [ ! -x "$PY" ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
  $PY -m pip install --quiet --upgrade pip
fi

if ! $PY -c "import fastapi" 2>/dev/null; then
  echo "Installing dependencies..."
  $PY -m pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  echo "No .env found. Running with sample data."
  echo "  cp .env.example .env  and add SPLITWISE_API_KEY to use your own."
fi

echo "Dashboard on http://localhost:${PORT}"
exec $PY -m uvicorn app.main:app --reload --port "$PORT"
