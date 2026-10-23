#!/usr/bin/env bash
# Restore the Home Assistant config volume from an archive made by
# backup-config.sh. Stops Home Assistant, replaces the volume contents,
# starts it again. A safety snapshot of the current state is taken first.
#
# Usage: scripts/restore-config.sh <archive.tar.gz> [--yes]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_env_file

archive="${1:-}"
[ -n "$archive" ] && [ -f "$archive" ] || die "usage: $0 <archive.tar.gz> [--yes]"
archive="$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")"
tar -tzf "$archive" >/dev/null || die "archive is not readable: $archive"

if [ "${2:-}" != "--yes" ]; then
  read -r -p "Replace current Vigilience Home Assistant state with $(basename "$archive")? [y/N] " a
  [ "$a" = y ] || [ "$a" = Y ] || die "aborted"
fi

info "Safety snapshot of current state"
"$(dirname "$0")/backup-config.sh"

IMAGE="$(ha_image)"
info "Stopping Home Assistant"
compose stop homeassistant
info "Restoring $(basename "$archive")"
with_ha_volume -v "$archive:/restore.tar.gz:ro" --entrypoint sh "$IMAGE" -euc '
  find /config -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  tar -xzf /restore.tar.gz -C /config
'
info "Starting Home Assistant"
compose up -d homeassistant
ok "restore complete; run scripts/verify.sh"
