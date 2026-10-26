# Deploying apps to the home server

How to host a self-built app on the HP server so it is reachable **only on
the home network**, deployed straight from the MacBook. Written for both
humans and coding agents working in other projects.

## When this applies

The user asks to deploy, host or run an app on "the home server", "the HP
server", "hp", "mint", "the linus server" or "the homelab". The server is
reached over SSH as the alias `mint` (user `linus`). The deploy tool is
`homelab-deploy` on the Mac's PATH; if it is missing, it lives at
`/Users/amir/Workspace/homelab-dashboard/scripts/homelab_deploy.py`
(symlink it with `ln -sf <that path> ~/.local/bin/homelab-deploy`).

Deployed apps appear automatically, with a live up/down dot, in the
Vigilience Home Assistant dashboard (**Apps** view, and a link row on
**Overview**) within about a minute. Nothing in this repo is edited per app.

## What the app must have

1. **A `homelab.yaml` manifest** in the app's folder. Flat `key: value`
   lines only (no nesting, no lists; `#` comments are fine).

   | key | required | meaning |
   |---|---|---|
   | `name` | yes | lowercase letters, digits, dashes; starts with a letter; max 30. Unique per app |
   | `port` | yes | LAN port, **8200–8299**, one per app |
   | `kind` | no | `docker` (has a `Dockerfile`), `compose` (has `compose.yaml`), `static` (built site). Inferred from the files present; `static` must be set explicitly |
   | `container_port` | docker, compose | port the app listens on inside its container |
   | `icon` | no | Material Design icon for the dashboard, e.g. `mdi:notebook` (default `mdi:application`) |
   | `health_path` | no | path that answers 2xx/3xx/401 when healthy (default `/`) |
   | `memory` | no | memory limit, e.g. `256m`, `1g` (default `512m`) |
   | `data` | docker only | absolute path in the container to persist in a named volume, e.g. `/app/data` |
   | `build` | static only | command run on the Mac before upload, e.g. `npm run build` |
   | `dist` | static only | folder holding `index.html` after the build (default `dist`) |
   | `service` | compose only | compose service that receives the port (default: `name`) |

2. **It listens on `0.0.0.0:<container_port>`**, not `localhost`/`127.0.0.1`.
   (Vite/Next/Flask dev defaults bind to localhost; production servers
   usually take `--host 0.0.0.0` or `HOST=0.0.0.0`.)

3. **It answers HTTP on `health_path` with 2xx, 3xx or 401** within about 30
   seconds of starting. A 404 on `/` counts as down: set `health_path` to a
   route that exists (e.g. `/health`).

4. **Persistent data lives in named volumes only.** Use `data:` (docker
   kind) or a top-level `volumes:` entry in your compose file. **No bind
   mounts** (`./data:/data`, `/home/...:/x`): the server's home folder is
   encrypted and not mounted after an unattended reboot, and the deploy
   tool refuses bind mounts.

5. **Compose apps** (e.g. app + Postgres):
   - no `ports:` on any service — the tool publishes the one `port` itself;
   - no `container_name`, no `privileged`, no `network_mode: host`;
   - other services (databases) are reached by service name, e.g.
     `postgres://app:${POSTGRES_PASSWORD}@db:5432/app`.

6. **Configuration via environment variables; secrets never in the repo
   or in labels.** Put server-side secrets in
   `~/.config/homelab/<name>.env` on the server:

   ```bash
   ssh mint 'mkdir -p ~/.config/homelab && install -m 600 /dev/null ~/.config/homelab/<name>.env'
   ssh -t mint 'nano ~/.config/homelab/<name>.env'
   ```

   For `docker`/`static` apps it is loaded as the container's environment;
   for `compose` apps it is passed as `--env-file`, so `${VAR}` in your
   compose file resolves from it (add `env_file: ~/.config/homelab/<name>.env`
   to a service if the container itself needs the variables). Local `.env*`
   files are never uploaded.

7. **Pinned base images** (`node:22.11-alpine`, not `node:latest`). The
   server is `linux/amd64` and builds the image itself, so no cross-builds.

8. **Static sites:** `build` must produce `<dist>/index.html`. The files are
   baked into an `nginx:1.27.3-alpine` image (single-page apps: client-side
   routes other than `/` return 404 from plain nginx; use hash routing or
   ship your own Dockerfile as a `docker` app).

### Examples

Docker app (Node server listening on 3000):

```yaml
name: notes
port: 8201
container_port: 3000
icon: mdi:notebook
health_path: /health
data: /app/data
```

Compose app with Postgres (`compose.yaml` has services `web` and `db`, no
`ports:`, a named volume `pgdata` for `db`):

```yaml
name: budget
port: 8202
service: web
container_port: 8000
icon: mdi:cash
memory: 768m
```

Static site:

```yaml
name: recipes
port: 8203
kind: static
build: npm ci && npm run build
dist: dist
icon: mdi:chef-hat
```

A minimal working example lives in `examples/hello-static/`.

## Pick a port

```bash
homelab-deploy ls
```

Choose a port in 8200–8299 that no listed app uses. The deploy refuses a
port held by another app or by anything else on the server.

## Deploy

From the app folder (or pass the folder):

```bash
homelab-deploy
homelab-deploy path/to/app
```

What happens: checks the server → uploads the source to `~/apps/<name>/`
(respecting `.gitignore`; `.git`, `.env*`, `node_modules` excluded) →
renders the compose config and refuses anything that breaks the rules above
→ `docker compose up -d --build` → waits up to 30 s for a healthy HTTP
answer. Success ends with:

```
✓ notes → http://<server-lan-ip>:8201
```

Redeploying is the same command. Apps restart automatically after a reboot.

## Operate

```bash
homelab-deploy ls            # all apps: name, URL, state
homelab-deploy logs notes    # follow logs (Ctrl-C to stop)
homelab-deploy down notes    # stop and remove containers; data volumes are kept
```

## Troubleshooting

| Message | Fix |
|---|---|
| `homelab.yaml: ...` | Fix the manifest key named in the message (see the table above) |
| `port N is already used by app 'x'` / `is in use on the server` | Pick another free port from `homelab-deploy ls` |
| `~/apps/<name> was deployed from <host:path>` | Another folder already owns this name. Rename the app, or `--force` **only if** this folder is meant to replace it |
| `refusing to start: ...` | Remove `ports:`, bind mounts, `privileged` or host networking from your compose file as listed |
| `no healthy HTTP answer ... must listen on 0.0.0.0:N` | Bind the server to `0.0.0.0`, check `container_port`, set `health_path`, read `homelab-deploy logs <name>` |
| `VIG_LAN_IP not set` | Server setup is incomplete: add `VIG_LAN_IP` to `~/.config/vigilience/production.env` on the server |
| `Permission denied (publickey)` | The server rebooted and its encrypted home is not mounted; log in on the server once, then retry |

## Rules for agents

- Deploy only when the user asked for it.
- Never use `--force` or `homelab-deploy down` without asking the user first.
- Never edit the Vigilience repo (dashboard, `compose.yaml`, socket-proxy
  allowlist) to add an app — discovery is automatic.
- Never commit the server's IP address or any secret; never put secrets in
  `homelab.yaml`.
- Before the first deploy, check the app against "What the app must have"
  and add a `homelab.yaml` (commit it with the app).
- After deploying, report the URL from the `✓` line, and say if the health
  wait failed.
