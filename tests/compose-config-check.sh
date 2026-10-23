#!/usr/bin/env bash
# Validate compose.yaml with the example env and assert security invariants.
set -euo pipefail
cd "$(dirname "$0")/.."

cfg="$(docker compose --project-name vigilience --env-file .env.example -f compose.yaml config --format json)"
echo "PASS compose config renders"

python3 - "$cfg" <<'EOF'
import json, sys
c = json.loads(sys.argv[1])
s = c["services"]
errs = []
for name, svc in s.items():
    if svc.get("privileged"):
        errs.append(f"{name}: privileged")
    img = svc.get("image", "")
    if img.endswith(":latest") or ":" not in img.split("/")[-1]:
        errs.append(f"{name}: image not pinned ({img})")
    for p in svc.get("ports", []):
        if p.get("host_ip") not in ("127.0.0.1",):
            errs.append(f"{name}: port {p.get('published')} not bound to loopback")
    for v in svc.get("volumes", []):
        if v.get("source") == "/var/run/docker.sock" and name != "docker-proxy":
            errs.append(f"{name}: mounts docker.sock directly")
        if v.get("source") == "/var/run/docker.sock" and not v.get("read_only"):
            errs.append(f"{name}: docker.sock not read-only")
    if svc.get("restart") != "unless-stopped":
        errs.append(f"{name}: restart policy {svc.get('restart')}")
env = s["docker-proxy"]["environment"]
if str(env.get("POST")) != "0":
    errs.append("docker-proxy: POST not disabled")
media = [v for v in s["glances"]["volumes"] if v.get("target") == "/mnt/media"][0]
if not media.get("read_only"):
    errs.append("glances: media mount not read-only")
if c.get("name") != "vigilience":
    errs.append("project name is not vigilience")
if errs:
    print("FAIL compose invariants:\n  " + "\n  ".join(errs)); sys.exit(1)
print("PASS compose invariants (no privileged, pinned images, loopback ports, read-only socket/media)")
EOF
