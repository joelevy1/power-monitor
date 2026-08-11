"""
Sheet-driven boot / OTA policy (persists on the Pico filesystem).

Config tab keys (via Apps Script commands on each log POST):
  auto_ota_on_boot     — 1/true/yes overrides ota_config.py on every boot
  boot_ota_max_seconds — cap for boot-time OTA (default from ota_config)
  boot_ota_prefer_wifi — 1|0: force Wi-Fi for boot OTA (home); omit = ble_policy default
  dock_mode — home: same as boot_ota_prefer_wifi=1 for boot OTA at the dock
  ota_manifest_profile — micro | ram-fix | feature-pack (sheet override)
  cmd_ota_force — one-shot: allow boot OTA / reboot when ota_degraded (cleared on success)
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
    if "boot_ota_prefer_wifi" in settings and str(settings.get("boot_ota_prefer_wifi")).strip() != "":
        data["boot_ota_prefer_wifi"] = _truthy(settings["boot_ota_prefer_wifi"])
        applied.append("boot_ota_prefer_wifi=%s" % (1 if data["boot_ota_prefer_wifi"] else 0))
    if "dock_mode" in settings and str(settings.get("dock_mode")).strip() != "":
        mode = str(settings.get("dock_mode")).strip().lower()
        data["dock_mode"] = mode
        applied.append("dock_mode=%s" % mode)
    if "ota_manifest_profile" in settings and str(settings.get("ota_manifest_profile")).strip() != "":
        data["ota_manifest_profile"] = str(settings["ota_manifest_profile"]).strip().lower()
        applied.append("ota_manifest_profile=%s" % data["ota_manifest_profile"])
    if _truthy(settings.get("clear_boot_ota_backoff")):
        data.pop("boot_ota_backoff_until", None)
        applied.append("clear_boot_ota_backoff=1")
    if _truthy(settings.get("cmd_ota_force")) or _truthy(settings.get("ota_force")):
        data["cmd_ota_force"] = True
        applied.append("cmd_ota_force=1")
    if _truthy(settings.get("cmd_clear_ota_degraded")) or _truthy(
        settings.get("clear_ota_degraded")
    ):
        try:
            import ota_health

            ota_health.clear_degraded()
        except Exception:
            data.pop("ota_degraded", None)
            data["boot_ota_fail_count"] = 0
            data.pop("cmd_ota_force", None)
        data.pop("boot_ota_backoff_until", None)
        applied.append("clear_ota_degraded=1")
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
    for key in ("interval_engine_on_s", "interval_engine_off_s"):
        val = settings.get(key)
        if val is not None and str(val).strip() != "":
            try:
                data[key] = max(60, int(val))
                applied.append("%s=%s" % (key, data[key]))
            except ValueError:
                pass
    if _truthy(settings.get("clear_pending_ota")) or _truthy(settings.get("cmd_clear_pending_ota")):
        clear_pending_ota()
        applied.append("clear_pending_ota=1")
    if applied:
        save(data)
    return applied


def apply_persisted_log_intervals():
    """Restore sheet log intervals after reboot (remote_boot_config.json)."""
    data = load()
    on_s = data.get("interval_engine_on_s")
    off_s = data.get("interval_engine_off_s")
    if on_s is None and off_s is None:
        return False
    try:
        import auto_log

        kwargs = {}
        if on_s is not None:
            kwargs["engine_on_s"] = int(on_s)
        if off_s is not None:
            kwargs["engine_off_s"] = int(off_s)
        auto_log.set_interval_overrides(**kwargs)
        return True
    except Exception as exc:
        print("remote_boot_config: log intervals failed:", exc)
        return False


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


def effective_boot_ota_prefer_wifi():
    """Boot-time OTA transport: sheet override, else ble_policy (Wi-Fi in standby only)."""
    data = load()
    if "boot_ota_prefer_wifi" in data:
        return bool(data["boot_ota_prefer_wifi"])
    dock = str(data.get("dock_mode") or "").strip().lower()
    if dock in ("home", "dock", "wifi"):
        return True
    try:
        import ble_policy

        return ble_policy.ota_prefer_wifi()
    except Exception:
        return False


def set_pending_ota(value=True, force=False):
    data = load()
    data["pending_ota"] = bool(value)
    if value:
        data["auto_ota_on_boot"] = True
        if force:
            data["cmd_ota_force"] = True
    save(data)


def clear_pending_ota():
    data = load()
    if "pending_ota" in data:
        data.pop("pending_ota", None)
        save(data)


def set_boot_ota_backoff(seconds=600):
    """Skip boot-time OTA until backoff expires (RAM/flash recovery)."""
    try:
        import time

        data = load()
        data["boot_ota_backoff_until"] = time.time() + max(60, int(seconds))
        save(data)
    except Exception:
        pass


def boot_ota_backoff_active():
    data = load()
    until = data.get("boot_ota_backoff_until")
    if not until:
        return False
    try:
        import time

        if time.time() < float(until):
            return True
        data.pop("boot_ota_backoff_until", None)
        save(data)
    except Exception:
        pass
    return False


def note_ota_reboot_reset():
    try:
        import time

        data = load()
        data["last_ota_reboot_at"] = time.time()
        save(data)
    except Exception:
        pass


def ota_reboot_cooldown_active(min_interval_s=600):
    data = load()
    last = data.get("last_ota_reboot_at")
    if not last:
        return False
    try:
        import time

        return (time.time() - float(last)) < min_interval_s
    except Exception:
        return False


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
    if boot_ota_backoff_active():
        return False
    data = load()
    try:
        import ota_health

        if ota_health.ota_degraded() and not data.get("cmd_ota_force"):
            if data.get("pending_ota"):
                clear_pending_ota()
            return False
    except ImportError:
        pass
    except Exception:
        pass
    if data.get("pending_ota") and current_meets_min_fw():
        clear_pending_ota()
        data = load()
    if data.get("pending_ota"):
        return True
    # Already at sheet min_fw: skip boot OTA unless pending/cmd_ota_force (avoids OOM loops).
    if current_meets_min_fw():
        return False
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
