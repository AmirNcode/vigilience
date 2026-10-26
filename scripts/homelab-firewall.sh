#!/usr/bin/env bash
# Restrict homelab app ports (8200-8299) to the home subnet. Run on the server.
#
#   ./scripts/homelab-firewall.sh            print the rule and the commands
#   ./scripts/homelab-firewall.sh --apply    apply them (asks for your sudo password)
#
# Ports published by Docker are DNATed before ufw's INPUT chain sees them, so
# a plain `ufw allow from <subnet>` would not restrict them. The rule goes in
# Docker's DOCKER-USER chain instead, matching the original (pre-DNAT)
# destination port. It is made persistent as a marked block in
# /etc/ufw/after.rules; re-running replaces the block rather than adding one.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_env_file
subnet="$(env_value VIG_LAN_SUBNET)"
[[ "$subnet" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$ ]] \
  || die "VIG_LAN_SUBNET in $ENV_FILE must be a CIDR like <network>/24 (got '${subnet}')"

ports="8200:8299"
rule=(-p tcp -m conntrack --ctorigdstport "$ports" --ctdir ORIGINAL ! -s "$subnet" -j DROP)
after_rules=/etc/ufw/after.rules
block="# BEGIN homelab-apps
*filter
:DOCKER-USER - [0:0]
-A DOCKER-USER ${rule[*]}
COMMIT
# END homelab-apps"

if [ "${1:-}" != "--apply" ]; then
  info "Rule: drop TCP to app ports $ports unless the source is in $subnet"
  echo "  sudo iptables -I DOCKER-USER ${rule[*]}"
  if [ -f "$after_rules" ]; then
    echo "  persisted as this block in $after_rules, then: sudo ufw reload"
    printf '%s\n' "$block" | sed 's/^/    /'
  else
    warn "$after_rules not found: the live rule will not survive a reboot"
  fi
  echo "Run with --apply to do it."
  exit 0
fi

if [ -f "$after_rules" ]; then
  tmp="$(mktemp)"
  # Drop any previous homelab-apps block, then append the current one.
  sudo sed '/^# BEGIN homelab-apps$/,/^# END homelab-apps$/d' "$after_rules" > "$tmp"
  printf '%s\n' "$block" >> "$tmp"
  sudo install -m 640 -o root -g root "$tmp" "$after_rules"
  rm -f "$tmp"
  ok "persisted in $after_rules"
  # ufw reload applies after.rules, which adds the live rule. (Each reload
  # appends it again; identical DROP rules are harmless and a reboot leaves one.)
  if ! sudo iptables -C DOCKER-USER "${rule[@]}" 2>/dev/null; then
    sudo ufw reload >/dev/null && ok "ufw reloaded"
  fi
elif sudo iptables -C DOCKER-USER "${rule[@]}" 2>/dev/null; then
  ok "live rule already present"
else
  sudo iptables -I DOCKER-USER "${rule[@]}"
  ok "live rule inserted into DOCKER-USER"
  warn "$after_rules not found: the rule will not survive a reboot"
fi
sudo iptables -S DOCKER-USER | grep -- "--ctorigdstport $ports" || die "rule not active"
