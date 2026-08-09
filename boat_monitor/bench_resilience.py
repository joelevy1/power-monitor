"""
Home bench — mode transitions, logging, OTA, and resilience (Thonny on Pico W).

Copy to the Pico with config.py + secrets.py (for real sheet posts).

IMPORTANT:
  - While Thonny has the USB REPL open, main.py may not be running (depends how
    you boot). For “real” BLE/standby behavior: close Thonny and power-cycle,
    or use oSoft reboot after closing the serial connection.
  - USB to PC does NOT enable BLE; switch/key GPIO (or ble_latch) does.

Run in Thonny:
    import bench_resilience
    bench_resilience.main()
"""

import time

import config as cfg


def _pause(msg="Enter to continue..."):
    try:
        input(msg)
    except (EOFError, KeyboardInterrupt):
        pass


def status():
    import version

    print("\n=== STATUS ===")
    print("VERSION", getattr(version, "VERSION", "?"))
    try:
        import ble_policy

        sk = ble_policy.read_switch_key()
        print("switch/key GPIO:", sk, "ble_wanted:", ble_policy.ble_wanted())
        print("ble_latch:", ble_policy.ble_latched(), "gpio_off_hold_s:", ble_policy.gpio_off_hold_s())
    except Exception as exc:
        print("ble_policy:", exc)

    try:
        import ble_service

        s = ble_service.read_status()
        print("mode:", s.get("mode"), "inputs:", s.get("inputs"))
        try:
            import gpio_probe

            print("note suffix:", gpio_probe.format_gpio_suffix(s))
        except Exception as exc:
            print("gpio_probe:", exc)
    except Exception as exc:
        print("read_status:", exc)

    try:
        import diag_log

        print("heap_kb:", diag_log.mem_kb())
    except Exception:
        pass
    print()


def watch_modes(interval=0.25):
    import ble_service

    print("\n=== MODE WATCH (Ctrl+C to stop) ===")
    print("Toggle bench 12V on Switch (Ch5) / Key (Ch6); expect key_on / switch_on_key_off.\n")
    last = None
    try:
        while True:
            s = ble_service.read_status()
            line = "%s  sw=%s key=%s  mode=%s" % (
                time.ticks_ms() if hasattr(time, "ticks_ms") else "",
                s["inputs"]["switch"],
                s["inputs"]["key"],
                s["mode"],
            )
            if line != last:
                print(line)
                last = line
            time.sleep(interval)
    except KeyboardInterrupt:
        print("stopped.\n")


def one_log(prefer_wifi=True):
    import ble_service

    print("\n=== ONE LOG (prefer_wifi=%s) ===" % prefer_wifi)
    print("May take 30-120s on cellular.\n")
    summary = ble_service.log_power_and_gps(note="bench_log", prefer_wifi=prefer_wifi, ble_monitor=None)
    print("RESULT:", summary)
    print()


def ota_check():
    import ota

    print("\n=== OTA CHECK (manifest only) ===")
    try:
        m = ota.check(prefer_wifi=True)
        print("manifest:", m.get("version"), m.get("notes", "")[:80])
    except Exception as exc:
        print("FAILED:", exc)
    print()


def ota_apply_wifi():
    import ota

    print("\n=== OTA APPLY (Wi-Fi, reboot if updated) ===")
    print("Downloads all manifest files from GitHub master.\n")
    try:
        changed = ota.update(reboot=True, prefer_wifi=True, max_total_s=120)
        print("changed:", changed)
    except Exception as exc:
        print("FAILED:", exc)
    print()


def diag_tail(n=40):
    import diag_log

    print("\n=== boat_diag.log (last %d) ===" % n)
    diag_log.tail(n)
    print()


def upload_diag():
    import diag_log

    print("\n=== UPLOAD diag to Events ===")
    diag_log.upload_tail_to_events(lines=25, event="bench_diag")
    print("done (if network ok)\n")


def clear_bench_state():
    import os

    print("\n=== CLEAR bench state files ===")
    for path in (
        "ble_latch.json",
        "auto_log_override.json",
        "pending_stall_reboot.json",
        "wifi_mode.txt",
    ):
        try:
            os.remove(path)
            print("removed", path)
        except OSError:
            print("skip", path)
    try:
        import ble_policy

        ble_policy.set_ble_latch(False)
    except Exception:
        pass
    print()


def ble_smoke(seconds=120):
    """Start BLE advertising without main.py (Wi-Fi off). Ctrl+C to stop."""
    print("\n=== BLE SMOKE %ds ===" % seconds)
    print("Scan with LightBlue / app for BoatMonitor.\n")
    import ble_service

    ble = ble_service.BoatMonitorBle()
    t0 = time.ticks_ms()
    try:
        while time.ticks_diff(time.ticks_ms(), t0) < int(seconds * 1000):
            ble.update_status()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    print("BLE smoke ended.\n")


def self_heal_info():
    print(
        """
=== SELF-HEAL (what to verify at home) ===

Standby (switch/key OFF, close Thonny, power-cycle → main.py):
  - Auto-log on interval_engine_off_s (sheet / auto_log_override.json)
  - Stall reboot after 2× interval with no successful log → Events standby_stall_reboot
  - auto_log_degraded / standby_overdue on 1.1.45+ (throttled Events)

BLE (switch OR key ON):
  - ble_service; 1.1.47+ holds BLE 60s+ after GPIO off; no auto-log while phone connected
  - cmd_ble_latch=1 on sheet → BLE even if GPIO reads OFF (after one config POST)

OTA:
  - Boot: AUTO_OTA_ON_BOOT (90s cap)
  - Sheet min_fw_version → reboot → boot OTA
  - bench: ota_check() / ota_apply_wifi() above

Opto proof (USB only):
  - bench_test.py menu 3 + 4 — Switch must pull GP20 low, Key GP21 low
"""
    )


def print_help():
    print(
        """
Commands:
  s   status (mode, GPIO, fw, heap)
  w   watch mode while toggling switch/key
  l   one log (Wi-Fi first)
  c   one log (cellular only path if Wi-Fi configured)
  b   BLE advertise smoke (2 min)
  o   OTA check manifest
  u   OTA apply + reboot
  d   diag tail
  e   upload diag to Events
  x   clear ble_latch / overrides / pending stall
  i   self-heal cheat sheet
  h   help
  q   quit
"""
    )


def main():
    print("bench_resilience.py — home bench")
    print_help()
    while True:
        try:
            cmd = input("bench> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if cmd in ("q", "quit"):
            break
        elif cmd == "h":
            print_help()
        elif cmd == "s":
            status()
        elif cmd == "w":
            watch_modes()
        elif cmd == "l":
            one_log(prefer_wifi=True)
        elif cmd == "c":
            one_log(prefer_wifi=False)
        elif cmd == "b":
            ble_smoke()
        elif cmd == "o":
            ota_check()
        elif cmd == "u":
            ota_apply_wifi()
        elif cmd == "d":
            diag_tail()
        elif cmd == "e":
            upload_diag()
        elif cmd == "x":
            clear_bench_state()
        elif cmd == "i":
            self_heal_info()
        else:
            print("Unknown (h for help)")


if __name__ == "__main__":
    main()
