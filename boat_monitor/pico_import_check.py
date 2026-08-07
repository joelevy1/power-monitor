"""Run on the Pico in Thonny to find which module fails to import."""

MODULES = (
    "version",
    "ota",
    "ota_config",
    # Do not import main here — main.py runs boot OTA on import (reboots / drops USB).
    "resilience",
    "diag_log",
    "secrets",
    "wifi_networks",
    "wifi_uplink",
    "cellular",
    "v50_energy",
    "remote_control",
    "sheets_log",
    "ble_service",
    "standby_monitor",
    "auto_log",
)


def run():
    for name in MODULES:
        try:
            __import__(name)
            print("OK", name)
        except SyntaxError as exc:
            print("SYNTAX", name, exc)
        except Exception as exc:
            print("FAIL", name, type(exc).__name__, exc)


if __name__ == "__main__":
    run()
