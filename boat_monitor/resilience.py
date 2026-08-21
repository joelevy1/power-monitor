"""
Remote-install resilience: hardware WDT, stall reboot that always resets,
and pending stall JSON so the next boot can POST Events even if upload hung.
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

PENDING_STALL_PATH = "pending_stall_reboot.json"
STALL_UPLOAD_MAX_S = 12
# RP2040 max ~8388 ms; fed from diag_log.log() and standby loop.
WDT_TIMEOUT_MS = 8000
WDT_FEED_INTERVAL_MS = 2500
HARDWARE_WDT = True

_wdt = None
_last_watchdog_feed_ms = None


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


def enable_watchdog(timeout_ms=None):
    global _wdt, _last_watchdog_feed_ms
    if not HARDWARE_WDT:
        return None
    if _wdt is not None:
        return _wdt
    try:
        import machine

        ms = int(timeout_ms or WDT_TIMEOUT_MS)
        _wdt = machine.WDT(timeout=ms)
        _last_watchdog_feed_ms = _ticks_ms()
        return _wdt
    except Exception as exc:
        print("resilience: WDT unavailable:", exc)
        return None


def feed_watchdog():
    """Feed the hardware WDT only if standby already enabled it."""
    global _last_watchdog_feed_ms
    if _wdt is None:
        return
    try:
        _wdt.feed()
        _last_watchdog_feed_ms = _ticks_ms()
    except Exception:
        pass


def feed_watchdog_if_due(interval_ms=None):
    """Feed a live WDT at a bounded cadence from progressing I/O loops.

    Polling loops can legally run much longer than the RP2040's ~8 second
    maximum watchdog timeout. Feeding every few seconds keeps slow I/O alive
    without hiding a deadlock that stops the loop entirely.
    """
    if _wdt is None:
        return
    gap = int(interval_ms or WDT_FEED_INTERVAL_MS)
    now = _ticks_ms()
    if _last_watchdog_feed_ms is None or _ticks_diff(now, _last_watchdog_feed_ms) >= gap:
        feed_watchdog()


def sleep_with_watchdog(seconds, slice_s=1, sleep_fn=None):
    """Sleep in bounded slices while preserving a live standby watchdog."""
    remaining = max(0, float(seconds))
    sleeper = sleep_fn or time.sleep
    feed_watchdog()
    while remaining > 0:
        step = min(float(slice_s), remaining)
        sleeper(step)
        remaining -= step
        feed_watchdog_if_due()


def write_pending_stall(device, reason, mode=None):
    payload = {
        "device": device or "boat-p2",
        "reason": str(reason),
        "mode": mode,
        "written_ms": _ticks_ms(),
    }
    try:
        with open(PENDING_STALL_PATH, "w") as f:
            f.write(json.dumps(payload))
    except Exception as exc:
        print("resilience: pending stall write failed:", exc)


def _clear_pending_stall():
    try:
        import os

        os.remove(PENDING_STALL_PATH)
    except OSError:
        pass
    except Exception:
        pass


def _load_pending_stall():
    try:
        with open(PENDING_STALL_PATH, "r") as f:
            return json.loads(f.read())
    except Exception:
        return None


def flush_pending_stall_on_boot():
    """POST a stall report left from the previous reboot (if any)."""
    pending = _load_pending_stall()
    if not pending:
        return False
    try:
        import mem_guard

        if mem_guard.skip_network_diag_upload():
            _clear_pending_stall()
            return False
    except Exception:
        pass
    import diag_log

    device = pending.get("device") or "boat-p2"
    reason = pending.get("reason") or "pending stall (boot flush)"
    mode = pending.get("mode")
    diag_log.log("flush pending stall from prior reboot: %s" % reason[:200])
    try:
        diag_log.upload_stall_report_bounded(
            device,
            reason + " (uploaded on boot)",
            mode=mode,
            max_total_s=STALL_UPLOAD_MAX_S,
            event="standby_stall_reboot",
        )
    except Exception as exc:
        diag_log.log("pending stall flush upload failed: %s" % exc)
    _clear_pending_stall()
    return True


def reboot_after_stall(device, reason, mode=None):
    """Persist stall context, try a short Events upload, then always reset."""
    import diag_log

    write_pending_stall(device, reason, mode=mode)
    diag_log.log("stall reboot: %s" % reason)
    uploaded = False
    skip_upload = False
    try:
        import mem_guard

        skip_upload = mem_guard.skip_network_diag_upload()
        if skip_upload:
            diag_log.log("stall upload skipped (low heap)")
    except Exception:
        pass
    if not skip_upload:
        try:
            uploaded = diag_log.upload_stall_report_bounded(
                device,
                reason,
                mode=mode,
                max_total_s=STALL_UPLOAD_MAX_S,
                event="standby_stall_reboot",
            )
        except Exception as exc:
            diag_log.log("stall upload bounded failed: %s" % exc)
    if uploaded:
        _clear_pending_stall()
    import machine

    time.sleep(0.3)
    machine.reset()
