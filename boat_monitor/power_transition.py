"""
Detect a major power-rail change (V50 bank -> boat house feed) and reboot once.

A full reset clears RAM fragmentation after long standby ENOMEM loops. Only
runs in standby when switch/key are still off (docked_off).
"""

_last_sig = None
_last_reboot_ms = None

# At least 5 minutes between power-transition reboots.
MIN_GAP_MS = 300000


def _v(metric):
    if not metric or not isinstance(metric, dict):
        return 0.0
    try:
        return float(metric.get("v") or 0)
    except Exception:
        return 0.0


def maybe_reboot_on_power_transition(status, mode):
    global _last_sig, _last_reboot_ms
    if mode != "docked_off":
        return False

    v50_v = _v(status.get("v50"))
    house_v = _v(status.get("house"))
    sig = (round(v50_v, 1), round(house_v, 1))

    try:
        import time

        now = time.ticks_ms()
    except Exception:
        return False

    if _last_sig is None:
        _last_sig = sig
        return False

    prev_v50, prev_house = _last_sig
    _last_sig = sig

    # Typical: on USB bank V50 ~4.5–5.2 V, house ~0. Boat feed: house >= 11 V.
    bank_like = prev_v50 > 3.5 and prev_v50 < 6.5 and prev_house < 2.0
    boat_house = house_v >= 11.0 and v50_v < 6.5

    if not (bank_like and boat_house):
        return False

    if _last_reboot_ms is not None:
        try:
            import time

            if time.ticks_diff(now, _last_reboot_ms) < MIN_GAP_MS:
                return False
        except Exception:
            pass

    try:
        import diag_log

        diag_log.log(
            "power transition reboot v50 %.2f->%.2f house %.2f->%.2f"
            % (prev_v50, v50_v, prev_house, house_v)
        )
    except Exception:
        pass

    _last_reboot_ms = now
    import machine

    time.sleep(0.3)
    machine.reset()
    return True
