#!/usr/bin/env bash
# Exercise scripts/homelab-firewall.sh --apply against stub sudo/ufw/iptables.
set -euo pipefail
cd "$(dirname "$0")/.."
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
mkdir "$t/bin"
printf 'VIG_LAN_SUBNET=192.0.2.0/24\n' > "$t/env"
touch "$t/after.rules"
cat > "$t/bin/sudo" <<'S'
#!/bin/sh
exec "$@"
S
# iptables: -C fails until -I/ufw reload has added the rule; -S lists it.
cat > "$t/bin/iptables" <<'S'
#!/bin/sh
echo "iptables $*" >> "$STUB_LOG"
case "$1" in
  -C) [ -f "$STUB_DIR/rule" ] ;;
  -I) touch "$STUB_DIR/rule" ;;
  -S) [ -f "$STUB_DIR/rule" ] && echo "-A DOCKER-USER -p tcp --ctorigdstport 8200:8299 -j DROP" ;;
esac
S
cat > "$t/bin/ufw" <<'S'
#!/bin/sh
echo "ufw $*" >> "$STUB_LOG"
case "$1" in
  status) echo "Status: $UFW_STATE" ;;
  reload) [ "$UFW_STATE" = active ] && touch "$STUB_DIR/rule"; exit 0 ;;
esac
S
cat > "$t/bin/install" <<'S'
#!/bin/sh
eval "dest=\${$#}"; eval "src=\${$(($# - 1))}"; cp "$src" "$dest"
S
chmod +x "$t/bin/"*

run() {
  rm -f "$t/rule" "$t/log"; : > "$t/after.rules"
  PATH="$t/bin:$PATH" STUB_LOG="$t/log" STUB_DIR="$t" UFW_STATE="$1" VIG_ENV_FILE="$t/env" \
    HOMELAB_UFW_AFTER_RULES="$t/after.rules" scripts/homelab-firewall.sh --apply > "$t/out" 2>&1 \
    || { cat "$t/out"; echo "FAIL firewall --apply with ufw $1"; exit 1; }
}

run inactive
grep -q "^iptables -I DOCKER-USER" "$t/log" || { cat "$t/out"; echo "FAIL inactive ufw: no live rule inserted"; exit 1; }
! grep -q "homelab-apps" "$t/after.rules" || { echo "FAIL inactive ufw: after.rules written"; exit 1; }

run active
grep -q "^ufw reload" "$t/log" || { echo "FAIL active ufw: not reloaded"; exit 1; }
[ "$(grep -c '^# BEGIN homelab-apps' "$t/after.rules")" = 1 ] || { echo "FAIL active ufw: block not persisted once"; exit 1; }
echo "PASS homelab-firewall --apply (ufw inactive and active)"
