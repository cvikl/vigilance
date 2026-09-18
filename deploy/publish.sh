#!/usr/bin/env bash
# Publish the vigilance workbench to the shared Hetzner box → https://vigilance.legislabs.uk
#   bash deploy/publish.sh            # code + docs + data, build, start, caddy drop-in, reload, health
#   DATA=0 bash deploy/publish.sh     # skip the 1.5 GB data sync (code-only redeploy)
# Conventions (compass/DEPLOY.md §0): app in /opt/vigilance, never touch /opt/compass, Caddy drop-ins in
# /opt/caddy-sites, zero-downtime `caddy reload`, never `docker compose down -v`.
set -euo pipefail
HOST=${SERVER:-root@37.27.202.168}
APP_DIR=/opt/vigilance
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for f in protocol.yaml config.yaml docs/demo_cases.txt data/processed/verdicts data/processed/cases.parquet; do
  [ -e "$ROOT/$f" ] || { echo "missing $ROOT/$f — restore the data first (docs/rebuild.md)"; exit 1; }
done

echo "==> code → $HOST:$APP_DIR"
ssh "$HOST" "mkdir -p $APP_DIR/data/processed $APP_DIR/docs"
rsync -az --delete --exclude __pycache__ "$ROOT/src" "$ROOT/scripts" "$ROOT/deploy" "$ROOT/protocol.yaml" "$ROOT/config.yaml" "$HOST:$APP_DIR/"
rsync -az "$ROOT/docs/demo_cases.txt" "$HOST:$APP_DIR/docs/"
for f in docs/report.md docs/report.fallback.md; do [ -f "$ROOT/$f" ] && rsync -az "$ROOT/$f" "$HOST:$APP_DIR/docs/"; done

if [ "${DATA:-1}" = "1" ]; then
  echo "==> data → $HOST:$APP_DIR/data/processed (pages are the bulk; rsync resumes)"
  rsync -az --exclude quarantine "$ROOT/data/processed/" "$HOST:$APP_DIR/data/processed/"
fi

echo "==> build + start"
ssh "$HOST" "cd $APP_DIR/deploy && docker compose build vigilance && docker compose up -d vigilance"

echo "==> caddy drop-in + reload"
rsync -az "$ROOT/deploy/vigilance.caddy" "$HOST:/opt/caddy-sites/vigilance.caddy"
ssh "$HOST" "cd /opt/compass/deploy && docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile"

echo "==> health"
sleep 4
ssh "$HOST" "docker exec vigilance python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8030/healthz').read().decode()[:160])\""
curl -sS -o /dev/null -w "https://vigilance.legislabs.uk/home   HTTP %{http_code}\n" --max-time 30 https://vigilance.legislabs.uk/home || echo "  (first HTTPS hit may lag while Let's Encrypt issues the cert — retry in ~30 s)"
curl -sS -o /dev/null -w "https://vigilance.legislabs.uk/queue  HTTP %{http_code}\n" --max-time 30 https://vigilance.legislabs.uk/queue || true
curl -sS -o /dev/null -w "https://legislabs.uk/                 HTTP %{http_code} (site untouched)\n" --max-time 30 https://legislabs.uk/ || true
echo "done — https://vigilance.legislabs.uk/home"
