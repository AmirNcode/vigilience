# Security model

## Public code, private service

- Repository: code and sanitized templates only. `tests/secret-scan.sh`
  blocks private IPv4/MAC addresses, credential-like assignments, tokens,
  private keys, RTSP and Plex-token URLs, and known private files.
- Server-only: `~/.config/vigilience/production.env` (mode 600) holds the
  gateway address and link URLs; Home Assistant users, tokens and
  integration credentials stay in its `.storage/` inside the Docker volume.

## Access

- The dashboard is Home Assistant on port 8123, reachable on the home LAN and
  over the existing home VPN. Nothing is port-forwarded or tunnelled to the
  internet by Vigilience.
- **PIN gate first.** `pin-gate` owns port 8123 and Home Assistant listens
  only on `127.0.0.1:8124`. A browser must enter the dashboard PIN (6+
  digits) before anything — including the Home Assistant login page —
  reaches Home Assistant. The device is then remembered for 24 hours
  (signed `HttpOnly` cookie, fixed expiry); `/__vig_pin/lock` forgets it.
- Every view still requires a Home Assistant login after the PIN. Use a
  unique strong password; enable TOTP MFA in your profile.
- If more people get access, create **non-admin** users. Home Assistant
  does not offer per-entity read-only permissions; non-admins can still
  operate devices shown on dashboards but cannot change configuration.
- Optional hardening (deliberately not enabled by default, because changing
  `http:` settings triggers a confirmation dialog on first login): add to
  `configuration.yaml`
  ```yaml
  http:
    ip_ban_enabled: true
    login_attempts_threshold: 10
  ```

## Self-hosted apps

- Apps deployed with `homelab-deploy` publish one port each (8200–8299) on
  the server's LAN IP only; the tool refuses extra ports, wildcard binds,
  host networking, `privileged` and bind mounts.
- `scripts/homelab-firewall.sh --apply` adds a `DOCKER-USER` rule dropping
  traffic to those ports from outside `VIG_LAN_SUBNET` (Docker-published
  ports bypass ufw's INPUT rules). It is persistent only when ufw is
  enabled.
- Apps have **no authentication** unless they bring their own; LAN-only
  reachability is the gate. Anyone on the home Wi-Fi can open them.
- Home Assistant reads every container's labels; `homelab.app.*` labels
  hold only name, URL, icon, port and health path. Secrets go in
  `~/.config/homelab/<name>.env` on the server (mode 600), never in labels
  or the app's repo.

## PIN gate

| Concern | Control |
|---|---|
| PIN storage | Only a PBKDF2-SHA256 hash (600k iterations, random salt) in the server env file, written by `scripts/set-pin.sh`. Changing the PIN rotates the cookie signing key, so every device must re-enter it. |
| Brute force | 5 wrong PINs per client IP lock that IP for 15 min; 30 wrong PINs across all clients in an hour lock everyone out for the rest of that hour. 1 s delay per wrong PIN. Attempts are logged (`docker logs vigilience-pin-gate`). |
| What passes without the PIN | Requests Home Assistant authenticates with a token itself: `/api/*` (REST, `/api/websocket`, webhooks with secret ids, camera/HLS with signed URLs) and `/auth/token`, `/auth/revoke`. This keeps the Companion app's background traffic working. Consequence: anyone already holding a valid HA token (e.g. extracted from an unlocked device) does not need the PIN. |
| What needs the PIN | Everything else: the frontend, `/auth/authorize` and the login flow (so HA passwords cannot be guessed without the PIN), static files. |
| Bypass attempts | Paths with `.`/`..` segments (also percent-encoded), `//` or `\` are rejected; one upstream connection per request and exactly `Content-Length` body bytes forwarded, so a second request cannot be smuggled behind an exempt one; only a real websocket handshake to `/api/websocket` may upgrade without the cookie; client `X-Forwarded-*`/`Forwarded` headers are replaced. Service-worker scripts return 404 so browsers cannot serve a cached UI offline. |
| Transport | Plain HTTP on the LAN/VPN like before; the cookie is not marked `Secure`. Anyone who can sniff the LAN can capture it (same as the HA session). |
| Container | Standard-library Python, non-root (`nobody`), read-only root fs, all capabilities dropped, no mounts; fails to start if no PIN is set. |

## Least privilege

| Concern | Control |
|---|---|
| Docker socket | Only the socket proxy mounts it (read-only, non-root, all capabilities dropped). Anchored allowlist: `GET /containers/json` and `GET /containers/<id>/stats`. Inspect (which would reveal container environment variables/secrets), logs, export, archive, exec, images and every non-GET method are refused — `verify.sh` asserts 403/405 for these. |
| Proxy exposure | Listens on `127.0.0.1` and only accepts loopback clients. Local processes can see container names, images, state and resource usage — nothing more. |
| Glances | REST API bound to `127.0.0.1`, web UI disabled; media drive mounted read-only. |
| Home Assistant | Host networking (official Linux guidance) without `privileged` or device access. No USB/Bluetooth radios passed through. |
| Images | Pinned versions, no `latest`, no auto-updaters. |

## What is not monitored (blind spots)

- Unknown devices joining the network (needs NetAlertX, Phase 2).
- Network-wide traffic or intrusions: the gateway exports no flow data and
  the server sees only its own traffic. Requires a flow-capable router,
  managed switch with port mirroring, or a TAP.
- DNS queries, port exposure, CVE feeds: not configured.

A quiet Security page means "no signal", not "secure".
