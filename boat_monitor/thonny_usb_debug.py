"""Thonny USB debug session — suppress auto-reboots and print every step.

Copy to the Pico (Thonny: open from PC repo and Save as thonny_usb_debug.py on device).

In Thonny (COM7, 115200):
  1. Stop any running main.py (Ctrl+C in Shell).
  2. Run this file (F5).

All output goes to the Thonny shell (print + DIAG: lines from diag_log).
"""


def _block_resets():
    """Patch machine.reset/soft_reset when present (no-op if missing)."""
    try:
        import machine
    except ImportError:
        print("DEBUG: no machine module — reset blocking skipped")
        return None

    saved = {}

    def _debug_reset(*_a, **_kw):
        print("DEBUG: machine reset BLOCKED (Thonny debug session)")

    for name in ("reset", "soft_reset"):
        fn = getattr(machine, name, None)
        if not callable(fn):
            continue
        saved[name] = fn

        def _make_block(real_name, _real_fn):
            def _block(*a, **kw):
                print("DEBUG: machine.%s() BLOCKED (Thonny debug)" % real_name)

            return _block

        try:
            setattr(machine, name, _make_block(name, fn))
        except AttributeError:
            pass
    if not saved:
        print("DEBUG: machine has no reset/soft_reset — blocking skipped")
    return saved


def _section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _pause(msg="  [Enter] continue, or type s + Enter to skip..."):
    try:
        line = input(msg)
        if line and str(line).strip().lower() in ("s", "skip", "q"):
            return False
    except (EOFError, KeyboardInterrupt):
        return False
    return True


def _status():
    import diag_log

    _section("STATUS")
    try:
        import version

        print("VERSION:", getattr(version, "VERSION", "?"))
    except Exception as exc:
        print("version:", exc)
    print("heap_kb:", diag_log.mem_kb())
    try:
        import ble_policy

        sk = ble_policy.read_switch_key()
        print("switch/key:", sk)
        print("ble_wanted:", ble_policy.ble_wanted())
        print("ble_latch:", ble_policy.ble_latched())
        print("gpio_off_hold_s:", ble_policy.gpio_off_hold_s())
    except Exception as exc:
        print("ble_policy:", exc)
    try:
        from ble_service import read_status

        s = read_status()
        print("mode:", s.get("mode"), "device:", s.get("device"))
        print("inputs:", s.get("inputs"))
        try:
            import gpio_probe

            print("gpio note:", gpio_probe.format_gpio_suffix(s))
        except Exception as exc:
            print("gpio_probe:", exc)
    except Exception as exc:
        print("read_status:", exc)
    try:
        import remote_boot_config as rbc

        print("boot_ota:", rbc.boot_ota_status_line())
        print("should_run_boot_ota:", rbc.should_run_boot_ota())
        print("needs_firmware_upgrade:", rbc.needs_firmware_upgrade())
        print("effective_auto_ota_on_boot:", rbc.effective_auto_ota_on_boot())
        try:
            print("remote_boot_config.json:", rbc.load())
        except Exception as exc:
            print("load config:", exc)
    except Exception as exc:
        print("remote_boot_config:", exc)
    try:
        import auto_log

        auto_log.load_persisted_overrides()
        print("interval docked_s:", auto_log.interval_for_mode("docked_off"))
        print("interval key_on_s:", auto_log.interval_for_mode("key_on"))
    except Exception as exc:
        print("auto_log:", exc)
    try:
        import diag_log

        print("\n--- boat_diag.log tail ---")
        diag_log.tail(25)
    except Exception as exc:
        print("diag tail:", exc)


def _boot_ota_once():
    _section("BOOT OTA (optional — can take many minutes)")
    try:
        import remote_boot_config as rbc

        if not rbc.should_run_boot_ota():
            print("should_run_boot_ota is False — skipping.")
            return
    except Exception as exc:
        print("check failed:", exc)
        return
    if not _pause("Run boot OTA now? "):
        print("skipped.")
        return
    try:
        import ota_config
        import remote_boot_config as rbc

        import ota

        max_s = rbc.effective_boot_ota_max_seconds()
        prefer = rbc.effective_boot_ota_prefer_wifi()
        print("ota.update max_s=%s prefer_wifi=%s ..." % (max_s, prefer))
        ok = ota.update(reboot=False, prefer_wifi=prefer, max_total_s=max_s)
        print("boot OTA result:", ok)
    except Exception as exc:
        print("boot OTA failed:", exc)
        import sys

        sys.print_exception(exc)


def _one_log(prefer_wifi=True):
    _section("ONE LOG (prefer_wifi=%s)" % prefer_wifi)
    print("Watch for DIAG: lines and cellular HTTP debug. Often 30-120s.\n")
    try:
        from ble_service import log_power_and_gps

        def on_progress(stage):
            print("  progress:", stage)

        summary = log_power_and_gps(
            note="thonny_debug_log",
            prefer_wifi=prefer_wifi,
            ble_monitor=None,
            gps_timeout_s=12,
            on_progress=on_progress,
        )
        print("\nRESULT:", summary)
        return summary
    except Exception as exc:
        print("LOG FAILED:", exc)
        import sys

        sys.print_exception(exc)
        return None


def _standby_loop():
    _section("STANDBY MONITOR (full loop — Ctrl+C to stop)")
    print("Stall/switch reboots are BLOCKED; WDT disabled.\n")
    import resilience

    resilience.HARDWARE_WDT = False

    def _patched_stall(device, reason, mode=None):
        print("DEBUG: stall reboot suppressed:", reason)

    resilience.reboot_after_stall = _patched_stall
    import standby_monitor

    standby_monitor.main()


def _clear_ble_latch():
    _section("CLEAR BLE LATCH")
    try:
        import ble_policy

        ble_policy.clear_ble_latch()
        print("ble_latch cleared. ble_wanted:", ble_policy.ble_wanted())
        print("Reboot (Thonny soft reboot) so main.py starts standby, not BLE.")
    except Exception as exc:
        print("clear failed:", exc)


def main():
    print("\nBoat Monitor — Thonny USB debug")
    print("Resets are blocked so you can read the shell.\n")
    _block_resets()
    try:
        import resilience

        resilience.HARDWARE_WDT = False
    except Exception:
        pass
    try:
        import diag_log

        diag_log.log("thonny_usb_debug session start")
    except Exception:
        pass

    while True:
        _section("MENU")
        print("1  Status + diag tail")
        print("2  One log (Wi-Fi first)")
        print("3  One log (cellular only)")
        print("4  Boot OTA (if configured)")
        print("5  Run standby_monitor (auto-log loop) — watch ~5 min cycle")
        print("6  Quit (stay in REPL)")
        print("7  Clear BLE latch (use when switch/key off but ble_wanted True)")
        try:
            choice = input("Choice [1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if choice == "1":
            _status()
        elif choice == "2":
            _one_log(prefer_wifi=True)
        elif choice == "3":
            _one_log(prefer_wifi=False)
        elif choice == "4":
            _boot_ota_once()
        elif choice == "5":
            try:
                _standby_loop()
            except KeyboardInterrupt:
                print("\nstandby loop stopped.")
        elif choice == "6":
            print("Done. Shell stays open.")
            return
        elif choice == "7":
            _clear_ble_latch()
        else:
            print("Unknown:", choice)


if __name__ == "__main__":
    main()
