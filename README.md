# Permobil ConnectMe (Gen 1) — Home Assistant integration

Read-only Home Assistant integration for **Permobil Gen 1 ConnectMe** wheelchairs. Exposes seating telemetry (tilt, recline, legrest, elevation, battery voltage) and motion state (driving / actuator active / seat up) as native HA sensors over Bluetooth Low Energy.

Reverse-engineered from the MyPermobil Android app (`com.permobil.sae.dockme`). No Permobil cloud account required, no internet required — pure local BLE.

## Status

Pre-alpha. Protocol decode validated against the decompiled app; live-chair verification still pending. **Do not rely on this for safety-critical use.**

## Compatibility

- **Chairs**: Permobil Gen 1 platforms with the ConnectMe BLE service (`18ca0001-3751-4081-b17c-59f8e09fc175`). Gen 2 PowerPlatform chairs use a different protocol and are out of scope.
- **Home Assistant**: 2025.1.0 or newer.
- **Bluetooth**: any HA-supported BLE adapter (built-in BlueZ, ESPHome BLE proxy, etc.).

## Installation (HACS)

1. HACS → ⋮ → Custom repositories.
2. Add this repo URL, category **Integration**.
3. Install **Permobil ConnectMe**, restart HA.
4. With chair in range and powered on: Settings → Devices & services → Add integration → Permobil ConnectMe (or accept the auto-discovered device prompt).

## Entities

| Entity | Unit | Notes |
|---|---|---|
| `sensor.<serial>_tilt_angle` | ° | Seat tilt, signed |
| `sensor.<serial>_recline_angle` | ° | Backrest, **relative to tilt** |
| `sensor.<serial>_legrest_angle` | ° | Legrest, **relative to tilt** |
| `sensor.<serial>_elevation` | raw | Seat lift; units pending real-chair verification |
| `sensor.<serial>_battery_voltage` | V | Scale assumed centivolts; verify before trusting |
| `sensor.<serial>_chair_type` | — | Model id from VSC key 8 |
| `binary_sensor.<serial>_driving` | — | Chair currently being driven |
| `binary_sensor.<serial>_actuator_active` | — | Seat actuator moving |
| `binary_sensor.<serial>_seat_up` | — | Lift ≥ 4 |

## How it works

The integration:

1. Scans for advertisements carrying service `18ca0001-…`.
2. Connects, reads the TIMER characteristic to get the chassis serial and current ownership window.
3. Waits out the ownership window if needed, then writes `#TAKE\r\n` to the TX characteristic — required to make the chair start emitting telemetry.
4. Subscribes to the RX characteristic and parses VSC text frames (ASCII, hex-encoded, `S<key>:<val>S…K<cksum>\r\n`).
5. Applies the same hysteresis deadband the app uses (0.8° angles, 2.0 lift) and pushes values to HA.

See [the protocol notes](docs/PROTOCOL.md) for full details (TBD).

## Caveats

- Recline and legrest are reported **relative to tilt**, matching the Permobil app. A chair tilted 30° with a backrest at 30° absolute reads recline = 0°.
- The chair only emits telemetry while ownership is held. If the MyPermobil phone app connects simultaneously, expect dropouts.
- Voltage and lift units are not yet calibrated — treat raw values until verified.

## License

MIT.
