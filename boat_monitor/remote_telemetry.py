"""
Throttled Events-tab posts while Power_Log is quiet (soft-fail / overdue standby).

1.1.44+ reduces ENOMEM but does not remove the need to see *why* the sheet
went silent. These uploads are rate-limited so a fail loop cannot spam Events.
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

STATE_PATH = "telemetry_throttle.json"
DEFAULT_MIN_GAP_S = 600

# Modes where the boat is "on" (switch/key/engine) — verbose remote diag.
BOAT_ACTIVE_MODES = frozenset(
    ("key_on", "switch_on_key_off", "float_alert", "bilge_active")
)

# Verbose Events uploads while underway (seconds between heartbeats if no log).
BOAT_HEARTBEAT_GAP_S = 90
BOAT_SESSION_DIAG_LINES = 55
BOAT_HEARTBEAT_DIAG_LINES = 40

# Power-bank / docked standby — keep sheet noise low.
STANDBY_DIAG_GAP_S = 1800
STANDBY_SESSION_DIAG_LINES = 22
STANDBY_HEARTBEAT_GAP_S = 3600
STANDBY_HEARTBEAT_DIAG_LINES = 18


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _ticks_diff(a, b):
    try:
        return time.ticks_diff(a, b)
    except AttributeError:
        return a - b


def _load_state():
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(data):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def should_upload(event_key, min_gap_s=None):
    gap_ms = int((min_gap_s if min_gap_s is not None else DEFAULT_MIN_GAP_S) * 1000)
    state = _load_state()
    last = int(state.get(event_key) or 0)
    if last and _ticks_diff(_ticks_ms(), last) < gap_ms:
        return False
    return True


def mark_uploaded(event_key):
    state = _load_state()
    state[event_key] = _ticks_ms()
    _save_state(state)


def _fw_version():
    try:
        import version

        return getattr(version, "VERSION", "?")
    except Exception:
        return "?"


def _boat_active(mode):
    return mode in BOAT_ACTIVE_MODES


def _upload_diag_event(device, event, header, lines, prefer_wifi, max_total_s=45):
    import diag_log

    tail = "\n".join(diag_log.recent_lines(lines))
    body = header
    if tail:
        body = body + "\n--- boat_diag.log ---\n" + tail
    return diag_log.upload_event_bounded(
        device,
        event,
        body,
        diag_tail_lines=0,
        max_total_s=max_total_s,
        prefer_wifi=prefer_wifi,
    )


def maybe_inline_session_diag(logger, device, mode, summary):
    """Attach a verbose diag Events row before close_data (same modem session)."""
    if not getattr(logger, "_data_open", False):
        return False
    summary = str(summary or "")
    if "failed" in summary.lower():
        return False
    active = _boat_active(mode)
    if active:
        event = "boat_log_session"
        lines = BOAT_SESSION_DIAG_LINES
    else:
        if not should_upload("standby_log_session", STANDBY_DIAG_GAP_S):
            return False
        event = "standby_log_session"
        lines = STANDBY_SESSION_DIAG_LINES
    header = "session ok mode=%s fw=%s summary=%s" % (
        mode,
        _fw_version(),
        summary[:200],
    )
    import diag_log

    tail = "\n".join(diag_log.recent_lines(lines))
    body = header
    if tail:
        body = body + "\n--- boat_diag.log ---\n" + tail
    try:
        logger.log_event(device, event, body[:1500])
        mark_uploaded(event)
        diag_log.log("inline Events %s (%d chars)" % (event, len(body)))
        return True
    except Exception as exc:
        diag_log.log("inline session diag failed: %s" % exc)
        return False


def after_logging_session(device, mode, summary, prefer_wifi=False):
    """Push diag to Events after a log attempt (failures open a new session)."""
    summary = str(summary or "")
    failed = "failed" in summary.lower() or summary.startswith("power: failed")

    if failed:
        try:
            import mem_guard

            if mem_guard.skip_followup_after_log_fail(summary):
                try:
                    import diag_log

                    diag_log.log("after_logging_session skip ble_log_failed: %s" % summary[:120])
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            import diag_log

            diag_log.report_ble_log_failure(device, summary, prefer_wifi=prefer_wifi)
        except Exception:
            pass
        return

    # Success path: boat/standby verbose Events row is posted inline in
    # sheets_log.log_power_and_gps() before close_data when possible.
    if _boat_active(mode):
        return

    if not should_upload("standby_log_session", STANDBY_DIAG_GAP_S):
        return
    header = "standby ok mode=%s fw=%s summary=%s" % (
        mode,
        _fw_version(),
        summary[:200],
    )
    _upload_diag_event(
        device,
        "standby_log_session",
        header,
        STANDBY_SESSION_DIAG_LINES,
        prefer_wifi,
        max_total_s=35,
    )
    mark_uploaded("standby_log_session")


def maybe_boat_heartbeat(device, mode, prefer_wifi=False):
    """While boat is on and BLE loop is idle, push diag between log intervals."""
    if not _boat_active(mode):
        return False
    if not should_upload("boat_diag_heartbeat", BOAT_HEARTBEAT_GAP_S):
        return False
    try:
        import diag_log

        heap = diag_log.mem_kb()
    except Exception:
        heap = -1
    header = "heartbeat mode=%s fw=%s heap=%sK" % (mode, _fw_version(), heap)
    ok = _upload_diag_event(
        device,
        "boat_diag_heartbeat",
        header,
        BOAT_HEARTBEAT_DIAG_LINES,
        prefer_wifi,
        max_total_s=50,
    )
    if ok:
        mark_uploaded("boat_diag_heartbeat")
    return ok


def maybe_standby_heartbeat(device, mode, prefer_wifi=True):
    """Rare diag while on power-bank standby."""
    if _boat_active(mode):
        return False
    if not should_upload("standby_diag_heartbeat", STANDBY_HEARTBEAT_GAP_S):
        return False
    header = "standby heartbeat mode=%s fw=%s" % (mode, _fw_version())
    ok = _upload_diag_event(
        device,
        "standby_diag_heartbeat",
        header,
        STANDBY_HEARTBEAT_DIAG_LINES,
        prefer_wifi,
        max_total_s=30,
    )
    if ok:
        mark_uploaded("standby_diag_heartbeat")
    return ok


def maybe_report_auto_log_fail(device, mode, since_success_s, failures, summary, min_gap_s=600):
    """POST auto_log_degraded when auto-log keeps failing (ENOMEM, POST errors, …)."""
    if not should_upload("auto_log_degraded", min_gap_s):
        return False
    enomem = summary and "ENOMEM" in str(summary)
    try:
        import mem_guard

        if enomem or mem_guard.skip_network_diag_upload():
            return False
    except Exception:
        if enomem:
            return False
    try:
        import diag_log

        heap = diag_log.mem_kb()
    except Exception:
        heap = -1
    last = str(summary or "")[:220]
    detail = (
        "failures=%s since_success=%.0fs mode=%s fw=%s heap=%sK last=%s"
        % (failures, since_success_s, mode, _fw_version(), heap, last)
    )
    import diag_log

    ok = diag_log.upload_event_bounded(
        device, "auto_log_degraded", detail, diag_tail_lines=10, max_total_s=22
    )
    if ok:
        mark_uploaded("auto_log_degraded")
    return ok


def maybe_report_standby_overdue(device, mode, since_success_s, interval_s, min_gap_s=900):
    """POST standby_overdue when the Pico is alive but past the log interval."""
    if since_success_s < float(interval_s) + 90:
        return False
    if not should_upload("standby_overdue", min_gap_s):
        return False
    try:
        import mem_guard

        if mem_guard.skip_network_diag_upload():
            return False
    except Exception:
        pass
    try:
        import diag_log

        heap = diag_log.mem_kb()
    except Exception:
        heap = -1
    detail = (
        "no successful auto-log for %.0fs (interval=%ss) mode=%s fw=%s heap=%sK"
        % (since_success_s, interval_s, mode, _fw_version(), heap)
    )
    import diag_log

    ok = diag_log.upload_event_bounded(
        device, "standby_overdue", detail, diag_tail_lines=6, max_total_s=22
    )
    if ok:
        mark_uploaded("standby_overdue")
    return ok
