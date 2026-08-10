#!/usr/bin/env python3
"""Host-side tests for ota_health (no MicroPython)."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_effective_manifest_profile_micro_after_fails():
    rbc = _load_module("remote_boot_config_test", "remote_boot_config.py")
    saved = {}

    def load():
        return dict(saved)

    def save(data):
        saved.clear()
        saved.update(data)

    rbc.load = load
    rbc.save = save
    ota_config = _load_module("ota_config_test", "ota_config.py")
    sys.modules["remote_boot_config"] = rbc
    sys.modules["ota_config"] = ota_config
    ota_health = _load_module("ota_health_test", "ota_health.py")

    assert ota_health.effective_manifest_profile() == "ram-fix"
    saved["boot_ota_fail_count"] = 2
    assert ota_health.effective_manifest_profile() == "micro"
    saved["ota_manifest_profile"] = "ram-fix"
    assert ota_health.effective_manifest_profile() == "ram-fix"


def test_ota_reboot_blocked():
    rbc = _load_module("remote_boot_config_test2", "remote_boot_config.py")
    saved = {"ota_degraded": True}

    rbc.load = lambda: dict(saved)
    rbc.save = lambda d: saved.update(d)
    sys.modules["remote_boot_config"] = rbc
    ota_health = _load_module("ota_health_test2", "ota_health.py")

    assert ota_health.ota_reboot_blocked() is True
    saved["cmd_ota_force"] = True
    assert ota_health.ota_reboot_blocked() is False


if __name__ == "__main__":
    test_effective_manifest_profile_micro_after_fails()
    test_ota_reboot_blocked()
    print("ota_health tests OK")
