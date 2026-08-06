# Wi-Fi field console debugging

The **BoatMonitor** AP (`boatmonitor` password) only means the CYW43439 radio is in AP mode. The web UI is a **single-threaded** HTTP server on the Pico (`field_console.py`). The AP can stay up while pages stop loading if that loop is **blocked** or **MicroPython crashed**.

## Quick checks on the iPhone

1. Use **`http://192.168.4.1`** (not `https`). Safari often upgrades to HTTPS and then fails.
2. Try **`http://192.168.4.1/ping`** — should show plain text `ok` in under a second.  
   - **Ping works, `/` does not:** status page is slow or stuck (modem/I2C); wait up to ~60s once, or power-cycle.
   - **Ping does not work:** HTTP server is down or phone traffic is not reaching the Pico (see below).
3. Turn **cellular data off** temporarily (or enable Airplane Mode and re-enable Wi‑Fi only). iOS sometimes routes traffic off the boat AP when it thinks there is “no internet”.
4. Close extra Safari tabs on the console; auto-refresh every 10s stacks requests on a server that only handles **one connection at a time** (`listen(5)` queue, but one active handler).

## USB serial (best signal)

1. Connect the Pico to a laptop with **Thonny** (or any serial monitor, 115200 baud).
2. Reproduce: app **Start Wi‑Fi** → reboot → join **BoatMonitor** → open the page.
3. Look for:
   - `AP active: BoatMonitor`
   - `Web server listening`
   - Lines like `HTTP GET /ping from ('192.168.4.1', …)` when you load pages
4. If you see **tracebacks** (`MemoryError`, `OSError`, etc.) right before pages die, copy that text — it is the real failure.
5. If output **stops entirely** but the AP remains, the RP2040 may have hung or reset; do a **full power cycle** (unplug ~10s). Soft reset does not always clear Wi‑Fi/BLE radio state on the CYW43439.

## Common causes

| Symptom | Likely cause |
|--------|----------------|
| AP visible, nothing loads | HTTP loop blocked on a **long** `/` request (`update_modem_cache()` talks to the modem for many seconds) or crashed interpreter |
| Worked, then died after **Log Now** / **OTA** | Background thread + modem work; rare **MemoryError** on Pico W — check serial, reboot |
| Intermittent on iPhone only | Captive-portal / probe URLs; firmware **1.1.6+** answers those with a fast `204` instead of running the full status page |
| After many soft reboots | Stale CYW43439 state — **power cycle** |

## Recovery without a laptop

1. Power-cycle the Pico.
2. Reconnect with the **iOS app** over BLE and tap **Start Wi‑Fi** again (writes `wifi_mode.txt` and reboots into the console).
3. Open **`http://192.168.4.1/ping`** first, then **`http://192.168.4.1/`**.

## Updating console firmware

OTA manifest on GitHub may ship `field_console.py` in a point release. Until you are on that version, paste the updated `field_console.py` via Thonny or **Update Files** on the console if it still responds.
