# Architecture

## Components

| Service | Image (pinned) | Network | Privileges | Purpose |
|---|---|---|---|---|
| `homeassistant` | `ghcr.io/home-assistant/home-assistant:2026.10.2` | host | none extra (no `privileged`) | Login, dashboards, history DB, alerts |
| `glances` | `nicolargo/glances:4.5.8` | host, `pid: host` | read-only bind of the media drive, empty SSD probe volume | Host CPU/RAM/load/sensors/filesystems/network, container stats |
| `docker-proxy` | `tecnativa/docker-socket-proxy:v0.5.0` | bridge, port bound to `127.0.0.1` | Docker socket mounted read-only, only `GET /containers` and `GET /images` allowed | Lets Glances read container state without socket access |

Compose project name: `vigilience`. Immich and the host-installed Plex are not
referenced by Compose in any way.

## Why these choices

- **Home Assistant** provides authentication, a responsive dashboard
  framework, a history database with long-term statistics, and future
  smart-home integrations. Custom code would duplicate all of that.
- **YAML packages instead of UI integrations.** The Glances, ping and system
  monitor integrations are UI-configured in current Home Assistant. Using the
  `rest` and `command_line` integrations keeps the whole sensor layer in Git,
  reviewable and reproducible on a fresh install.
- **Glances in a container** (instead of the distro's Glances 3.4 service,
  which runs in XML-RPC mode without the REST API) avoids changing system
  services or needing sudo.
- **Docker named volumes for state.** The server's home directory is
  ecryptfs and only mounts after the user logs in. Docker starts earlier at
  boot, so bind-mounting Home Assistant state from the home directory would
  start it against an empty directory after a reboot. Named volumes live in
  `/var/lib/docker` on the internal SSD and are always available.
- **SSD capacity via an empty volume.** Mounting a named volume into Glances
  reports the filesystem holding `/var/lib/docker` (the internal SSD) without
  exposing any host files.
- **Media drive via a read-only `rslave` bind.** If the drive is unmounted on
  the host the unmount propagates into the container, the filesystem
  disappears from Glances, and the dashboard reports *not mounted*.

## Data flow

```
probe.sh (command_line, 60 s)  ─► sensor.vig_*_probe (up/down + ms, loss, code)
                                   └─► template: binary_sensor.vig_internet/gateway/immich/plex
                                   └─► template: sensor.vig_*_latency / *_response (ms; unknown when down)
Glances REST (rest, 30–300 s)  ─► sensor.vig_cpu_usage, memory, load, fs, sensors, network, uptime
Glances containers (jq, 60 s)  ─► sensor.vig_containers (+ items attribute)
health templates               ─► sensor.vig_issues (critical/warnings lists) ─► sensor.vig_health
automations                    ─► persistent notifications + logbook entries
```

Polling cost: ~10 HTTP calls and 5 small ping/curl probes per minute, all
local except the internet pings.

## Health model

| Level | Triggers |
|---|---|
| **Critical** | internet unreachable, gateway down, Immich down, Plex down, WD drive unmounted, metrics not collected |
| **Attention** | SSD or WD free space below threshold (default 15 %), CPU temperature above threshold (default 85 °C), RAM ≥ 90 %, internet latency ≥ 150 ms |
| **Healthy** | none of the above |

The missing media backup is shown permanently as a separate risk, not folded
into the health level, so the headline still changes when something breaks.

## Alerts

- Outage: entity `off` for 2 minutes → one persistent notification per
  service (fixed id, so no duplicates) + logbook entry. Recovery dismisses
  it and logs downtime duration.
- Services already down at startup are caught by a sweep 3 minutes after
  Home Assistant starts.
- Thresholds: condition true for 5 minutes → notification; clears on recovery.
- Dismissing a notification is the acknowledgement.

## Retention

- Recorder: 30 days of state history (`purge_keep_days: 30`), long-term
  hourly statistics kept indefinitely (small).
- Raw probe sensors and per-container detail are excluded from the recorder;
  derived sensors carry the history.
- Container logs: json-file, 3 × 10 MB per container.
