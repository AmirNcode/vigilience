#!/usr/bin/env bash
# Validate the Home Assistant configuration with Home Assistant itself
# (check_config) in a throwaway volume, plus a YAML parse of the dashboard.
set -euo pipefail
cd "$(dirname "$0")/.."

image="ghcr.io/home-assistant/home-assistant:$(grep -E '^HA_VERSION=' .env.example | cut -d= -f2)"
vol="vigilience_test_config_$$"
trap 'docker volume rm -f "$vol" >/dev/null 2>&1 || true' EXIT
docker volume create "$vol" >/dev/null

docker run --rm -v "$vol:/config" -v "$PWD/config/homeassistant:/src:ro" --entrypoint sh "$image" -euc '
  mkdir -p /config/vigilience
  for d in packages dashboards themes scripts; do cp -R /src/$d /config/vigilience/; done
  cp /src/configuration.yaml /config/
  echo "[]" > /config/automations.yaml; echo "[]" > /config/scenes.yaml; : > /config/scripts.yaml
'
out="$(docker run --rm -v "$vol:/config" --entrypoint python3 "$image" -m homeassistant --script check_config -c /config 2>&1)"
if grep -qiE 'invalid config|Failed config|^ERROR' <<<"$out"; then
  echo "$out" | tail -40; echo "FAIL check_config"; exit 1
fi
echo "PASS Home Assistant check_config ($image)"

# Dashboard is not covered by check_config: parse it and verify entity refs.
docker run --rm -i -v "$PWD/config/homeassistant:/src:ro" --entrypoint python3 "$image" - <<'EOF'
import re, sys, yaml, glob
dash = yaml.safe_load(open("/src/dashboards/vigilience.yaml"))
views = [v["path"] for v in dash["views"]]
assert views == ["overview","apps","server","network","smart-home","cameras","security","activity"], views
text = open("/src/dashboards/vigilience.yaml").read()
refs = set(re.findall(r"\b((?:sensor|binary_sensor|input_number)\.vig_[a-z0-9_]+)", text))
pk = "".join(open(f).read() for f in glob.glob("/src/packages/*.yaml"))
defined = set()
for m in re.finditer(r"unique_id: (vig_[a-z0-9_]+)", pk):
    defined.add(m.group(1))
for m in re.finditer(r"^  (vig_[a-z0-9_]+):\s*$", pk, re.M):
    defined.add(m.group(1))
missing = sorted(r for r in refs if r.split(".",1)[1] not in defined)
if missing:
    print("FAIL dashboard references undefined entities:", missing); sys.exit(1)
print(f"PASS dashboard: {len(views)} views, {len(refs)} entity references all defined")
EOF
