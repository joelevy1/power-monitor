"""
Pure-Python unit test for sheets_log.py's maps_link_url() helper -- no
MicroPython/hardware dependency (sheets_log.py only imports machine/gps/
cellular lazily inside method bodies, specifically so this stays
importable here). Run directly with:

    python3 boat_monitor/test_sheets_log_parser.py
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_log import SheetsLogger, append_wifi_fallback_note, maps_link_url  # noqa: E402


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # A real fix -- both lat/lon present -- should produce a usable,
    # clickable Google Maps URL (7 decimal places, same precision
    # field_console.py's existing "Open in Google Maps" link already uses).
    check(
        "maps_link_url builds a Google Maps URL",
        maps_link_url(31.222388, 121.354)
        == "https://www.google.com/maps?q=31.2223880,121.3540000",
    )

    # Negative lat/lon (Southern/Western hemisphere) shouldn't break the
    # URL format.
    check(
        "maps_link_url handles negative lat/lon",
        maps_link_url(-33.865143, -151.209900) == "https://www.google.com/maps?q=-33.8651430,-151.2099000",
    )

    # No fix yet -- lat and/or lon is None. A blank cell reads far better
    # in the sheet than a broken link with the literal text "None" in it.
    check("maps_link_url blank when lat is None", maps_link_url(None, 121.354) == "")
    check("maps_link_url blank when lon is None", maps_link_url(31.222388, None) == "")
    check("maps_link_url blank when both are None", maps_link_url(None, None) == "")

    report = "reason=timeout ssid=Dock scan=Dock:-82,Boat:missing"
    check(
        "fallback report appends to existing note",
        append_wifi_fallback_note("scheduled", report)
        == "scheduled; wifi_fallback " + report,
    )
    check(
        "fallback report omitted when empty",
        append_wifi_fallback_note("scheduled", "") == "scheduled",
    )
    bounded = append_wifi_fallback_note("x" * 200, "reason=" + ("y" * 200))
    check("fallback note stays bounded", len(bounded) <= 600)
    check("bounded fallback note retains telemetry marker", "wifi_fallback " in bounded)
    check("bounded fallback note retains existing note prefix", bounded.startswith("x"))

    source = (Path(__file__).resolve().parent / "sheets_log.py").read_text(
        encoding="utf-8"
    )
    check(
        "Wi-Fi posts preserve unacknowledged commands",
        '"consume_commands": not bool(self._wifi_ssid)' in source,
    )
    log_method = source.split("def log_power_and_gps(", 1)[1].split(
        "def log_gps_now(", 1
    )[0]
    before_power = log_method.split("last_response = self.log_power(", 1)[0]
    check(
        "critical Power_Log runs before optional OTA backlog",
        "flush_pending" not in before_power,
    )
    check(
        "BLE cellular handoffs suppress optional OTA backlog",
        'note == "ble_log_now"' in log_method
        and "_suppress_optional_ota_flush" in source,
    )
    check(
        "failed Power_Log suppresses optional OTA backlog",
        "self._last_power_success\n                and not getattr("
        in source,
    )

    fake_wifi = types.ModuleType("wifi_uplink")
    fake_wifi.load_networks = lambda: [("Dock", "password")]
    fake_wifi.connect = lambda timeout_s=15: None
    fake_wifi.get_last_connection_report = lambda: "reason=timeout ssid=Dock scan=Dock:-82"

    fake_cellular = types.ModuleType("cellular")

    class FakeCellularError(Exception):
        pass

    class FakeModem:
        def ensure_data(self, registration_timeout_s=60):
            return None

    fake_cellular.CellularError = FakeCellularError
    fake_cellular.Sim7600Modem = FakeModem
    fake_config = types.ModuleType("config")
    fake_config.ALLOW_CELLULAR_WIFI_FALLBACK = True
    fake_diag = types.ModuleType("diag_log")
    fake_diag.log = lambda _message: None
    module_names = ("wifi_uplink", "cellular", "config", "diag_log")
    originals = {name: sys.modules.get(name) for name in module_names}
    try:
        sys.modules["wifi_uplink"] = fake_wifi
        sys.modules["cellular"] = fake_cellular
        sys.modules["config"] = fake_config
        sys.modules["diag_log"] = fake_diag
        logger = SheetsLogger(url="https://example.test/exec")
        logger.ensure_data(registration_timeout_s=1)
        check(
            "successful cellular fallback captures Wi-Fi report",
            logger._wifi_fallback_report == fake_wifi.get_last_connection_report(),
        )

        cellular_only = SheetsLogger(url="https://example.test/exec", prefer_wifi=False)
        cellular_only.ensure_data(registration_timeout_s=1)
        check(
            "cellular-only request has no Wi-Fi fallback report",
            cellular_only._wifi_fallback_report == "",
        )
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
