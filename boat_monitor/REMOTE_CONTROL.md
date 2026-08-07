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
| `wifi_networks` | see below | Saves networks on the Pico (`wifi_sheet.json`); used on next Wi-Fi connect |
| `boat-p2:v50_capacity_mah` | `13400` | V50 rated mAh (Pico + **Away** app % estimate) |
| `boat-p2:v50_full_at_utc` | ISO time | **Mark bank full** — app button **Bank is 100% full**, or set this manually; Pico resets cumulative mAh on next log when it changes |

Use **`boat-p2:v50_capacity_mah` only** — do not set legacy `v50_capacity_wh`. Run `python3 sheets_config_cleanup.py` to remove empty `cmd_*` dupes and backup rows.

**Reset power bank to “100% full”:** In the iOS app → **Away from boat** → **Bank is 100% full** (needs Apps Script **v5** deployed). Or set Config `boat-p2:v50_full_at_utc` to an ISO timestamp (e.g. `2026-08-07T22:00:00Z`). The Pico applies it on the next successful log.

**`wifi_networks` value** — one network per line in the **value** cell (use a tall cell or paste multiple lines):

```text
Seattle Boat|marina-password
HomeSSID|home-password
```

Lines starting with `#` are ignored. Separator is `|` or tab. Applied on every log POST that returns this key (persistent until you change the cell).

## Wi-Fi networks in GitHub (recommended default list)

Edit **`boat_monitor/wifi_known_networks.py`** on `master` — a Python list of `("SSID", "password")` tuples. Tell your Cursor agent what to add; it ships on the next **OTA**.

**On the Pico, try order:** `wifi_credentials.py` (local) → **Sheet** `wifi_networks` → **GitHub** `wifi_known_networks.py`.

Use the **Sheet** when you want a change on the boat without OTA. Use **GitHub** when you want the list versioned and easy to ask the agent to maintain.

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

## How to verify (remote test)

| Signal | Where | What to look for |
|--------|--------|------------------|
| Firmware version | **Power_Log** `fw` column | e.g. `1.1.16` |
| Upload path | **Power_Log** `uplink` column | Wi-Fi SSID or `cellular` |
| Config applied | **Events** tab | `event=remote_config`, `detail` lists intervals / `cmd_ota` / `min_fw_version` |
| Log cadence | **Power_Log** timestamps | ~**6 minutes** apart after `interval_engine_*_s=360` |
| OTA ran | Next **Power_Log** `note` | `fw=` bumps from `1.1.8` → `1.1.9` |
| BLE (if nearby) | App status JSON | `"fw": "1.1.9"` |

Interval overrides are **in RAM only** (lost on reboot until Config is read again on the next log POST).

## Remote reboot when logging stops

| Method | When it works |
|--------|----------------|
| **`cmd_reboot` = `1`** (or `boat-p2:cmd_reboot`) | Next **successful** Power_Log POST — does **not** help if the Pico is wedged and never finishes a log cycle. |
| **Firmware 1.1.38+** | Boot OTA capped at **90s** (`BOOT_OTA_MAX_SECONDS`). Stall reboot writes **`pending_stall_reboot.json`**, tries Events upload for **≤12s**, then **always** resets; next boot flushes pending stall. Standby checks **stale every ~2s** (not only on heartbeat). Hardware **WDT** (~8s, fed via `diag_log` + loop). |
| **Firmware 1.1.35+** | Standby reboots if no successful auto-log for **2×** the current `interval_engine_*_s` (sheet overrides included), if one log runs longer than that same limit, or after **3** consecutive failures. Posts **`standby_stall_reboot`** on Events with `boat_diag.log` tail when possible. |
| **Power cycle** | Immediate — unplug Pico/USB path ~10s if the REPL or auto-log is hung. |

After a stall, check **Events** for `diag_log` uploads (standby posts tail on exceptions) or Thonny `diag_log.tail(80)` if you have USB.

## Modem LEDs (SIM7600 HAT) in Wi‑Fi-only standby

With **switch/key off**, the modem should be **off** (`AT+CPOF` after each cellular session; standby watchdog also powers off if AT responds). The HAT may still show **solid red** (5 V present on the modem rail from the V50/USB feed) — that is not necessarily “cellular active.”

**Solid + flashing red** usually means the module is **powered and doing network activity** (registering, data, or stuck between states) — **not** the desired idle state when you are only logging over **Levy-Guest** Wi‑Fi. If lights stay that way for hours with `uplink` = Wi‑Fi in the sheet, treat it as a bug/leak; 1.1.34+ tries `AT+CPOF` from standby when the UART still answers.
