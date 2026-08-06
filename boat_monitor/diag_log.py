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


def clear():
    try:
        import os

        os.remove(LOG_PATH)
        print("cleared", LOG_PATH)
    except Exception as exc:
        print("clear failed:", exc)


def upload_tail_to_events(device="boat-p2", lines=15):
    """Best-effort: post last diag lines to Events tab (one row)."""
    try:
        with open(LOG_PATH, "r") as f:
            text = "\n".join(f.read().splitlines()[-lines:])
    except Exception as exc:
        text = "no diag log: %s" % exc
    try:
        import sheets_log

        logger = sheets_log.SheetsLogger(prefer_wifi=True)
        try:
            logger.ensure_data()
            logger.log_event(device, "diag", text[:1500])
        finally:
            logger.close_data()
        log("uploaded tail to Events tab")
    except Exception as exc:
        log("upload_tail failed: %s" % exc)
