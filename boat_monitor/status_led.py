"""
Onboard RGB status (active HIGH — see config PIN_LED_*).

At-a-glance patterns (R / G / B):
  boot     — off / off / fast blink   (~4 Hz blue)
  ota      — off / off / faster blink (~8 Hz blue)
  ble      — off / solid on / off     (advertising, no phone)
  ble_link — off / slow blink / off   (~1 Hz green, phone connected)
  standby  — off / off / slow blink  (~0.5 Hz blue, auto-log idle)
  cellular — fast blink / (base) / off  (red ~5 Hz while modem HTTP active)
  fault    — solid on / off / fast blink (stuck OTA / repeated reboot)

Call tick() from main loops; set_mode() on mode changes; wrap uplink with
cellular_active(True/False).
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import config as cfg
except ImportError:
    cfg = None

_mode = "off"
_cellular_overlay = False
_pins = None
_last_toggle_ms = 0
_phase_on = False


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _init():
    global _pins
    if _pins is not None:
        return _pins
    if cfg is None:
        return None
    try:
        from machine import Pin

        _pins = {
            "r": Pin(cfg.PIN_LED_RED, Pin.OUT, value=0),
            "g": Pin(cfg.PIN_LED_GREEN, Pin.OUT, value=0),
            "b": Pin(cfg.PIN_LED_BLUE, Pin.OUT, value=0),
        }
    except Exception:
        _pins = None
    return _pins


def _write(r, g, b):
    pins = _init()
    if not pins:
        return
    try:
        pins["r"].value(1 if r else 0)
        pins["g"].value(1 if g else 0)
        pins["b"].value(1 if b else 0)
    except Exception:
        pass


def set_mode(mode):
    global _mode, _last_toggle_ms, _phase_on
    _mode = str(mode or "off")
    _last_toggle_ms = _ticks_ms()
    _phase_on = False
    if _mode == "ble":
        _write(0, 1, 0)
    elif _mode == "off":
        _write(0, 0, 0)


def set_cellular_active(active):
    global _cellular_overlay
    _cellular_overlay = bool(active)
    if not active and _mode == "ble":
        _write(0, 1, 0)


def cellular_active(active):
    """Context manager helper for sheets_log ensure/close."""
    set_cellular_active(active)


def _blink(period_ms, r=0, g=0, b=0):
    global _last_toggle_ms, _phase_on
    now = _ticks_ms()
    try:
        elapsed = time.ticks_diff(now, _last_toggle_ms)
    except AttributeError:
        elapsed = now - _last_toggle_ms
    if elapsed >= period_ms:
        _last_toggle_ms = now
        _phase_on = not _phase_on
    if _phase_on:
        _write(r, g, b)
    else:
        _write(0, 0, 0)


def tick():
    if _cellular_overlay:
        _blink(100, r=1, g=0, b=0)
        return
    mode = _mode
    if mode == "off":
        _write(0, 0, 0)
    elif mode == "boot":
        _blink(125, b=1)
    elif mode == "ota":
        _blink(62, b=1)
    elif mode == "ble":
        _write(0, 1, 0)
    elif mode == "ble_link":
        _blink(500, g=1)
    elif mode == "standby":
        _blink(1000, b=1)
    elif mode == "fault":
        global _last_toggle_ms, _phase_on
        now = _ticks_ms()
        try:
            elapsed = time.ticks_diff(now, _last_toggle_ms)
        except AttributeError:
            elapsed = now - _last_toggle_ms
        if elapsed >= 125:
            _last_toggle_ms = now
            _phase_on = not _phase_on
        _write(1, 0, 1 if _phase_on else 0)
    else:
        _write(0, 0, 0)
