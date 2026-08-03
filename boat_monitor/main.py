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

try:
    import os

    try:
        os.stat("wifi_mode.txt")
        os.remove("wifi_mode.txt")
        print("Starting Wi-Fi service console")
        import field_console
    except OSError:
        print("Starting BLE service")
        import ble_service

        ble_service.main()
except Exception as exc:
    print("BLE service failed, falling back to Wi-Fi:", exc)
    import field_console
