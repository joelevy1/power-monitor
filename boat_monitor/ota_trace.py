"""
Per-step OTA trace: every major step -> boat_diag.log, one Events row at end.

Event name on sheet: ota_trace (detail + recent diag tail for analysis).
"""

try:
    import utime as time
except ImportError:
    import time

PENDING_PATH = "ota_trace_pending.json"

_steps = []
_meta = {}


def _elapsed_s():
    t0 = _meta.get("t0")
    if t0 is None:
        return 0.0
    try:
        return time.time() - t0
    except Exception:
        try:
            return time.ticks_diff(time.ticks_ms(), t0) / 1000.0
        except Exception:
            return 0.0


def begin(*, fw_from=None, prefer_wifi=None, max_total_s=None, source="ota.update"):
    global _steps, _meta
    _steps = []
    try:
        t0 = time.time()
    except Exception:
        t0 = time.ticks_ms()
    _meta = {
        "t0": t0,
        "fw_from": fw_from,
        "prefer_wifi": prefer_wifi,
        "max_total_s": max_total_s,
        "source": source,
        "http_sessions": 0,
    }
    step("begin", fw_from=fw_from)


def note_http_session():
    _meta["http_sessions"] = int(_meta.get("http_sessions") or 0) + 1


def step(label, **extra):
    parts = ["+%.1fs" % _elapsed_s(), str(label)]
    for k, v in extra.items():
        if v is not None and str(v) != "":
            parts.append("%s=%s" % (k, v))
    line = " ".join(parts)
    _steps.append(line)
    try:
        import diag_log

        diag_log.log("ota_step " + line)
    except Exception:
        print("ota_step", line)


def _header(outcome, **extra):
    parts = [
        "outcome=%s" % outcome,
        "source=%s" % (_meta.get("source") or "ota"),
        "http_sessions=%s" % (_meta.get("http_sessions") or 0),
        "elapsed_s=%.1f" % _elapsed_s(),
    ]
    if _meta.get("fw_from"):
        parts.append("fw_from=%s" % _meta["fw_from"])
    if _meta.get("prefer_wifi") is not None:
        parts.append("prefer_wifi=%s" % _meta["prefer_wifi"])
    if _meta.get("max_total_s") is not None:
        parts.append("max_s=%s" % _meta["max_total_s"])
    for k, v in extra.items():
        if v is not None and str(v) != "":
            parts.append("%s=%s" % (k, v))
    return "; ".join(parts)


def build_detail(outcome, **extra):
    header = _header(outcome, **extra)
    steps_text = "\n".join(_steps[-35:])
    body = header + "\n--- steps ---\n" + steps_text
    return body[:1500]


def stats():
    """Summary for boot_ota / ota_lifecycle (no import of private state)."""
    return {
        "elapsed_s": round(_elapsed_s(), 1),
        "http_sessions": int(_meta.get("http_sessions") or 0),
    }


def upload(device="boat-p2", outcome="unknown", prefer_wifi=None, max_total_s=45, **extra):
    """Post trace to Events (modem must still be up if cellular)."""
    detail = build_detail(outcome, **extra)
    try:
        import diag_log

        diag_log.log("ota_trace upload outcome=%s" % outcome)
        ok = diag_log.upload_event_bounded(
            device,
            "ota_trace",
            detail,
            diag_tail_lines=18,
            max_total_s=max_total_s,
            prefer_wifi=False if prefer_wifi is False else True,
        )
        if not ok:
            _queue_pending(detail, device)
        return ok
    except Exception as exc:
        try:
            import diag_log

            diag_log.log("ota_trace upload failed: %s" % exc)
        except Exception:
            pass
        _queue_pending(detail, device)
        return False


def queue(device="boat-p2", outcome="unknown", **extra):
    """Persist trace for a later normal session without opening a transport."""
    detail = build_detail(outcome, **extra)
    _queue_pending(detail, device)
    return True


def _queue_pending(detail, device):
    try:
        import ujson as json
    except ImportError:
        import json
    try:
        with open(PENDING_PATH, "w") as f:
            json.dump({"device": device, "detail": detail[:1500]}, f)
    except Exception:
        pass


def flush_pending(device=None, prefer_wifi=False, max_total_s=35):
    try:
        import ujson as json
    except ImportError:
        import json
    try:
        with open(PENDING_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        return False
    if not isinstance(data, dict) or not data.get("detail"):
        return False
    device = device or data.get("device") or "boat-p2"
    try:
        import diag_log

        ok = diag_log.upload_event_bounded(
            device,
            "ota_trace",
            data["detail"],
            diag_tail_lines=0,
            max_total_s=max_total_s,
            prefer_wifi=prefer_wifi,
        )
        if ok:
            try:
                import os

                os.remove(PENDING_PATH)
            except OSError:
                pass
        return ok
    except Exception:
        return False
