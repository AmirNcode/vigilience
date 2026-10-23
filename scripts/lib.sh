# Shared helpers for Vigilience operator scripts. Source, do not execute.
# shellcheck shell=bash

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="vigilience"
ENV_FILE="${VIG_ENV_FILE:-$HOME/.config/vigilience/production.env}"
BACKUP_DIR="${VIG_BACKUP_DIR:-$HOME/vigilience-backups}"
STATE_FILE="${VIG_STATE_FILE:-$HOME/.config/vigilience/deploy-history.log}"
HA_VOLUME="${PROJECT}_ha_config"

if [ -t 1 ]; then
  C_RED=$'\e[31m'; C_GRN=$'\e[32m'; C_YLW=$'\e[33m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_DIM=""; C_OFF=""
fi

info() { printf '%s==>%s %s\n' "$C_DIM" "$C_OFF" "$*"; }
ok()   { printf '%sPASS%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%sWARN%s %s\n' "$C_YLW" "$C_OFF" "$*"; }
fail() { printf '%sFAIL%s %s\n' "$C_RED" "$C_OFF" "$*"; }
die()  { fail "$*"; exit 1; }

require_env_file() {
  [ -f "$ENV_FILE" ] || die "Env file not found: $ENV_FILE (copy .env.example there, chmod 600)"
}

# Read one KEY from the env file without sourcing it (never echoes secrets).
env_value() {
  local key="$1" default="${2:-}" line
  line="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 || true)"
  if [ -n "$line" ]; then
    line="${line#*=}"; line="${line%\"}"; line="${line#\"}"
    printf '%s' "$line"
  else
    printf '%s' "$default"
  fi
}

compose() {
  docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" \
    -f "$REPO_DIR/compose.yaml" "$@"
}

ha_image() {
  printf 'ghcr.io/home-assistant/home-assistant:%s' "$(env_value HA_VERSION 2026.10.2)"
}

# Run a shell snippet in a throwaway container with the HA config volume.
with_ha_volume() {
  docker run --rm -v "$HA_VOLUME:/config" "$@"
}
