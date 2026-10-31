#!/usr/bin/env bash
# One command to set up (first run only) and start the app on macOS or Linux:  ./start.sh
# Options:  ./start.sh --demo   try it with invented data      ./start.sh --port 9000
set -euo pipefail
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. $2" >&2; exit 1; }; }
need uv   "Install it: https://docs.astral.sh/uv/getting-started/installation/"
need node "Install Node.js 20 or newer: https://nodejs.org/"
need npm  "It comes with Node.js: https://nodejs.org/"

if [ ! -d backend/.venv ]; then
  echo "== Installing Python packages (first run only)"
  (cd backend && uv sync)
fi
if [ ! -d frontend/node_modules ]; then
  echo "== Installing interface packages (first run only)"
  (cd frontend && npm install)
fi
if [ ! -f frontend/dist/index.html ]; then
  echo "== Building the interface (first run only)"
  (cd frontend && npm run build)
fi

cd backend
exec uv run utcoursesplus serve --open "$@"
