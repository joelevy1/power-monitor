# power-monitor

Boat house/engine power monitoring — Raspberry Pi Pico W on the boat.

**GitHub:** [github.com/joelevy1/power-monitor](https://github.com/joelevy1/power-monitor)

## Layout

| Path | Description |
|------|-------------|
| `boat_monitor/` | **P2** — wiring docs, bench tests, field console, OTA-capable firmware |
| `boat_monitor_app/` | **iOS** — Expo BLE app (TestFlight via `EAS_CI.md`; run `npm install` **here**, not repo root) |
| `remotebatterystatus/` | **P1** — deployed firmware; mirrors [remotebatterystatus](https://github.com/joelevy1/remotebatterystatus) |
| `BOAT_MONITOR_P2_PLAN.md` | Phased build plan |

## Bench testing (P2 hardware)

Copy to Pico: `boat_monitor/config.py`, `boat_monitor/bench_test.py` → run `bench_test.main()` in Thonny.

Print wiring: `boat_monitor/WIRING_CHEAT_SHEET.docx`

## Pico field/service files

Core files to copy to Pico:

- `boat_monitor/config.py`
- `boat_monitor/main.py`
- `boat_monitor/field_console.py`
- `boat_monitor/FIELD_CONSOLE_DEBUG.md` — Wi-Fi console troubleshooting (AP up, page won't load)
- `boat_monitor/ota.py`
- `boat_monitor/ota_config.py`
- `boat_monitor/version.py`

Useful debug files:

- `boat_monitor/bench_test.py`
- `boat_monitor/modem_check.py`
- `boat_monitor/ble_probe.py`
- `boat_monitor/ble_status.py`

The phone service console starts a `BoatMonitor` Wi-Fi AP and serves
`http://192.168.4.1`. OTA updates pull files from GitHub using
`boat_monitor/ota_manifest.json`; see `boat_monitor/OTA_UPDATE.md`.
