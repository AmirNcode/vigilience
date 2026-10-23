#!/usr/bin/env bash
# Snapshot the Home Assistant config volume (users, integrations, history DB)
# to a tar.gz in $VIG_BACKUP_DIR (default ~/vigilience-backups). Keeps the 14
# newest archives. Home Assistant keeps running; the SQLite DB is copied with
# its own backup API for a consistent snapshot.
#
# This backs up Vigilience only. It is NOT a backup of Immich or Plex media.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_env_file

IMAGE="$(ha_image)"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
commit="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
name="vigilience-config-${stamp}-${commit}.tar.gz"

info "Creating $BACKUP_DIR/$name"
with_ha_volume -v "$BACKUP_DIR:/backup" --entrypoint sh "$IMAGE" -euc "
  cd /config
  rm -rf /tmp/snap && mkdir -p /tmp/snap
  if [ -f home-assistant_v2.db ]; then
    python3 -c 'import sqlite3; s=sqlite3.connect(\"home-assistant_v2.db\"); d=sqlite3.connect(\"/tmp/snap/home-assistant_v2.db\"); s.backup(d); d.close(); s.close()'
  fi
  tar -czf /backup/$name \
    --exclude='./home-assistant_v2.db*' --exclude='./backups' --exclude='./tts' \
    --exclude='./vigilience.prev' . -C /tmp/snap .
  chmod 600 /backup/$name
  size=\$(du -m /backup/$name | cut -f1)
  printf '{\"timestamp\":\"%s\",\"file\":\"%s\",\"size_mb\":%s}\n' \"\$(date -Iseconds)\" \"$name\" \"\$size\" \
    > vigilience-state/last_backup.json
"
ok "backup written ($(du -h "$BACKUP_DIR/$name" | cut -f1))"

# Retention: keep the newest 14 archives.
ls -1t "$BACKUP_DIR"/vigilience-config-*.tar.gz 2>/dev/null | tail -n +15 | while read -r old; do
  rm -f -- "$old" && info "pruned $(basename "$old")"
done
warn "Backups are on the same machine. Copy $BACKUP_DIR to another device periodically."
