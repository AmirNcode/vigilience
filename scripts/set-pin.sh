#!/usr/bin/env bash
# Set or change the dashboard PIN (6+ digits). Run on the HP server:
#
#   cd ~/vigilience && ./scripts/set-pin.sh
#
# Writes PIN_GATE_PIN_HASH and a fresh PIN_GATE_SECRET into the env file
# (the PIN itself is never stored), then recreates the gate if it is running.
# A new secret invalidates every remembered device.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_env_file
command -v python3 >/dev/null || die "python3 is required"

read -rsp "New PIN (6+ digits): " pin; echo
[[ "$pin" =~ ^[0-9]{6,32}$ ]] || die "PIN must be 6 to 32 digits"
read -rsp "Repeat PIN: " again; echo
[ "$pin" = "$again" ] || die "PINs do not match"

out="$(printf '%s\n' "$pin" | python3 "$REPO_DIR/pin-gate/pin_gate.py" hash)"
unset pin again
hash="$(sed -n 1p <<<"$out")"
key="$(sed -n 2p <<<"$out")"

tmp="$(mktemp "$ENV_FILE.XXXXXX")"
chmod 600 "$tmp"
grep -vE '^(PIN_GATE_PIN_HASH|PIN_GATE_SECRET)=' "$ENV_FILE" > "$tmp" || true
printf 'PIN_GATE_PIN_HASH=%s\nPIN_GATE_SECRET=%s\n' "$hash" "$key" >> "$tmp"
mv "$tmp" "$ENV_FILE"
ok "PIN saved to $ENV_FILE"

if [ "$(docker inspect -f '{{.State.Running}}' vigilience-pin-gate 2>/dev/null || echo false)" = true ]; then
  info "Recreating the PIN gate (all devices must re-enter the PIN)"
  compose up -d --no-deps pin-gate
fi
