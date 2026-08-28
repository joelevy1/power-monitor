#!/usr/bin/env python3
"""Host checks for the standby logging/status module split."""

import ast
import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class _Pin:
    IN = 0
    PULL_UP = 1

    def __init__(self, *args, **kwargs):
        pass

    def value(self):
        return 1


machine = types.ModuleType("machine")
machine.Pin = _Pin
machine.I2C = object
machine.reset = lambda: None
sys.modules["machine"] = machine

import boat_status  # noqa: E402
import log_session  # noqa: E402
import apply_recovery_manifest  # noqa: E402


def _inputs(**enabled):
    values = {
        "key": False,
        "switch": False,
        "mid_float": False,
        "aft_float": False,
        "mid_bilge": False,
        "aft_bilge": False,
    }
    values.update(enabled)
    return values


def test_current_mode_priority():
    assert boat_status.current_mode(_inputs()) == "docked_off"
    assert boat_status.current_mode(_inputs(aft_bilge=True)) == "bilge_active"
    assert boat_status.current_mode(_inputs(mid_float=True, aft_bilge=True)) == "float_alert"
    assert (
        boat_status.current_mode(_inputs(switch=True, mid_float=True, aft_bilge=True))
        == "switch_on_key_off"
    )
    assert (
        boat_status.current_mode(
            _inputs(key=True, switch=True, mid_float=True, aft_bilge=True)
        )
        == "key_on"
    )


def test_standby_imports_do_not_load_ble():
    tree = ast.parse((ROOT / "standby_monitor.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert "ble_service" not in imported
    assert "bluetooth" not in imported


def test_ble_wrapper_reexports_and_supplies_handoff():
    bluetooth = types.ModuleType("bluetooth")
    bluetooth.UUID = lambda value: value
    bluetooth.BLE = object
    micropython = types.ModuleType("micropython")
    micropython.const = lambda value: value
    micropython.schedule = lambda fn, arg: fn(arg)
    sys.modules["bluetooth"] = bluetooth
    sys.modules["micropython"] = micropython
    sys.modules["auto_log"] = types.ModuleType("auto_log")
    sys.modules["ble_policy"] = types.ModuleType("ble_policy")

    sys.modules.pop("ble_service", None)
    ble_service = importlib.import_module("ble_service")
    assert ble_service.read_status is boat_status.read_status
    assert ble_service.current_mode is boat_status.current_mode
    assert ble_service.ensure_wifi_off is importlib.import_module(
        "wifi_uplink"
    ).ensure_wifi_off

    captured = {}

    def fake_log(*args, **kwargs):
        captured.update(kwargs)
        return "ok"

    monitor = types.SimpleNamespace()
    ble_service._log_power_and_gps = fake_log
    assert ble_service.log_power_and_gps("test", ble_monitor=monitor) == "ok"
    assert captured["ble_monitor"] is monitor
    assert callable(captured["wifi_handoff"])


def test_log_session_uses_optional_handoff_without_bluetooth():
    calls = []

    class FakeLogger:
        def __init__(self, prefer_wifi, keep_wifi_connected=None):
            calls.append(("logger", prefer_wifi))
            assert keep_wifi_connected is False
            self._last_remote_actions = []

        def log_power_and_gps(self, **kwargs):
            calls.append(("log", kwargs["note"]))
            return "power: ok, gps: ok"

        def close_data(self, mode=None):
            calls.append(("close", mode))

    sheets_log = types.ModuleType("sheets_log")
    sheets_log.SheetsLogger = FakeLogger
    sys.modules["sheets_log"] = sheets_log
    gpio_probe = types.ModuleType("gpio_probe")
    gpio_probe.enrich_note = lambda note, status: note
    sys.modules["gpio_probe"] = gpio_probe
    diag_log = types.ModuleType("diag_log")
    diag_log.log = lambda message: None
    sys.modules["diag_log"] = diag_log
    log_session._wifi_uplink_configured = lambda: True
    log_session.read_status = lambda: {
        "device": "boat-p2",
        "mode": "docked_off",
        "engine": {},
        "house": {},
        "v50": {},
    }
    monitor = types.SimpleNamespace(_cellular_busy=False, connections=set())

    def handoff(fn):
        calls.append(("handoff", None))
        return fn()

    result = log_session.log_power_and_gps(
        "host_test",
        ble_monitor=monitor,
        wifi_handoff=handoff,
        before_network=lambda: calls.append(("release", None)),
    )
    assert result == "power: ok, gps: ok"
    assert calls == [
        ("handoff", None),
        ("logger", True),
        ("release", None),
        ("log", "host_test"),
        ("close", "docked_off"),
    ]
    assert monitor._cellular_busy is False


def test_standby_manifest_mode_is_complete_and_version_last():
    paths = apply_recovery_manifest.STANDBY_WIFI_FIX_PATHS
    assert paths[-1] == "version.py"
    assert set(paths[:-1]) == {
        "boat_status.py",
        "log_session.py",
        "wifi_uplink.py",
        "ble_service.py",
        "standby_monitor.py",
        "main.py",
    }
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "import field_console" not in main_source
    assert "os.remove(\"wifi_mode.txt\")" in main_source
    assert main_source.index("DOCK_LOG_REQUEST_PATH") < main_source.index(
        "import ota_telemetry"
    )
    dock_log = main_source.split("if _dock_log_requested:", 1)[1].split(
        "if _standby_after_log:", 1
    )[0]
    assert main_source.index("_early_os.remove(_request_path)") < main_source.index(
        "_dock_log_once("
    )
    assert "with open(STANDBY_AFTER_LOG_PATH" in dock_log
    assert "_dock_resilience.set_service_hook(_dock_log_deadline)" in dock_log
    assert "periodic_cellular_sync=True" in dock_log
    assert "before_network=_release_ota_tls_reserve" in dock_log
    assert dock_log.index("_dock_wifi.ensure_wifi_off()") < dock_log.index(
        "_dock_machine.reset()"
    )
    standby_after = main_source.split("if _standby_after_log:", 1)[1].split(
        "try:\n    import gc", 1
    )[0]
    assert "_early_standby.main(skip_boot_log=True)" in standby_after
    normal_standby = main_source.split(
        'print("Rebooting into fresh-heap dock log handoff")', 1
    )[1].split("except Exception as exc:", 1)[0]
    assert normal_standby.index("open(DOCK_LOG_REQUEST_PATH") < normal_standby.index(
        "_standby_machine.reset()"
    )
    standby_source = (ROOT / "standby_monitor.py").read_text(encoding="utf-8")
    assert "from log_session import log_power_and_gps" not in standby_source.split(
        "def main(", 1
    )[0]
    due = standby_source.split("and auto_log.should_log_now", 1)[1].split(
        "last_auto_log_mode = mode", 1
    )[0]
    assert due.index("open(DOCK_LOG_REQUEST_PATH") < due.index("machine.reset()")


def main():
    test_current_mode_priority()
    test_standby_imports_do_not_load_ble()
    test_ble_wrapper_reexports_and_supplies_handoff()
    test_log_session_uses_optional_handoff_without_bluetooth()
    test_standby_manifest_mode_is_complete_and_version_last()
    print("standby Wi-Fi refactor tests OK")


if __name__ == "__main__":
    main()
