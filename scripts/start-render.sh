#!/usr/bin/env bash
set -uo pipefail

load_secret_files() {
  local secrets_dir="${SYLO_SECRETS_DIR:-/etc/secrets}"
  local file line key value current_value loaded
  [[ -d "$secrets_dir" ]] || return 0

  for file in "$secrets_dir"/*; do
    [[ -f "$file" ]] || continue
    loaded=0
    while IFS= read -r line || [[ -n "$line" ]]; do
      line=${line%$'\r'}
      line="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$line" || "$line" == \#* ]] && continue
      if [[ "$line" == export[[:space:]]* ]]; then
        line=${line#export}
        line="${line#"${line%%[![:space:]]*}"}"
      fi
      [[ "$line" == *=* ]] || continue

      key="${line%%=*}"
      value="${line#*=}"
      key="${key#"${key%%[![:space:]]*}"}"
      key="${key%"${key##*[![:space:]]}"}"
      [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

      value="${value#"${value%%[![:space:]]*}"}"
      value="${value%"${value##*[![:space:]]}"}"
      if [[ ${value:0:1} == '"' && ${value: -1} == '"' ]] ||
        [[ ${value:0:1} == "'" && ${value: -1} == "'" ]]; then
        value="${value:1:${#value}-2}"
      fi

      if [[ -v $key ]]; then
        current_value=${!key}
        [[ -n "$current_value" ]] && continue
      fi
      export "$key=$value"
      loaded=$((loaded + 1))
    done < "$file"
    printf 'loaded %d variables from %s\n' "$loaded" "$file" >&2
  done
}

load_secret_files

engine_pid=
web_pid=
guardian_pid=
shutdown_requested=false

if [[ -z "${OPERATOR_TOKEN:-}" ]]; then
  export OPERATOR_TOKEN
  OPERATOR_TOKEN="$(python -c 'import secrets;print(secrets.token_hex(24))')"
fi

forward_termination() {
  trap - TERM INT
  shutdown_requested=true
  if [[ -n "$guardian_pid" ]]; then
    kill -TERM "$guardian_pid" 2>/dev/null || true
  fi
  if [[ -n "$engine_pid" ]]; then
    kill -TERM "$engine_pid" 2>/dev/null || true
  fi
  if [[ -n "$web_pid" ]]; then
    kill -TERM "$web_pid" 2>/dev/null || true
  fi
}

trap forward_termination TERM INT

(cd /app/engine && exec uvicorn sylo.main:app --host 127.0.0.1 --port 8000 --workers 1) &
engine_pid=$!

engine_ready=false
for attempt in {1..360}; do
  if [[ "$shutdown_requested" == true ]] || ! kill -0 "$engine_pid" 2>/dev/null; then
    break
  fi
  if /app/engine/.venv/bin/python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1)' >/dev/null 2>&1; then
    engine_ready=true
    break
  fi
  sleep 0.5
done

if [[ "$engine_ready" != true ]]; then
  echo "Engine did not become healthy; refusing to start the web server" >&2
  forward_termination
  wait "$engine_pid" 2>/dev/null || true
  exit 1
fi

if [[ "${CHAIN_MODE:-mock}" == "fuji" && -n "${GUARDIAN_PK:-}" ]]; then
  (
    guardian_child_pid=
    guardian_sleep_pid=
    stop_guardian_loop() {
      trap - TERM INT
      if [[ -n "$guardian_child_pid" ]]; then
        kill -TERM "$guardian_child_pid" 2>/dev/null || true
        wait "$guardian_child_pid" 2>/dev/null || true
      fi
      if [[ -n "$guardian_sleep_pid" ]]; then
        kill -TERM "$guardian_sleep_pid" 2>/dev/null || true
        wait "$guardian_sleep_pid" 2>/dev/null || true
      fi
      exit 0
    }
    trap stop_guardian_loop TERM INT
    cd /app/chain || exit 1
    while true; do
      /app/engine/.venv/bin/python -m sylo_chain.guardian watch --engine-url http://127.0.0.1:8000 &
      guardian_child_pid=$!
      wait "$guardian_child_pid" || true
      guardian_child_pid=
      echo "guardian exited, restarting" >&2
      sleep 10 &
      guardian_sleep_pid=$!
      wait "$guardian_sleep_pid" || true
      guardian_sleep_pid=
    done
  ) &
  guardian_pid=$!
fi

(cd /app/web && exec env HOSTNAME=0.0.0.0 PORT="${PORT:-10000}" node server.js) &
web_pid=$!

wait -n "$engine_pid" "$web_pid"
forward_termination
wait "$engine_pid" 2>/dev/null || true
wait "$web_pid" 2>/dev/null || true
exit 1
