#!/usr/bin/env bash
# One-time VM setup (Debian 12): swap, Caddy, the app user and Python 3.12. Safe to re-run.
# deploy.sh runs this automatically on the first deploy; the code itself is uploaded by deploy.sh (the repo is private).
set -euo pipefail
APP=/opt/huskymatch

apt-get update -qq
apt-get install -y -qq curl debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null

# 1 GB of RAM on an e2-micro: add swap so installs and bursts don't get OOM-killed
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Caddy (official apt repository): HTTPS certificates are automatic
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

# App user, directories and uv (Debian 12 ships Python 3.11; the backend uses 3.12)
id huskymatch >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/huskymatch --shell /usr/sbin/nologin huskymatch
mkdir -p "$APP/data/huskymatch/jobs" "$APP/frontend"
chown -R huskymatch:huskymatch "$APP"
if [ ! -x /home/huskymatch/.local/bin/uv ]; then
  sudo -u huskymatch -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' >/dev/null
fi
if [ ! -x "$APP/.venv/bin/python" ]; then
  sudo -u huskymatch -H bash -c "cd $APP && ~/.local/bin/uv venv --quiet --python 3.12 .venv"
fi
systemctl enable caddy >/dev/null 2>&1
echo "VM setup done"
