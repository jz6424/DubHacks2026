#!/usr/bin/env bash
# One-time VM setup (Debian 12). Run on the VM as root: sudo bash setup-vm.sh
set -euo pipefail
REPO=https://github.com/jz6424/DubHacks2026.git
BRANCH=huskymatch
APP=/opt/huskymatch

apt-get update
apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https gnupg

# 1 GB of RAM on an e2-micro: add swap so installs and bursts don't get OOM-killed
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Caddy (official apt repository)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi

# App user and code
id huskymatch >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/huskymatch --shell /usr/sbin/nologin huskymatch
if [ ! -d "$APP/.git" ]; then git clone --branch "$BRANCH" "$REPO" "$APP"; fi
mkdir -p "$APP/data/huskymatch/jobs" "$APP/frontend/dist"
chown -R huskymatch:huskymatch "$APP"

# Python 3.12 via uv (Debian 12 ships 3.11; the backend uses 3.12 syntax)
sudo -u huskymatch -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u huskymatch -H bash -c "cd $APP && ~/.local/bin/uv venv --python 3.12 .venv && ~/.local/bin/uv pip install --python .venv/bin/python -r backend/requirements.txt"

install -m 644 "$APP/deploy/huskymatch.service" /etc/systemd/system/huskymatch.service
install -m 644 "$APP/deploy/Caddyfile" /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable huskymatch caddy
echo "Setup done. Next: copy .env, frontend/dist and data, then: systemctl restart huskymatch caddy"
