# USB recovery (reboot loop / stuck on old firmware)

When **boat-p2** is power-cycling and cellular boot OTA cannot finish (common on **fw < 1.1.85**), push the current **ram-fix** files over USB in one step.

## Prerequisites

- Pico W on USB to your PC (power bank or dock is fine).
- **Close Thonny** (or any serial monitor) so `mpremote` can open the port.
- Repo checked out at **master** (or the branch you intend to ship).

## One command (from repo root)

```bash
python3 -m pip install -q mpremote && python3 boat_monitor/usb_recovery_push.py
```

Or:

```bash
chmod +x boat_monitor/run_usb_recovery.sh
./boat_monitor/run_usb_recovery.sh
```

Optional:

- `--port /dev/ttyACM0` (or `COM5` on Windows) if auto-detect fails
- `--no-prefer-wifi` to leave boot OTA transport unchanged
- `--dry-run` to print steps only

### Windows troubleshooting

1. **Quit Thonny** completely (not just disconnect).
2. Find the Pico COM port:

   ```bat
   python -m mpremote connect list
   ```

3. Re-run with that port, e.g. `python3 boat_monitor/usb_recovery_push.py --port COM7`

If you see `failed to access cp`, update `usb_recovery_push.py` from PR #77+ (older script passed `connect cp`, which mpremote mis-read as a device named `cp`).

## What it does

1. Runs **flash cleanup** on the Pico (`.bak` / `.new`, OTA bundle leftovers, large logs).
2. Copies **13** recovery modules (`ota_health.py`, streaming OTA stack, `main.py`, `version.py`, …).
3. **Merges** `remote_boot_config.json` on the Pico: clears `pending_ota`, `ota_degraded`, fail counts; sets `boot_ota_prefer_wifi=1` (unless `--no-prefer-wifi`). **Keeps** sheet keys like `min_fw_version`.
4. **Soft-resets** so `main.py` runs automatically.

After recovery, leave the unit on **home Wi‑Fi** (switch/key off) so boot OTA can pull **1.1.87+** from GitHub. Clear sheet `ota_degraded` / `boot_ota_prefer_wifi` overrides once Power_Log shows the new fw.

## Thonny-only fallback

If you cannot run `mpremote` on the PC, use Thonny **File → Save copy** for the same files listed in `usb_recovery_push.py`, then in the shell:

```python
import usb_recovery_patch
usb_recovery_patch.main()
import machine
machine.soft_reset()
```

(Copy `usb_recovery_patch.py` to the board first.)
