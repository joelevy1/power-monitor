"""USB recovery patch with boot OTA enabled (run on Pico via mpremote run)."""

try:
    import ujson as json
except ImportError:
    import json

PATH = "remote_boot_config.json"
PREFER_WIFI = False
AUTO_OTA_ON_BOOT = True


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
    data["auto_ota_on_boot"] = True
    data["pending_ota"] = True
    if PREFER_WIFI:
        data["boot_ota_prefer_wifi"] = True
    with open(PATH, "w") as f:
        json.dump(data, f)
    print("remote_boot_config patched: auto_ota_on_boot=True pending_ota=True")


if __name__ == "__main__":
    main()
