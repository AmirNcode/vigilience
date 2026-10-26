#!/usr/bin/env bash
# Exercise scripts/homelab_deploy.py with a fake runner (stdlib Python, no Docker/SSH).
set -euo pipefail
cd "$(dirname "$0")"
python3 -I homelab_deploy_test.py
echo "PASS homelab-deploy tests"
