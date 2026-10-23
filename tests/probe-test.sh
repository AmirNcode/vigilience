#!/usr/bin/env bash
# Exercise probe.sh inside the pinned HA image (same busybox/curl/jq).
set -euo pipefail
cd "$(dirname "$0")/.."
image="ghcr.io/home-assistant/home-assistant:$(grep -E '^HA_VERSION=' .env.example | cut -d= -f2)"

docker run --rm -v "$PWD/config/homeassistant/scripts:/s:ro" --entrypoint sh "$image" -euc '
  check() { name="$1"; shift; out="$(sh /s/probe.sh "$@")"; echo "$out" | jq -e . >/dev/null || { echo "FAIL $name: not JSON: $out"; exit 1; }; echo "$out"; }
  r=$(check "ping loopback" ping 127.0.0.1);         echo "$r" | jq -e ".up == true and (.ms|type==\"number\")" >/dev/null
  r=$(check "ping unroutable" ping 192.0.2.1);       echo "$r" | jq -e ".up == false and .loss == 100" >/dev/null
  r=$(check "ping unset" ping "");                   echo "$r" | jq -e ".up == false and .error" >/dev/null
  r=$(check "http refused" http http://127.0.0.1:9); echo "$r" | jq -e ".up == false and .code == 0" >/dev/null
  r=$(check "http unset" http "");                   echo "$r" | jq -e ".up == false" >/dev/null
  VIG_IMMICH_URL=http://x:1 r=$(check "links" links); echo "$r" | jq -e ".ok == true" >/dev/null
  echo "PASS probe.sh behaves (JSON always, up/down semantics)"
'
