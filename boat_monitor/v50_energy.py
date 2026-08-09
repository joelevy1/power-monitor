"""
Track cumulative V50 USB bank discharge (mAh) on the Pico between sheet logs.

Samples on standby heartbeat (~60s) and at each Power_Log POST. Persists to
v50_energy.json. Reset when Config v50_full_at_utc changes (sheet / app).
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

STATE_FILE = "v50_energy.json"


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(a, b):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


def _load():
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("v50_energy: save failed:", exc)


def _state():
    data = _load()
    data.setdefault("mah_since_full", 0.0)
    data.setdefault("capacity_mah", 0)
    data.setdefault("full_anchor_utc", "")
    data.setdefault("last_sample_ms", None)
    data.setdefault("last_a", 0.0)
    return data


def set_capacity_mah(mah):
    data = _state()
    try:
        data["capacity_mah"] = max(0, int(float(mah)))
    except Exception:
        return
    _save(data)


def mark_full_if_anchor(anchor_utc):
    """Reset integrator when sheet/app sets a new v50_full_at_utc."""
    anchor = str(anchor_utc or "").strip()
    if not anchor:
        return
    data = _state()
    if data.get("full_anchor_utc") == anchor:
        return
    data["full_anchor_utc"] = anchor
    data["mah_since_full"] = 0.0
    data["last_sample_ms"] = None
    data["last_a"] = 0.0
    _save(data)
    print("v50_energy: reset at full anchor", anchor)


def reset_full(anchor_utc=""):
    data = _state()
    data["mah_since_full"] = 0.0
    data["last_sample_ms"] = None
    data["last_a"] = 0.0
    if anchor_utc:
        data["full_anchor_utc"] = str(anchor_utc).strip()
    _save(data)


def tick(v50, now_ms=None):
    """Integrate discharge mAh since last sample. v50: {v, a} from read_v50()."""
    if not v50 or not v50.get("ok", True):
        return
    if v50.get("bank_idle"):
        return
    a = v50.get("a")
    if a is None:
        return
    try:
        a = float(a)
    except Exception:
        return

    if now_ms is None:
        now_ms = _ticks_ms()

    data = _state()
    last_ms = data.get("last_sample_ms")
    if last_ms is not None:
        dt_h = _ticks_diff(now_ms, last_ms) / 3600000.0
        if dt_h > 0:
            a_prev = float(data.get("last_a") or 0)
            a_avg = max(0.0, (max(0.0, a_prev) + max(0.0, a)) / 2.0)
            data["mah_since_full"] = float(data.get("mah_since_full") or 0) + a_avg * dt_h * 1000.0

    data["last_sample_ms"] = now_ms
    data["last_a"] = a
    _save(data)


def snapshot():
    """Values for Power_Log / V50_Bank rows."""
    data = _state()
    mah_used = round(float(data.get("mah_since_full") or 0), 2)
    cap = int(data.get("capacity_mah") or 0)
    pct = None
    if cap > 0:
        remaining = max(0.0, cap - mah_used)
        pct = round(min(100.0, max(0.0, (remaining / cap) * 100.0)), 1)
    return {
        "mah_used": mah_used,
        "mah_capacity": cap if cap > 0 else None,
        "pct_remain": pct,
        "full_anchor_utc": data.get("full_anchor_utc") or "",
    }


def apply_config_settings(settings):
    if not settings:
        return
    cap = settings.get("v50_capacity_mah")
    if cap is not None and str(cap).strip() != "":
        set_capacity_mah(cap)
    wh = settings.get("v50_capacity_wh")
    if wh is not None and str(wh).strip() != "" and (cap is None or str(cap).strip() == ""):
        try:
            set_capacity_mah(int(float(wh) * 1000.0 / 5.0))
        except Exception:
            pass
    anchor = settings.get("v50_full_at_utc")
    if anchor is not None and str(anchor).strip():
        mark_full_if_anchor(anchor)
