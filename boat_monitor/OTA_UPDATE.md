# Boat Monitor P2 OTA updates

The Pico can update its MicroPython files from GitHub. It prefers **Wi-Fi**
(via `wifi_uplink.py`, if a known network is configured and reachable — no
cellular data usage, no modem needed) and falls back to the SIM7600 **cellular**
modem otherwise. See `APPS_SCRIPT_SETUP.md` for the same Wi-Fi-first pattern
applied to Sheets logging.

## One-time setup on Pico

Copy these files to the Pico:

- `config.py`
- `main.py`
- `ble_service.py`
- `field_console.py`
- `ota.py`
- `ota_config.py`
- `version.py`
- `wifi_uplink.py`
- `cellular.py`

Optional (needed for Wi-Fi-first OTA/Sheets logging — copy
`wifi_credentials.example.py` as `wifi_credentials.py`, fill in your real
SSIDs/passwords; gitignored, never commit it):

- `wifi_credentials.py`

Optional debug/service files:

- `bench_test.py`
- `bench_resilience.py` (home bench: mode, log, OTA — see `BENCH_HOME_TESTING.md`)
- `modem_check.py`
- `ble_probe.py`
- `ble_status.py`
- `gps.py`
- `sheets_log.py`
- `cellular_test.py` (bare cellular connectivity test -- no Sheets/Apps
  Script setup needed, just confirms the modem/SIM/registration/NETOPEN
  sequence works with your antenna and SIM)

## Default boot behavior (0.3.0+)

- Boot first runs an OTA check (`ota_config.AUTO_OTA_ON_BOOT`), **before** BLE
  starts — this is the only place Wi-Fi is safe to try automatically, since
  Wi-Fi and BLE share one radio on the Pico W and cannot run at the same time
  (see `ensure_wifi_off()` in `ble_service.py`). If no configured Wi-Fi
  network is in range, this adds up to ~15s per network before falling back
  to cellular (or skipping OTA entirely if cellular isn't available either)
  — tune `timeout_s` in `wifi_uplink.connect()` calls, or set
  `AUTO_OTA_ON_BOOT = False` in `ota_config.py`, if boot speed matters more
  than automatic update checks.
- Normal boot then starts the **BLE** service (`BoatMonitor` advertisement).
- Use the iOS app or send a BLE command `wifi` to reboot into the **Wi‑Fi
  access point** field console (`wifi_mode.txt` one-shot flag) — this is a
  *different* Wi-Fi mode (the Pico becomes its own AP) than the Wi-Fi *client*
  mode `wifi_uplink.py` uses to reach the internet; both still can't run
  alongside BLE.
- If BLE fails to start, `main.py` falls back to the Wi‑Fi field console.

## Manual OTA from the Pico REPL

```python
import ota
ota.check()
ota.update()
```

Set `reboot=True` to reboot after replacing files:

```python
ota.update(reboot=True)
```

## Manual OTA from phone service page

1. Connect phone to the Pico Wi-Fi AP.
2. Open `http://192.168.4.1`.
3. Tap `OTA from GitHub`.
4. Wait for the update result.
5. Reboot after a successful update.

## Release process

**Read `RELEASE_PROCESS.md` first.** Summary:

1. Update the files in `boat_monitor/`.
2. Bump `VERSION` in `version.py` and the same `version` in `ota_manifest.json`.
3. Run `python3 boat_monitor/build_ota_bundle.py` then `python3 boat_monitor/validate_release.py`.
4. **Merge to `master`** and push.
5. Run `python3 boat_monitor/validate_release.py --check-github`.
6. **Only then** set Config `min_fw_version` (or `apply_ship_config.py`).
7. The installed Pico will pull from:

```text
https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json
```

Never set `min_fw_version` above the version published on **`master`** — see
`RELEASE_PROCESS.md` for why.

## Safety notes

- The updater writes each downloaded file to `<name>.new` before replacing the
  current file.
- The previous file is kept as `<name>.bak` where possible.
- Keep device-specific secrets in `secrets.py` on the Pico only. Do not add
  `secrets.py` to `ota_manifest.json`; it is intentionally ignored by git.
- Avoid removing or renaming `ota.py` and `ota_config.py` from the manifest
  unless you have tested the replacement path.
- Keep `bench_test.py` and `modem_check.py` available as recovery/debug tools.
