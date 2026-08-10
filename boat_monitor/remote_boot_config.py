"""
Sheet-driven boot / OTA policy (persists on the Pico filesystem).

Config tab keys (via Apps Script commands on each log POST):
  auto_ota_on_boot     — 1/true/yes overrides ota_config.py on every boot
  boot_ota_max_seconds — cap for boot-time OTA (default from ota_config)
  keep_modem_awake_underway — 1|0: skip AT+CPOF after cellular log while underway

When the sheet requests OTA (min_fw_version, cmd_ota, …), remote_control sets
pending_ota so the next boot runs ota.update() even if ota_config.py still
says AUTO_OTA_ON_BOOT = False (bench leftovers).
"""

try:
    import ujson as json
except ImportError:
    import json

PATH = "remote_boot_config.json"


def _truthy(value):
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")


def load():
    try:
        with open(PATH, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data):
    try:
        with open(PATH, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("remote_boot_config save failed:", exc)


def apply_settings(settings):
    """Merge recognized keys from sheet settings into remote_boot_config.json."""
    if not settings:
        return []
    data = load()
    applied = []
    if "auto_ota_on_boot" in settings and str(settings.get("auto_ota_on_boot")).strip() != "":
        data["auto_ota_on_boot"] = _truthy(settings["auto_ota_on_boot"])
        applied.append("auto_ota_on_boot=%s" % (1 if data["auto_ota_on_boot"] else 0))
    if "boot_ota_max_seconds" in settings and str(settings.get("boot_ota_max_seconds")).strip() != "":
        try:
            data["boot_ota_max_seconds"] = max(30, int(settings["boot_ota_max_seconds"]))
            applied.append("boot_ota_max_seconds=%s" % data["boot_ota_max_seconds"])
        except ValueError:
            pass
    if "keep_modem_awake_underway" in settings and str(
        settings.get("keep_modem_awake_underway")
    ).strip() != "":
        data["keep_modem_awake_underway"] = _truthy(settings["keep_modem_awake_underway"])
        applied.append(
            "keep_modem_awake_underway=%s" % (1 if data["keep_modem_awake_underway"] else 0)
        )
    min_fw = settings.get("min_fw_version") or settings.get("target_fw_version")
    if min_fw is not None and str(min_fw).strip() != "":
        data["min_fw_version"] = str(min_fw).strip()
        applied.append("min_fw_persisted=%s" % data["min_fw_version"])
    if _truthy(settings.get("clear_pending_ota")) or _truthy(settings.get("cmd_clear_pending_ota")):
        clear_pending_ota()
        applied.append("clear_pending_ota=1")
    if applied:
        save(data)
    return applied


def effective_auto_ota_on_boot():
    data = load()
    if "auto_ota_on_boot" in data:
        return bool(data["auto_ota_on_boot"])
    try:
        import ota_config

        return bool(getattr(ota_config, "AUTO_OTA_ON_BOOT", False))
    except Exception:
        return False


def effective_boot_ota_max_seconds():
    data = load()
    if "boot_ota_max_seconds" in data:
        seconds = int(data["boot_ota_max_seconds"])
    else:
        try:
            import ota_config

            seconds = int(getattr(ota_config, "BOOT_OTA_MAX_SECONDS", 420))
        except Exception:
            seconds = 420
    seconds = max(90, seconds)
    # Full manifest (~26 files) over cellular AT+HTTP often exceeds 180s.
    try:
        import ble_policy

        if not ble_policy.ota_prefer_wifi():
            seconds = max(seconds, 420)
    except Exception:
        seconds = max(seconds, 420)
    return seconds


def set_pending_ota(value=True):
    data = load()
    data["pending_ota"] = bool(value)
    if value:
        data["auto_ota_on_boot"] = True
    save(data)


def clear_pending_ota():
    data = load()
    if "pending_ota" in data:
        data.pop("pending_ota", None)
        save(data)


def current_meets_min_fw():
    """True when version.py is at or above persisted sheet min_fw_version."""
    data = load()
    min_fw = data.get("min_fw_version")
    if not min_fw:
        return True
    try:
        import version

        current = getattr(version, "VERSION", "0")
        return not _version_lt(current, min_fw)
    except Exception:
        return False


def clear_pending_ota_if_current():
    """Drop stale pending_ota after boot OTA when fw already meets min_fw."""
    if current_meets_min_fw():
        clear_pending_ota()


def should_run_boot_ota():
    data = load()
    if data.get("pending_ota") and current_meets_min_fw():
        clear_pending_ota()
        data = load()
    if data.get("pending_ota"):
        return True
    return effective_auto_ota_on_boot()


def boot_ota_status_line():
    data = load()
    return "pending_ota=%s sheet_auto_ota=%s effective_auto_ota=%s" % (
        bool(data.get("pending_ota")),
        data.get("auto_ota_on_boot", "(file default)"),
        effective_auto_ota_on_boot(),
    )


def _parse_version(text):
    parts = []
    for piece in str(text or "").strip().split("."):
        try:
            parts.append(int(piece))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _version_lt(current, minimum):
    return _parse_version(current) < _parse_version(minimum)


def needs_firmware_upgrade():
    """True when device fw is older than sheet min_fw (not the pending_ota flag alone)."""
    return not current_meets_min_fw()
