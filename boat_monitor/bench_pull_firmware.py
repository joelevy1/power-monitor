"""
Pull the full boat-monitor firmware set from GitHub over Wi-Fi (Thonny / bench).

Does not touch secrets.py or wifi_credentials.py. Uses the same pending/verify
logic as ota.update() (ota_state.py): logs when the pull starts, writes
version.py and main.py last, and verifies every manifest file before clearing
ota_pending.json.

Thonny steps:
  1. Stub or rename main.py first (see stop_main.py) so a mid-pull reboot does
     not autorun boot OTA and drop USB.
  2. Pico on marina/home Wi-Fi (or Levy-Guest in wifi_known_networks).
  3. Save THIS file on the Pico as bench_pull_firmware.py
  4. REPL: import bench_pull_firmware; bench_pull_firmware.run(reboot=False)
  5. When it prints Done, soft reboot and run pico_import_check.run()
  6. Restore main.py.autorun for field use.

If import wifi_uplink fails, copy wifi_uplink.py from the PC repo once, then retry.
"""

try:
    import ujson as json
except ImportError:
    import json

import time

MANIFEST_URL = (
    "https://raw.githubusercontent.com/joelevy1/power-monitor/"
    "master/boat_monitor/ota_manifest.json"
)

REQUIRE_VERSION = None

WIFI_CONNECT_TIMEOUT_S = 25

EXTRA_FILES = (
    {
        "path": "ble_policy.py",
        "url": (
            "https://raw.githubusercontent.com/joelevy1/power-monitor/"
            "master/boat_monitor/ble_policy.py"
        ),
        "min_size": 1,
    },
)


class PullError(Exception):
    pass


def _current_version():
    try:
        import version

        return getattr(version, "VERSION", "?")
    except Exception:
        return "?"


def run(reboot=False):
    print("bench_pull_firmware")
    print("Manifest:", MANIFEST_URL)
    print("Current VERSION:", _current_version())

    import wifi_uplink

    ssid = wifi_uplink.connect(timeout_s=WIFI_CONNECT_TIMEOUT_S)
    if not ssid:
        raise PullError(
            "Wi-Fi did not connect — check wifi_known_networks / wifi_credentials"
        )
    print("Wi-Fi:", ssid)

    client = wifi_uplink.WifiHttp()
    try:
        import ota

        manifest_text = ota._http_get_retry(client, MANIFEST_URL)
        manifest = json.loads(manifest_text)
        target = manifest.get("version", "?")
        print("Manifest version:", target)
        if REQUIRE_VERSION and target != REQUIRE_VERSION:
            raise PullError("manifest is %s, required %s" % (target, REQUIRE_VERSION))

        ota.apply_manifest(client, manifest, extra_entries=EXTRA_FILES)
        print("Pull complete. VERSION on disk:", _current_version())
        print("Notes:", manifest.get("notes", ""))
    except ota.OtaError as exc:
        raise PullError(str(exc)) from exc
    finally:
        try:
            wifi_uplink.disconnect()
        except Exception as exc:
            print("disconnect warning:", exc)

    if reboot:
        import machine

        time.sleep(0.5)
        machine.soft_reset()
    else:
        print("Done. Soft reboot recommended: import machine; machine.soft_reset()")


if __name__ == "__main__":
    run()
