"""MicroPython heap helpers for logging paths (avoid ENOMEM on Sheets POST)."""


def free_bytes():
    try:
        import gc

        gc.collect()
        return gc.mem_free()
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
