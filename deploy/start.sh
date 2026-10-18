#!/bin/bash
# A small supervisor for one container: FalkorDB (localhost only), the LeakTrace API (which also serves the web
# app) and the helpers. If any of them stops, the others are stopped too and the container exits with an error,
# so the platform starts it again (fail loudly; never run half the system).
#
# Required: LEAKTRACE_SECRET, LEAKTRACE_DEMO_PASSWORD (shared practice password), LEAKTRACE_MANAGER_PASSWORD.
# Optional: FALKORDB_PERSIST=1 keeps an append-only file in FALKORDB_DATA_DIR (default /data; mount a volume);
# without it the graph lives in memory and every start rebuilds the practice data. PORT (default 8000).
set -u

TENANT="${LEAKTRACE_DEMO_TENANT:-demo}"
PIDS=()

stop_all() {
  kill -TERM "${PIDS[@]}" 2>/dev/null
  wait
}
trap 'stop_all; exit 0' TERM INT

if [ "${FALKORDB_PERSIST:-0}" = "1" ]; then
  DATA="${FALKORDB_DATA_DIR:-/data}"
  mkdir -p "$DATA"
  STORE=(--dir "$DATA" --appendonly yes --appendfsync everysec)
else
  STORE=(--dir /tmp --save "" --appendonly no)
fi

# shellcheck disable=SC2086
redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes "${STORE[@]}" \
  --loadmodule "${FALKORDB_BIN_PATH}/falkordb.so" ${FALKORDB_ARGS:-} ${FALKORDB_EXTRA_ARGS:-} &
PIDS+=($!)

for _ in $(seq 1 150); do
  redis-cli -h 127.0.0.1 -p 6379 PING >/dev/null 2>&1 && break
  sleep 0.2
done
if ! redis-cli -h 127.0.0.1 -p 6379 PING >/dev/null 2>&1; then
  echo "start: FalkorDB did not answer within 30 s" >&2
  stop_all
  exit 1
fi

# The web server starts now: until the practice data is ready, /health answers 503 and the screens say
# "waking up" instead of failing.
python -m uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
PIDS+=($!)

# ensure-demo on every start: leaves existing data alone, builds the practice story on an empty graph.
if ! python -m app.cli ensure-demo --tenant "$TENANT" --pack packs/datacenter/topology.json; then
  echo "start: ensure-demo failed (are LEAKTRACE_DEMO_PASSWORD and LEAKTRACE_MANAGER_PASSWORD set?)" >&2
  stop_all
  exit 1
fi

python -m app.agents.worker --tenant "$TENANT" --loop "${HELPER_LOOP_S:-5}" &
PIDS+=($!)

wait -n "${PIDS[@]}"
code=$?
echo "start: a process stopped (exit $code); stopping the container so it is started again" >&2
stop_all
exit 1
