#!/bin/sh
# One container: FalkorDB (bound to localhost only), the LeakTrace API, and the helpers.
# The graph lives in memory only (nothing is saved to disk), so every cold start begins empty and the demo
# customer is created and seeded again. Required: LEAKTRACE_SECRET, LEAKTRACE_DEMO_PASSWORD. Optional:
# LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (without them the helpers use the rule-based chooser). PORT is set by
# the host (default 7860).
set -eu

redis-server --bind 127.0.0.1 --port 6379 --protected-mode yes --save "" --appendonly no --dir /tmp \
  --loadmodule "${FALKORDB_BIN_PATH}/falkordb.so" ${FALKORDB_ARGS} --daemonize yes

i=0
until redis-cli -h 127.0.0.1 -p 6379 PING >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 50 ]; then echo "FalkorDB did not start" >&2; exit 1; fi
  sleep 0.2
done

export FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379
python -m app.cli ensure-demo --tenant "${LEAKTRACE_DEMO_TENANT:-demo}" --pack packs/datacenter/topology.json
python -m app.agents.worker --tenant "${LEAKTRACE_DEMO_TENANT:-demo}" --loop 5 &
exec python -m uvicorn app.api.main:app --host 0.0.0.0 --port "${PORT:-7860}"
