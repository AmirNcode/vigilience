#!/usr/bin/env bash
# Optional convenience wrapper, run explicitly on the MacBook:
#
#   VIG_SSH=linus@<server-lan-ip> ./scripts/deploy-from-mac.sh
#
# Refuses to run unless local main is clean and already pushed, then runs the
# server-side deploy script over SSH. Nothing here runs automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

host="${VIG_SSH:?set VIG_SSH=user@host (or an ~/.ssh/config alias)}"
remote_dir="${VIG_REMOTE_DIR:-/home/linus/vigilience}"

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || { echo "not on main" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "working tree not clean" >&2; exit 1; }
git fetch --quiet origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "local main != origin/main; push first" >&2; exit 1; }

echo "==> Deploying $(git log -1 --format='%h %s') to $host:$remote_dir"
ssh -t "$host" "cd '$remote_dir' && ./scripts/deploy.sh"
