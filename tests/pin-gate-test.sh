#!/usr/bin/env bash
# Exercise the PIN gate against a fake upstream (stdlib Python, no Docker).
set -euo pipefail
cd "$(dirname "$0")"
python3 -I pin_gate_test.py
echo "PASS PIN gate tests"
