"""
When the Boat Monitor should run BLE (phone app) vs standby-only (logging, no radio).

BLE is enabled when someone might use the app at the boat:
  - Master battery switch ON, or
  - Ignition key ON

USB micro-USB to a PC (Thonny, serial console) does **not** force BLE — standby
still runs so boot OTA and Wi-Fi auto-log work on the bench with the cable
plugged in. Use switch/key on when you need the phone app.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import config as cfg
except ImportError:
    cfg = None

_BLE_LATCH_PATH = "ble_latch.json"
_DEFAULT_GPIO_OFF_HOLD_S = 30
_gpio_off_hold_s = None
_ble_latch = False


def _load_latch_file():
    global _ble_latch, _gpio_off_hold_s
    try:
        with open(_BLE_LATCH_PATH, "r") as f:
            data = json.load(f)
    except Exception:
        return
    if data.get("latch"):
        _ble_latch = True
    if data.get("gpio_off_hold_s") is not None:
        _gpio_off_hold_s = max(10, int(data["gpio_off_hold_s"]))


def _save_latch_file():
    try:
        data = {}
        if _ble_latch:
            data["latch"] = True
        if _gpio_off_hold_s is not None:
            data["gpio_off_hold_s"] = _gpio_off_hold_s
        if not data:
            return
        with open(_BLE_LATCH_PATH, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("ble_policy: latch save failed:", exc)


_load_latch_file()


def _input_on(gpio):
    from machine import Pin

    return Pin(gpio, Pin.IN, Pin.PULL_UP).value() == 0


def read_switch_key():
    if cfg is None:
        return {"switch": False, "key": False}
    return {
        "switch": _input_on(cfg.PIN_BATTERY_SWITCH),
        "key": _input_on(cfg.PIN_KEY),
    }


def ble_inputs_on():
    inputs = read_switch_key()
    return inputs["switch"] or inputs["key"]


def set_ble_latch(enabled=True):
    """Keep BLE mode even if GPIO reads OFF (field debug); persisted across reboot."""
    global _ble_latch
    _ble_latch = bool(enabled)
    _save_latch_file()


def set_gpio_off_hold_s(seconds):
    """Seconds GPIO must read OFF before ble_service reboots to standby."""
    global _gpio_off_hold_s
    _gpio_off_hold_s = max(10, int(seconds))
    _save_latch_file()


def gpio_off_hold_s():
    if _gpio_off_hold_s is not None:
        return _gpio_off_hold_s
    return _DEFAULT_GPIO_OFF_HOLD_S


def ble_latched():
    return bool(_ble_latch)


def usb_host_connected():
    """True when a PC has the Pico's USB CDC console open (Thonny, rshell, etc.)."""
    try:
        import usb_cdc

        console = usb_cdc.console
        if console is not None and console.connected():
            return True
        data = getattr(usb_cdc, "data", None)
        if data is not None and data.connected():
            return True
    except Exception:
        pass
    return False


def ble_wanted():
    """Start ble_service.main() instead of standby_monitor (switch/key only)."""
    if _ble_latch:
        return True
    return ble_inputs_on()


def wait_for_ble_wanted(timeout_s=3.0, poll_s=0.2):
    """Deprecated wait for USB CDC; kept for API compatibility — switch/key only."""
    import time

    deadline = time.ticks_add(time.ticks_ms(), int(timeout_s * 1000))
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if ble_wanted():
            return True
        time.sleep(poll_s)
    return ble_wanted()
