"""
Sheet-driven boot / OTA policy (persists on the Pico filesystem).

Config tab keys (via Apps Script commands on each log POST):
  auto_ota_on_boot     — 1/true/yes overrides ota_config.py on every boot
  boot_ota_max_seconds — cap for boot-time OTA (default from ota_config)
  boot_ota_prefer_wifi — 1|0: force Wi-Fi for boot OTA; omit = policy below
  standby_prefer_wifi  — 1|0: force Wi-Fi-first or cellular standby logging
  keep_wifi_connected_docked — 1|0: preserve dock STA between standby logs
  dock_mode — home: Wi-Fi-first standby logging; boot OTA defaults to cellular
  ota_manifest_profile — micro | ram-fix | feature-pack (sheet override)
  cmd_ota_force — one-shot: allow boot OTA / reboot when ota_degraded (cleared on success)
  keep_modem_awake_underway — 1|0: skip AT+CPOF after cellular log while underway
  cellular_control_sync_every_logs — periodic dock cellular command sync (0 disables)

When the sheet requests OTA (min_fw_version, cmd_ota, …), remote_control sets
pending_ota so the next boot runs ota.update() even if ota_config.py still
says AUTO_OTA_ON_BOOT = False (bench leftovers).
"""

try:
    import ujson as json
except ImportError:
    import json

PATH = "remote_boot_config.json"
CELLULAR_CONTROL_SYNC_DEFAULT = 12
CELLULAR_CONTROL_SYNC_MAX = 255
CELLULAR_CONTROL_SYNC_COUNT_KEY = "_cellular_control_sync_success_count"


def _truthy(value):
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")


def load():
    for path in (PATH, PATH + ".bak"):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save(data):
    try:
        tmp_path = PATH + ".new"
        with open(tmp_path, "w") as f:
            json.dump(data, f)
        try:
            import os

            try:
                os.remove(PATH + ".bak")
            except OSError:
                pass
            try:
                os.rename(PATH, PATH + ".bak")
            except OSError:
                pass
            try:
                os.rename(tmp_path, PATH)
            except Exception:
                # Keep the last complete config readable if replacement fails.
                try:
                    os.rename(PATH + ".bak", PATH)
                except Exception:
                    pass
                raise
        except Exception:
            # Host and supported MicroPython ports can atomically replace by
            # rename. Avoid a direct truncate if that final rename failed.
            raise
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
    if "standby_prefer_wifi" in settings and str(settings.get("standby_prefer_wifi")).strip() != "":
        data["standby_prefer_wifi"] = _truthy(settings["standby_prefer_wifi"])
        applied.append("standby_prefer_wifi=%s" % (1 if data["standby_prefer_wifi"] else 0))
    if "keep_wifi_connected_docked" in settings and str(
        settings.get("keep_wifi_connected_docked")
    ).strip() != "":
        data["keep_wifi_connected_docked"] = _truthy(
            settings["keep_wifi_connected_docked"]
        )
        applied.append(
            "keep_wifi_connected_docked=%s"
            % (1 if data["keep_wifi_connected_docked"] else 0)
        )
    if "dock_mode" in settings and str(settings.get("dock_mode")).strip() != "":
        mode = str(settings.get("dock_mode")).strip().lower()
        data["dock_mode"] = mode
        applied.append("dock_mode=%s" % mode)
    if "ota_manifest_profile" in settings and str(settings.get("ota_manifest_profile")).strip() != "":
        data["ota_manifest_profile"] = str(settings["ota_manifest_profile"]).strip().lower()
        applied.append("ota_manifest_profile=%s" % data["ota_manifest_profile"])
    if _truthy(settings.get("clear_boot_ota_backoff")):
        data.pop("boot_ota_backoff_until", None)
        data.pop("boot_ota_skip_remaining", None)
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
            pass
        # ota_health.clear_degraded() writes through this module, but `data`
        # was loaded before that call. Clear the local copy too so save(data)
        # below cannot resurrect the state that was just removed.
        data.pop("ota_degraded", None)
        data["boot_ota_fail_count"] = 0
        data.pop("cmd_ota_force", None)
        data.pop("boot_ota_backoff_until", None)
        data.pop("boot_ota_skip_remaining", None)
        applied.append("clear_ota_degraded=1")
    if "keep_modem_awake_underway" in settings and str(
        settings.get("keep_modem_awake_underway")
    ).strip() != "":
        data["keep_modem_awake_underway"] = _truthy(settings["keep_modem_awake_underway"])
        applied.append(
            "keep_modem_awake_underway=%s" % (1 if data["keep_modem_awake_underway"] else 0)
        )
    if "cellular_control_sync_every_logs" in settings and str(
        settings.get("cellular_control_sync_every_logs")
    ).strip() != "":
        try:
            every = int(settings["cellular_control_sync_every_logs"])
            if 0 <= every <= CELLULAR_CONTROL_SYNC_MAX:
                data["cellular_control_sync_every_logs"] = every
                data[CELLULAR_CONTROL_SYNC_COUNT_KEY] = 0
                applied.append("cellular_control_sync_every_logs=%s" % every)
        except (TypeError, ValueError):
            pass
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
        # Do not call clear_pending_ota() and then save this stale local copy:
        # that reintroduced pending_ota at the end of apply_settings().
        data.pop("pending_ota", None)
        data.pop("cmd_ota_force", None)
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


def effective_standby_log_prefer_wifi():
    """Standby Power_Log uplink: explicit standby_prefer_wifi beats dock_mode Wi-Fi."""
    data = load()
    if "standby_prefer_wifi" in data and str(data.get("standby_prefer_wifi")).strip() != "":
        if not data["standby_prefer_wifi"]:
            return False
    dock = str(data.get("dock_mode") or "").strip().lower()
    if dock in ("home", "dock", "wifi"):
        return True
    if "standby_prefer_wifi" in data and str(data.get("standby_prefer_wifi")).strip() != "":
        return bool(data["standby_prefer_wifi"])
    try:
        import ble_policy

        return ble_policy.ota_prefer_wifi()
    except Exception:
        return False


def effective_keep_wifi_connected_docked(mode=None):
    """Whether a dock standby logger may leave STA associated after closing.

    An explicit setting wins.  Otherwise persistence follows the same explicit
    dock Wi-Fi intent used for standby logging; generic/manual Wi-Fi sessions
    never become persistent merely because Wi-Fi is available.
    """
    if mode not in ("docked_off", "bilge_active", "float_alert"):
        return False
    data = load()
    if "keep_wifi_connected_docked" in data:
        return bool(data["keep_wifi_connected_docked"])
    if "standby_prefer_wifi" in data and str(
        data.get("standby_prefer_wifi")
    ).strip() != "":
        return bool(data["standby_prefer_wifi"])
    return str(data.get("dock_mode") or "").strip().lower() in (
        "home",
        "dock",
        "wifi",
    )


def effective_cellular_control_sync_every_logs():
    """Return the bounded dock command-sync interval; zero disables it."""
    value = load().get(
        "cellular_control_sync_every_logs", CELLULAR_CONTROL_SYNC_DEFAULT
    )
    try:
        value = int(value)
    except (TypeError, ValueError):
        return CELLULAR_CONTROL_SYNC_DEFAULT
    if value < 0 or value > CELLULAR_CONTROL_SYNC_MAX:
        return CELLULAR_CONTROL_SYNC_DEFAULT
    return value


def cellular_control_sync_due():
    """Select cellular for the Nth successful scheduled dock log session."""
    every = effective_cellular_control_sync_every_logs()
    if every == 0:
        return False
    try:
        count = int(load().get(CELLULAR_CONTROL_SYNC_COUNT_KEY, 0))
    except (TypeError, ValueError):
        count = 0
    return max(0, count) >= every - 1


def note_cellular_control_sync_power_success(used_cellular):
    """Persist one successful Power_Log outcome without relying on an RTC."""
    data = load()
    every = effective_cellular_control_sync_every_logs()
    if every == 0:
        if data.get(CELLULAR_CONTROL_SYNC_COUNT_KEY):
            data[CELLULAR_CONTROL_SYNC_COUNT_KEY] = 0
            save(data)
        return
    if used_cellular:
        count = 0
    else:
        try:
            count = int(data.get(CELLULAR_CONTROL_SYNC_COUNT_KEY, 0)) + 1
        except (TypeError, ValueError):
            count = 1
        count = max(0, min(every - 1, count))
    data[CELLULAR_CONTROL_SYNC_COUNT_KEY] = count
    save(data)


def effective_boot_ota_prefer_wifi():
    """Boot-time OTA transport only (not standby logging).

    Rare OTAs: cellular is safer on Pico heap. dock_mode=home still uses Wi-Fi
    for routine standby logs via effective_standby_log_prefer_wifi().
    """
    data = load()
    if "boot_ota_prefer_wifi" in data:
        return bool(data["boot_ota_prefer_wifi"])
    dock = str(data.get("dock_mode") or "").strip().lower()
    if dock in ("home", "dock", "wifi"):
        return False
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


def set_boot_ota_backoff(seconds=600, skip_boots=None):
    """Skip boot-time OTA until backoff expires or skip_boots exhausted.

    Uses boot_ota_skip_remaining (RTC-safe) plus optional wall-clock cap.
    """
    try:
        import time

        data = load()
        if skip_boots is None:
            skip_boots = max(1, min(6, int(seconds) // 120))
        data["boot_ota_skip_remaining"] = max(1, int(skip_boots))
        data["boot_ota_backoff_until"] = time.time() + max(60, int(seconds))
        save(data)
    except Exception:
        pass


def _consume_boot_ota_skip():
    data = load()
    remaining = data.get("boot_ota_skip_remaining")
    if remaining is None:
        return
    try:
        n = int(remaining) - 1
        if n <= 0:
            data.pop("boot_ota_skip_remaining", None)
        else:
            data["boot_ota_skip_remaining"] = n
        save(data)
    except Exception:
        pass


def boot_ota_backoff_active():
    data = load()
    remaining = data.get("boot_ota_skip_remaining")
    if remaining is not None:
        try:
            if int(remaining) > 0:
                _consume_boot_ota_skip()
                return True
            data.pop("boot_ota_skip_remaining", None)
            save(data)
        except Exception:
            pass
    until = data.get("boot_ota_backoff_until")
    if not until:
        return False
    try:
        import time

        now = time.time()
        until_f = float(until)
        if now < until_f:
            # Pico RTC resets on machine.reset(); absolute until can block forever.
            try:
                if data.get("pending_ota") and needs_firmware_upgrade():
                    if until_f - now > 1200:
                        data.pop("boot_ota_backoff_until", None)
                        save(data)
                        return False
            except Exception:
                pass
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


def boot_ota_block_reason():
    """Return the exact boot OTA gate reason, or None when OTA may run."""
    data = load()
    force = bool(data.get("cmd_ota_force"))
    # A force command is an explicit recovery override. Do not consume a
    # backoff boot while forced, and bypass every normal scheduling gate.
    if not force and boot_ota_backoff_active():
        return "backoff_active"
    data = load()
    try:
        import ota_health

        if ota_health.ota_degraded() and not force:
            if data.get("pending_ota"):
                clear_pending_ota()
            return "ota_degraded"
    except ImportError:
        pass
    except Exception:
        pass
    if force:
        return None
    if data.get("pending_ota") and current_meets_min_fw():
        clear_pending_ota()
        data = load()
    if data.get("pending_ota"):
        return None
    # Already at sheet min_fw: skip boot OTA unless pending/cmd_ota_force (avoids OOM loops).
    if current_meets_min_fw():
        return "current_meets_min_fw"
    if not effective_auto_ota_on_boot():
        return "auto_ota_disabled"
    return None


def should_run_boot_ota():
    return boot_ota_block_reason() is None


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
