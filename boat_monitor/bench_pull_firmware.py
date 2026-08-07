"""
Pull the full boat-monitor firmware set from GitHub over Wi-Fi (Thonny / bench).

Stable target is whatever version is in ota_manifest.json on the master branch
(currently 1.1.39). Does not touch secrets.py or wifi_credentials.py.

Thonny steps:
  1. Pico on marina/home Wi-Fi (or run from boat with Levy-Guest in wifi_known_networks).
  2. Save THIS file on the Pico as bench_pull_firmware.py
  3. Run: import bench_pull_firmware; bench_pull_firmware.run()
  4. When it prints Done, soft reboot: import machine; machine.soft_reset()
  5. Verify: import version; print(version.VERSION)
  6. Unplug USB and let main.py run on boat power.

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

# Optional: pin a version string; pull aborts if manifest version does not match.
REQUIRE_VERSION = None  # e.g. "1.1.39" or None to accept manifest as-is

WIFI_CONNECT_TIMEOUT_S = 25
HTTP_TIMEOUT_S = 45
GET_ATTEMPTS = 3

# Shipped in manifest for OTA but easy to miss on hand installs — always pull too.
EXTRA_FILES = (
    (
        "ble_policy.py",
        "https://raw.githubusercontent.com/joelevy1/power-monitor/"
        "master/boat_monitor/ble_policy.py",
    ),
)


class PullError(Exception):
    pass


def _http_get(client, url):
    last = None
    for attempt in range(1, GET_ATTEMPTS + 1):
        try:
            try:
                return client.http_get(url, timeout_s=HTTP_TIMEOUT_S)
            except TypeError:
                return client.http_get(url)
        except Exception as exc:
            last = exc
            print("GET %d/%d failed: %s" % (attempt, GET_ATTEMPTS, exc))
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            if attempt < GET_ATTEMPTS:
                time.sleep(1.5)
    raise PullError(str(last))


def _write_file(path, data):
    tmp_path = path + ".new"
    bak_path = path + ".bak"
    print("Writing", path, "(%d bytes)" % len(data))
    with open(tmp_path, "w") as f:
        f.write(data)
    try:
        import os

        try:
            os.remove(bak_path)
        except OSError:
            pass
        try:
            os.rename(path, bak_path)
        except OSError:
            pass
        os.rename(tmp_path, path)
    except Exception as exc:
        raise PullError("replace %s: %s" % (path, exc))


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
        raise PullError("Wi-Fi did not connect — check wifi_known_networks / wifi_credentials")
    print("Wi-Fi:", ssid)

    client = wifi_uplink.WifiHttp()
    try:
        manifest_text = _http_get(client, MANIFEST_URL)
        manifest = json.loads(manifest_text)
        target = manifest.get("version", "?")
        print("Manifest version:", target)
        if REQUIRE_VERSION and target != REQUIRE_VERSION:
            raise PullError("manifest is %s, required %s" % (target, REQUIRE_VERSION))

        files = list(manifest.get("files") or [])
        for path, url in EXTRA_FILES:
            files.append({"path": path, "url": url})

        for entry in files:
            path = entry["path"]
            url = entry["url"]
            min_size = entry.get("min_size", 1)
            data = _http_get(client, url)
            if len(data) < min_size:
                raise PullError("%s too small (%d bytes)" % (path, len(data)))
            _write_file(path, data)

        print("Pull complete. VERSION on disk:", _current_version())
        print("Notes:", manifest.get("notes", ""))
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
