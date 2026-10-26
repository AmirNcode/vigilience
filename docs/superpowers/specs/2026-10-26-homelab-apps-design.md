# Homelab Apps — Design

Status: approved 2026-10-26.

## Goal

Host self-built apps on the HP server (`mint`) that are reachable only on
the home LAN, deploy each one from the MacBook with one command, and list
every deployed app (link + up/down) in the Vigilience Home Assistant
dashboard without editing the dashboard per app. Agents working in other
projects must be able to deploy an app by following a written guide.

## Decisions (from Q&A)

| Topic | Decision |
|---|---|
| App types | Web apps with a Dockerfile, static sites, apps needing a database |
| URLs (v1) | `http://<server-LAN-IP>:<port>`; hostnames via reverse proxy are v2 |
| Deploy | From the Mac: rsync source to the server over SSH, `docker compose up -d --build` there. No registry, no GitHub required |
| Discovery | Docker labels `homelab.app.*` set at deploy time; HA reads them through the existing socket proxy (`GET /containers/json`, already allowlisted) |
| Dashboard | New **Apps** view (card per app: icon, link, up/down, uptime) + compact link row on **Overview** |
| Code layout | Mixed/undecided: the tool works from any folder holding a manifest |
| LAN-only | Publish only on the server's LAN IP + host firewall rule allowing the app port range from the home subnet only (user runs it; needs sudo) |
| Agents | A guide + Claude Code skill that agents in other projects read when told to deploy to the home server ("hp", "mint", "linus server") |

## Components

1. **Manifest `homelab.yaml`** in the app folder. Flat `key: value` only.
2. **`homelab-deploy` CLI** (in this repo, symlinked onto the Mac's PATH):
   `deploy` (default), `ls`, `logs <name>`, `down <name>`.
3. **App kinds:** `docker` (Dockerfile), `compose` (app's own
   `compose.yaml`, e.g. app + Postgres), `static` (built on the Mac, baked
   into a pinned nginx image).
4. **Server layout:** source in `~/apps/<name>/`, optional server-only
   secrets in `~/.config/homelab/<name>.env` (mode 600), compose project
   `app-<name>`.
5. **HA:** `probe.sh apps` → `sensor.vig_apps`; Apps view; Overview row;
   down apps listed under "Needs attention".
6. **Firewall:** `scripts/homelab-firewall.sh` prints/applies a
   `DOCKER-USER` rule (Docker-published ports bypass ufw's INPUT chain).
7. **Agent guide:** `docs/deploying-apps.md` (source of truth) and a skill
   `skills/homelab-deploy/SKILL.md` symlinked into `~/.claude/skills/`.
8. **Example app:** `examples/hello-static/` used as smoke test and template.

## Rules

- App ports: 8200–8299. One port per app.
- No bind mounts of host paths: `/home/linus` is ecryptfs and only mounts
  after login. Persistent data uses named volumes.
- Labels must not hold secrets (HA can read every container's labels).
- Apps have no auth by default; LAN-only is the gate.
- The socket-proxy allowlist does not change.
- The public repo holds no LAN IPs; the server's IP and subnet live in
  `~/.config/vigilience/production.env` (`VIG_LAN_IP`, `VIG_LAN_SUBNET`).

## v2 (out of scope)

Caddy on :80 reads the same labels and routes `<name>.home.arpa`; only the
`homelab.app.url` label changes.
