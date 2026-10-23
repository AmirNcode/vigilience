#!/usr/bin/env bash
# Copy the Git-managed Home Assistant config into the HA config volume and
# validate it with Home Assistant's own checker. On validation failure the
# previous config is restored and the script exits non-zero.
#
# Managed (overwritten):   configuration.yaml, vigilience/**
# Never touched:           .storage/, home-assistant_v2.db, secrets.yaml,
#                          automations.yaml / scripts.yaml / scenes.yaml (UI)
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_env_file
IMAGE="$(ha_image)"
docker volume inspect "$HA_VOLUME" >/dev/null 2>&1 || docker volume create "$HA_VOLUME" >/dev/null

info "Syncing config into volume $HA_VOLUME"
with_ha_volume -v "$REPO_DIR/config/homeassistant:/src:ro" --entrypoint sh "$IMAGE" -euc '
  cd /config
  mkdir -p vigilience-state
  rm -rf vigilience.prev vigilience.new
  mkdir vigilience.new
  for d in packages dashboards themes scripts; do cp -R "/src/$d" vigilience.new/; done
  chmod +x vigilience.new/scripts/*.sh
  [ -f configuration.yaml ] && cp configuration.yaml vigilience-state/configuration.yaml.prev
  [ -d vigilience ] && mv vigilience vigilience.prev
  mv vigilience.new vigilience
  cp /src/configuration.yaml configuration.yaml
  [ -f automations.yaml ] || echo "[]" > automations.yaml
  [ -f scenes.yaml ] || echo "[]" > scenes.yaml
  [ -f scripts.yaml ] || : > scripts.yaml
  [ -f secrets.yaml ] || : > secrets.yaml
'

info "Validating with Home Assistant check_config ($IMAGE)"
if out="$(with_ha_volume --entrypoint python3 "$IMAGE" -m homeassistant --script check_config -c /config 2>&1)" \
   && ! grep -qiE 'invalid config|Failed config|^ERROR' <<<"$out"; then
  ok "Home Assistant configuration valid"
  with_ha_volume --entrypoint sh "$IMAGE" -c 'rm -rf /config/vigilience.prev'
else
  printf '%s\n' "$out" | tail -n 40
  warn "Restoring previous configuration"
  with_ha_volume --entrypoint sh "$IMAGE" -c '
    cd /config
    if [ -d vigilience.prev ]; then rm -rf vigilience && mv vigilience.prev vigilience; fi
    [ -f vigilience-state/configuration.yaml.prev ] && cp vigilience-state/configuration.yaml.prev configuration.yaml || true
  '
  die "Configuration check failed; nothing was restarted"
fi
