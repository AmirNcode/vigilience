# Test results

## 2026-10-23 — initial deployment (commits 6643447 → current)

### Static (Mac, `./tests/run-all.sh`)

| Check | Result |
|---|---|
| Secret scan (private IPs, MACs, credentials, tokens, keys, RTSP, Plex tokens, private files) | PASS |
| Compose renders with example env | PASS |
| Compose invariants: no `privileged`, pinned images, loopback-only helpers, non-root GET-allowlist socket proxy, read-only socket and media mounts, Glances without Docker access | PASS |
| Home Assistant `check_config` (2026.10.2) on the managed config | PASS |
| Dashboard: 7 views, 51 entity references all defined | PASS |
| `probe.sh`: always valid JSON; up/down semantics for ping, HTTP, unset targets | PASS |

### Local runtime (Mac, Docker Desktop, test account on localhost)

| Check | Result |
|---|---|
| All `vig_*` entities created, no template/registry errors in HA log | PASS (after fixes: `none` rendering in rest/command_line, uptime quoting) |
| Desktop render (1440 px) of all views | PASS |
| iPhone-width render (375 px): single column, alerts above fold, `scrollWidth == innerWidth` (no sideways scroll) | PASS |
| Socket proxy: list/stats 200; inspect, logs, export, images, info 403; POST 405 | PASS |
| Startup outage sweep raises alerts for services down at boot | PASS |

### Production (HP server)

| Check | Result |
|---|---|
| `preflight.sh` (tools, env 600, clean checkout, 123 GiB free, media mounted/shared, 8 GiB RAM available, ports free, Immich/Plex up) | PASS |
| `deploy.sh` (ff-only pull, backup, validated sync, up, verify) — 3 deploys | PASS |
| `verify.sh`: HA UI, Glances API, media drive visible, proxy list OK, proxy denies inspect/logs/writes, helpers not on LAN, Immich + Plex healthy, Immich containers healthy | PASS |
| From Mac over LAN: `http://<server-ip>:8123` answers; ports 61208/2375 closed on LAN | PASS |
| Live probes: gateway ~2 ms, internet ~15 ms, Immich 200, Plex `/identity` 200 | PASS |
| Live Glances: CPU package/core temps, NVMe temp, battery, WD exFAT %, SSD %, `wlp1s0` | PASS |
| Container table: 9 containers incl. Immich (healthy) with CPU/RAM | PASS |
| **Outage test**: stopped `vigilience-glances` 160 s → collector `off` + health `Critical` in 3 s → alert logged at +2 min → `recovered … after 3.0 min` → health `Healthy` | PASS |
| Resource footprint (idle): HA ~270–360 MiB, Glances ~88 MiB, proxy ~3 MiB; CPU < 1 % each | PASS (≈ 0.45 GiB total, target ≤ 2 GiB) |
| Immich and Plex unaffected before/after every deploy | PASS |

### Not yet tested (need the owner)

- Home Assistant owner onboarding and dashboard view on the production instance.
- iPhone Safari *Add to Home Screen* on the real device; access through the home VPN.
- Full HP reboot (would briefly interrupt Immich/Plex; needs approval).
- Restore drill (`restore-config.sh`) after real data exists.
