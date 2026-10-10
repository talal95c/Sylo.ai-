#!/usr/bin/env bash
# Runs the engine and the web app together. Ctrl-C stops both.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
ENGINE_PORT="${ENGINE_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"
# Both services listen on this machine only; set WEB_HOST=0.0.0.0 to open the demo from another device.
WEB_HOST="${WEB_HOST:-localhost}"
export NEXT_PUBLIC_ENGINE_URL="${NEXT_PUBLIC_ENGINE_URL:-http://localhost:${ENGINE_PORT}}"

# Each service gets its own process group, so stopping it also stops the processes it spawned.
set -m
(cd engine && exec uv run uvicorn sylo.main:app --reload --port "$ENGINE_PORT") &
ENGINE_PID=$!
(cd web && exec pnpm dev --hostname "$WEB_HOST" --port "$WEB_PORT") &
WEB_PID=$!

stop() {
  trap - INT TERM EXIT
  # Signal uv itself, not its group: uv forwards the signal to uvicorn, and a second copy can deadlock uvicorn's reloader.
  kill -TERM "$ENGINE_PID" 2>/dev/null || true
  kill -TERM -- "-$WEB_PID" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 -- "-$ENGINE_PID" 2>/dev/null || kill -0 -- "-$WEB_PID" 2>/dev/null || break
    sleep 0.5
  done
  kill -KILL -- "-$ENGINE_PID" "-$WEB_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  echo "Stopped the engine and the web app."
}
trap 'stop; exit 130' INT
trap 'stop; exit 143' TERM
trap stop EXIT

cat <<EOF

Sylo.ai is starting:
  engine  http://localhost:${ENGINE_PORT}   (events: /v1/stream)
  web     http://${WEB_HOST}:${WEB_PORT}
Press Ctrl-C to stop both.

EOF

while kill -0 "$ENGINE_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 1
done
echo "One of the two services exited; stopping the other." >&2
