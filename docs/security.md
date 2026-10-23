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
- Every view requires a Home Assistant login. Use a unique strong password;
  enable TOTP MFA in your profile.
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
