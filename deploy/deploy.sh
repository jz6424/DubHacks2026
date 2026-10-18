#!/usr/bin/env bash
# Build locally and push to the VM. Run from anywhere on your laptop:  bash deploy/deploy.sh
# First deploy only: SYNC_DATA=1 bash deploy/deploy.sh  (also uploads the demo job + club catalog). Later deploys leave
# the server's data alone, so visitors' research, the live catalog and the spend ledger are never overwritten.
# The repo is private, so the code travels from this machine: a `git archive` of what is committed (no local edits).
set -euo pipefail
export COPYFILE_DISABLE=1  # no macOS ._ metadata files in the tarballs
VM=${VM:-huskymatch}
ZONE=${ZONE:-us-west1-b}
SYNC_DATA=${SYNC_DATA:-0}
APP=/opt/huskymatch
cd "$(dirname "$0")/.."

echo "== building frontend"
npm --prefix frontend run build >/dev/null

echo "== packing"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git archive --format=tar.gz -o "$tmp/code.tgz" HEAD backend deploy prompts
tar -czf "$tmp/dist.tgz" -C frontend dist
# limits.db is this machine's spend ledger: never ship it, or local test spend would count against the live budget
tar -czf "$tmp/data.tgz" -C . --exclude 'data/huskymatch/limits.db' data/huskymatch
# Only the Anthropic key (and optional limit settings) go to the server: nothing else from the local .env.
grep -E '^ANTHROPIC_API_KEY=' .env > "$tmp/env"
for k in HUSKYMATCH_MAX_JOBS_PER_IP_PER_DAY HUSKYMATCH_DAILY_BUDGET_USD HUSKYMATCH_JOB_COST_RESERVE_USD; do
  grep -E "^$k=" .env >> "$tmp/env" || true
done
cp deploy/setup-vm.sh "$tmp/"

echo "== uploading"
gcloud compute scp --quiet --zone "$ZONE" "$tmp/code.tgz" "$tmp/dist.tgz" "$tmp/data.tgz" "$tmp/env" "$tmp/setup-vm.sh" "$VM":/tmp/ >/dev/null

echo "== updating the VM"
gcloud compute ssh --quiet "$VM" --zone "$ZONE" --command "sudo SYNC_DATA=$SYNC_DATA bash -s" <<'REMOTE'
set -euo pipefail
export COPYFILE_DISABLE=1  # no macOS ._ metadata files in the tarballs
APP=/opt/huskymatch
if ! command -v caddy >/dev/null || [ ! -x $APP/.venv/bin/python ]; then bash /tmp/setup-vm.sh; fi
cd $APP
# replace code (keeps .venv and data/), then the frontend build
rm -rf backend deploy prompts && tar -xzf /tmp/code.tgz -C $APP
rm -rf frontend/dist && mkdir -p frontend && tar -xzf /tmp/dist.tgz -C frontend
if [ "$SYNC_DATA" = "1" ]; then tar -xzf /tmp/data.tgz -C $APP; echo "data uploaded"; fi
install -m 600 /tmp/env .env
chown -R huskymatch:huskymatch $APP
sudo -u huskymatch -H bash -c "cd $APP && ~/.local/bin/uv pip install --quiet --python .venv/bin/python -r backend/requirements.txt"
install -m 644 deploy/huskymatch.service /etc/systemd/system/huskymatch.service
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable huskymatch >/dev/null 2>&1
systemctl restart huskymatch
systemctl reload caddy 2>/dev/null || systemctl restart caddy
rm -f /tmp/code.tgz /tmp/dist.tgz /tmp/data.tgz /tmp/env /tmp/setup-vm.sh
for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf localhost:8000/api/options >/dev/null && break; sleep 1; done
curl -sf localhost:8000/api/options >/dev/null && echo "API OK" || { journalctl -u huskymatch -n 40 --no-pager; exit 1; }
REMOTE
echo "== deployed"
