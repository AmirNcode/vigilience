# Deployment runbook

Production runs on the HP server under Docker Compose project `vigilience`.
Deployment is always manual: **Mac → `git push origin main` → SSH to the
server → `./scripts/deploy.sh`**. Pushing to GitHub changes nothing in
production by itself.

Paths on the server:

| What | Where |
|---|---|
| Git checkout (public code) | `~/vigilience` |
| Private env file | `~/.config/vigilience/production.env` (mode 600) |
| Deploy history | `~/.config/vigilience/deploy-history.log` |
| Home Assistant state | Docker volume `vigilience_ha_config` |
| Config backups | `~/vigilience-backups/` |

## 1. One-time bootstrap

```bash
ssh <user>@<server-ip>
git clone https://github.com/AmirNcode/vigilience.git ~/vigilience
mkdir -p ~/.config/vigilience && chmod 700 ~/.config/vigilience
install -m 600 ~/vigilience/.env.example ~/.config/vigilience/production.env
nano ~/.config/vigilience/production.env
```

Set `DOCKER_GID` (`getent group docker | cut -d: -f3`), `VIG_GATEWAY_HOST`
(router LAN IP) and the quick-link URLs (`VIG_IMMICH_URL`, `VIG_PLEX_URL`)
as you reach them from your phone.

Set the dashboard PIN (6+ digits; only its hash is stored):

```bash
cd ~/vigilience && ./scripts/set-pin.sh
```

```bash
cd ~/vigilience
./scripts/preflight.sh      # read-only checks; must end with "preflight passed"
./scripts/deploy.sh         # first install
```

Then, from a browser on the LAN, open `http://<server-ip>:8123`:

1. Create the owner account (strong, unique password). Optionally enable
   MFA: profile → Security → Multi-factor authentication modules.
2. Location/units step: set home, metric/°C as preferred.
3. Open **Vigilience** in the sidebar. Optional: profile → Dashboard →
   make Vigilience your default dashboard.

**iPhone:** open the URL in Safari → Share → *Add to Home Screen*. Works on
the LAN and through the home VPN.

### Move Home Assistant behind the PIN gate (once)

Home Assistant 2026.x manages HTTP settings in the UI, not YAML, so this is
one manual step. Until it is done `pin-gate` keeps retrying to bind :8123
and `verify.sh` fails its PIN checks.

1. Open `http://<server-ip>:8123` (still Home Assistant directly), sign in.
2. **Settings → System → Network → HTTP server**:
   - Server port: `8124`
   - Listen addresses: `127.0.0.1`
   - Trust X-Forwarded-For: on; Trusted proxies: `127.0.0.1`
3. Save and restart Home Assistant. Within a few seconds the gate takes
   over :8123; reload the page and enter the PIN.
4. `./scripts/verify.sh` should now pass. The Companion app keeps the same
   URL (`:8123`); open it once and enter the PIN in its webview.

Bypass the gate for recovery (e.g. forgotten PIN before running
`set-pin.sh` again): `ssh -L 8124:127.0.0.1:8124 <server>` and open
`http://localhost:8124`.

Change the PIN any time with `./scripts/set-pin.sh` (signs out every
device). Lock the current device: open `/__vig_pin/lock`.

## 2. Routine deployment

On the Mac:

```bash
./tests/run-all.sh
git status --short          # expect no output
git push origin main
ssh <user>@<server-ip> 'cd ~/vigilience && ./scripts/deploy.sh'
# or: VIG_SSH=<user>@<server-ip> ./scripts/deploy-from-mac.sh
```

`deploy.sh` does, in order, and stops at the first failure:

1. Refuse if the checkout is dirty or not on `main`; `git fetch` +
   `git merge --ff-only origin/main` (refuses diverged history).
2. `preflight.sh` (tools, env file, disk, memory, ports, Immich/Plex health).
3. `docker compose config --quiet` with the production env file.
4. Config backup (skipped on first install).
5. Pull pinned images.
6. `sync-config.sh`: copy managed config into the volume, run Home
   Assistant `check_config`; on failure restore the previous config and stop
   without restarting anything.
7. `docker compose up -d`; restart Home Assistant only if managed config changed.
8. Record `previous -> new` commit, then `verify.sh`.

It never runs `down -v`, never prunes, never touches the Immich project.

## 3. Verify

```bash
./scripts/verify.sh
```

Checks containers, HA UI, Glances API, media drive visibility, container
listing via proxy, that the proxy rejects writes (403), that helper ports are
not on the LAN, Immich/Plex health, and prints resource usage.

## 4. Rollback

```bash
./scripts/rollback.sh              # to the commit before the last deploy
./scripts/rollback.sh <commit>     # to a specific commit
git checkout main                  # afterwards, before the next normal deploy
```

Rollback restores code, config and pinned image versions. It does not roll
back Home Assistant's database. If a rollback downgrades Home Assistant
across a database migration, also restore the matching backup:

```bash
./scripts/restore-config.sh ~/vigilience-backups/vigilience-config-<stamp>-<commit>.tar.gz
```

## 5. Updating image versions

1. Read the release notes (Home Assistant breaking changes in particular).
2. Bump `HA_VERSION` / `GLANCES_VERSION` / `SOCKET_PROXY_VERSION` defaults in
   `compose.yaml` **and** `.env.example`; run `./tests/run-all.sh`.
3. Commit, push, deploy. Also update the versions in the server's
   `production.env` if you set them there (env file values win).

## 6. Stop / remove (non-destructive)

```bash
docker compose --project-name vigilience --env-file ~/.config/vigilience/production.env -f compose.yaml stop
```

To remove containers but keep all state: replace `stop` with `down` (no `-v`).
