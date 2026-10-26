#!/usr/bin/env bash
# Read-only pre-deployment checks on the HP server. Changes nothing.
# Exit status is non-zero if a critical check fails.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

crit=0
critical() { fail "$*"; crit=$((crit + 1)); }

info "Vigilience preflight ($(hostname), $(date '+%F %T'))"

# Tooling
command -v docker >/dev/null && ok "docker $(docker --version | awk '{print $3}' | tr -d ,)" || critical "docker missing"
docker compose version >/dev/null 2>&1 && ok "compose $(docker compose version --short)" || critical "docker compose plugin missing"
docker info >/dev/null 2>&1 && ok "docker daemon reachable as $(id -un)" || critical "cannot talk to docker daemon"

# Private env file
if [ -f "$ENV_FILE" ]; then
  mode="$(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %Lp "$ENV_FILE")"
  [ "$mode" = "600" ] && ok "env file present, mode 600" || warn "env file mode is $mode (expected 600)"
  if [ -n "$(env_value PIN_GATE_PIN_HASH)" ] && [ -n "$(env_value PIN_GATE_SECRET)" ]; then
    ok "dashboard PIN configured"
  else
    critical "dashboard PIN not set (run scripts/set-pin.sh)"
  fi
else
  critical "env file missing: $ENV_FILE"
fi

# Git checkout must not contain secrets or local edits
if git -C "$REPO_DIR" rev-parse >/dev/null 2>&1; then
  if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]; then
    critical "tracked files modified in $REPO_DIR (deploy only committed code)"
  else
    ok "checkout clean at $(git -C "$REPO_DIR" rev-parse --short HEAD)"
  fi
  if git -C "$REPO_DIR" ls-files | grep -E '(^|/)(\.env|production\.env|secrets\.yaml)$' >/dev/null; then
    critical "secret-looking file is tracked by Git"
  fi
fi

# Storage
ssd_free=$(df -P / | awk 'NR==2 {print int($4/1048576)}')
[ "$ssd_free" -ge 10 ] && ok "internal SSD free: ${ssd_free} GiB" || critical "internal SSD free only ${ssd_free} GiB"
media="$(env_value MEDIA_MOUNT /mnt/media)"
if findmnt -n "$media" >/dev/null 2>&1; then
  ok "media drive mounted at $media ($(findmnt -n -o FSTYPE "$media"), propagation $(findmnt -n -o PROPAGATION "$media"))"
else
  warn "media drive NOT mounted at $media (dashboard will report it)"
fi

# Memory headroom
avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
[ "$avail" -ge 1500 ] && ok "memory available: ${avail} MiB" || warn "memory available only ${avail} MiB"

# Port conflicts (ignore ports already held by our own containers)
ours="$(docker ps --filter "label=com.docker.compose.project=$PROJECT" -q | wc -l)"
for p in 8123 "$(env_value HA_INTERNAL_PORT 8124)" "$(env_value GLANCES_PORT 61208)" "$(env_value DOCKER_PROXY_PORT 2375)"; do
  if ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN && [ "$ours" -eq 0 ]; then
    critical "port $p already in use by something else"
  else
    ok "port $p available or owned by vigilience"
  fi
done

# Existing services must be healthy before and after
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:2283/api/server/ping || true)
[ "$code" = 200 ] && ok "Immich responding (HTTP 200)" || warn "Immich not responding (HTTP $code)"
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:32400/identity || true)
[ "$code" = 200 ] && ok "Plex responding (HTTP 200)" || warn "Plex not responding (HTTP $code)"
systemctl is-active --quiet plexmediaserver 2>/dev/null && ok "plexmediaserver.service active" || warn "plexmediaserver.service not active"

if [ "$crit" -gt 0 ]; then
  die "$crit critical check(s) failed"
fi
ok "preflight passed"
