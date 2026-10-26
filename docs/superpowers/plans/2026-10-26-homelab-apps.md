# Homelab Apps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy self-built LAN-only apps from the MacBook to the HP server with one command, and list every deployed app (link + up/down) in the Vigilience HA dashboard automatically.

**Architecture:** A stdlib-Python CLI (`homelab-deploy`) reads a flat `homelab.yaml` manifest in the app folder, rsyncs the source to `mint:~/apps/<name>/`, writes a generated compose file next to it and runs `docker compose up -d --build` over SSH. The generated compose publishes the app only on the server's LAN IP and stamps `homelab.app.*` labels; HA's existing `probe.sh` reads those labels through the existing socket proxy and HTTP-probes each app.

**Tech Stack:** Python 3.9+ stdlib (Mac), rsync, OpenSSH, Docker Compose v2 (server), Home Assistant YAML packages, busybox sh + jq (probe.sh), iptables `DOCKER-USER` chain.

**Spec:** `docs/superpowers/specs/2026-10-26-homelab-apps-design.md`

## Global Constraints

- App host ports: **8200–8299**, one per app.
- Compose project name `app-<name>`; container name `app-<name>` for `docker`/`static` kinds; image `homelab-app-<name>:local`.
- Labels (exact keys): `homelab.app.name`, `homelab.app.url`, `homelab.app.icon`, `homelab.app.port`, `homelab.app.health`.
- `homelab.app.url` = `http://<VIG_LAN_IP>:<port>` (no path). v2 replaces only this value.
- Every published port binds to `VIG_LAN_IP`, never `0.0.0.0`. Only the manifest's port is published.
- No bind mounts in generated or merged app compose configs (`/home/linus` is ecryptfs, absent until login). Persistence = named volumes.
- `restart: unless-stopped`; default `mem_limit` `512m`.
- Static kind base image pinned: `nginx:1.27.3-alpine`.
- Server paths: source `~/apps/<name>/`, generated files `~/apps/<name>/.homelab/`, optional secrets `~/.config/homelab/<name>.env` (mode 600). LAN values in `~/.config/vigilience/production.env`: `VIG_LAN_IP`, `VIG_LAN_SUBNET`.
- Mac env: `HOMELAB_SSH` (default `mint`), `HOMELAB_ENV_FILE` (default `.config/vigilience/production.env`, relative to remote home).
- Socket-proxy allowlist in `compose.yaml` does not change.
- Public repo: no RFC1918 IPs anywhere (secret-scan enforces). Use `192.0.2.x` (TEST-NET) in tests and docs.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Two different folders using the same `name` → second deploy would silently overwrite the first. Expect refusal naming the other source path unless `--force`. (Task 3)
2. App listens on `127.0.0.1` inside its container → container "runs" but is unreachable. Expect deploy to exit non-zero after the health wait with the hint "app must listen on 0.0.0.0:<container_port>". (Task 3)
3. Local `.env` / secrets in the app folder → must never reach the server via rsync. Expect `--exclude=.env*` and `.git` excluded. (Task 3)
4. App's own `compose.yaml` publishes extra ports (e.g. Postgres `5432:5432` on all interfaces) or bind-mounts `./data` → expect deploy to refuse before `up`, listing each violation. (Task 2)
5. Proxy down or zero apps deployed → HA must show "No apps deployed" / "App data not available", never a template error. (Task 5)

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/homelab_deploy.py` | Whole CLI: manifest, rendering, checks, orchestration. Executable, `#!/usr/bin/env python3`. Symlinked as `~/.local/bin/homelab-deploy` |
| `tests/homelab_deploy_test.py` + `tests/homelab-deploy-test.sh` | unittest suite + wrapper (mirrors `pin-gate-test.sh`) |
| `scripts/homelab-firewall.sh` | Print (default) or apply (`--apply`, sudo) the `DOCKER-USER` LAN-only rule |
| `examples/hello-static/` | Minimal static app: `homelab.yaml`, `index.html` — smoke test + template |
| `config/homeassistant/scripts/probe.sh` | New `apps` mode |
| `config/homeassistant/packages/vig_server.yaml` | New `sensor.vig_apps` |
| `config/homeassistant/packages/vig_health.yaml` | Down apps → warnings |
| `config/homeassistant/dashboards/vigilience.yaml` | New `apps` view; Overview link row |
| `docs/deploying-apps.md` | Human + agent guide (source of truth) |
| `skills/homelab-deploy/SKILL.md` | Claude Code skill pointing at the guide; symlinked into `~/.claude/skills/` |

---

### Task 1: Manifest parsing and validation

**Files:**
- Create: `scripts/homelab_deploy.py`
- Create: `tests/homelab_deploy_test.py`, `tests/homelab-deploy-test.sh`
- Modify: `tests/run-all.sh` (add `homelab-deploy-test.sh` after `pin-gate-test.sh`)

**Interfaces:**
- Produces:
  - `class ManifestError(Exception)`
  - `parse_flat_yaml(text: str) -> dict[str, str]` — `key: value` lines; `#` comments and blank lines ignored; surrounding single/double quotes stripped; raises `ManifestError` on indentation, list items (`- `), missing colon, duplicate key.
  - `@dataclass(frozen=True) class Manifest: name: str; port: int; kind: str; icon: str; container_port: int; health_path: str; memory: str; data: str | None; build: str | None; dist: str; service: str`
  - `load_manifest(app_dir: Path) -> Manifest`

**Manifest keys and rules** (unknown key → `ManifestError`):

| key | required | rule / default |
|---|---|---|
| `name` | yes | `^[a-z][a-z0-9-]{0,29}$` |
| `port` | yes | int, 8200–8299 |
| `kind` | no | `docker`\|`compose`\|`static`; inferred: `compose.yaml`/`compose.yml`/`docker-compose.yml` present → `compose`, else `Dockerfile` → `docker`, else error "no Dockerfile or compose.yaml; set kind: static for static sites" |
| `container_port` | docker, compose | int 1–65535; `static` → fixed 80 (setting it is an error) |
| `icon` | no | `^mdi:[a-z0-9-]+$`, default `mdi:application` |
| `health_path` | no | starts with `/`, default `/` |
| `memory` | no | `^[0-9]+[mg]$`, default `512m` |
| `data` | no | absolute container path; `docker` kind only (compose apps declare their own named volumes) |
| `build` | no | `static` only: shell command run on the Mac in the app dir |
| `dist` | no | `static` only: relative dir, default `dist`; must not contain `..` |
| `service` | no | `compose` only: service that gets port + labels, default = `name` |

- [ ] **Step 1: Write failing tests** in `tests/homelab_deploy_test.py` (unittest, `sys.path` insert of `../scripts`, temp dirs via `tempfile.TemporaryDirectory`):
  - `test_parse_flat_yaml_strips_comments_and_quotes`: `'name: "notes"  # c\n\nport: 8201\n'` → `{"name": "notes", "port": "8201"}`
  - `test_parse_flat_yaml_rejects_nesting` (`"a:\n  b: 1"`), `..._rejects_list` (`"- x"`), `..._rejects_duplicate` — each `assertRaises(ManifestError)`
  - `test_docker_kind_inferred_from_dockerfile`: dir with `Dockerfile`, manifest `name: notes / port: 8201 / container_port: 3000` → `kind == "docker"`, `icon == "mdi:application"`, `memory == "512m"`, `health_path == "/"`, `service == "notes"`
  - `test_compose_kind_inferred`: `compose.yaml` present → `kind == "compose"`
  - `test_static_requires_explicit_kind`: no Dockerfile/compose, no `kind` → `ManifestError` whose message contains `kind: static`
  - `test_static_container_port_is_80` and `test_static_rejects_container_port`
  - `test_port_out_of_range` for `8199` and `8300`; `test_bad_name` for `Notes`, `9x`, `a_b`; `test_unknown_key`; `test_data_only_for_docker`; `test_dist_rejects_dotdot`; `test_missing_container_port_for_docker`

- [ ] **Step 2: Create wrapper** `tests/homelab-deploy-test.sh` (same shape as `tests/pin-gate-test.sh`, running `python3 -I homelab_deploy_test.py`, printing `PASS homelab-deploy tests`), `chmod +x`. Run `tests/homelab-deploy-test.sh` → FAIL (`ModuleNotFoundError: homelab_deploy`).

- [ ] **Step 3: Implement** `ManifestError`, `parse_flat_yaml`, `Manifest`, `load_manifest` in `scripts/homelab_deploy.py` (module docstring in the style of `pin-gate/pin_gate.py`; `chmod +x`).

- [ ] **Step 4: Run** `tests/homelab-deploy-test.sh` → `PASS homelab-deploy tests`. Run `tests/secret-scan.sh` → passes.

- [ ] **Step 5: Commit** — `git add scripts/homelab_deploy.py tests/homelab_deploy_test.py tests/homelab-deploy-test.sh tests/run-all.sh && git commit -m "Add homelab app manifest parser"`

---

### Task 2: Compose rendering, config checks, port conflicts

**Files:**
- Modify: `scripts/homelab_deploy.py`
- Modify: `tests/homelab_deploy_test.py`

**Interfaces:**
- Consumes: `Manifest` (Task 1).
- Produces:
  - `STATIC_BASE_IMAGE = "nginx:1.27.3-alpine"`
  - `render_compose(m: Manifest, lan_ip: str, env_path: str | None) -> dict` — compose document written as JSON to `.homelab/compose.json`; compose is run with `--project-directory ~/apps/<name>`, so `build.context` is `"."` (docker) or `".homelab/static"` (static).
  - `static_dockerfile(m: Manifest) -> str` — `FROM nginx:1.27.3-alpine` + `COPY site/ /usr/share/nginx/html/`.
  - `check_rendered(cfg: dict, m: Manifest, lan_ip: str) -> list[str]` — input is `docker compose ... config --format json` output; returns human-readable violations (empty = OK).
  - `find_port_conflict(m: Manifest, owners: dict[str, int], listening: bool) -> str | None` — `owners` maps deployed app name → port.

**Rendering rules:**
- `docker`/`static`: full document `{"name": "app-<n>", "services": {<n>: {...}}}` with `build`, `image: homelab-app-<n>:local`, `container_name: app-<n>`, `ports: [{"host_ip": lan_ip, "published": "<port>", "target": <container_port>, "protocol": "tcp"}]`, `restart`, `mem_limit`, `labels`; `env_file: [{"path": env_path, "required": false}]` only when `env_path` given; `data` → `volumes: ["data:<path>"]` + top-level `volumes: {"data": {}}`.
- `compose`: override `{"services": {<service>: {ports, restart, mem_limit, labels}}}` only (merged after the app's own file).
- `labels`: the five keys from Global Constraints; `homelab.app.port` and `homelab.app.health` as strings.

**`check_rendered` violations** (message must name service and value):
- any service with `privileged: true`
- any port on a service other than `m.service`/`m.name` → `"<svc> publishes port <published>; only <service> may publish"`
- any port whose `host_ip != lan_ip` → `"... not bound to the LAN IP"`
- any volume with `type == "bind"` → `"<svc> bind-mounts <source>; use a named volume"`
- the target service missing → `"service <service> not found in compose.yaml"`

- [ ] **Step 1: Write failing tests:**
  - `test_render_docker`: manifest docker `notes`/8201/3000, `lan_ip="192.0.2.10"`, `env_path=None` → `svc["ports"] == [{"host_ip": "192.0.2.10", "published": "8201", "target": 3000, "protocol": "tcp"}]`, `svc["labels"]["homelab.app.url"] == "http://192.0.2.10:8201"`, `svc["container_name"] == "app-notes"`, `"env_file" not in svc`, `doc["name"] == "app-notes"`
  - `test_render_env_file_optional`: `env_path="/home/u/.config/homelab/notes.env"` → `svc["env_file"] == [{"path": ..., "required": False}]`
  - `test_render_data_volume`: `data: /app/data` → `svc["volumes"] == ["data:/app/data"]`, `doc["volumes"] == {"data": {}}`
  - `test_render_static`: `build.context == ".homelab/static"`, target 80; `static_dockerfile` starts with `FROM nginx:1.27.3-alpine`
  - `test_render_compose_override_only_touches_service`: `set(doc) == {"services"}` and `set(doc["services"]) == {"web"}` for `service: web`
  - `test_check_rejects_extra_port`, `test_check_rejects_wildcard_bind` (`host_ip` absent / `"0.0.0.0"`), `test_check_rejects_bind_mount`, `test_check_rejects_privileged`, `test_check_missing_service`, `test_check_ok_for_named_volume_db` (db service with named volume, no ports → `[]`)
  - `test_port_conflict_other_app`: `owners={"todo": 8201}` → message contains `todo`; `test_port_redeploy_same_app_ok`: `owners={"notes": 8201}, listening=True` → `None`; `test_port_taken_by_non_app`: `owners={}, listening=True` → message contains `in use`

- [ ] **Step 2: Run** `tests/homelab-deploy-test.sh` → new tests FAIL (`AttributeError`/`NameError`).
- [ ] **Step 3: Implement** the four functions + constant.
- [ ] **Step 4: Run** `tests/homelab-deploy-test.sh` → PASS.
- [ ] **Step 5: Commit** — `"Render homelab app compose files and enforce LAN-only invariants"`

---

### Task 3: CLI orchestration, install, example app, first real deploy

**Files:**
- Modify: `scripts/homelab_deploy.py`, `tests/homelab_deploy_test.py`
- Modify: `.env.example` (add `VIG_LAN_IP=` and `VIG_LAN_SUBNET=` under "Private network values", with comments: server LAN IP apps publish on; home subnet in CIDR allowed by the firewall)
- Create: `examples/hello-static/homelab.yaml` (`name: hello`, `port: 8200`, `kind: static`, `dist: .`, `icon: mdi:hand-wave`), `examples/hello-static/index.html` (one-line page "Hello from the homelab")

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `class Runner` with `run(argv: list[str], *, input: str | None = None, check: bool = True) -> subprocess.CompletedProcess` (text mode, captures stdout) and `stream(argv: list[str]) -> int` (inherits stdio; for logs/up output). Tests pass a `FakeRunner` recording argv lists and returning scripted results.
  - `remote_facts(runner, host: str, env_file: str, m: Manifest) -> RemoteFacts` — one `ssh host sh -s` call with a script on stdin printing `KEY=value` lines; `@dataclass RemoteFacts: home: str; lan_ip: str; owners: dict[str, int]; listening: bool; source: str | None; env_exists: bool` (`source` = contents of `~/apps/<name>/.homelab/source`, if any; `env_exists` = `~/.config/homelab/<name>.env` exists).
  - `rsync_args(app_dir: Path, host: str, dest: str) -> list[str]`
  - `deploy(app_dir: Path, host: str, env_file: str, runner: Runner, force: bool = False) -> int`
  - `main(argv: list[str]) -> int` — subcommands `deploy [DIR] [--force]` (default when first arg is a path or absent), `ls`, `logs NAME`, `down NAME`.

**`deploy` flow** (each failure → message on stderr, return 1):
1. `load_manifest`; `ManifestError` → print `homelab.yaml: <msg>`.
2. `remote_facts`; empty `lan_ip` → `"VIG_LAN_IP not set in ~/<env_file> on <host>"`.
3. `find_port_conflict` → refuse.
4. `source` marker = `"<socket.gethostname()>:<app_dir.resolve()>"`; if remote `source` exists and differs and not `force` → `"~/apps/<name> was deployed from <other>; use --force to replace"`.
5. `static`: run `m.build` (if set) via `runner.run(["sh", "-c", m.build], ...)` with cwd = app dir; require `<dist>/index.html`; stage `site/` + `Dockerfile` in a temp dir.
6. Write `compose.json` (+ `source` file) into a local temp `.homelab/`.
7. rsync: `docker`/`compose` → source tree, then `.homelab/` (and `static/` for static) to `<host>:apps/<name>/.homelab/`. `rsync_args` = `["rsync", "-az", "--delete", "--exclude=.git", "--exclude=.env*", "--exclude=.homelab", "--exclude=node_modules", "--filter=:- .gitignore", f"{app_dir}/", f"{host}:apps/{name}/"]`. Static skips the source rsync.
8. Remote: `docker compose -p app-<n> --project-directory ~/apps/<n> [--env-file <envpath>] [-f <app compose>] -f .homelab/compose.json config --format json` → `check_rendered`; any violation → print all, return 1. `--env-file` (and `env_path` for `render_compose`) only when `facts.env_exists`.
9. Remote `... up -d --build --remove-orphans` via `stream`.
10. Health wait: remote `curl -s -o /dev/null -w '%{http_code}' -m 3 <url><health_path>` up to 15 tries, 2 s apart; success = 2xx, 3xx or 401 (same rule as `probe.sh http`, so a deploy that passes also shows green in HA). Fail → `"no HTTP answer at <url>; app must listen on 0.0.0.0:<container_port> inside the container (logs: homelab-deploy logs <name>)"`, return 1.
11. Print `✓ <name> → <url>`.

- `ls`: `ssh host docker ps -a --filter label=homelab.app.name --format '{{.Label "homelab.app.name"}}\t{{.Label "homelab.app.url"}}\t{{.State}}\t{{.Status}}'` → aligned table.
- `logs NAME`: stream `docker compose -p app-<n> logs -f --tail 200`.
- `down NAME`: stream `docker compose -p app-<n> down` (keeps volumes); print that data volumes are kept.
- Validate `NAME` with the manifest name regex before putting it in any remote command; quote all remote args with `shlex.quote`.

- [ ] **Step 1: Write failing tests** with `FakeRunner`:
  - `test_rsync_excludes_secrets`: `rsync_args(...)` contains `--exclude=.env*` and `--exclude=.git`
  - `test_deploy_refuses_other_source`: facts `source="otherhost:/x"` → returns 1, stderr contains `otherhost:/x` and `--force`; no `rsync` call recorded
  - `test_deploy_force_replaces`: same with `force=True` → reaches `up`
  - `test_deploy_missing_lan_ip` → 1, message contains `VIG_LAN_IP`
  - `test_deploy_reports_check_violations`: scripted `config` JSON with a `db` service publishing `5432` → 1, no `up` call
  - `test_deploy_health_fail_hint`: curl always returns `000` (patch sleep) → 1, stderr contains `0.0.0.0:3000`
  - `test_deploy_happy_path_order`: recorded commands appear in order ssh(facts) → rsync(source) → rsync(.homelab) → ssh(config) → ssh(up) → ssh(curl); output contains `http://192.0.2.10:8201`
  - `test_down_rejects_bad_name`: `main(["down", "x;rm"])` → 1, no runner calls

- [ ] **Step 2: Run** `tests/homelab-deploy-test.sh` → new tests FAIL.
- [ ] **Step 3: Implement** `Runner`, `RemoteFacts`, `remote_facts`, `rsync_args`, `deploy`, `main`, `if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.
- [ ] **Step 4: Run** `tests/homelab-deploy-test.sh` and `tests/secret-scan.sh` → both PASS.
- [ ] **Step 5: Install on the Mac:** `ln -sf "$PWD/scripts/homelab_deploy.py" ~/.local/bin/homelab-deploy`; `homelab-deploy --help` prints usage.
- [ ] **Step 6: Server env (one-time):** check `ssh mint 'grep -E "^VIG_LAN_(IP|SUBNET)=" ~/.config/vigilience/production.env'`. If absent, append both with the server's LAN IP (`HostName` of `mint` in `~/.ssh/config`) and its /24, keeping mode 600. Never commit the values.
- [ ] **Step 7: Smoke deploy:** `homelab-deploy examples/hello-static` → ends with `✓ hello → http://<lan-ip>:8200`; `curl -s http://<lan-ip>:8200 | grep -q homelab` from the Mac; `homelab-deploy ls` shows `hello  running`. Run `homelab-deploy examples/hello-static` again → succeeds (idempotent redeploy, same port).
- [ ] **Step 8: Verify `down`/`logs` work by project name without compose files:** `homelab-deploy logs hello` shows nginx lines (Ctrl-C); leave `hello` running for Task 5.
- [ ] **Step 9: Commit** — `"Add homelab-deploy CLI and hello-static example"`

---

### Task 4: LAN-only firewall rule

**Files:**
- Create: `scripts/homelab-firewall.sh`

**Interfaces:**
- Consumes: `VIG_LAN_SUBNET` from the server env file (`scripts/lib.sh` `require_env_file` pattern).
- Produces: `scripts/homelab-firewall.sh [--apply]`, run on the server.

Behaviour: without `--apply`, print the rule and the exact `sudo` commands; with `--apply`, run them via `sudo`. Docker-published ports skip ufw's INPUT chain, so the rule goes in `DOCKER-USER`:
`iptables -I DOCKER-USER -p tcp -m conntrack --ctorigdstport 8200:8299 --ctdir ORIGINAL ! -s "$VIG_LAN_SUBNET" -j DROP`
Persistence: idempotent block appended to `/etc/ufw/after.rules` between `# BEGIN homelab-apps` / `# END homelab-apps` markers (`*filter` / `:DOCKER-USER - [0:0]` / rule / `COMMIT`), then `sudo ufw reload`. Re-running replaces the block, never duplicates it. Refuse if `VIG_LAN_SUBNET` is empty or not CIDR.

- [ ] **Step 1: Write** the script; `bash -n scripts/homelab-firewall.sh` → no output; `shellcheck` if installed.
- [ ] **Step 2: Dry run on server:** push, `ssh mint 'cd ~/vigilience && git pull --ff-only && ./scripts/homelab-firewall.sh'` → prints rule containing the subnet and `8200:8299`.
- [ ] **Step 3: User applies it** (needs their sudo password — Claude does not run this): `ssh -t mint 'cd ~/vigilience && ./scripts/homelab-firewall.sh --apply'`. Verify: `curl` from the Mac to `:8200` still works; `ssh mint 'sudo iptables -S DOCKER-USER'` shows the rule.
- [ ] **Step 4: Commit** — `"Add LAN-only firewall rule for homelab app ports"`

---

### Task 5: Home Assistant discovery, Apps view, Overview row

**Files:**
- Modify: `config/homeassistant/scripts/probe.sh` (header usage line + `apps` mode)
- Modify: `tests/probe-test.sh`
- Modify: `config/homeassistant/packages/vig_server.yaml` (after `vig_containers`)
- Modify: `config/homeassistant/packages/vig_health.yaml` (warnings block)
- Modify: `config/homeassistant/dashboards/vigilience.yaml`
- Modify: `tests/yaml-structure-check.sh` (expected views)

**Interfaces:**
- Produces:
  - `probe.sh apps` → `{"count": n, "items": [{"name", "url", "icon", "state", "status", "up": bool, "code": int, "ms": float|null}]}` sorted by name; proxy unreachable → `{"count": null, "items": [], "error": "proxy unreachable"}`. Source: same `GET /containers/json?all=1`, filtered to containers with label `homelab.app.name`; each `up` = `http` mode semantics against `url + health` (reuse the `http` branch logic, e.g. by calling `sh "$0" http ...`), probes run in parallel like the stats loop; non-running containers get `up:false, code:0` without probing.
  - `sensor.vig_apps` (command_line, `unique_id: vig_apps`, `scan_interval: 60`, `command_timeout: 30`, `availability: "{{ value_json.count is number }}"`, state = count of `up` items, `json_attributes: [count, items]`, `icon: mdi:apps`).

- [ ] **Step 1: Write failing probe test** in `tests/probe-test.sh`: inside the container, write fixture `/tmp/px/containers/json` (two containers: `app-hello` running with all five labels, url `http://127.0.0.1:18080`, health `/`; `app-dead` State `exited` with labels; plus one unlabelled container), serve it with `python3 -m http.server 18375 -d /tmp/px &`, serve a page on `18080` with a second `http.server`, then with `VIG_DOCKER_PROXY_PORT=18375`:
  - `apps` → `.count == 2`, `[.items[].name] == ["dead","hello"]`, hello `.up == true`, dead `.up == false and .code == 0`
  - with `VIG_DOCKER_PROXY_PORT=9` → `.count == null and .items == []`
  (http.server ignores `?all=1`, so the path resolves to the fixture file.)
- [ ] **Step 2: Run** `tests/probe-test.sh` → FAIL (`unknown mode`).
- [ ] **Step 3: Implement** `apps` mode in `probe.sh`.
- [ ] **Step 4: Run** `tests/probe-test.sh` → PASS.
- [ ] **Step 5: Add `sensor.vig_apps`** to `vig_server.yaml`; in `vig_health.yaml` warnings, append one entry per item with `up == false`: `'App <name> is down'`, guarded so a missing attribute yields nothing.
- [ ] **Step 6: Dashboard:**
  - New view `title: Apps`, `path: apps`, `icon: mdi:apps`, inserted directly after Overview. One full-width markdown card (style of the Docker containers table at the Server view): per item a row `🟢/🔴 | <ha-icon icon> [name](url) | status | ms`; empty list → `No apps deployed yet. See docs/deploying-apps.md.`; sensor unavailable → `App data not available (socket proxy not responding).`
  - Overview "Quick actions" markdown: after the existing links, a second line listing each app as `<a href=url target=_blank><ha-icon icon></ha-icon> name</a>` prefixed 🟢/🔴, only when items exist; heading tap navigates to `apps`.
  - `tests/yaml-structure-check.sh`: expected views → `["overview","apps","server","network","smart-home","cameras","security","activity"]`.
- [ ] **Step 7: Run** `tests/run-all.sh` → `all checks passed`.
- [ ] **Step 8: Commit, push, deploy Vigilience:** commit `"Show homelab apps in the dashboard"`, `git push`, `ssh mint 'cd ~/vigilience && ./scripts/deploy.sh'` → verify step passes.
- [ ] **Step 9: Verify live:** within 60 s `sensor.vig_apps` state is `1` with `hello` up (check via the dashboard Apps view in the browser pane at `http://<lan-ip>:8123/vigilience/apps` — user signs in through the PIN gate themselves). Then `homelab-deploy down hello`, wait 60 s → hello disappears from Apps view; redeploy hello so the example stays visible (user's call).

---

### Task 6: Agent/human deploy guide and Claude skill

**Files:**
- Create: `docs/deploying-apps.md`
- Create: `skills/homelab-deploy/SKILL.md`
- Modify: `README.md` (repo layout + one "Hosting your own apps" paragraph linking the guide), `docs/architecture.md` (apps box in the diagram), `docs/security.md` (LAN-only model, labels readable by HA, no auth on apps)

**`docs/deploying-apps.md` must contain, in this order:**
1. **When this applies:** user says deploy to "the home server", "hp", "mint", "linus server", "homelab".
2. **What the app must have:**
   - `homelab.yaml` (full key table from Task 1, with three complete examples: docker app, compose app with Postgres, static site).
   - Listens on `0.0.0.0:<container_port>`, not `localhost`.
   - Answers HTTP on `health_path` with 2xx, 3xx or 401 within ~30 s of start (a 404 on `/` counts as down — set `health_path`).
   - All persistent data in named volumes (`data:` key or compose `volumes:`); no bind mounts, no host paths.
   - Compose apps: no `ports:` on any service (the tool adds the one port), no `container_name`, no `privileged`; DB reached by service name on the compose network.
   - Config via env vars; secrets never in the repo or labels — put them in `~/.config/homelab/<name>.env` on the server (`ssh mint 'install -m 600 /dev/null ~/.config/homelab/<name>.env'`, then edit). Compose files interpolate `${VAR}` from the same file.
   - Images built for `linux/amd64` from pinned base tags (no `:latest`).
   - Static: `build` produces `dist/index.html` (or set `dist`).
3. **Pick a port:** `homelab-deploy ls` → choose a free one in 8200–8299.
4. **Deploy:** `homelab-deploy` (in the app folder) or `homelab-deploy path/to/app`; what success looks like; redeploy = same command.
5. **Operate:** `ls`, `logs <name>`, `down <name>` (volumes kept); the dashboard Apps view picks it up within a minute.
6. **Troubleshooting:** each CLI error message → fix (port conflict, other source/`--force`, check violations, health hint, `VIG_LAN_IP` missing).
7. **Agent rules:** never deploy without the user asking; never use `--force` or `down` without asking; never edit Vigilience files to add an app; never widen the socket proxy; never commit the server IP; if `homelab-deploy` is not on PATH, it lives at `/Users/amir/Workspace/homelab-dashboard/scripts/homelab_deploy.py`.

**`skills/homelab-deploy/SKILL.md`:** frontmatter `name: homelab-deploy`, `description:` "Use when the user asks to deploy, host or run an app on their home server (the HP server, mint, the linus server, homelab) so it is reachable on the home network." Body: 5–10 lines — read `/Users/amir/Workspace/homelab-dashboard/docs/deploying-apps.md` in full before acting, then follow it.

- [ ] **Step 1: Write** both files and doc updates.
- [ ] **Step 2: Install skill:** `ln -sfn "$PWD/skills/homelab-deploy" ~/.claude/skills/homelab-deploy`; `ls -l ~/.claude/skills/homelab-deploy/SKILL.md` resolves.
- [ ] **Step 3: Dry-run the guide as an agent would:** in a scratch dir, create a tiny docker app (`python:3.12-alpine`, `python -m http.server 8000`, `homelab.yaml` with port `8201`, `container_port: 8000`) by following only `docs/deploying-apps.md`; `homelab-deploy` succeeds; `homelab-deploy down` it afterwards. Fix any guide gap found.
- [ ] **Step 4: Run** `tests/run-all.sh` → `all checks passed` (secret scan covers new docs).
- [ ] **Step 5: Commit** — `"Document homelab app deploys for humans and agents"`; push.
