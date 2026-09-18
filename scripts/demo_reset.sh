#!/usr/bin/env bash
# Reset the workbench to the rehearsal state: stop :8080, re-seed 150 reviews (demo cases excluded),
# recompute estimates, restart, wait for /healthz. ≈ 30 s. Held-back arrivals re-hold on restart.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8080}"
pid=$(ss -ltnp 2>/dev/null | grep ":${PORT} " | grep -o 'pid=[0-9]*' | cut -d= -f2 || true)
if [ -n "$pid" ]; then kill "$pid"; sleep 1; fi
uv run python scripts/seed_reviews.py --per-criterion "${PER_CRITERION:-25}" --seed 42 --wipe | tail -8
uv run auditpace estimate --coverage | tail -1
mkdir -p logs
nohup uv run auditpace workbench --port "$PORT" > logs/workbench.log 2>&1 &
for _ in $(seq 1 30); do
  sleep 1
  if curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null; then
    for _ in $(seq 1 "${PRE_RELEASE:-3}"); do curl -s -X POST "http://127.0.0.1:${PORT}/demo/release" >/dev/null; sleep 0.2; done
    curl -s "http://127.0.0.1:${PORT}/healthz"; echo
    echo "demo: http://127.0.0.1:${PORT}/queue?demo=1"
    exit 0
  fi
done
echo "workbench did not come up; see logs/workbench.log" >&2
exit 1
