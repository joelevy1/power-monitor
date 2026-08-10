"""Free flash before USB recovery (run on Pico via mpremote run)."""

import gc
import os


def _try_remove(path):
    try:
        os.remove(path)
        print("removed", path)
        return True
    except Exception as exc:
        print("skip", path, exc)
        return False


def _free_suffixes():
    try:
        names = os.listdir()
    except Exception as exc:
        print("listdir failed:", exc)
        return 0
    freed = 0
    for name in names:
        if name.endswith((".bak", ".new")):
            if _try_remove(name):
                freed += 1
    for name in names:
        low = name.lower()
        if low.endswith(".bmota") or low.startswith("ota_release"):
            if _try_remove(name):
                freed += 1
    for log_name in ("boat_diag.log", "diag.log", "ota_events_queue.json"):
        if log_name in names:
            try:
                st = os.stat(log_name)
                if st[6] > 8000:
                    _try_remove(log_name)
                    freed += 1
            except Exception:
                pass
    gc.collect()
    try:
        import micropython

        micropython.mem_info()
    except Exception:
        pass
    try:
        stat = os.statvfs("/")
        print("fs_free_b", stat[0] * stat[3])
    except Exception as exc:
        print("statvfs:", exc)
    print("cleanup_done removed=%s" % freed)
    return freed


if __name__ == "__main__":
    _free_suffixes()
