#!/usr/bin/env bash
# Build locally and push to the VM. Run from the repo root on your laptop:  bash deploy/deploy.sh
# First deploy only: SYNC_DATA=1 bash deploy/deploy.sh  (uploads the demo job + club catalog). Later deploys leave the
# server's data alone, so visitors' research and the live catalog are never overwritten.
# Needs: gcloud signed in, project set, and the VM created (see deploy/README.md).
set -euo pipefail
VM=${VM:-huskymatch}
SYNC_DATA=${SYNC_DATA:-0}
ZONE=${ZONE:-us-west1-b}
APP=/opt/huskymatch
cd "$(dirname "$0")/.."

echo "== building frontend"
npm --prefix frontend run build

echo "== packing frontend + data (data/ is gitignored, so it travels separately)"
tmp=$(mktemp -d)
tar -czf "$tmp/dist.tgz" -C frontend dist
# limits.db is this machine's spend ledger: never ship it, or local test spend would count against the live budget
tar -czf "$tmp/data.tgz" -C . --exclude 'data/huskymatch/limits.db' data/huskymatch
# Only the Anthropic key goes to the server: nothing else from the local .env.
grep -E '^ANTHROPIC_API_KEY=' .env > "$tmp/env"
for k in HUSKYMATCH_MAX_JOBS_PER_IP_PER_DAY HUSKYMATCH_DAILY_BUDGET_USD; do grep -E "^$k=" .env >> "$tmp/env" || true; done

gcloud compute scp --zone "$ZONE" "$tmp/dist.tgz" "$tmp/data.tgz" "$tmp/env" "$VM":/tmp/
rm -rf "$tmp"

echo "== updating the VM"
gcloud compute ssh "$VM" --zone "$ZONE" --command "sudo bash -s" <<REMOTE
set -euo pipefail
cd $APP
sudo -u huskymatch git fetch --quiet origin && sudo -u huskymatch git reset --quiet --hard origin/huskymatch
rm -rf frontend/dist && tar -xzf /tmp/dist.tgz -C frontend
if [ "$SYNC_DATA" = "1" ]; then tar -xzf /tmp/data.tgz -C .; echo "data uploaded"; fi
install -m 600 /tmp/env .env
chown -R huskymatch:huskymatch $APP
sudo -u huskymatch -H bash -c "cd $APP && ~/.local/bin/uv pip install --quiet --python .venv/bin/python -r backend/requirements.txt"
install -m 644 deploy/huskymatch.service /etc/systemd/system/huskymatch.service
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl restart huskymatch
systemctl reload caddy || systemctl restart caddy
rm -f /tmp/dist.tgz /tmp/data.tgz /tmp/env
sleep 2
curl -sf localhost:8000/api/options >/dev/null && echo "API OK" || (journalctl -u huskymatch -n 30 --no-pager; exit 1)
REMOTE
echo "== deployed"
