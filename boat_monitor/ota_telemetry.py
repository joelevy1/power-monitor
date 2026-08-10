"""
Post boot-time / remote OTA outcomes to the Google Sheet Events tab (cellular or Wi-Fi).

No USB required: failures queue to pending_ota_event.json and flush on the next boot
before another OTA attempt.
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

PENDING_PATH = "pending_ota_event.json"
DEFAULT_DEVICE = "boat-p2"
UPLOAD_MAX_S = 40


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _fw_version():
    try:
        import version

        return getattr(version, "VERSION", "?")
    except Exception:
        return "?"


def _uplink_prefer_wifi():
    try:
        import ble_policy

        return ble_policy.ota_prefer_wifi()
    except Exception:
        return False


def _format_detail(payload):
    parts = []
    for key in (
        "outcome",
        "source",
        "fw",
        "fw_from",
        "fw_target",
        "max_s",
        "prefer_wifi",
        "elapsed_s",
        "error",
        "status",
    ):
        if key in payload and payload[key] is not None and str(payload[key]) != "":
            parts.append("%s=%s" % (key, payload[key]))
    return "; ".join(parts)


def queue_result(payload, device=None):
    data = dict(payload or {})
    data["device"] = device or data.get("device") or DEFAULT_DEVICE
    data["fw"] = data.get("fw") or _fw_version()
    data["written_ms"] = _ticks_ms()
    try:
        with open(PENDING_PATH, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        try:
            import diag_log

            diag_log.log("ota_telemetry queue failed: %s" % exc)
        except Exception:
            print("ota_telemetry queue failed:", exc)


def _clear_pending():
    try:
        import os

        os.remove(PENDING_PATH)
    except OSError:
        pass
    except Exception:
        pass


def _load_pending():
    try:
        with open(PENDING_PATH, "r") as f:
            data = json.loads(f.read())
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def upload_result(payload, device=None, prefer_wifi=None, max_total_s=None):
    import diag_log

    device = device or (payload or {}).get("device") or DEFAULT_DEVICE
    if prefer_wifi is None:
        prefer_wifi = _uplink_prefer_wifi()
    body = _format_detail(payload or {})
    tail = "\n".join(diag_log.recent_lines(22))
    if tail:
        body = body + "\n--- boat_diag.log ---\n" + tail
    diag_log.log("ota_telemetry upload %s" % body[:120])
    return diag_log.upload_event_bounded(
        device,
        "boot_ota",
        body,
        diag_tail_lines=0,
        max_total_s=max_total_s or UPLOAD_MAX_S,
        prefer_wifi=prefer_wifi,
    )


def flush_pending_inline(logger, device=None):
    """POST queued boot_ota row on an open Sheets session (cellular/Wi-Fi up)."""
    pending = _load_pending()
    if not pending:
        return False
    if not getattr(logger, "_data_open", False):
        return False
    device = device or pending.get("device") or DEFAULT_DEVICE
    body = _format_detail(pending)
    try:
        import diag_log

        tail = "\n".join(diag_log.recent_lines(10))
        if tail:
            body = body + "\n--- boat_diag.log ---\n" + tail
    except Exception:
        pass
    try:
        logger.log_event(device, "boot_ota", body[:1500])
        _clear_pending()
        try:
            import diag_log

            diag_log.log("boot_ota inline Events (%d chars)" % len(body))
        except Exception:
            pass
        return True
    except Exception as exc:
        try:
            import diag_log

            diag_log.log("boot_ota inline failed: %s" % exc)
        except Exception:
            pass
        return False


def flush_pending_on_boot(device=None):
    """POST queued OTA report from prior boot (success after reboot, or failed upload)."""
    pending = _load_pending()
    if not pending:
        return False
    device = device or pending.get("device") or DEFAULT_DEVICE
    try:
        import diag_log

        diag_log.log("flush pending OTA event: %s" % _format_detail(pending)[:200])
    except Exception:
        pass
    ok = False
    try:
        ok = upload_result(pending, device=device, prefer_wifi=False)
    except Exception as exc:
        try:
            import diag_log

            diag_log.log("pending OTA flush failed: %s" % exc)
        except Exception:
            pass
    _clear_pending()
    return ok


def report_boot_ota(
    outcome,
    *,
    fw_target=None,
    max_s=None,
    prefer_wifi=None,
    error=None,
    elapsed_s=None,
    source="boot",
    device=None,
):
    """Try Events upload; queue to flash if upload fails (except immediate reboot success)."""
    payload = {
        "outcome": outcome,
        "source": source,
        "fw": _fw_version(),
        "fw_from": _fw_version(),
        "fw_target": fw_target,
        "max_s": max_s,
        "prefer_wifi": prefer_wifi,
        "elapsed_s": elapsed_s,
        "error": (str(error)[:300] if error else None),
    }
    if outcome == "success_pending_reboot":
        payload["outcome"] = "success"
        payload["status"] = "rebooting"
        queue_result(payload, device=device)
        return True
    prefer = False if prefer_wifi is False else _uplink_prefer_wifi()
    if upload_result(payload, device=device, prefer_wifi=prefer, max_total_s=max_total_s or 90):
        return True
    queue_result(payload, device=device)
    return False


def upload_pending_uplink(device=None, prefer_wifi=False, max_total_s=35):
    pending = _load_pending()
    if not pending:
        return False
    device = device or pending.get("device") or DEFAULT_DEVICE
    body = _format_detail(pending)
    try:
        import diag_log

        tail = "\n".join(diag_log.recent_lines(8))
        if tail:
            body = body + "\n--- boat_diag.log ---\n" + tail
    except Exception:
        pass
    try:
        if upload_result(
            pending,
            device=device,
            prefer_wifi=prefer_wifi,
            max_total_s=max_total_s,
        ):
            _clear_pending()
            return True
    except Exception:
        pass
    return False


def note_ota_reboot_queued(source="run_actions", device=None, detail=""):
    """Before reset for sheet/app OTA: queue + best-effort cellular Events row."""
    payload = {
        "outcome": "reboot_queued",
        "source": source,
        "status": detail[:200] if detail else "pending_ota set",
    }
    queue_result(payload, device=device)
    try:
        upload_result(payload, device=device, prefer_wifi=False, max_total_s=18)
    except Exception:
        pass
