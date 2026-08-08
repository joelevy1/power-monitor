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


def maybe_report_auto_log_fail(device, mode, since_success_s, failures, summary, min_gap_s=600):
    """POST auto_log_degraded when auto-log keeps failing (ENOMEM, POST errors, …)."""
    if not should_upload("auto_log_degraded", min_gap_s):
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
