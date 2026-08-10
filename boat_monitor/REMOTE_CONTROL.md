# Remote control via Google Sheets

You can change boat behavior **from the spreadsheet** without visiting the Pico. Every successful **log POST** (auto-log or Log Now) returns a `commands` object from Apps Script; firmware applies it before the next sleep interval.

**Requires:** Apps Script **receiver v3** (`RECEIVER_VERSION = 3` in `Code.gs`) deployed as a **new Web App version** (see `APPS_SCRIPT_SETUP.md`). Pico firmware with `remote_control.py` (OTA **1.1.7+**).

## Config tab

Created by `sheets_bootstrap.py` — columns: `key` | `value` | `updated_utc` | `note`.

| Key | Value example | Effect |
|-----|----------------|--------|
| `interval_engine_on_s` | `60` | Auto-log interval while mode is `key_on` (min 60) |
| `interval_engine_off_s` | `300` | Auto-log when engine off / docked (min 60); use `3600` for long storage |
| `min_fw_version` | `1.1.7` | If Pico `version.py` is older, **OTA on that log cycle** — persisted on the Pico. **1.1.54+:** cellular path **reboots right after** Power_Log (skips GPS). **1.1.55+:** also **ignores the 60s auto-log interval** until upgraded (next tick runs acknowledge+log+reboot, not another minute of waiting). |
| `auto_ota_on_boot` | `1` | **1.1.52+:** Persist on Pico (`remote_boot_config.json`); overrides `ota_config.py` every boot |
| `boot_ota_max_seconds` | `420` | Max seconds for boot-time OTA; use **420+** on cellular (~28 HTTPS file fetches on LTE, not just bytes). On boat power the Pico enforces at least 420s even if this is lower. |
| `keep_modem_awake_underway` | `1` | **1.1.53+:** On boat power (`key_on` / `engine_on`), leave SIM7600 on after each cellular log (default **on**). Set `0` to power off every cycle (saves mA, slower next log). |
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

`AUTO_OTA_ON_BOOT` in `ota_config.py` is the **default** when the sheet has not set
`auto_ota_on_boot`. **1.1.52+** also reads **`remote_boot_config.json`** (written from
Config on each log) and runs boot OTA when **`pending_ota`** is set after
`min_fw_version` / `cmd_ota` — even if `ota_config.py` on disk still says `False`.

Sheet commands also add:

- OTA **between** logs (no boat visit)
- Interval changes **without** reflashing
- Forced reboot

## Firmware update flow (fully remote)

**Mandatory:** See **`boat_monitor/RELEASE_PROCESS.md`**. Merge to **`master`**
and verify GitHub `ota_manifest.json` **before** raising `min_fw_version` on the
sheet. Otherwise the Pico reboots for OTA but installs nothing new.

1. Merge firmware + bump `ota_manifest.json` on GitHub `master`.
2. Run `python3 boat_monitor/validate_release.py --check-github`.
3. In **Config**, set either:
   - `min_fw_version` = new version (persistent until Pico catches up), or
   - `cmd_ota` = `1` once (or `boat-p2:cmd_ota`).
3. Wait for the next **auto-log** (or trigger Log Now over BLE). The Pico downloads the manifest over cellular, installs, and reboots.

No TestFlight or Wi-Fi console required for Pico updates.

## How to verify (remote test)

| Signal | Where | What to look for |
|--------|--------|------------------|
| Firmware version | **Power_Log** `fw` column | e.g. `1.1.16` |
| Upload path | **Power_Log** `uplink` column | Wi-Fi SSID or `cellular` |
| OTA boot / remote (1.1.59+) | **Events** tab | `boot_ota` — outcome, `max_s`, `prefer_wifi`, errors, diag tail (cellular default on boat) |
| Config applied | **Events** tab | `event=remote_config`, `detail` lists intervals / `cmd_ota` / `ota_action=1` / `min_fw_version` |
| Degraded logging (1.1.45+) | **Events** tab | `auto_log_degraded` — soft-fail summary + diag tail (throttled ~10 min) |
| GPIO opto test (1.1.46+) | **Power_Log** `note` | Suffix `gpio sw=0 key=0 gp20=1 gp21=1` — firmware ON when `sw`/`key`=1; raw `gp*=0` means pin LOW (opto active). Header pins **26/27** = GP20/GP21. |
| Overdue but alive (1.1.45+) | **Events** tab | `standby_overdue` — past log interval, no Power_Log yet (throttled ~15 min) |
| BLE Log Now failure (1.1.50+) | **Events** tab | `ble_log_failed` — reason + `boat_diag.log` tail (cellular upload when possible) |
| Boat underway (1.1.51+) | **Events** | `boat_log_session` — full diag tail appended to each successful log (same cell session) |
| Boat underway (1.1.51+) | **Events** | `boat_diag_heartbeat` — ~every 90s between logs when switch/key on (no phone on BLE) |
| Power-bank standby (1.1.51+) | **Events** | `standby_log_session` / `standby_diag_heartbeat` — throttled (~30 min / ~60 min) |
| Manual diag dump (1.1.50+) | **Events** tab | `ble_diag` — send BLE command `diag` from a serial/console tool or future app button |
| Log cadence | **Power_Log** timestamps | ~**6 minutes** apart after `interval_engine_*_s=360` |
| OTA ran | Next **Power_Log** `note` | `fw=` bumps from `1.1.8` → `1.1.9` |
| BLE (if nearby) | App status JSON | `"fw": "1.1.9"` |

Interval overrides are **in RAM only** (lost on reboot until Config is read again on the next log POST).

## Remote reboot when logging stops

| Method | When it works |
|--------|----------------|
| **`cmd_ble_latch` = `1`** (1.1.47+) | **One-shot:** keep BLE service up even if switch/key GPIO reads OFF (field debug). Cleared when applied. |
| **`ble_gpio_off_hold_s`** | **1.1.47+:** seconds switch/key must read OFF before Pico leaves BLE for standby (default **30**). |
| **Firmware 1.1.38+** | Boot OTA capped at **90s** (`BOOT_OTA_MAX_SECONDS`). Stall reboot writes **`pending_stall_reboot.json`**, tries Events upload for **≤12s**, then **always** resets; next boot flushes pending stall. Standby checks **stale every ~2s** (not only on heartbeat). Hardware **WDT** (~8s, fed via `diag_log` + loop). |
| **Firmware 1.1.45+** | While Power_Log is quiet but standby is running: **`auto_log_degraded`** (ENOMEM/POST soft-fails) and **`standby_overdue`** (alive past interval) on **Events**, rate-limited so fail loops do not spam the sheet. **1.1.44** still reduces how often those fire. |
| **Firmware 1.1.35+** | Standby reboots if no successful auto-log for **2×** the current `interval_engine_*_s` (sheet overrides included), if one log runs longer than that same limit, or after **4** consecutive soft-fails (`AUTO_LOG_FAIL_REBOOT_COUNT`). Posts **`standby_stall_reboot`** on Events with `boat_diag.log` tail when possible. |
| **Power cycle** | Immediate — unplug Pico/USB path ~10s if the REPL or auto-log is hung. |

After a stall, check **Events** for `boot_ota`, `standby_stall_reboot`, or `boat_log_session` rows. USB `diag_log.tail()` is last resort only.

## Modem LEDs (SIM7600 HAT) in Wi‑Fi-only standby

With **switch/key off**, the modem should be **off** (`AT+CPOF` after each cellular session; standby watchdog also powers off if AT responds). The HAT may still show **solid red** (5 V present on the modem rail from the V50/USB feed) — that is not necessarily “cellular active.”

**Solid + flashing red** usually means the module is **powered and doing network activity** (registering, data, or stuck between states) — **not** the desired idle state when you are only logging over **Levy-Guest** Wi‑Fi. If lights stay that way for hours with `uplink` = Wi‑Fi in the sheet, treat it as a bug/leak; 1.1.34+ tries `AT+CPOF` from standby when the UART still answers.

## At the boat (recommended order)

Use this when the sheet has gone quiet or you are upgrading after a stuck session.

1. **Home / marina Wi‑Fi first (if available)** — Join **Levy-Guest** or **Seattle Boat** so the Pico can reach the internet without burning cellular during OTA.
2. **Power** — Prefer a **healthy V50 bank** or boat feed; if moving from bank-only to boat house power with switch/key still **off**, firmware **1.1.44+** may do one **power-transition reboot** (clears RAM).
3. **Force firmware** — In Config set **`cmd_ota` = `1`** once (or ensure **`min_fw_version`** ≥ ship version, e.g. **1.1.44**). Unplug USB data / close Thonny so `main.py` auto-runs.
4. **Wait one cycle** — Up to **~5 min** on docked standby (**300 s** off-interval) for a row; confirm **Power_Log `fw`** bumped.
5. **Underway / BLE** — Turn **battery switch ON** (then key if you use it) **before** or right after power-up so the Pico enters **BLE mode**. Connect in the app; **`inputs.switch` / `inputs.key`** should be true. **Log Now** uses **cellular** (no Wi‑Fi handoff).

   **Auto-log while the app is connected:** intentionally **off** (stability). Background cellular logs block the only BLE thread for 1–2 minutes; overlapping **Signal** / **Diag** during a log could corrupt modem UART use. For steady sheet rows with the phone open, **disconnect BLE** (Pico keeps logging) or tap **Log Now** when you want a row. Power is not the issue on boat 12V — this is overlap/UX, not saving mAh.

6. **Verify** — Power_Log **`mode=key_on`**, **`uplink=cellular`**, timestamps ~**1 min** apart with engine on **when the app is not connected**.

Overnight on **power bank only** away from home: expect **cellular fallback**; success still depends on memory and signal. If the sheet is silent for **>15 min** with **300 s** Config, the unit is likely in a fail/reboot loop — repeat from step 3 when you return.

## Stuck on old `fw` while Events show `min_fw_version` newer

**Firmware before 1.1.54** can keep logging every minute on the old version and **will not** self-heal from the sheet alone (OTA action lost after GPS POST on some builds; boot OTA wasted time on unreachable Wi‑Fi SSIDs).

**You need one manual upgrade**, then sheet-driven OTA works again (**1.1.54+**).

**Fastest (boat, USB once):** Thonny → Pico running `main.py` → paste:

```python
import ota
ota.update(reboot=True, prefer_wifi=False)
```

**Or:** Full power cycle (~10 s unplug) with **battery switch ON** and **`auto_ota_on_boot=1`** on Config — on **1.1.56+** boot OTA uses **cellular first**; on **1.1.52** prefer marina **Levy-Guest** / **Seattle Boat** Wi‑Fi for that one boot if cellular boot OTA fails.

After **`fw` ≥ 1.1.54**, raising `min_fw_version` should cause **one Power row → reboot → new `fw`**, not endless minute pings.

**1.1.57+:** Boot OTA and `ota.update()` use **`ble_policy.ota_prefer_wifi()`** — **cellular only** when master switch or key is on; Wi‑Fi only when both are off (dock standby).
