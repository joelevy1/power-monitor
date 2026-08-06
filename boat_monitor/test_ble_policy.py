#!/usr/bin/env python3
"""Unit tests for ble_policy (host-side; no MicroPython hardware)."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ble_policy", ROOT / "ble_policy.py")
ble_policy = importlib.util.module_from_spec(spec)
# Stub machine/config so import succeeds on PC
sys.modules["machine"] = type(sys)("machine")


class _FakePin:
    IN = 0
    PULL_UP = 1

    def __init__(self, *a, **k):
        pass

    def value(self):
        return 1


sys.modules["machine"].Pin = _FakePin

class _FakeCfg:
    PIN_BATTERY_SWITCH = 20
    PIN_KEY = 21


sys.modules["config"] = _FakeCfg()
ble_policy.cfg = _FakeCfg()
spec.loader.exec_module(ble_policy)


def test_usb_false_without_micropython():
    assert ble_policy.usb_host_connected() is False


def test_ble_wanted_false_without_inputs():
    assert ble_policy.ble_wanted() is False


if __name__ == "__main__":
    test_usb_false_without_micropython()
    test_ble_wanted_false_without_inputs()
    print("ble_policy tests OK")
