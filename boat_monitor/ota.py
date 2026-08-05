"""
Boat Monitor P2 - manifest-driven OTA updater. Prefers Wi-Fi (wifi_uplink.py)
over the cellular SIM7600 modem (cellular.py) when a known network is
configured and reachable -- no cellular data usage, no modem needed, and
much faster. Falls back to cellular automatically if Wi-Fi isn't configured
or fails to connect.

Run manually from the Pico:

    import ota
    ota.update()

Safe to prefer Wi-Fi here specifically because main.py runs this OTA check
BEFORE BLE ever starts -- Wi-Fi and BLE share one radio on the Pico W and
cannot run at the same time (see ensure_wifi_off() in ble_service.py). Do
not call ota.update()/check() while BLE is active.

The updater downloads ota_manifest.json, then fetches each listed file from
GitHub raw URLs. Files are written as .new first, then the previous copy is
kept as .bak where possible.
"""

import time

try:
    import ujson as json
except ImportError:
    import json

import ota_config


class OtaError(Exception):
    pass


def current_version():
    try:
        import version

        return getattr(version, "VERSION", "unknown")
    except Exception:
        return "unknown"


def load_manifest(client):
    data = client.http_get(ota_config.OTA_MANIFEST_URL)
    return json.loads(data)


def write_file(path, data):
    tmp_path = path + ".new"
    bak_path = path + ".bak"

    print("Writing", tmp_path)
    with open(tmp_path, "w") as f:
        f.write(data)

    try:
        # Remove stale backup before replacing current file.
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
        raise OtaError("failed replacing %s: %s" % (path, exc))


def apply_manifest(client, manifest):
    files = manifest.get("files", [])
    if not files:
        raise OtaError("manifest has no files")

    for entry in files:
        path = entry["path"]
        url = entry["url"]
        min_size = entry.get("min_size", 1)

        print("Updating", path)
        data = client.http_get(url)
        if len(data) < min_size:
            raise OtaError("%s was too small (%d bytes)" % (path, len(data)))
        write_file(path, data)


def _get_client(reset_modem=False, prefer_wifi=True):
    """Prefer Wi-Fi over cellular when prefer_wifi is True -- see module
    docstring for why this is only safe when BLE is NOT active (e.g. the
    boot-time OTA check). Callers that can run while BLE is connected --
    e.g. the "ota" BLE command in ble_service.py -- MUST pass
    prefer_wifi=False so this never touches the Wi-Fi radio and only uses
    the cellular modem (separate UART hardware, no conflict with BLE).

    Returns (client, used_wifi); used_wifi tells the caller which teardown
    to run.
    """
    if prefer_wifi:
        try:
            import wifi_uplink

            ssid = wifi_uplink.connect(timeout_s=15)
            if ssid:
                print("OTA: using Wi-Fi (%s)" % ssid)
                return wifi_uplink.WifiHttp(), True
        except Exception as exc:
            print("OTA: Wi-Fi attempt failed, falling back to cellular:", exc)

    print("OTA: using cellular")
    from cellular import Sim7600Modem

    client = Sim7600Modem()
    client.ensure_data(reset_modem=reset_modem)
    return client, False


def _close_client(client, used_wifi):
    if used_wifi:
        try:
            import wifi_uplink

            wifi_uplink.disconnect()
        except Exception as exc:
            print("OTA: wifi_uplink.disconnect() warning:", exc)
        return

    client.close_data()  # cellular.py handles HTTPTERM/NETCLOSE (Phase 2.4 discipline)


def update(reset_modem=False, reboot=False, prefer_wifi=True):
    print("Boat Monitor OTA update")
    print("Current version:", current_version())
    print("Manifest:", ota_config.OTA_MANIFEST_URL)

    client, used_wifi = _get_client(reset_modem, prefer_wifi=prefer_wifi)
    try:
        manifest = load_manifest(client)
        target_version = manifest.get("version", "unknown")
        print("Target version:", target_version)

        if target_version == current_version():
            print("Already at target version.")
            return False

        apply_manifest(client, manifest)
        print("Update complete.")
        print("Reboot required to run new files.")

        if reboot:
            import machine

            time.sleep(1)
            machine.reset()

        return True
    finally:
        _close_client(client, used_wifi)


def check(prefer_wifi=True):
    client, used_wifi = _get_client(prefer_wifi=prefer_wifi)
    try:
        manifest = load_manifest(client)
        print("Current:", current_version())
        print("Available:", manifest.get("version", "unknown"))
        print("Notes:", manifest.get("notes", ""))
        return manifest
    finally:
        _close_client(client, used_wifi)
