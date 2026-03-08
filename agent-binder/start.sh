#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$SCRIPT_DIR/../backend-python"
FRONTEND="$SCRIPT_DIR"

# Activate venv
source "$BACKEND/venv/bin/activate" || { echo "Run: cd backend-python && python -m venv venv && pip install -r requirements.txt"; exit 1; }

# Start backend in background, capture PID
cd "$BACKEND"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Cleanup on exit
cleanup() { kill $BACKEND_PID 2>/dev/null; exit 0; }
trap cleanup SIGINT SIGTERM

# Start frontend in foreground
cd "$FRONTEND"
npm run dev
