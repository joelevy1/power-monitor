# USB recovery (boat-p2, Windows COM7)

When the Pico stops auto-logging or is stuck in a reboot/OTA loop, use USB from the PC.

**Before you start:** Close **Thonny** (or any serial monitor). Plug Pico USB; bank power can stay on.

## Week-away kit (recommended)

One USB session loads the full stack **plus** lean failure paths when heap is low,
home-dock Wi-Fi logging, V50 energy tracking, and OTA recovery capability.

```bat
cd path\to\power-monitor
git pull
boat_monitor\run_usb_ota_self_sufficient.bat
```

Or explicitly:

```bat
py boat_monitor\usb_recovery_push.py --ota-self-sufficient --port COM7
```

**Files copied:** `mem_guard.py`, `diag_log.py`, `resilience.py`, `remote_telemetry.py`,
`ble_service.py`, `v50_energy.py`, `standby_monitor.py`, `sheets_log.py`, `ota_*`, `main.py`,
`version.py` (the current repository version), …

**Flash patch sets:** clears pending/degraded/backoff state,
`auto_ota_on_boot=false`, `dock_mode=home`, `standby_prefer_wifi=1`,
`boot_ota_prefer_wifi=1`, `ota_manifest_profile=feature-pack`, and
`ota_self_sufficient=1`. It does not arm an update.

### ENOMEM rules

| When heap &lt; ~22K or ENOMEM on POST | Firmware skips |
|---------------------------------------|----------------|
| OTA telemetry / lifecycle flush before log | Extra HTTPS before Power_Log |
| `auto_log_degraded` Events upload | Failure path that worsens OOM |
| Stall reboot Events + diag tail | `standby_stall_reboot` upload |
| `upload_tail_to_events` on exception | Second POST while OOM |

Local `boat_diag.log` still records everything; sheet may be quiet during heap crisis until
a successful cellular log clears fragmentation.

### After USB (do not skip)

1. **Unplug USB**, power-cycle V50 once (no LEDs is normal).
2. Charge overnight; **mark V50 full** in the app when charged.
3. Wait for one `auto_log` row on Power_Log (~5 min first boot, then **1h** if sheet has
   `interval_engine_off_s=3600`).
4. Run verification gate (from repo on PC):

```bat
for /f "tokens=2 delims== " %V in ('findstr VERSION boat_monitor\version.py') do py boat_monitor\usb_recovery_verify.py --expect-fw %~V
```

Green = device firmware at the repository version, no reboot trap, and an
`ota_capability` Events row containing `will_boot_ota=`.

5. **Sheet Config** (agent or manual): `min_fw_version` = current repository
   version, `interval_engine_off_s=3600`,
   clear `force_ota`, `cmd_ota`, `cmd_ota_force`.

6. Optional OTA stress campaign (not required for week-away monitoring):

```bat
bash boat_monitor/run_week_away_dock_ota.sh
```

---

## Quick fix (patch-only — not recommended)

Patches `remote_boot_config.json` only. Does **not** update ENOMEM lean paths.

```bat
py boat_monitor\usb_recovery_push.py --patch-only --port COM7 --enable-boot-ota
```

Use only if full push fails (no space on device — run cleanup first).

---

## Full push (legacy ram-fix set)

```bat
boat_monitor\run_usb_recovery.bat
```

Prefer `run_usb_ota_self_sufficient.bat` instead.

---

## What each layer prevents

| Layer | Prevents |
|-------|----------|
| `mem_guard` + lean diag path | ENOMEM failure loops from extra Events POSTs |
| Cellular standby at dock | Wi-Fi TLS heap pressure on every log |
| `ota_reboot.py` guard | Reboot storm when boot OTA cannot run |
| `v50_energy.py` + `ble_service` | Empty `v50_mah_used` / `v50_pct_remain` on sheet |
| `sheets_log` Wi-Fi passthrough | Cellular boot OTA after Wi-Fi log at dock |
| `ota_health` manifest tier cap | Multi-file CDN on cellular without `cmd_ota_force` |
| `usb_recovery_verify.py` | Leaving dock before USB actually stuck |
| Harness guardrails | Auto-pause `min_fw` on reboot trap during week-away |

---

## Bench test (USB, switch/key off)

```bat
py -m mpremote connect COM7 run boat_monitor\usb_bench_log.py
```

---

## Confidence

After the current USB kit + verify + 1h logging: **high** for week-away monitoring without USB.
USB may still be needed for catastrophic flash corruption or multi-file feature packs.
