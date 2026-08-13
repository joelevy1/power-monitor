"""MicroPython heap helpers for logging paths (avoid ENOMEM on Sheets POST)."""


def free_bytes():
    try:
        import gc

        gc.collect()
        if hasattr(gc, "mem_free"):
            return gc.mem_free()
        return 99999999
    except Exception:
        return 0


def collect_aggressive():
    try:
        import gc

        gc.collect()
        gc.collect()
    except Exception:
        pass


def is_enomem(exc):
    if exc is None:
        return False
    if getattr(exc, "args", None) and exc.args and exc.args[0] == 12:
        return True
    return "ENOMEM" in str(exc) or "errno 12" in str(exc).lower()


def low_heap_threshold():
    # Pico W: stay above ~20K before large HTTPS/json work
    return 22000


def heap_ok_for_https_post():
    """Enough free heap for a Sheets HTTPS POST (TLS + json.dumps)."""
    return free_bytes() >= low_heap_threshold()


def skip_network_diag_upload():
    """Skip stall/degraded Events uploads that worsen ENOMEM loops."""
    if not heap_ok_for_https_post():
        return True
    return False


def skip_followup_after_log_fail(summary_or_exc=None):
    """After a failed log POST: never open a second HTTPS session (ENOMEM / fragmentation)."""
    if summary_or_exc is not None:
        text = str(summary_or_exc)
        if "ENOMEM" in text or is_enomem(summary_or_exc):
            return True
    return skip_network_diag_upload()
