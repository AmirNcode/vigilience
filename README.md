# Vigilience

A private, self-hosted control center for a home server and home network.
It answers, at a glance: is the internet up, are the server's services
(Immich, Plex) healthy, how are CPU / RAM / temperature / storage trending,
and what changed recently.

Built on **Home Assistant Container** (auth, dashboards, history, alerts) with
**Glances** for host metrics and an **allowlisted Docker socket proxy** for
container status. Everything is configuration-as-code in this repository;
private values and runtime state live only on the server.

> This repository is public. It contains no credentials, network inventory,
> camera URLs or runtime state. See [docs/security.md](docs/security.md).

## What you get

| View | Contents |
|---|---|
| **Overview** | Health headline, status strip (internet, server, Immich, Plex, WD drive, backups), "needs attention" list, latency + CPU/RAM 24 h charts, storage gauges, quick links, recent activity |
| **Server** | CPU usage/temp/frequency/load, memory/swap, SSD + WD drive capacity and mount state, Docker containers (status, uptime, CPU, RAM), service response times, 7–30 day charts |
| **Network** | Internet vs gateway reachability (tells ISP outage from local fault), latency and packet loss, 7-day uptime, HP Wi-Fi throughput |
| **Smart Home / Cameras** | Integration status; populates once devices are added in the HA UI. No fake controls or feeds |
| **Security** | Access model, backup risk, software inventory, explicit blind spots |
| **Activity** | 72 h timeline of outages/recoveries/threshold alerts, 7-day availability, editable alert thresholds |

Every value is measured. Anything not integrated is labelled
*Not configured* or *Not available*.

## Architecture

```
iPhone / Mac ──LAN or home VPN──► PIN gate :8123  (6+ digit PIN, remembered 24 h)
                                    ▼
                                  Home Assistant 127.0.0.1:8124  (login required)
                                    │  YAML packages: rest + command_line sensors
                                    ├─► Glances API      127.0.0.1:61208 (host metrics)
                                    ├─► socket proxy     127.0.0.1:2375  (GET container list + stats only)
                                    ├─► probe.sh → ping gateway / 2 internet hosts
                                    └─► probe.sh → HTTP Immich :2283, Plex :32400/identity
```

Details: [docs/architecture.md](docs/architecture.md).

## Quick start

```bash
# On the server, once
git clone https://github.com/AmirNcode/vigilience.git ~/vigilience
mkdir -p ~/.config/vigilience
install -m 600 ~/vigilience/.env.example ~/.config/vigilience/production.env
nano ~/.config/vigilience/production.env      # set VIG_* values
cd ~/vigilience && ./scripts/set-pin.sh       # dashboard PIN
./scripts/deploy.sh
```

Then open `http://<server-ip>:8123`, create the admin account, move Home
Assistant behind the PIN gate (one UI step, see the runbook), and choose
**Vigilience** in the sidebar. Full runbook: [docs/deployment.md](docs/deployment.md).

## Repository layout

```
compose.yaml                     PIN gate, Home Assistant, Glances, socket proxy
pin-gate/                        PIN reverse proxy (stdlib Python) + Dockerfile
.env.example                     template for the server-only env file
config/homeassistant/
  configuration.yaml             managed HA config
  packages/                      sensors, health logic, alerts
  dashboards/vigilience.yaml     the dashboard (7 views)
  themes/vigilience.yaml         dark theme
  scripts/probe.sh               ping/HTTP probe helper
scripts/                         preflight, deploy, verify, backup, restore, rollback
tests/                           secret scan, compose invariants, HA check_config, probe tests
docs/                            architecture, deployment, security, integrations, troubleshooting
```

## Development

```bash
./tests/run-all.sh     # needs Docker; validates everything that can be checked off-server
```

Deployment is manual over SSH. There is deliberately no CI/CD.
