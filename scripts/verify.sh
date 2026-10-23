#!/usr/bin/env bash
# Post-deploy verification. Read-only.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
require_env_file

bad=0
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else fail "$1"; bad=$((bad + 1)); fi; }

info "Containers"
compose ps --format 'table {{.Name}}\t{{.Status}}'
for c in vigilience-homeassistant vigilience-glances vigilience-docker-proxy; do
  check "$c running" "[ \"\$(docker inspect -f '{{.State.Running}}' $c)\" = true ]"
done

info "Endpoints"
for i in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -m 3 -w '%{http_code}' http://127.0.0.1:8123/manifest.json)" = 200 ] && break
  sleep 3
done
check "Home Assistant UI answers on :8123" "curl -sf -m 5 http://127.0.0.1:8123/manifest.json"
check "Glances API answers on loopback" "curl -sf -m 5 http://127.0.0.1:$(env_value GLANCES_PORT 61208)/api/4/quicklook"
check "Glances sees the media drive" "curl -sf -m 5 http://127.0.0.1:$(env_value GLANCES_PORT 61208)/api/4/fs | grep -q '/mnt/media'"
proxy="http://127.0.0.1:$(env_value DOCKER_PROXY_PORT 2375)"
check "Socket proxy lists containers" "curl -sf -m 5 $proxy/containers/json | grep -q vigilience-homeassistant"
check "Socket proxy denies inspect (env vars)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' $proxy/containers/vigilience-homeassistant/json)\" = 403 ]"
check "Socket proxy denies logs" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' $proxy/containers/vigilience-homeassistant/logs)\" = 403 ]"
check "Socket proxy denies writes" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $proxy/containers/vigilience-glances/restart)\" = 405 ] || [ \"\$(curl -s -o /dev/null -w '%{http_code}' -X POST $proxy/containers/vigilience-glances/restart)\" = 403 ]"
check "Socket proxy not exposed on LAN" "! ss -ltn | grep -E '(0\\.0\\.0\\.0|\\*|\\[::\\]):$(env_value DOCKER_PROXY_PORT 2375)\\b'"
check "Glances not exposed on LAN" "! ss -ltn | grep -E '0\\.0\\.0\\.0:$(env_value GLANCES_PORT 61208)\\b'"

info "Existing services"
check "Immich healthy" "curl -sf -m 5 http://127.0.0.1:2283/api/server/ping"
check "Plex healthy" "curl -sf -m 5 http://127.0.0.1:32400/identity"
check "Immich containers still healthy" "[ \"\$(docker ps --filter name=immich --filter health=healthy -q | wc -l)\" -ge 4 ]"

info "Resource footprint"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' \
  vigilience-homeassistant vigilience-glances vigilience-docker-proxy

[ "$bad" -eq 0 ] && ok "verification passed" || die "$bad check(s) failed"
