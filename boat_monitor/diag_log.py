"""
Append-only diagnostic log on the Pico filesystem (boat_diag.log).

Firmware 1.1.23+ writes stage lines during standby auto-log, Wi-Fi connect,
Sheets POST, and sheet-driven reboot/OTA. Each line is also printed as
DIAG: ... on the USB serial console (Thonny).

Thonny (device still running or after a soft hang — power-cycle first if
the REPL is wedged):

    import diag_log
    diag_log.tail(80)

Push the last lines to the sheet Events tab (needs Wi-Fi + secrets):

    import diag_log
    diag_log.upload_tail_to_events(lines=25)

Clear the file (fresh capture after a fix):

    diag_log.clear()

If auto-log throws, standby_monitor already calls upload_tail_to_events().

BLE Log Now failures (1.1.50+): firmware logs stages to boat_diag.log and tries
an Events row with event=ble_log_failed (cellular). Check the Events tab or:

    import diag_log
    diag_log.tail(40)

From the app (1.1.50+), send BLE command ``diag`` to print tail to serial and
attempt the same Events upload.
"""

try:
    import utime as time
except ImportError:
    import time

LOG_PATH = "boat_diag.log"
MAX_BYTES = 24000


def _stamp():
    try:
        t = time.localtime()
        return "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        return "?"


def mem_kb():
    try:
        import gc

        return gc.mem_free() // 1024
    except Exception:
        return -1


def log(msg):
    try:
        import resilience

        resilience.feed_watchdog()
    except Exception:
        pass
    line = "[%s] (heap %dK) %s" % (_stamp(), mem_kb(), str(msg))
    print("DIAG:", line)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception as exc:
        print("diag_log write failed:", exc)
        return
    try:
        import os

        if os.stat(LOG_PATH)[6] > MAX_BYTES:
            with open(LOG_PATH, "r") as f:
                data = f.read()
            with open(LOG_PATH, "w") as f:
                f.write(data[-(MAX_BYTES // 2) :])
    except Exception:
        pass


def tail(n=60):
    try:
        with open(LOG_PATH, "r") as f:
            lines = f.read().splitlines()
    except Exception as exc:
        print("No diag log:", exc)
        return []
    out = lines[-n:]
    for line in out:
        print(line)
    return out


def recent_lines(n=8):
    """Last n diag lines (no print) — for BLE status JSON."""
    try:
        with open(LOG_PATH, "r") as f:
            return f.read().splitlines()[-n:]
    except Exception:
        return []


def clear():
    try:
        import os

        os.remove(LOG_PATH)
        print("cleared", LOG_PATH)
    except Exception as exc:
        print("clear failed:", exc)


def upload_tail_to_events(device="boat-p2", lines=15, event="diag", prefer_wifi=True):
    """Best-effort: post last diag lines to Events tab (one row)."""
    try:
        with open(LOG_PATH, "r") as f:
            text = "\n".join(f.read().splitlines()[-lines:])
    except Exception as exc:
        text = "no diag log: %s" % exc
    try:
        import sheets_log

        logger = sheets_log.SheetsLogger(prefer_wifi=prefer_wifi)
        try:
            logger.ensure_data()
            logger.log_event(device, event, text[:1500])
        finally:
            logger.close_data()
        log("uploaded tail to Events tab event=%s prefer_wifi=%s" % (event, prefer_wifi))
    except Exception as exc:
        log("upload_tail failed: %s" % exc)


def report_ble_log_failure(device, reason, lines=18, prefer_wifi=False):
    """After a failed BLE Log Now: keep local diag and try Events upload (cellular default)."""
    reason = str(reason)[:400]
    log("ble_log_failed reason=%s" % reason)
    try:
        import version

        fw = getattr(version, "VERSION", "?")
    except Exception:
        fw = "?"
    detail = "fw=%s heap=%sK reason=%s" % (fw, mem_kb(), reason)
    tail_text = "\n".join(recent_lines(lines))
    if tail_text:
        detail = detail + "\n--- boat_diag.log ---\n" + tail_text
    upload_event_bounded(
        device,
        "ble_log_failed",
        detail,
        diag_tail_lines=0,
        max_total_s=28,
        prefer_wifi=prefer_wifi,
    )


def _stall_report_detail(reason, mode=None, lines=40):
    import auto_log

    interval_s = auto_log.interval_for_mode(mode) if mode else None
    threshold_s = auto_log.stale_reboot_threshold_s(mode) if mode else None
    header = reason
    if mode is not None:
        header += " mode=%s interval_s=%s stale_threshold_s=%s" % (
            mode,
            interval_s,
            threshold_s,
        )
    try:
        with open(LOG_PATH, "r") as f:
            tail_text = "\n".join(f.read().splitlines()[-lines:])
    except Exception as exc:
        tail_text = "no diag log: %s" % exc
    return header, header + "\n--- boat_diag.log ---\n" + tail_text


def upload_event_bounded(
    device, event, detail, diag_tail_lines=0, max_total_s=20, prefer_wifi=True
):
    """Best-effort Events POST with a wall-clock cap (custom detail text)."""
    try:
        start = time.time()
    except AttributeError:
        start = time.ticks_ms() / 1000.0

    def elapsed_s():
        try:
            return time.time() - start
        except AttributeError:
            return (time.ticks_ms() - int(start * 1000)) / 1000.0

    body = str(detail)
    if diag_tail_lines:
        try:
            with open(LOG_PATH, "r") as f:
                tail_text = "\n".join(f.read().splitlines()[-diag_tail_lines:])
            body = body + "\n--- boat_diag.log ---\n" + tail_text
        except Exception as exc:
            body = body + "\n(no diag log: %s)" % exc
    log("upload_event_bounded event=%s" % event)
    if elapsed_s() >= max_total_s:
        log("event upload skipped (no time left)")
        return False
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    try:
        import sheets_log

        logger = sheets_log.SheetsLogger(prefer_wifi=prefer_wifi)
        try:
            logger.ensure_data()
            if elapsed_s() >= max_total_s:
                log("event upload skipped after ensure_data (timeout)")
                return False
            logger.log_event(device, event, body[:1500])
        finally:
            try:
                logger.close_data()
            except Exception:
                pass
        log("uploaded %s to Events (%.1fs)" % (event, elapsed_s()))
        return True
    except Exception as exc:
        log("upload_event_bounded failed: %s" % exc)
        return False


def upload_stall_report_bounded(
    device, reason, mode=None, lines=12, max_total_s=12, event="standby_stall_reboot"
):
    """Best-effort Events POST with a wall-clock cap (never blocks reboot long)."""
    try:
        start = time.time()
    except AttributeError:
        start = time.ticks_ms() / 1000.0

    def elapsed_s():
        try:
            return time.time() - start
        except AttributeError:
            return (time.ticks_ms() - int(start * 1000)) / 1000.0

    header, detail = _stall_report_detail(reason, mode=mode, lines=lines)
    log(header)
    if elapsed_s() >= max_total_s:
        log("stall upload skipped (no time left)")
        return False
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    try:
        import sheets_log

        logger = sheets_log.SheetsLogger(prefer_wifi=True)
        try:
            logger.ensure_data()
            if elapsed_s() >= max_total_s:
                log("stall upload skipped after ensure_data (timeout)")
                return False
            logger.log_event(device, event, detail[:800])
        finally:
            try:
                logger.close_data()
            except Exception:
                pass
        log("uploaded %s to Events (%.1fs)" % (event, elapsed_s()))
        return True
    except Exception as exc:
        log("upload_stall_report_bounded failed: %s" % exc)
        return False


def upload_stall_report(device, reason, mode=None, lines=40):
    """Log stall reason locally, then try to POST Events row before reboot."""
    upload_stall_report_bounded(
        device, reason, mode=mode, lines=lines, max_total_s=45, event="standby_stall_reboot"
    )
