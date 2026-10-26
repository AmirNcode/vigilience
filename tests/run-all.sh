#!/usr/bin/env bash
# Run every static check. Needs Docker (pulls the pinned HA image once).
set -euo pipefail
cd "$(dirname "$0")"
for t in secret-scan.sh compose-config-check.sh pin-gate-test.sh homelab-deploy-test.sh yaml-structure-check.sh probe-test.sh; do
  echo "──── $t"
  "./$t"
done
echo "──── all checks passed"
