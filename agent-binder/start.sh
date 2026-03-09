#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/../backend-python"
FRONTEND="$SCRIPT_DIR"

# Activate venv
source "$BACKEND/venv/bin/activate" || { echo "Run: cd backend-python && python -m venv venv && pip install -r requirements.txt"; exit 1; }

# Load .env into environment before starting backend
cd "$BACKEND"
if [ -f .env ] && [ -s .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  echo "Loaded .env"
else
  echo "WARN: .env missing or empty — add OPENAI_API_KEY, ANTHROPIC_API_KEY, and optionally TAMARIND_API_KEY"
fi
export DEMO_MODE=true
echo "DEMO_MODE=true — running fail/fail/pass hardcoded data"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Cleanup on exit
cleanup() { kill $BACKEND_PID 2>/dev/null; exit 0; }
trap cleanup SIGINT SIGTERM

# Start frontend in foreground
cd "$FRONTEND"
npm run dev
