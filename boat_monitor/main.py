try:
    import ota_config

    if getattr(ota_config, "AUTO_OTA_ON_BOOT", False):
        try:
            import ota

            ota.update(reboot=getattr(ota_config, "AUTO_OTA_REBOOT_AFTER_UPDATE", True))
        except Exception as exc:
            # Never let a failed update check prevent the boat monitor from
            # booting into its local service console.
            print("Boot OTA skipped/failed:", exc)
except Exception as exc:
    print("OTA config unavailable:", exc)

# Decide which mode was requested BEFORE trying to start either one -- a
# single try/except wrapping both the os.stat() check AND the import that
# starts a whole radio mode was a real bug: os.stat() raising OSError
# (file missing -- the normal "no Wi-Fi requested" case) and, say,
# field_console.py's start_ap() raising OSError (AP failed to come up --
# a real error) both landed in the SAME "except OSError:" branch. That
# branch always printed "Starting BLE service" regardless of which one
# actually happened, silently misreporting a real Wi-Fi AP failure as
# "no wifi_mode.txt file" and masking the actual error entirely.
wifi_requested = False
try:
    import os

    os.stat("wifi_mode.txt")
    os.remove("wifi_mode.txt")
    wifi_requested = True
except OSError:
    wifi_requested = False
except Exception as exc:
    print("wifi_mode.txt check failed:", exc)

if wifi_requested:
    try:
        print("Starting Wi-Fi service console")
        import field_console
    except Exception as exc:
        print("Wi-Fi service console failed:", exc)
        try:
            print("Falling back to BLE service")
            import ble_service

            ble_service.main()
        except Exception as exc2:
            print("BLE service also failed:", exc2)
else:
    try:
        import ble_policy

        if ble_policy.ble_wanted():
            print("Starting BLE service (switch/key on or USB host)")
            import ble_service

            ble_service.main()
        else:
            print("Starting standby monitor (BLE off)")
            import standby_monitor

            standby_monitor.main()
    except Exception as exc:
        print("Primary service failed:", exc)
        try:
            print("Falling back to BLE service")
            import ble_service

            ble_service.main()
        except Exception as exc2:
            print("BLE service also failed:", exc2)
            import field_console
