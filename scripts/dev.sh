#!/usr/bin/env bash
# Start the engine (:8000) and the web app (:3000). Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

ENGINE_PORT="${ENGINE_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
export NEXT_PUBLIC_ENGINE_URL="${NEXT_PUBLIC_ENGINE_URL:-http://localhost:$ENGINE_PORT}"

trap 'trap - INT TERM EXIT; kill 0' INT TERM EXIT

(cd "$ROOT/engine" && exec uv run uvicorn sylo.main:app --port "$ENGINE_PORT") &
(cd "$ROOT" && exec pnpm -C web dev --port "$WEB_PORT") &

echo
echo "  Sylo.ai engine   http://localhost:$ENGINE_PORT   (health: /health, events: /v1/stream)"
echo "  Sylo.ai web      http://localhost:$WEB_PORT"
echo "  Everything is simulated. Press Ctrl-C to stop both."
echo

wait
