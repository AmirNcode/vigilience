# Integration matrix

Status legend: **Live** (real data, verified on the server) · **Not
configured** (possible, needs your input) · **Not available** (current
hardware/topology cannot provide it).

## Infrastructure

| Signal | Source | Status |
|---|---|---|
| CPU %, load, frequency | Glances `/api/4/quicklook`, `/load` | Live |
| CPU package / NVMe temperature | Glances `/api/4/sensors` (coretemp, nvme hwmon) | Live |
| RAM, swap | Glances `/api/4/mem`, `/quicklook` | Live |
| Internal SSD capacity | Glances `/api/4/fs` via SSD probe volume | Live |
| WD drive capacity + mount state | Glances `/api/4/fs` via read-only `rslave` bind | Live |
| WD SMART health | smartctl over USB bridge | Not configured (needs root; USB bridge support unverified) |
| Docker containers | socket proxy (list + stats) | Live |
| HP Wi-Fi throughput | Glances `/api/4/network` | Live (server's own traffic only) |
| Internet reachability, latency, loss | ping to 2 public resolvers | Live |
| Gateway reachability, latency | ping to router LAN IP (env) | Live once `VIG_GATEWAY_HOST` set |
| Immich health | HTTP `/api/server/ping` | Live |
| Plex health | HTTP `/identity` (native service) | Live |
| Battery | Glances sensors | Shown only if the OS reports a percentage |
| Wall power / kWh | — | Not available (no meter) |
| Intel GPU | — | Not available (no supported exporter) |
| Internet speed history | Speedtest Tracker or HA Speedtest | Not configured (Phase 2) |
| LAN device inventory / new devices | NetAlertX | Not configured (Phase 2, needs approval: raw-socket ARP scan) |
| Per-device / household bandwidth | — | Not available (gateway exports no flows) |

## Smart home and cameras

All of these are added from **Settings → Devices & services → Add
integration** in Home Assistant (sign-in/MFA happens there, credentials stay
in `.storage`). After an integration exists, its entities appear on the Smart
Home / Cameras views automatically.

| Device | HA integration | Status / what's needed |
|---|---|---|
| ecobee thermostat | ecobee (official, cloud) | Not configured: ecobee account sign-in |
| VeSync switch + 3 outlets | VeSync (official, cloud) | Not configured: VeSync sign-in; confirm models |
| Meross outdoor switch | none official; evaluate before using a custom component | Not configured: model needed |
| Shark robots ×2 | SharkIQ (official, cloud) | Not configured: models/account |
| Roomba | iRobot Roomba and Braava (official, local) | Not configured: model + on-robot pairing |
| Fire TV ×2 | Android TV Remote (official, local) | Not configured: pairing code on TV |
| Apple TV | Apple TV (official, local) | Not configured: pairing code on TV |
| Legacy analog DVR + 3 wired cameras | Generic Camera (still image URL, basic auth) | Snapshots only: DVR has no RTSP/ONVIF. Entities `camera.dvr_ch1`, `camera.dvr_ch3`, `camera.dvr_ch4`. HD needs HD-over-coax cameras + hybrid DVR |
| Tapo porch camera | TP-Link Tapo (official) | Not configured: model + camera account |
| Blink ×3 | Blink (official, cloud) | Not configured: account sign-in; snapshots/motion/battery only |

## Adding an integration later

1. Verify the exact model is supported (integration docs page → supported devices).
2. Add it in the HA UI. Note the created entity ids.
3. If you want it on a specific view with controls, add tile cards for those
   entity ids to `config/homeassistant/dashboards/vigilience.yaml`, run
   `./tests/run-all.sh`, commit, push, deploy.
4. Update this matrix with the verified status.
