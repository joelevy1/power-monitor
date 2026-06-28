# power-monitor

Boat house/engine power monitoring — Raspberry Pi Pico W on the boat.

**GitHub:** [github.com/joelevy1/power-monitor](https://github.com/joelevy1/power-monitor)

## Layout

| Path | Description |
|------|-------------|
| `boat_monitor/` | **P2** — wiring docs, `bench_test.py`, firmware (in progress) |
| `remotebatterystatus/` | **P1** — deployed firmware; mirrors [remotebatterystatus](https://github.com/joelevy1/remotebatterystatus) |
| `BOAT_MONITOR_P2_PLAN.md` | Phased build plan |

## Bench testing (P2 hardware)

Copy to Pico: `boat_monitor/config.py`, `boat_monitor/bench_test.py` → run `bench_test.main()` in Thonny.

Print wiring: `boat_monitor/WIRING_CHEAT_SHEET.docx`
