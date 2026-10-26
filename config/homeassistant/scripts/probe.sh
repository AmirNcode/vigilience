#!/bin/sh
# Vigilience probe helper, executed by Home Assistant command_line sensors
# inside the Home Assistant container (Alpine: busybox ping, curl, jq).
#
# Every mode prints exactly one JSON object and always exits 0, so a failed
# check is reported as {"up": false, ...} instead of an "unknown" sensor.
#
#   probe.sh ping <host>   -> {"up":bool,"ms":float|null,"loss":int}
#   probe.sh http <url>    -> {"up":bool,"code":int,"ms":float|null}
#   probe.sh containers    -> {"running":n,"total":n,"items":[...]} via socket proxy
#   probe.sh links         -> quick-link URLs taken from VIG_*_URL env vars
#   probe.sh apps          -> {"count":n,"items":[...]} homelab apps (homelab.app.* labels) + HTTP probe

mode="$1"
target="$2"

case "$mode" in
  ping)
    if [ -z "$target" ]; then
      echo '{"up":false,"ms":null,"loss":100,"error":"not configured"}'
      exit 0
    fi
    out=$(ping -c 3 -W 2 -q "$target" 2>/dev/null)
    loss=$(printf '%s\n' "$out" | sed -n 's/.* \([0-9]*\)% packet loss.*/\1/p')
    avg=$(printf '%s\n' "$out" | sed -n 's#.*= [0-9.]*/\([0-9.]*\)/.*#\1#p')
    [ -z "$loss" ] && loss=100
    if [ "$loss" -lt 100 ] && [ -n "$avg" ]; then
      printf '{"up":true,"ms":%s,"loss":%s}\n' "$avg" "$loss"
    else
      printf '{"up":false,"ms":null,"loss":%s}\n' "$loss"
    fi
    ;;
  http)
    if [ -z "$target" ]; then
      echo '{"up":false,"code":0,"ms":null,"error":"not configured"}'
      exit 0
    fi
    res=$(curl -s -o /dev/null -m 6 -w '%{http_code} %{time_total}' "$target" 2>/dev/null)
    code=${res%% *}
    secs=${res##* }
    case "$code" in
      2??|3??|401) up=true ;;
      *) up=false ;;
    esac
    if [ "$up" = true ]; then
      ms=$(awk -v s="$secs" 'BEGIN { printf "%.1f", s * 1000 }')
    else
      ms=null
    fi
    printf '{"up":%s,"code":%d,"ms":%s}\n' "$up" "${code:-0}" "$ms"
    ;;
  containers)
    # Docker container summary via the allowlisted socket proxy, which only
    # permits GET /containers/json and GET /containers/<id>/stats (no
    # inspect, so no environment variables or other secrets are readable).
    api="http://127.0.0.1:${VIG_DOCKER_PROXY_PORT:-2375}"
    list=$(curl -sf -m 5 "$api/containers/json?all=1" 2>/dev/null) || {
      echo '{"running":null,"total":null,"items":[],"error":"proxy unreachable"}'
      exit 0
    }
    tmp=$(mktemp -d)
    for id in $(printf '%s' "$list" | jq -r '.[] | select(.State == "running") | .Id'); do
      # stream=false samples twice (~1 s) so CPU % can be computed.
      curl -sf -m 10 "$api/containers/$id/stats?stream=false" > "$tmp/$id.json" 2>/dev/null &
    done
    wait
    stats=$(cat "$tmp"/*.json 2>/dev/null | jq -s '
      map({key: .id, value: {
        cpu: (((.cpu_stats.cpu_usage.total_usage - .precpu_stats.cpu_usage.total_usage)
               / ((.cpu_stats.system_cpu_usage - .precpu_stats.system_cpu_usage) | if . > 0 then . else 1 end)
               * (.cpu_stats.online_cpus // 1) * 100) * 10 | round / 10),
        mem: (((.memory_stats.usage // 0) - (.memory_stats.stats.inactive_file // 0)) / 1048576 | round)
      }}) | from_entries' 2>/dev/null) || stats='{}'
    rm -rf "$tmp"
    printf '%s' "$list" | jq -c --argjson s "$stats" '
      {running: (map(select(.State == "running")) | length),
       total: length,
       items: (map({
         name: (.Names[0] | ltrimstr("/")),
         status: (if .State != "running" then .State
                  elif (.Status | test("\\(unhealthy\\)")) then "unhealthy"
                  elif (.Status | test("\\(healthy\\)")) then "healthy"
                  elif (.Status | test("\\(health: starting\\)")) then "starting"
                  else "running" end),
         uptime: (if .State == "running"
                  then (.Status | sub("^Up "; "") | sub(" \\(.*\\)$"; ""))
                  else .Status end),
         image: .Image,
         cpu: ($s[.Id].cpu // null),
         mem: ($s[.Id].mem // null)
       }) | sort_by(.name))}'
    ;;
  links)
    jq -cn \
      --arg immich "${VIG_IMMICH_URL:-}" \
      --arg plex "${VIG_PLEX_URL:-}" \
      --arg router "${VIG_ROUTER_URL:-}" \
      --arg vpn "${VIG_VPN_URL:-}" \
      '{ok:true, immich:$immich, plex:$plex, router:$router, vpn:$vpn}'
    ;;
  apps)
    # Self-hosted apps deployed with homelab-deploy, discovered from their
    # homelab.app.* container labels (same allowlisted list call as above),
    # each probed over HTTP in parallel. Stopped containers count as down.
    api="http://127.0.0.1:${VIG_DOCKER_PROXY_PORT:-2375}"
    list=$(curl -sf -m 5 "$api/containers/json?all=1" 2>/dev/null) || {
      echo '{"count":null,"items":[],"error":"proxy unreachable"}'
      exit 0
    }
    tmp=$(mktemp -d)
    printf '%s' "$list" | jq -c '.[] | select(.Labels["homelab.app.name"] != null) | {
        name: .Labels["homelab.app.name"],
        url: (.Labels["homelab.app.url"] // ""),
        icon: (.Labels["homelab.app.icon"] // "mdi:application"),
        health: (.Labels["homelab.app.health"] // "/"),
        state: .State, status: .Status}' > "$tmp/apps" 2>/dev/null
    i=0
    while IFS= read -r app; do
      i=$((i + 1))
      printf '%s' "$app" > "$tmp/$i.app"
      if [ "$(printf '%s' "$app" | jq -r .state)" = running ]; then
        sh "$0" http "$(printf '%s' "$app" | jq -r '.url + .health')" > "$tmp/$i.probe" &
      else
        echo '{"up":false,"code":0,"ms":null}' > "$tmp/$i.probe"
      fi
    done < "$tmp/apps"
    wait
    n=1
    while [ "$n" -le "$i" ]; do
      jq -c -s '.[0] + .[1] | del(.health)' "$tmp/$n.app" "$tmp/$n.probe" > "$tmp/$n.item"
      n=$((n + 1))
    done
    cat "$tmp"/*.item 2>/dev/null | jq -c -s '{count: length, items: sort_by(.name)}'
    rm -rf "$tmp"
    ;;
  *)
    echo '{"up":false,"error":"unknown mode"}'
    ;;
esac
exit 0
