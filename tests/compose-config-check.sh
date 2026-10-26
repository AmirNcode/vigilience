#!/usr/bin/env bash
# Validate compose.yaml with the example env and assert security invariants.
set -euo pipefail
cd "$(dirname "$0")/.."

cfg="$(DOCKER_GID=999 PIN_GATE_PIN_HASH=pbkdf2:test PIN_GATE_SECRET=test docker compose --project-name vigilience --env-file .env.example -f compose.yaml config --format json)"
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
    if "build" in svc:
        # Locally built: the Dockerfile's base image must be pinned instead.
        df = open(svc["build"]["context"] + "/Dockerfile").read()
        img = [l.split()[1] for l in df.splitlines() if l.startswith("FROM ")][0]
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
px = s["docker-proxy"]
cmd = px.get("command", [])
if any(not a.startswith(("-listenip=", "-proxyport=", "-allowfrom=", "-allowGET=", "-watchdog", "-stoponwatchdog", "-shutdowngracetime")) for a in cmd):
    errs.append(f"docker-proxy: unexpected flag (only GET allowlist permitted): {cmd}")
if "-listenip=127.0.0.1" not in cmd or "-allowfrom=127.0.0.1/32" not in cmd:
    errs.append("docker-proxy: not restricted to loopback")
if str(px.get("user", "")).startswith("0") or not px.get("user"):
    errs.append("docker-proxy: runs as root")
if "ALL" not in px.get("cap_drop", []) or not px.get("read_only"):
    errs.append("docker-proxy: not cap_drop ALL + read_only")
if "DOCKER_HOST" in s["glances"].get("environment", {}):
    errs.append("glances: has Docker access")
media = [v for v in s["glances"]["volumes"] if v.get("target") == "/mnt/media"][0]
if not media.get("read_only"):
    errs.append("glances: media mount not read-only")
pg = s["pin-gate"]
if "ALL" not in pg.get("cap_drop", []) or not pg.get("read_only") or pg.get("volumes"):
    errs.append("pin-gate: not cap_drop ALL + read_only without mounts")
if c.get("name") != "vigilience":
    errs.append("project name is not vigilience")
if errs:
    print("FAIL compose invariants:\n  " + "\n  ".join(errs)); sys.exit(1)
print("PASS compose invariants (no privileged, pinned images, loopback-only, GET-allowlist proxy, read-only socket/media)")
EOF
