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
    import config as cfg
except ImportError:
    cfg = None


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
    inputs = read_switch_key()
    return inputs["switch"] or inputs["key"]


def wait_for_ble_wanted(timeout_s=3.0, poll_s=0.2):
    """Deprecated wait for USB CDC; kept for API compatibility — switch/key only."""
    import time

    deadline = time.ticks_add(time.ticks_ms(), int(timeout_s * 1000))
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if ble_wanted():
            return True
        time.sleep(poll_s)
    return ble_wanted()
