# USB recovery (boat-p2, Windows COM7)

When the Pico stops auto-logging or is stuck in a reboot/OTA loop, use USB from the PC.

**Before you start:** Close **Thonny** (or any serial monitor). Plug Pico USB; bank power can stay on.

## Quick fix (keeps firmware on the Pico)

Patches `remote_boot_config.json` (clears pending OTA, `auto_ota_on_boot=false` by default) and soft-resets. Does **not** copy files from the repo.

For **OTA stress recovery** (device behind `min_fw`), use `--enable-boot-ota` so boot OTA runs after patch:

```bat
py boat_monitor\usb_recovery_push.py --patch-only --port COM7 --enable-boot-ota
```

```bat
cd path\to\power-monitor
git pull
boat_monitor\run_usb_recovery.bat --patch-only
```

Default port is **COM7**. Another port:

```bat
py boat_monitor\usb_recovery_push.py --patch-only --port COM5
```

## Full push (ram-fix file set from this repo)

Only if patch-only is not enough. Requires all files listed in `usb_recovery_push.py` (on `master` you may need the `cursor/usb-recovery-ota-health` branch merged first).

```bat
boat_monitor\run_usb_recovery.bat
```

After success: **unplug USB**, power-cycle once, **switch/key OFF**, do not open BLE for 15 minutes; watch for `auto_log` rows on the sheet.

**Note:** Standby **1.1.89+** posts one **`boot_log`** row as soon as standby starts (when boot OTA is not running), then continues on the normal `auto_log` interval. Older firmware waits up to one interval (~5 minutes with `interval_engine_off_s=300`) before the first row.

**Bench test (USB, switch/key off):** force one upload without the phone app:

```bat
py -m mpremote connect COM7 run boat_monitor\usb_bench_log.py
```
