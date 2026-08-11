"""Merge USB recovery boot policy (run on Pico via mpremote run)."""

try:
    import ujson as json
except ImportError:
    import json

PATH = "remote_boot_config.json"
PREFER_WIFI = False
AUTO_OTA_ON_BOOT = False
DOCK_MODE = "home"
OTA_MANIFEST_PROFILE = "stress"
OTA_SELF_SUFFICIENT = False


def main():
    try:
        with open(PATH, "r") as f:
            data = json.load(f)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["boot_ota_fail_count"] = 0
    data.pop("ota_degraded", None)
    data.pop("pending_ota", None)
    data.pop("cmd_ota_force", None)
    data.pop("boot_ota_backoff_until", None)
    data.pop("boot_ota_skip_remaining", None)
    data["last_boot_ota_outcome"] = "usb_recovery"
    data["auto_ota_on_boot"] = bool(AUTO_OTA_ON_BOOT)
    if DOCK_MODE:
        data["dock_mode"] = str(DOCK_MODE)
    if OTA_MANIFEST_PROFILE:
        data["ota_manifest_profile"] = str(OTA_MANIFEST_PROFILE)
    if OTA_SELF_SUFFICIENT:
        data["ota_self_sufficient"] = True
        try:
            import time

            data["ota_self_sufficient_since"] = int(time.time())
        except Exception:
            pass
    if AUTO_OTA_ON_BOOT:
        try:
            import version

            data["pending_ota"] = True
            print("remote_boot_config: pending_ota=True for boot OTA after USB recovery")
        except Exception:
            data["pending_ota"] = True
    if PREFER_WIFI:
        data["boot_ota_prefer_wifi"] = True
    else:
        data["boot_ota_prefer_wifi"] = False
    with open(PATH, "w") as f:
        json.dump(data, f)
    print(
        "remote_boot_config patched: auto_ota=%s dock=%s profile=%s self_sufficient=%s"
        % (AUTO_OTA_ON_BOOT, DOCK_MODE, OTA_MANIFEST_PROFILE, OTA_SELF_SUFFICIENT)
    )


if __name__ == "__main__":
    main()
