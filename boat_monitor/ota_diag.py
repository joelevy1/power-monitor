"""
Lightweight device snapshot for OTA / boot Events (mem + flash + fw).

Event name on sheet: device_stats (key=value detail).
"""


def _mem_free():
    try:
        import gc

        gc.collect()
        return int(gc.mem_free())
    except Exception:
        return None


def _fs_free_bytes():
    try:
        import os

        s = os.statvfs("/")
        # f_frsize * f_bavail (MicroPython statvfs)
        if len(s) >= 4:
            return int(s[0] * s[3])
        return int(s[1] * s[3])
    except Exception:
        return None


def snapshot():
    out = {}
    m = _mem_free()
    if m is not None:
        out["mem_free"] = m
    fs = _fs_free_bytes()
    if fs is not None:
        out["fs_free_b"] = fs
    try:
        import version

        out["fw"] = getattr(version, "VERSION", "?")
    except Exception:
        pass
    return out


def format_kv(extra=None):
    parts = []
    for k, v in snapshot().items():
        parts.append("%s=%s" % (k, v))
    if extra:
        for k, v in extra.items():
            if v is not None and str(v) != "":
                parts.append("%s=%s" % (k, v))
    return "; ".join(parts)


def log_phase(phase, logger=None, device=None, inline=False, **extra):
    detail = format_kv(dict(extra, phase=phase))
    try:
        import diag_log

        diag_log.log("device_stats %s" % detail[:220])
    except Exception:
        pass
    if not inline or logger is None or not getattr(logger, "_data_open", False):
        return detail
    try:
        logger.log_event(device or "boat-p2", "device_stats", detail[:1500])
    except Exception:
        pass
    return detail


def upload_bounded(device=None, phase="boot", prefer_wifi=False, max_total_s=25, **extra):
    detail = format_kv(dict(extra, phase=phase))
    try:
        import diag_log

        return diag_log.upload_event_bounded(
            device or "boat-p2",
            "device_stats",
            detail,
            diag_tail_lines=0,
            max_total_s=max_total_s,
            prefer_wifi=prefer_wifi,
        )
    except Exception:
        return False
