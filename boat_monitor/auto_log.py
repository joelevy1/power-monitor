"""
Boat Monitor P2 - automatic background logging schedule.

Decides how often ble_service.py's run() loop should auto-log to Google
Sheets, based on the boat's current mode (from current_mode()/
read_status() in ble_service.py): frequent while the engine is running
(mode == "key_on"), much less frequent otherwise. This is independent of
manual "Log Now" presses (BLE command or web console) -- those still work
exactly as before, on top of whatever auto-logging is also doing.

Note this is a deliberately different design from BOAT_MONITOR_P2_PLAN.md's
original Phase 6/7 vision (RTC alarms + deep sleep between wakes). This
codebase ended up running BLE continuously instead (simpler to reason
about, already hardened through extensive real-hardware testing) rather
than the sleep/wake architecture the original plan assumed, so this
schedules within that already-running loop instead of RTC wake logic that
doesn't exist here.

Pure decision logic only -- no hardware/network calls -- so it's
unit-testable on a PC; see test_auto_log_parser.py. The actual Sheets
POST happens in ble_service.py's run() loop, which calls should_log_now()
every ~2s tick and only does the real (hardware-touching, many-second)
cellular work when it returns True.
"""

# "Frequent" while the engine is running (mode == "key_on") -- close to
# real-time tracking while underway, without being so frequent that one
# logging cycle (modem reset + registration + NETOPEN + 1-2 HTTPS POSTs,
# commonly 10-90s depending on network conditions -- see cellular.py) risks
# overlapping the next one.
INTERVAL_ENGINE_ON_S = 60  # 1 minute while engine on (sheet can override)

# Docked / standby default when Config has no override — use sheet
# interval_engine_off_s (often 300 for field tests).
INTERVAL_ENGINE_OFF_S = 3600  # 60 minutes docked / standby

ENGINE_ON_MODE = "key_on"

_OVERRIDE_ENGINE_ON_S = None
_OVERRIDE_ENGINE_OFF_S = None
_OVERRIDE_FILE = "auto_log_override.json"


def set_interval_overrides(engine_on_s=None, engine_off_s=None):
    """Runtime overrides from the sheet Config tab (remote_control.py)."""
    global _OVERRIDE_ENGINE_ON_S, _OVERRIDE_ENGINE_OFF_S
    if engine_on_s is not None:
        _OVERRIDE_ENGINE_ON_S = max(60, int(engine_on_s))
    if engine_off_s is not None:
        _OVERRIDE_ENGINE_OFF_S = max(60, int(engine_off_s))
    persist_interval_overrides()


def persist_interval_overrides():
    try:
        import ujson as json
    except ImportError:
        import json
    if _OVERRIDE_ENGINE_ON_S is None and _OVERRIDE_ENGINE_OFF_S is None:
        return
    data = {}
    if _OVERRIDE_ENGINE_ON_S is not None:
        data["interval_engine_on_s"] = _OVERRIDE_ENGINE_ON_S
    if _OVERRIDE_ENGINE_OFF_S is not None:
        data["interval_engine_off_s"] = _OVERRIDE_ENGINE_OFF_S
    try:
        with open(_OVERRIDE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("auto_log: persist overrides failed:", exc)


def load_persisted_overrides():
    global _OVERRIDE_ENGINE_ON_S, _OVERRIDE_ENGINE_OFF_S
    try:
        import ujson as json
    except ImportError:
        import json
    try:
        with open(_OVERRIDE_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        return
    if data.get("interval_engine_on_s") is not None:
        _OVERRIDE_ENGINE_ON_S = max(60, int(data["interval_engine_on_s"]))
    if data.get("interval_engine_off_s") is not None:
        _OVERRIDE_ENGINE_OFF_S = max(60, int(data["interval_engine_off_s"]))


def interval_for_mode(mode):
    if mode == ENGINE_ON_MODE:
        if _OVERRIDE_ENGINE_ON_S is not None:
            return _OVERRIDE_ENGINE_ON_S
        return INTERVAL_ENGINE_ON_S
    if _OVERRIDE_ENGINE_OFF_S is not None:
        return _OVERRIDE_ENGINE_OFF_S
    return INTERVAL_ENGINE_OFF_S


def stale_reboot_threshold_s(mode):
    """Standby watchdog: reboot after this long without a successful auto-log.

    Uses 2× the current interval for `mode` (sheet overrides included).
    Minimum 120s so a very short test interval does not reboot instantly.
    """
    return max(120, 2 * interval_for_mode(mode))


def should_log_now(mode, elapsed_s, last_mode=None):
    """elapsed_s: seconds since the last auto-log ATTEMPT (successful or
    not) -- ble_service.py updates its last-attempt timestamp regardless
    of outcome, so a persistent Sheets/cellular failure can't turn into a
    retry-storm hammering the modem every ~2s tick forever.

    last_mode: the mode observed on the previous tick, or None if this is
    the first tick since boot (no prior mode to compare against yet).

    Logs immediately on a mode CHANGE into the frequent state (engine just
    started) rather than waiting out whatever was left of the old, longer
    interval -- e.g. if the engine starts 5 minutes into a 60-minute
    docked interval, the very next tick logs right away instead of
    potentially waiting up to another 55 minutes to notice the boat is now
    underway. Does NOT do the reverse (no forced log on engine-off) --
    that transition already gets picked up on its own next scheduled tick
    at the (now-longer) docked interval, and the "engine just stopped"
    moment isn't as time-sensitive to capture immediately.
    """
    if last_mode is not None and mode == ENGINE_ON_MODE and last_mode != ENGINE_ON_MODE:
        return True
    try:
        import remote_boot_config

        if remote_boot_config.needs_firmware_upgrade():
            return True
    except Exception:
        pass
    return elapsed_s >= interval_for_mode(mode)
