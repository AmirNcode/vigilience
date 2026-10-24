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
| Kasa kitchen switch (HS200) | TP-Link Smart Home (official, local) | Connected: `switch.kitchen_lights` |
| Shark robots ×2 | Custom `sharkiq` (dr34ming/ha-sharkiq @ `c2482d7`, cloud) — overrides the official one, whose server-side login Shark's Auth0 blocks ("Suspicious request requires verification") | Installed; not signed in yet. Browser PKCE sign-in, see below |
| Roomba | iRobot Roomba and Braava (official, local) | Not configured: robot (found on the LAN, MQTT port 8883 open) returns a password it then rejects ("Bad username or password"); model needed |
| Fire TV ×2 | Android TV Remote (official, local) | Not configured: pairing code on TV |
| Apple TV | Apple TV (official, local) | Not configured: pairing code on TV |
| Legacy analog DVR + 3 wired cameras | Generic Camera (still image URL, basic auth) | Snapshots only: DVR has no RTSP/ONVIF. Entities `camera.dvr_ch1`, `camera.dvr_ch3`, `camera.dvr_ch4`. HD needs HD-over-coax cameras + hybrid DVR |
| Tapo pan/tilt camera (Chipstead) | TP-Link Smart Home (official, local) | Connected: `camera.chipstead_live_view`, pan/tilt buttons on the Cameras view. Needed Tapo Lab → Third-Party Compatibility |
| Blink ×3 | Blink (official, cloud) | Not configured: account sign-in; snapshots/motion/battery only |

## Custom integrations (HACS)

HACS 2.0.5 and the custom `sharkiq` integration were copied by hand into
`/config/custom_components/` in the `vigilience_ha_config` volume. Deploys never
touch that directory, and `scripts/backup-config.sh` includes it.

- **Pinned, reviewed code.** `custom_components/sharkiq/.source-commit` records
  the commit that was reviewed. It only talks to `login.sharkninja.com` and
  `user-sharkue1.aylanetworks.com` and never sees the Shark password. Read the
  diff before accepting an update offered by HACS.
- **Overrides core.** It shadows the official `sharkiq`. When HA ships a
  `sharkiq` library that signs in again (reportedly 1.5.1+), delete
  `custom_components/sharkiq`, restart, and switch back to the official one.

## Adding an integration later

1. Verify the exact model is supported (integration docs page → supported devices).
2. Add it in the HA UI. Note the created entity ids.
3. If you want it on a specific view with controls, add tile cards for those
   entity ids to `config/homeassistant/dashboards/vigilience.yaml`, run
   `./tests/run-all.sh`, commit, push, deploy.
4. Update this matrix with the verified status.
