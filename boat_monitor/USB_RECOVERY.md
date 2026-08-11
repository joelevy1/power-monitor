# USB recovery (boat-p2, Windows COM7)

When the Pico stops auto-logging or is stuck in a reboot/OTA loop, use USB from the PC.

**Before you start:** Close **Thonny** (or any serial monitor). Plug Pico USB; bank power can stay on.

## OTA self-sufficient kit (recommended — week-away)

One USB session loads the full dock-fix stack **plus** firmware that refuses reboot-without-OTA,
manifest tier caps, and Wi-Fi transport passthrough. Designed so future upgrades are OTA-only.

```bat
cd path\to\power-monitor
git pull
boat_monitor\run_usb_ota_self_sufficient.bat
```

Or explicitly:

```bat
py boat_monitor\usb_recovery_push.py --ota-self-sufficient --enable-boot-ota --port COM7
```

**Files copied:** `main.py`, `standby_monitor.py`, `ota_reboot.py`, `ota_health.py`,
`remote_boot_config.py`, `sheets_log.py`, `ota_capability.py`, `version.py` (1.1.111+), …

**Flash patch sets:** clears `ota_degraded`/backoff, `auto_ota_on_boot=true`, `dock_mode=home`,
`boot_ota_prefer_wifi=0`, `ota_manifest_profile=stress`, `ota_self_sufficient=1`.

### After USB (do not skip)

1. **Unplug USB**, power-cycle V50 once.
2. Wait for one `auto_log` row on the sheet (~5 min with default interval).
3. Run verification gate (from repo on PC):

```bat
py boat_monitor\usb_recovery_verify.py --expect-fw 1.1.111
```

Green = `fw>=1.1.111`, no reboot trap, `ota_capability` Events row with `will_boot_ota=`.

4. Start week-away OTA campaign (cloud agent or local):

```bat
bash boat_monitor/run_week_away_dock_ota.sh
```

This sets 3h log interval, starts `boat_p2_watch`, runs 6 version-only stress rounds.

---

## Quick fix (patch-only — not recommended for OTA self-sufficiency)

Patches `remote_boot_config.json` only. Does **not** update `ota_reboot.py` / `standby_monitor.py`.

```bat
py boat_monitor\usb_recovery_push.py --patch-only --port COM7 --enable-boot-ota
```

Use only if full push fails (no space on device — run cleanup first).

---

## Full push (legacy ram-fix set)

```bat
boat_monitor\run_usb_recovery.bat
```

Prefer `run_usb_ota_self_sufficient.bat` instead — it includes dock-critical files.

---

## What each layer prevents

| Layer | Prevents |
|-------|----------|
| `ota_reboot.py` guard | Reboot storm when boot OTA cannot run |
| `standby_monitor` fix | Keeps logging when degraded so sheet clears work |
| `sheets_log` Wi-Fi passthrough | Cellular boot OTA after Wi-Fi log at dock |
| `ota_health` manifest tier cap | Multi-file CDN on cellular without `cmd_ota_force` |
| `ota_capability` Events | Remote visibility of heap/policy every log |
| `usb_recovery_verify.py` | Leaving dock before USB actually stuck |
| Harness guardrails | Auto-pause `min_fw` on reboot trap during week-away |

---

## Bench test (USB, switch/key off)

```bat
py -m mpremote connect COM7 run boat_monitor\usb_bench_log.py
```

---

## Confidence

After the self-sufficient kit + verify + week-away harness: **~90%** no USB for version-only
stress rounds. USB may still be needed for catastrophic flash corruption or multi-file feature
packs (by design).
