#!/bin/sh
# Vigilience probe helper, executed by Home Assistant command_line sensors
# inside the Home Assistant container (Alpine: busybox ping, curl, jq).
#
# Every mode prints exactly one JSON object and always exits 0, so a failed
# check is reported as {"up": false, ...} instead of an "unknown" sensor.
#
#   probe.sh ping <host>   -> {"up":bool,"ms":float|null,"loss":int}
#   probe.sh http <url>    -> {"up":bool,"code":int,"ms":float|null}
#   probe.sh links         -> quick-link URLs taken from VIG_*_URL env vars

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
  links)
    jq -cn \
      --arg immich "${VIG_IMMICH_URL:-}" \
      --arg plex "${VIG_PLEX_URL:-}" \
      --arg router "${VIG_ROUTER_URL:-}" \
      --arg vpn "${VIG_VPN_URL:-}" \
      '{ok:true, immich:$immich, plex:$plex, router:$router, vpn:$vpn}'
    ;;
  *)
    echo '{"up":false,"error":"unknown mode"}'
    ;;
esac
exit 0
