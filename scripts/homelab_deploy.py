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

import re
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
    if not health_path.startswith("/"):
        raise ManifestError("health_path must start with /")
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
