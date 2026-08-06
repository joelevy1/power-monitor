"""
When the Boat Monitor should run BLE (phone app) vs standby-only (logging, no radio).

BLE is enabled only when someone might use the app:
  - Master battery switch ON, or
  - Ignition key ON, or
  - Pico micro-USB connected to a PC host (USB serial / CDC active)

Otherwise standby_monitor.py runs with BLE off for lower power and simpler Wi-Fi uplink.
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
    inputs = read_switch_key()
    if inputs["switch"] or inputs["key"]:
        return True
    return usb_host_connected()
