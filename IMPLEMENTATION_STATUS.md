# Implementation status

_Last updated: 2026-10-23_

## Phase 0 — audit and repository ✅

- Read-only server audit: Docker/Compose versions, running containers,
  Immich Compose project, native Plex service, disks/mounts, ports, sensors.
- Findings that shaped the design:
  - Home directory is ecryptfs (mounted at login) → Vigilience state uses
    Docker named volumes, not bind mounts from home.
  - Distro Glances 3.4 service runs in XML-RPC mode (no REST API) → separate
    Glances 4.5.8 container on loopback; the system service is untouched.
  - No passwordless sudo → nothing in the deployment needs root.
- Public repo initialised with secret scan, sanitized templates, no handoff.

## Phase 1 — MVP ✅ (deployed)

- [x] Home Assistant Container in Compose project `vigilience`, pinned, no `privileged`
- [x] Git-managed YAML dashboard (7 views) + dark theme, mobile layout checked at 375 px
- [x] Glances host metrics: CPU, RAM, swap, load, temps, SSD, WD drive, Wi-Fi throughput
- [x] Docker container status through a GET-only socket proxy
- [x] Reachability: internet (2 hosts), gateway, Immich, native Plex
- [x] Health model, de-duplicated alerts, activity timeline
- [x] Manual SSH deploy with validation, backup, verify, rollback
- [ ] Owner account onboarding — **user action** (see deployment.md §1)
- [ ] iPhone home-screen + VPN check — **user action**

## Phase 2 — pending

- Internet speed history (≤ 2 runs/day)
- NetAlertX device inventory — needs approval (raw-socket ARP scan of the home subnet)
- Optional: Uptime Kuma only if HA history proves insufficient

## Phase 3 — pending (needs user sign-ins / model info)

ecobee, VeSync, Meross, SharkIQ, Roomba, Fire TV, Apple TV, NVR cameras,
Tapo, Blink. See docs/integration-matrix.md.

## Phase 4–5 — not started

Security posture pages beyond blind-spot listing, off-device backup target,
energy metering (needs hardware).
