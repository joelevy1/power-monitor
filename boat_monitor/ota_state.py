"""
Track OTA / firmware pulls so a partial install cannot look "done".

Writes ota_pending.json while files are being replaced; on boot, main.py
calls on_boot_check() to log incomplete installs and clear pending only when
every manifest path exists with min_size.
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

PENDING_PATH = "ota_pending.json"
# Write version + boot entrypoint last so "already at target" and autorun do not
# mask a partial install (Thonny EOF mid-pull).
DEFER_PATHS = ("version.py", "main.py")


def _now_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _load():
    try:
        with open(PENDING_PATH, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    try:
        with open(PENDING_PATH, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("ota_state: save failed:", exc)


def _clear():
    try:
        import os

        os.remove(PENDING_PATH)
    except OSError:
        pass
    except Exception:
        pass


def _log(msg):
    print("ota_state:", msg)
    try:
        import diag_log

        diag_log.log(msg)
    except Exception:
        pass


def sort_manifest_files(files):
    """Return manifest file entries with version.py then main.py last."""
    by_path = {}
    for entry in files or []:
        path = entry.get("path") or ""
        by_path[path] = entry
    normal = []
    for entry in files or []:
        path = entry.get("path") or ""
        if path not in DEFER_PATHS:
            normal.append(entry)
    deferred = [by_path[p] for p in DEFER_PATHS if p in by_path]
    return normal + deferred


def begin(target_version, paths):
    data = {
        "target_version": str(target_version),
        "paths": list(paths),
        "done": [],
        "started_ms": _now_ms(),
        "phase": "writing",
    }
    _save(data)
    _log("OTA begin target=%s files=%d" % (target_version, len(paths)))


def mark_done(path):
    data = _load()
    if not data:
        return
    done = data.get("done") or []
    if path not in done:
        done.append(path)
    data["done"] = done
    _save(data)


def verify_manifest(manifest):
    """True if every manifest file exists and meets min_size; version.py matches."""
    target = manifest.get("version", "")
    if target:
        try:
            import version

            if getattr(version, "VERSION", "") != target:
                _log("verify: version.py=%s want %s" % (getattr(version, "VERSION", "?"), target))
                return False
        except Exception as exc:
            _log("verify: version import failed: %s" % exc)
            return False

    try:
        import os
    except ImportError:
        return False

    for entry in manifest.get("files") or []:
        path = entry.get("path")
        if not path:
            continue
        min_size = entry.get("min_size", 1)
        try:
            st = os.stat(path)
            size = st[6] if len(st) > 6 else st[0]
        except OSError:
            _log("verify: missing %s" % path)
            return False
        if size < min_size:
            _log("verify: %s too small (%d < %d)" % (path, size, min_size))
            return False
    return True


def verify_pending():
    """Check ota_pending.json against on-disk files (no network)."""
    data = _load()
    if not data:
        return True, "no pending"
    paths = data.get("paths") or []
    done = set(data.get("done") or [])
    missing = [p for p in paths if p not in done]
    if missing:
        return False, "incomplete done=%d/%d missing=%s" % (len(done), len(paths), missing[:5])
    try:
        import os
    except ImportError:
        return False, "no os"

    for path in paths:
        try:
            os.stat(path)
        except OSError:
            return False, "missing on disk: %s" % path
    return True, "pending complete"


def complete(target_version):
    _log("OTA complete verified target=%s" % target_version)
    _clear()


def fail(reason):
    _log("OTA incomplete: %s" % reason)
    data = _load()
    if data:
        data["phase"] = "failed"
        data["fail_reason"] = str(reason)[:200]
        _save(data)


def on_boot_check():
    """Call early from main.py — log and leave pending if install was interrupted."""
    ok, detail = verify_pending()
    if not ok:
        _log("boot: prior OTA interrupted (%s)" % detail)
        try:
            import diag_log

            diag_log.upload_event_bounded(
                "boat-p2", "ota_incomplete", detail, max_total_s=15
            )
        except Exception:
            pass
        return False
    data = _load()
    if not data:
        return True
    target = data.get("target_version") or ""
    if target:
        try:
            import version

            if getattr(version, "VERSION", "") == target:
                _log("boot: prior OTA finished; clearing pending")
                _clear()
                return True
        except Exception:
            pass
    if data.get("phase") == "writing":
        _clear()
    return True
