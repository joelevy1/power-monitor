#!/usr/bin/env python3
"""Host tests for persistent dock Wi-Fi policy and radio lifecycle."""

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import remote_boot_config
import sheets_log
import wifi_uplink


class FakeWlan:
    def __init__(self, connected=True, status=3, ip="192.0.2.10"):
        self.enabled = connected
        self.connected = connected
        self.state = status
        self.ip = ip
        self.connect_calls = []
        self.disconnect_calls = 0
        self.deinit_calls = 0
        self.config_calls = []

    def active(self, value=None):
        if value is not None:
            self.enabled = bool(value)
        return self.enabled

    def isconnected(self):
        return self.connected

    def status(self, *args):
        if args and args[0] == "rssi":
            return -47
        if args and args[0] == "ssid":
            return "DockNet"
        return self.state

    def ifconfig(self):
        return (self.ip, "255.255.255.0", "192.0.2.1", "192.0.2.1")

    def config(self, *args, **kwargs):
        if args and args[0] == "ssid":
            return "DockNet"
        self.config_calls.append(kwargs)

    def scan(self):
        return [(b"DockNet", b"not-reported", 1, -47, 3, 0)]

    def connect(self, ssid, password):
        self.connect_calls.append((ssid, password))
        self.connected = True
        self.state = 3
        self.ip = "192.0.2.10"

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False

    def deinit(self):
        self.deinit_calls += 1
        self.enabled = False


def test_remote_policy():
    original_path = remote_boot_config.PATH
    with tempfile.TemporaryDirectory() as tmp:
        remote_boot_config.PATH = str(Path(tmp) / "remote_boot_config.json")
        try:
            remote_boot_config.save({"dock_mode": "home"})
            assert remote_boot_config.effective_keep_wifi_connected_docked(
                "docked_off"
            )
            assert not remote_boot_config.effective_keep_wifi_connected_docked(
                "key_on"
            )
            applied = remote_boot_config.apply_settings(
                {"keep_wifi_connected_docked": "0"}
            )
            assert "keep_wifi_connected_docked=0" in applied
            assert not remote_boot_config.effective_keep_wifi_connected_docked(
                "docked_off"
            )
            remote_boot_config.apply_settings(
                {"keep_wifi_connected_docked": "yes"}
            )
            assert remote_boot_config.effective_keep_wifi_connected_docked(
                "bilge_active"
            )
        finally:
            remote_boot_config.PATH = original_path


def test_reuse_and_stale_reset():
    original_wlan = wifi_uplink._wlan
    original_load = wifi_uplink._load_networks
    original_sleep = wifi_uplink._sleep_with_watchdog
    try:
        wifi_uplink._load_networks = lambda: [("DockNet", "secret")]
        wifi_uplink._sleep_with_watchdog = lambda _seconds: None

        healthy = FakeWlan()
        wifi_uplink._wlan = lambda: healthy
        assert wifi_uplink.connect() == "DockNet"
        assert healthy.connect_calls == []
        report = wifi_uplink.get_last_connection_report()
        assert "outcome=reused" in report and "rssi=-47" in report
        assert "secret" not in report

        stale = FakeWlan(status=-3, ip="0.0.0.0")
        wifi_uplink._wlan = lambda: stale
        assert wifi_uplink.connect(timeout_s=1) == "DockNet"
        assert stale.disconnect_calls >= 1
        assert stale.deinit_calls == 0
        assert len(stale.connect_calls) == 1
        assert "path=fresh" in wifi_uplink.get_last_connection_report()
    finally:
        wifi_uplink._wlan = original_wlan
        wifi_uplink._load_networks = original_load
        wifi_uplink._sleep_with_watchdog = original_sleep


def test_sheets_close_persistence():
    calls = []
    fake_wifi = types.ModuleType("wifi_uplink")
    fake_wifi.disconnect = lambda: calls.append("disconnect")
    fake_wifi.set_request_power_mode = lambda idle=False: (
        calls.append(("pm", idle)) or "powersave"
    )
    fake_rbc = types.ModuleType("remote_boot_config")
    fake_rbc.effective_keep_wifi_connected_docked = (
        lambda mode: mode == "docked_off"
    )
    fake_flush = types.ModuleType("ota_events_flush")
    fake_flush.flush_ota_events = lambda *args, **kwargs: None
    fake_reboot = types.ModuleType("ota_reboot")
    fake_reboot.reboot_if_upgrade_pending = lambda **kwargs: None
    original_modules = {
        name: sys.modules.get(name)
        for name in (
            "wifi_uplink",
            "remote_boot_config",
            "ota_events_flush",
            "ota_reboot",
        )
    }
    try:
        sys.modules["wifi_uplink"] = fake_wifi
        sys.modules["remote_boot_config"] = fake_rbc
        sys.modules["ota_events_flush"] = fake_flush
        sys.modules["ota_reboot"] = fake_reboot

        logger = sheets_log.SheetsLogger(url="https://example.test")
        logger._wifi_ssid = "DockNet"
        logger._data_open = True
        logger.close_data(mode="docked_off")
        assert calls == [("pm", True)]

        calls[:] = []
        logger = sheets_log.SheetsLogger(url="https://example.test")
        logger._wifi_ssid = "DockNet"
        logger.close_data(mode=None)
        assert calls == ["disconnect"]

        calls[:] = []
        logger = sheets_log.SheetsLogger(
            url="https://example.test", keep_wifi_connected=True
        )
        logger._wifi_ssid = "DockNet"
        logger.close_data(mode=None)
        assert calls == [("pm", True)]
    finally:
        for name, module in original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_cellular_policy_disconnects_persistent_wifi():
    calls = []
    fake_wifi = types.ModuleType("wifi_uplink")
    fake_wifi.disconnect = lambda: calls.append("wifi_off")
    fake_cell = types.ModuleType("cellular")

    class CellularError(Exception):
        pass

    class Modem:
        def ensure_data(self, registration_timeout_s=60):
            calls.append(("cellular", registration_timeout_s))

    fake_cell.CellularError = CellularError
    fake_cell.Sim7600Modem = Modem
    originals = {
        "wifi_uplink": sys.modules.get("wifi_uplink"),
        "cellular": sys.modules.get("cellular"),
    }
    try:
        sys.modules["wifi_uplink"] = fake_wifi
        sys.modules["cellular"] = fake_cell
        logger = sheets_log.SheetsLogger(
            url="https://example.test", prefer_wifi=False
        )
        logger.ensure_data(registration_timeout_s=12)
        assert calls[:2] == ["wifi_off", ("cellular", 12)]
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_ble_shutdown_deactivates_without_cyw43_deinit():
    sta = FakeWlan()
    ap = FakeWlan()
    network = types.ModuleType("network")
    network.STA_IF = 0
    network.AP_IF = 1
    network.WLAN = lambda iface: sta if iface == network.STA_IF else ap
    original = sys.modules.get("network")
    original_time = wifi_uplink.time
    try:
        sys.modules["network"] = network
        wifi_uplink.time = types.SimpleNamespace(sleep_ms=lambda _ms: None)
        wifi_uplink.ensure_wifi_off()
        for wlan in (sta, ap):
            assert wlan.enabled is False
            assert wlan.deinit_calls == 0
        assert sta.disconnect_calls == 1
    finally:
        wifi_uplink.time = original_time
        if original is None:
            sys.modules.pop("network", None)
        else:
            sys.modules["network"] = original


def test_standby_tears_down_wifi_before_ble_reset():
    source = (ROOT / "standby_monitor.py").read_text(encoding="utf-8")
    loop = source.split("while True:", 1)[1]
    branch = loop.split("if ble_policy.ble_wanted():", 1)[1].split(
        "status = read_status()", 1
    )[0]
    assert "wifi_uplink.ensure_wifi_off()" in branch
    assert branch.index("wifi_uplink.ensure_wifi_off()") < branch.index("machine.reset()")


def test_standby_arms_switch_irq_before_blocking_boot_log():
    source = (ROOT / "standby_monitor.py").read_text(encoding="utf-8")
    main = source.split("def main(", 1)[1]
    assert main.index("_arm_ble_transition_irq()") < main.index(
        "if not skip_boot_log and _boot_log_wanted():"
    )
    irq = source.split("def _arm_ble_transition_irq():", 1)[1].split(
        "def _standby_prefer_wifi():", 1
    )[0]
    assert "machine.Pin.IRQ_FALLING" in irq
    assert "_micropython.schedule(_transition_to_ble, 0)" in source
    transition = source.split("def _transition_to_ble", 1)[1].split(
        "def _ble_input_irq", 1
    )[0]
    assert transition.index("wifi_uplink.ensure_wifi_off()") < transition.index(
        "machine.reset()"
    )


def test_ble_deactivates_shared_radio_before_standby_reset():
    source = (ROOT / "ble_service.py").read_text(encoding="utf-8")
    shutdown = source.split("def _shutdown_ble_for_standby", 1)[1].split(
        "def update_status", 1
    )[0]
    assert "self.ble.gap_advertise(None)" in shutdown
    assert "self.ble.gap_disconnect(conn)" in shutdown
    assert "self.ble.active(False)" in shutdown
    loop = source.split("def run(self):", 1)[1].split("def main():", 1)[0]
    assert loop.index("self._shutdown_ble_for_standby()") < loop.index(
        "machine.reset()"
    )


def main():
    test_remote_policy()
    test_reuse_and_stale_reset()
    test_sheets_close_persistence()
    test_cellular_policy_disconnects_persistent_wifi()
    test_ble_shutdown_deactivates_without_cyw43_deinit()
    test_standby_tears_down_wifi_before_ble_reset()
    test_standby_arms_switch_irq_before_blocking_boot_log()
    test_ble_deactivates_shared_radio_before_standby_reset()
    print("persistent dock Wi-Fi tests OK")


if __name__ == "__main__":
    original_cwd = os.getcwd()
    try:
        main()
    finally:
        os.chdir(original_cwd)
