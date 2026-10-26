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
  # apps: fake socket proxy (static file) + one live app page.
  mkdir -p /tmp/px/containers /tmp/site
  echo hi > /tmp/site/index.html
  cat > /tmp/px/containers/json <<JSON
[{"Id":"a1","State":"running","Status":"Up 2 hours","Labels":{"homelab.app.name":"hello","homelab.app.url":"http://127.0.0.1:18080","homelab.app.icon":"mdi:hand-wave","homelab.app.port":"18080","homelab.app.health":"/"}},
 {"Id":"a2","State":"exited","Status":"Exited (1) 3 minutes ago","Labels":{"homelab.app.name":"dead","homelab.app.url":"http://127.0.0.1:18081","homelab.app.icon":"mdi:skull","homelab.app.port":"18081","homelab.app.health":"/"}},
 {"Id":"a3","State":"running","Status":"Up 1 day","Labels":{}},
 {"Id":"a4","State":"running","Status":"Up 1 day","Labels":{"homelab.app.name":"evil","homelab.app.url":"javascript:alert(1)","homelab.app.icon":"x\" onmouseover=\"y","homelab.app.health":"/"}},
 {"Id":"a5","State":"running","Status":"Up 1 day","Labels":{"homelab.app.name":"<b>x</b>","homelab.app.url":"http://127.0.0.1:18080","homelab.app.health":"/"}}]
JSON
  python3 -m http.server 18375 -d /tmp/px >/dev/null 2>&1 &
  python3 -m http.server 18080 -d /tmp/site >/dev/null 2>&1 &
  sleep 1
  r=$(VIG_DOCKER_PROXY_PORT=18375 check "apps" apps)
  echo "$r" | jq -e ".count == 2 and ([.items[].name] == [\"dead\",\"hello\"])" >/dev/null || { echo "FAIL apps list: $r"; exit 1; }
  echo "$r" | jq -e "(.items[] | select(.name==\"hello\") | .up == true and .icon == \"mdi:hand-wave\" and .url == \"http://127.0.0.1:18080\")" >/dev/null || { echo "FAIL apps hello: $r"; exit 1; }
  echo "$r" | jq -e "(.items[] | select(.name==\"dead\") | .up == false and .code == 0 and .state == \"exited\")" >/dev/null || { echo "FAIL apps dead: $r"; exit 1; }
  r=$(VIG_DOCKER_PROXY_PORT=9 check "apps proxy down" apps)
  echo "$r" | jq -e ".count == null and .items == []" >/dev/null || { echo "FAIL apps proxy down: $r"; exit 1; }
  echo "PASS probe.sh behaves (JSON always, up/down semantics)"
'
