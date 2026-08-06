# Remote control via Google Sheets

You can change boat behavior **from the spreadsheet** without visiting the Pico. Every successful **log POST** (auto-log or Log Now) returns a `commands` object from Apps Script; firmware applies it before the next sleep interval.

**Requires:** Apps Script **receiver v3** (`RECEIVER_VERSION = 3` in `Code.gs`) deployed as a **new Web App version** (see `APPS_SCRIPT_SETUP.md`). Pico firmware with `remote_control.py` (OTA **1.1.7+**).

## Config tab

Created by `sheets_bootstrap.py` — columns: `key` | `value` | `updated_utc` | `note`.

| Key | Value example | Effect |
|-----|----------------|--------|
| `interval_engine_on_s` | `300` | Auto-log interval while mode is `key_on` (min 60) |
| `interval_engine_off_s` | `3600` | Auto-log when engine off / docked (min 60) |
| `min_fw_version` | `1.1.7` | If Pico `version.py` is older, run **OTA** on that log cycle |
| `cmd_ota` | `1` | **One-shot:** OTA + reboot after this log; cell cleared by script |
| `cmd_reboot` | `1` | **One-shot:** reboot after this log; cell cleared |

Per-device keys use `device_id:` prefix (device id from logs, e.g. `boat-p2`):

| Key | Value |
|-----|--------|
| `boat-p2:cmd_ota` | `1` |
| `boat-p2:interval_engine_off_s` | `1800` |

Keys without a prefix apply to **all** devices.

## What still happens on boot

`AUTO_OTA_ON_BOOT` in `ota_config.py` still checks GitHub on every **power-on / reset**. Sheet commands add:

- OTA **between** logs (no boat visit)
- Interval changes **without** reflashing
- Forced reboot

## Firmware update flow (fully remote)

1. Merge firmware + bump `ota_manifest.json` on GitHub `master`.
2. In **Config**, set either:
   - `min_fw_version` = new version (persistent until Pico catches up), or
   - `cmd_ota` = `1` once (or `boat-p2:cmd_ota`).
3. Wait for the next **auto-log** (or trigger Log Now over BLE). The Pico downloads the manifest over cellular, installs, and reboots.

No TestFlight or Wi-Fi console required for Pico updates.

## GitHub config file (optional later)

A raw JSON file in the repo (e.g. `boat_monitor/remote_config.json`) could be fetched on each log for extra keys. The sheet is enough for intervals and OTA triggers and is easier to edit on a phone. Both can coexist later (sheet overrides file).

## How to verify (remote test)

| Signal | Where | What to look for |
|--------|--------|------------------|
| Firmware version | **Power_Log** `note` column | `auto_log fw=1.1.9` (auto-log rows only) |
| Config applied | **Events** tab | `event=remote_config`, `detail` lists intervals / `cmd_ota` / `min_fw_version` |
| Log cadence | **Power_Log** timestamps | ~**6 minutes** apart after `interval_engine_*_s=360` |
| OTA ran | Next **Power_Log** `note` | `fw=` bumps from `1.1.8` → `1.1.9` |
| BLE (if nearby) | App status JSON | `"fw": "1.1.9"` |

Interval overrides are **in RAM only** (lost on reboot until Config is read again on the next log POST).
