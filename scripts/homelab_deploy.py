#!/usr/bin/env python3
"""homelab-deploy: ship a self-built app from the Mac to the home server.

Run in (or point at) a folder holding a `homelab.yaml` manifest:

    homelab-deploy [deploy] [DIR] [--force]
    homelab-deploy ls | logs NAME | down NAME

The source is rsynced to `~/apps/<name>/` on the server, a generated compose
file is written to `~/apps/<name>/.homelab/compose.json`, and the app is
built and started there with `docker compose up -d --build`. The app is
published only on the server's LAN IP and carries `homelab.app.*` labels,
which Vigilience reads to list it on the dashboard.

Standard library only. Guide: docs/deploying-apps.md.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PORT_MIN, PORT_MAX = 8200, 8299
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,29}$")
KINDS = ("docker", "compose", "static")
COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
KEYS = {"name", "port", "kind", "container_port", "icon", "health_path",
        "memory", "data", "build", "dist", "service"}


class ManifestError(Exception):
    """homelab.yaml is missing, malformed or breaks a rule."""


@dataclass(frozen=True)
class Manifest:
    name: str
    port: int
    kind: str
    icon: str
    container_port: int
    health_path: str
    memory: str
    data: str | None
    build: str | None
    dist: str
    service: str


def parse_flat_yaml(text: str) -> dict[str, str]:
    """Parse the flat `key: value` subset of YAML that homelab.yaml allows."""
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        if not line.strip():
            continue
        if line[0].isspace() or line.lstrip().startswith("- "):
            raise ManifestError(f"line {n}: only flat 'key: value' lines are allowed")
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise ManifestError(f"line {n}: expected 'key: value'")
        if not value:
            raise ManifestError(f"line {n}: '{key}' has no value (nesting is not allowed)")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key in out:
            raise ManifestError(f"line {n}: duplicate key '{key}'")
        out[key] = value
    return out


def _int(raw: dict[str, str], key: str, lo: int, hi: int) -> int:
    try:
        v = int(raw[key])
    except ValueError:
        raise ManifestError(f"{key} must be a number") from None
    if not lo <= v <= hi:
        raise ManifestError(f"{key} must be between {lo} and {hi}")
    return v


def load_manifest(app_dir: Path) -> Manifest:
    path = app_dir / "homelab.yaml"
    if not path.is_file():
        raise ManifestError(f"no homelab.yaml in {app_dir}")
    raw = parse_flat_yaml(path.read_text())

    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise ManifestError(f"unknown key(s): {', '.join(unknown)}")
    for key in ("name", "port"):
        if key not in raw:
            raise ManifestError(f"'{key}' is required")

    name = raw["name"]
    if not NAME_RE.match(name):
        raise ManifestError("name must be lowercase letters, digits and dashes, starting with a letter (max 30)")
    port = _int(raw, "port", PORT_MIN, PORT_MAX)

    kind = raw.get("kind")
    if kind is None:
        if any((app_dir / f).is_file() for f in COMPOSE_FILES):
            kind = "compose"
        elif (app_dir / "Dockerfile").is_file():
            kind = "docker"
        else:
            raise ManifestError("no Dockerfile or compose.yaml; set kind: static for static sites")
    if kind not in KINDS:
        raise ManifestError(f"kind must be one of {', '.join(KINDS)}")

    def only(key: str, *kinds: str) -> None:
        if key in raw and kind not in kinds:
            raise ManifestError(f"'{key}' is only allowed for kind {' / '.join(kinds)}")

    only("container_port", "docker", "compose")
    only("data", "docker")
    only("build", "static")
    only("dist", "static")
    only("service", "compose")

    if kind == "static":
        container_port = 80
    elif "container_port" in raw:
        container_port = _int(raw, "container_port", 1, 65535)
    else:
        raise ManifestError(f"container_port is required for kind {kind} (the port the app listens on inside the container)")

    icon = raw.get("icon", "mdi:application")
    if not re.match(r"^mdi:[a-z0-9-]+$", icon):
        raise ManifestError("icon must look like mdi:notebook")
    health_path = raw.get("health_path", "/")
    # Same rule as probe.sh apps, which skips labels it can't trust.
    if not re.match(r"^/[A-Za-z0-9._~/-]*$", health_path):
        raise ManifestError("health_path must be a plain path like /health (no query string)")
    memory = raw.get("memory", "512m")
    if not re.match(r"^[0-9]+[mg]$", memory):
        raise ManifestError("memory must look like 512m or 1g")
    data = raw.get("data")
    if data is not None and not data.startswith("/"):
        raise ManifestError("data must be an absolute path inside the container, e.g. /app/data")
    dist = raw.get("dist", "dist")
    if dist.startswith("/") or ".." in Path(dist).parts:
        raise ManifestError("dist must be a relative path inside the app folder")

    return Manifest(name=name, port=port, kind=kind, icon=icon,
                    container_port=container_port, health_path=health_path,
                    memory=memory, data=data, build=raw.get("build"), dist=dist,
                    service=raw.get("service", name))


# --- compose rendering and invariants ---------------------------------------

STATIC_BASE_IMAGE = "nginx:1.27.3-alpine"


def labels(m: Manifest, lan_ip: str) -> dict[str, str]:
    # Read by Vigilience (probe.sh apps). Never put secrets here: Home
    # Assistant can read every container's labels.
    return {
        "homelab.app.name": m.name,
        "homelab.app.url": f"http://{lan_ip}:{m.port}",
        "homelab.app.icon": m.icon,
        "homelab.app.port": str(m.port),
        "homelab.app.health": m.health_path,
    }


def render_compose(m: Manifest, lan_ip: str, env_path: str | None) -> dict:
    """Compose document for .homelab/compose.json.

    docker/static: the whole project. compose: an override merged after the
    app's own compose file, touching only the published service.
    Compose runs with --project-directory ~/apps/<name>, so paths are
    relative to the app's source folder.
    """
    svc = {
        "ports": [{"host_ip": lan_ip, "published": str(m.port),
                   "target": m.container_port, "protocol": "tcp"}],
        "restart": "unless-stopped",
        "mem_limit": m.memory,
        "labels": labels(m, lan_ip),
    }
    if m.kind == "compose":
        return {"services": {m.service: svc}}

    svc = {
        "build": {"context": ".homelab/static" if m.kind == "static" else "."},
        "image": f"homelab-app-{m.name}:local",
        "container_name": f"app-{m.name}",
        **svc,
    }
    if env_path:
        svc["env_file"] = [{"path": env_path, "required": False}]
    doc = {"name": f"app-{m.name}", "services": {m.name: svc}}
    if m.data:
        svc["volumes"] = [f"data:{m.data}"]
        doc["volumes"] = {"data": {}}
    return doc


def static_dockerfile(m: Manifest) -> str:
    # Files are baked into the image: a bind mount from /home/linus (ecryptfs)
    # would be missing after an unattended reboot.
    return (f"FROM {STATIC_BASE_IMAGE}\n"
            f"COPY site/ /usr/share/nginx/html/\n")


def check_rendered(cfg: dict, m: Manifest, lan_ip: str) -> list[str]:
    """Violations in `docker compose config --format json` output (merged)."""
    services = cfg.get("services") or {}
    errs = []
    if m.service not in services:
        errs.append(f"service {m.service} not found in compose.yaml (set service: in homelab.yaml)")
    for name, svc in sorted(services.items()):
        if svc.get("privileged"):
            errs.append(f"{name} is privileged")
        if svc.get("network_mode") == "host":
            errs.append(f"{name} uses network_mode: host, which bypasses LAN-only publishing")
        ports = svc.get("ports") or []
        for p in ports:
            published = p.get("published")
            if name != m.service:
                errs.append(f"{name} publishes port {published}; only {m.service} may publish (remove ports: from compose.yaml)")
            elif str(published) != str(m.port):
                errs.append(f"{name} publishes port {published}; only {m.port} from homelab.yaml is allowed (remove ports: from compose.yaml)")
            if p.get("host_ip") != lan_ip:
                errs.append(f"{name} port {published} is not bound to the LAN IP")
        for v in svc.get("volumes") or []:
            if v.get("type") == "bind":
                errs.append(f"{name} bind-mounts {v.get('source')}; use a named volume")
    return errs


def find_port_conflict(m: Manifest, owners: dict[str, int], listening: bool) -> str | None:
    """Why m.port can't be used, or None. owners: deployed app name -> port."""
    for other, port in sorted(owners.items()):
        if port == m.port and other != m.name:
            return f"port {m.port} is already used by app '{other}' (pick another in {PORT_MIN}-{PORT_MAX}; see homelab-deploy ls)"
    if listening and owners.get(m.name) != m.port:
        return f"port {m.port} is in use on the server by something that is not a homelab app"
    return None


# --- talking to the server ---------------------------------------------------

DEFAULT_HOST = "mint"
DEFAULT_ENV_FILE = ".config/vigilience/production.env"
STAGE_IGNORE = shutil.ignore_patterns(".git", ".homelab", "node_modules", ".env*", "homelab.yaml")


class Runner:
    """Runs local commands (ssh/rsync/build). Tests substitute a fake."""

    def run(self, argv: list[str], *, input: str | None = None, check: bool = True,
            cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(argv, input=input, check=check, cwd=cwd,
                              text=True, capture_output=True)

    def stream(self, argv: list[str], *, cwd: Path | None = None) -> int:
        return subprocess.run(argv, cwd=cwd).returncode


@dataclass
class RemoteFacts:
    home: str
    lan_ip: str
    owners: dict[str, int]
    listening: bool
    source: str | None
    env_exists: bool


FACTS_SCRIPT = r"""
echo "HOME=$HOME"
f="$HOME/@ENV_FILE@"
[ -f "$f" ] && echo "LAN_IP=$(sed -n 's/^VIG_LAN_IP=//p' "$f" | tail -n 1)"
docker ps -a --filter label=homelab.app.name \
  --format 'OWNER={{.Label "homelab.app.name"}}={{.Label "homelab.app.port"}}'
ss -ltnH "sport = :@PORT@" 2>/dev/null | grep -q . && echo LISTENING=1
s="$HOME/apps/@NAME@/.homelab/source"
[ -f "$s" ] && echo "SOURCE=$(cat "$s")"
[ -f "$HOME/.config/homelab/@NAME@.env" ] && echo ENV_EXISTS=1
exit 0
"""


def remote_facts(runner: Runner, host: str, env_file: str, m: Manifest) -> RemoteFacts:
    script = (FACTS_SCRIPT.replace("@ENV_FILE@", env_file)
              .replace("@PORT@", str(m.port)).replace("@NAME@", m.name))
    out = runner.run(["ssh", host, "sh", "-s"], input=script).stdout
    vals: dict[str, str] = {}
    owners: dict[str, int] = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key == "OWNER":
            app, _, port = value.partition("=")
            if app and port.isdigit():
                owners[app] = int(port)
        else:
            vals[key] = value.strip()
    return RemoteFacts(home=vals.get("HOME", ""), lan_ip=vals.get("LAN_IP", "").strip("'\""),
                       owners=owners, listening="LISTENING" in vals,
                       source=vals.get("SOURCE") or None, env_exists="ENV_EXISTS" in vals)


def rsync_args(app_dir: Path, host: str, dest: str) -> list[str]:
    # Local secrets (.env*) and VCS data never leave the Mac.
    return ["rsync", "-az", "--delete", "--exclude=.git", "--exclude=.env*",
            "--exclude=.homelab", "--exclude=node_modules", "--filter=:- .gitignore",
            f"{app_dir}/", f"{host}:{dest}"]


def compose_cmd(m: Manifest, facts: RemoteFacts, app_compose: str | None, args: str) -> str:
    q = shlex.quote
    parts = [f"cd {q(f'{facts.home}/apps/{m.name}')} &&",
             f"docker compose -p app-{m.name} --project-directory ."]
    if facts.env_exists:
        parts.append(f"--env-file {q(env_path(m, facts))}")
    if app_compose:
        parts.append(f"-f {q(app_compose)}")
    parts.append(f"-f .homelab/compose.json {args}")
    return " ".join(parts)


def env_path(m: Manifest, facts: RemoteFacts) -> str:
    return f"{facts.home}/.config/homelab/{m.name}.env"


HEALTH_SCRIPT = """c=000; for i in $(seq 15); do
  c=$(curl -s -o /dev/null -w '%{http_code}' -m 3 @URL@)
  case "$c" in 2??|3??|401) break ;; esac; sleep 2
done; echo "$c\""""


def fail(msg: str) -> int:
    print(f"homelab-deploy: {msg}", file=sys.stderr)
    return 1


def info(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def deploy(app_dir: Path, host: str, env_file: str, runner: Runner, force: bool = False) -> int:
    app_dir = app_dir.resolve()
    try:
        m = load_manifest(app_dir)
    except ManifestError as e:
        return fail(f"homelab.yaml: {e}")

    info(f"Checking {host} for {m.name} ({m.kind}, port {m.port})")
    facts = remote_facts(runner, host, env_file, m)
    if not facts.lan_ip:
        return fail(f"VIG_LAN_IP not set in ~/{env_file} on {host}")
    conflict = find_port_conflict(m, facts.owners, facts.listening)
    if conflict:
        return fail(conflict)
    source = f"{socket.gethostname()}:{app_dir}"
    if facts.source and facts.source != source and not force:
        return fail(f"~/apps/{m.name} was deployed from {facts.source}; "
                    f"rename this app or use --force to replace it")

    app_compose = next((f for f in COMPOSE_FILES if (app_dir / f).is_file()), None) \
        if m.kind == "compose" else None
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / ".homelab"
        stage.mkdir()
        if m.kind == "static":
            if m.build:
                info(f"Building: {m.build}")
                if runner.stream(["sh", "-c", m.build], cwd=app_dir) != 0:
                    return fail("build command failed")
            dist = app_dir / m.dist
            if not (dist / "index.html").is_file():
                return fail(f"{m.dist}/index.html not found (set dist: in homelab.yaml)")
            shutil.copytree(dist, stage / "static" / "site", ignore=STAGE_IGNORE)
            (stage / "static" / "Dockerfile").write_text(static_dockerfile(m))
        doc = render_compose(m, facts.lan_ip, env_path(m, facts) if facts.env_exists else None)
        (stage / "compose.json").write_text(json.dumps(doc, indent=2) + "\n")
        (stage / "source").write_text(source + "\n")

        info(f"Uploading to {host}:~/apps/{m.name}/")
        runner.run(["ssh", host, f"mkdir -p apps/{m.name}/.homelab"])
        if m.kind != "static":
            runner.run(rsync_args(app_dir, host, f"apps/{m.name}/"))
        runner.run(["rsync", "-az", "--delete", f"{stage}/", f"{host}:apps/{m.name}/.homelab/"])

    res = runner.run(["ssh", host, compose_cmd(m, facts, app_compose, "config --format json")], check=False)
    if res.returncode != 0:
        return fail(f"docker compose config failed:\n{res.stderr}")
    errs = check_rendered(json.loads(res.stdout), m, facts.lan_ip)
    if errs:
        return fail("refusing to start:\n  " + "\n  ".join(errs))

    info("Building and starting")
    if runner.stream(["ssh", host, compose_cmd(m, facts, app_compose, "up -d --build --remove-orphans")]) != 0:
        return fail("docker compose up failed")

    url = labels(m, facts.lan_ip)["homelab.app.url"]
    info(f"Waiting for {url}{m.health_path}")
    code = runner.run(["ssh", host, HEALTH_SCRIPT.replace("@URL@", shlex.quote(url + m.health_path))],
                      check=False).stdout.strip()
    if not re.match(r"^(2..|3..|401)$", code):
        return fail(f"no healthy HTTP answer at {url}{m.health_path} (last status {code or 'none'}); "
                    f"the app must listen on 0.0.0.0:{m.container_port} inside the container "
                    f"(logs: homelab-deploy logs {m.name})")
    print(f"✓ {m.name} → {url}")
    return 0


USAGE = """usage: homelab-deploy [deploy] [DIR] [--force]
       homelab-deploy ls
       homelab-deploy logs NAME
       homelab-deploy down NAME

Deploys the app in DIR (default: current folder, needs homelab.yaml) to the
home server. Env: HOMELAB_SSH (default mint), HOMELAB_ENV_FILE.
Guide: docs/deploying-apps.md in the vigilience repo."""


def main(argv: list[str], runner: Runner | None = None) -> int:
    runner = runner or Runner()
    host = os.environ.get("HOMELAB_SSH", DEFAULT_HOST)
    env_file = os.environ.get("HOMELAB_ENV_FILE", DEFAULT_ENV_FILE)
    cmd = argv[0] if argv else "deploy"

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd == "ls":
        fmt = '{{.Label "homelab.app.name"}}\t{{.Label "homelab.app.url"}}\t{{.State}}\t{{.Status}}'
        res = runner.run(["ssh", host, f"docker ps -a --filter label=homelab.app.name --format {shlex.quote(fmt)}"],
                         check=False)
        rows = sorted(line.split("\t") for line in res.stdout.splitlines() if line.strip())
        if not rows:
            print("no homelab apps deployed")
        for r in rows:
            print("  ".join(c.ljust(w) for c, w in zip(r, (20, 28, 10, 0))).rstrip())
        return res.returncode
    if cmd in ("logs", "down"):
        if len(argv) != 2 or not NAME_RE.match(argv[1]):
            return fail(f"usage: homelab-deploy {cmd} NAME")
        name = argv[1]
        if cmd == "logs":
            return runner.stream(["ssh", host, f"docker compose -p app-{name} logs -f --tail 200"])
        rc = runner.stream(["ssh", host, f"docker compose -p app-{name} down"])
        if rc == 0:
            print(f"{name} stopped and removed; its data volumes are kept")
        return rc

    rest = argv[1:] if cmd == "deploy" else argv
    force = "--force" in rest
    paths = [a for a in rest if a != "--force"]
    if len(paths) > 1 or any(a.startswith("-") for a in paths):
        print(USAGE, file=sys.stderr)
        return 1
    try:
        return deploy(Path(paths[0] if paths else "."), host, env_file, runner, force=force)
    except subprocess.CalledProcessError as e:
        return fail(f"command failed ({e.returncode}): {' '.join(e.cmd[:3])} ...\n{e.stderr or ''}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
