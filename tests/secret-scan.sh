#!/usr/bin/env bash
# Fail if files that would be committed contain secrets or private network
# details. Scans tracked + staged + untracked-but-not-ignored files.
set -euo pipefail
cd "$(dirname "$0")/.."

files="$(git ls-files --cached --others --exclude-standard | grep -vE '^tests/secret-scan\.sh$' || true)"
[ -n "$files" ] || { echo "no files to scan"; exit 0; }

bad=0
scan() {
  local label="$1" pattern="$2" hits
  hits="$(printf '%s\n' "$files" | xargs grep -nIE "$pattern" 2>/dev/null || true)"
  if [ -n "$hits" ]; then
    echo "FAIL $label:"; printf '%s\n' "$hits" | sed 's/^/  /'; bad=1
  else
    echo "PASS no $label"
  fi
}

# Private IPv4 ranges (RFC1918), excluding loopback which is fine.
scan "private IPv4 addresses" '(^|[^0-9.])(10\.[0-9]{1,3}|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}(\.[0-9]{1,3})?([^0-9]|$)'
scan "MAC addresses" '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}'
scan "credential assignments" '(password|passwd|secret|token|api_key|apikey)[[:space:]]*[:=][[:space:]]*["'\'']?[A-Za-z0-9/+_-]{12,}'
scan "JWT / bearer tokens" 'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
scan "private keys" 'BEGIN [A-Z ]*PRIVATE KEY'
scan "RTSP URLs" 'rtsp://'
scan "Plex tokens" 'X-Plex-Token=[A-Za-z0-9]'

for f in homelab_dashboard_agent_handoff.md production.env secrets.yaml .env; do
  if printf '%s\n' "$files" | grep -qx "$f"; then echo "FAIL $f would be committed"; bad=1; fi
done

[ "$bad" -eq 0 ] && echo "secret scan passed" || { echo "secret scan FAILED"; exit 1; }
