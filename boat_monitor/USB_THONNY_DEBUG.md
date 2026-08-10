# Thonny USB live debug (COM7)

Use this when auto-log is quiet and you need to see **where it hangs** — full `print` / `DIAG:` output in the Thonny shell. Resets are **blocked** during the debug session so the board does not disappear mid-trace.

## One-time: copy the script to the Pico

**Option A — batch (Thonny closed):**

```bat
cd C:\dev\power-monitor
git pull
boat_monitor\push_thonny_debug.bat
```

**Option B — Thonny only:** Open `boat_monitor\thonny_usb_debug.py` from the repo → **File → Save as…** → save on the Pico as `thonny_usb_debug.py`.

## Run (Thonny open)

1. **Thonny** → interpreter **MicroPython (Raspberry Pi Pico)** → port **COM7**.
2. **Shell:** press **Ctrl+C** until you get `>>>` (stops `main.py` if it was running).
3. **Open** `thonny_usb_debug.py` on the device → **Run** (F5).

You get a **menu**:

| Key | What it does |
|-----|----------------|
| **1** | Version, GPIO/mode, `remote_boot_config`, intervals, `boat_diag.log` tail |
| **2** | One full log — **Wi‑Fi first** (watch progress lines) |
| **3** | One full log — **cellular only** (same path as BLE Log Now) |
| **4** | Boot OTA if `should_run_boot_ota` (optional; can be slow) |
| **5** | Full **`standby_monitor`** loop (auto-log); **Ctrl+C** to stop; stall reboots suppressed |
| **6** | Exit menu (REPL stays open) |

While a log runs, watch the shell for:

- `progress: logging_modem` / `logging_power` / …
- `DIAG:` lines from `diag_log`
- Cellular `HTTP READ` debug from `cellular.py`
- `RESULT: power: ok` vs `power: failed: …`

## Tips

- **Bank power** on; **switch/key OFF** matches docked standby (menu **5**).
- If **main.py** keeps restarting, use **Ctrl+C** right after connect, then run the debug file.
- When finished debugging, **soft reboot** (Thonny **Run → Soft reboot**) or power-cycle to return to normal `main.py` on boot.
- **mpremote** recovery scripts need Thonny **closed**; this workflow is the opposite — Thonny **open** for trace.

## After you find the failure

Paste the last **~30 lines** of Thonny output (especially `RESULT:` or any traceback). That pinpoints modem vs Sheets vs standby scheduling.
