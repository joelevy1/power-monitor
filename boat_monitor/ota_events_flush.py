"""
Flush queued OTA telemetry to the sheet Events tab before modem teardown or reset.

boot_ota and ota_lifecycle rows are often queued with inline=False; without an
explicit flush they never appear on Events when the device reboots immediately.
"""

DEFAULT_DEVICE = "boat-p2"
UPLOAD_MAX_S = 30


def _now_ms():
    try:
        import time

        return time.ticks_ms()
    except Exception:
        import time

        return int(time.time() * 1000)


def _elapsed_s(start_ms):
    try:
        import time

        return max(0, time.ticks_diff(time.ticks_ms(), start_ms)) / 1000
    except Exception:
        return max(0, _now_ms() - start_ms) / 1000


def flush_ota_events(logger=None, device=None, prefer_wifi=False):
    """Prefer inline flush on an open SheetsLogger; else bounded cellular upload."""
    device = device or DEFAULT_DEVICE
    posted = 0
    if logger is not None and getattr(logger, "_data_open", False):
        try:
            import ota_lifecycle

            posted += ota_lifecycle.flush_pending(logger, device)
        except Exception:
            pass
        try:
            import ota_telemetry

            if ota_telemetry.flush_pending_inline(logger, device):
                posted += 1
        except Exception:
            pass
        return posted
    return flush_ota_events_uplink(device=device, prefer_wifi=prefer_wifi)


def flush_ota_events_uplink(device=None, prefer_wifi=False, max_total_s=None):
    """Post a bounded sample of queued OTA events within one shared deadline."""
    device = device or DEFAULT_DEVICE
    max_s = max_total_s or UPLOAD_MAX_S
    started_ms = _now_ms()
    posted = 0
    try:
        import ota_lifecycle

        posted += ota_lifecycle.upload_pending_uplink(
            device=device,
            prefer_wifi=prefer_wifi,
            max_total_s=max(2, max_s - _elapsed_s(started_ms)),
            max_rows=2,
        )
    except Exception:
        pass
    remaining_s = max_s - _elapsed_s(started_ms)
    if remaining_s < 2:
        return posted
    try:
        import ota_telemetry

        if ota_telemetry.upload_pending_uplink(
            device=device,
            prefer_wifi=prefer_wifi,
            max_total_s=remaining_s,
        ):
            posted += 1
    except Exception:
        pass
    remaining_s = max_s - _elapsed_s(started_ms)
    if remaining_s < 2:
        return posted
    try:
        import ota_trace

        if ota_trace.flush_pending(
            device=device,
            prefer_wifi=prefer_wifi,
            max_total_s=remaining_s,
        ):
            posted += 1
    except Exception:
        pass
    if posted:
        try:
            import diag_log

            diag_log.log("ota_events_flush uplink posted=%s" % posted)
        except Exception:
            pass
    return posted
