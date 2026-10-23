#!/usr/bin/env bash
# Manual deployment on the HP server. Never triggered automatically.
#
#   cd /home/linus/vigilience && ./scripts/deploy.sh
#
# Steps: fast-forward to origin/main -> preflight -> config backup ->
# sync + validate HA config -> compose up -> restart HA if config changed ->
# verify. Records previous/new commit in the deploy history for rollback.
#
# Options:
#   --no-pull    deploy the currently checked-out commit (used by rollback.sh)
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd "$REPO_DIR"

pull=1
[ "${1:-}" = "--no-pull" ] && pull=0

require_env_file
prev="$(git rev-parse HEAD)"

if [ "$pull" -eq 1 ]; then
  [ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "checkout is not on main"
  [ -z "$(git status --porcelain --untracked-files=no)" ] || die "tracked files modified; refusing to deploy"
  info "Fetching origin/main"
  git fetch --quiet origin main
  git merge --ff-only origin/main || die "cannot fast-forward (diverged history); resolve manually"
fi
new="$(git rev-parse HEAD)"
info "Deploying $(git log -1 --format='%h %s' "$new") (previous ${prev:0:7})"

"$REPO_DIR/scripts/preflight.sh"

info "Validating compose file"
compose config --quiet

if docker volume inspect "$HA_VOLUME" >/dev/null 2>&1 \
   && with_ha_volume --entrypoint sh "$(ha_image)" -c '[ -d /config/.storage ]' 2>/dev/null; then
  "$REPO_DIR/scripts/backup-config.sh"
else
  info "First install: no existing state to back up"
fi

info "Pulling pinned images"
compose pull --quiet

# Fingerprint the managed config before/after sync to decide on a restart.
fingerprint() {
  with_ha_volume --entrypoint sh "$(ha_image)" -c \
    'cd /config && { cat configuration.yaml; find vigilience -type f | sort | xargs cat; } 2>/dev/null | md5sum' 2>/dev/null || true
}
before="$(fingerprint)"
"$REPO_DIR/scripts/sync-config.sh"
after="$(fingerprint)"

info "Starting/updating Vigilience containers"
was_running="$(docker inspect -f '{{.State.Running}}' vigilience-homeassistant 2>/dev/null || echo false)"
compose up -d --remove-orphans
if [ "$was_running" = true ] && [ "$before" != "$after" ]; then
  info "Managed config changed; restarting Home Assistant"
  compose restart homeassistant
fi

mkdir -p "$(dirname "$STATE_FILE")"
printf '%s deploy %s -> %s\n' "$(date -Iseconds)" "$prev" "$new" >> "$STATE_FILE"

"$REPO_DIR/scripts/verify.sh"
ok "Deployed ${new:0:7}. Dashboard: http://<server-lan-ip>:8123/vigilience-hq"
