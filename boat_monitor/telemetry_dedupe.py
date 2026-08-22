"""Small, best-effort persistent state for optional telemetry Events."""

try:
    import ujson as json
except ImportError:
    import json


MAX_STATE_BYTES = 2048


def load_value(path):
    """Return the last posted value, or None for missing/corrupt state."""
    for candidate in (path, path + ".bak"):
        try:
            with open(candidate, "r") as handle:
                raw = handle.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                continue
            data = json.loads(raw)
            value = data.get("value") if isinstance(data, dict) else None
            if isinstance(value, str) and len(value) <= MAX_STATE_BYTES:
                return value
        except Exception:
            pass
    return None


def should_post(path, value):
    return load_value(path) != value


def mark_posted(path, value):
    """Atomically-enough replace bounded state; persistence is best effort."""
    value = str(value)
    if len(value) > MAX_STATE_BYTES:
        value = value[:MAX_STATE_BYTES]
    tmp_path = path + ".tmp"
    backup_path = path + ".bak"
    try:
        raw = json.dumps({"value": value})
        if len(raw) > MAX_STATE_BYTES:
            return False
        with open(tmp_path, "w") as handle:
            handle.write(raw)
        try:
            import os

            try:
                os.remove(backup_path)
            except Exception:
                pass
            try:
                os.rename(path, backup_path)
            except Exception:
                pass
            os.rename(tmp_path, path)
            try:
                os.remove(backup_path)
            except Exception:
                pass
        except Exception:
            # Some host/MicroPython ports can replace directly only after remove.
            try:
                import os

                try:
                    os.remove(path)
                except Exception:
                    pass
                os.rename(tmp_path, path)
            except Exception:
                return False
        return True
    except Exception:
        try:
            import os

            os.remove(tmp_path)
        except Exception:
            pass
        return False
