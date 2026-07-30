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

import field_console
