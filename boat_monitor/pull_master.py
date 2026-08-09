"""
Download the shipped BLE stack from GitHub master (Thonny REPL >>> only).

  import pull_master
  pull_master.run()

Pulls: version.py, resilience.py, ble_policy.py, ble_service.py, main.py

If wifi_uplink on the Pico is old (no download_to_file), this script updates
wifi_uplink.py first so ble_service.py can stream without MemoryError.

Rename main.py to main.py.off before running if you want to stay in REPL.
Does not touch secrets.py or wifi_credentials.py.
"""

BRANCH = "master"
WIFI_TIMEOUT_S = 25
HTTP_TIMEOUT_S = 90

FILES = (
    "version.py",
    "resilience.py",
    "ble_policy.py",
    "ble_service.py",
    "main.py",
)

STREAM_FILES = frozenset(("ble_service.py", "wifi_uplink.py"))


def _base():
    return (
        "https://raw.githubusercontent.com/joelevy1/power-monitor/"
        "%s/boat_monitor/" % BRANCH
    )


def _install_bytes(name, data):
    if len(data) < 50:
        raise OSError("%s too small (%d)" % (name, len(data)))
    tmp = name + ".new"
    with open(tmp, "w") as f:
        f.write(data)
    import os

    try:
        os.remove(name + ".bak")
    except OSError:
        pass
    try:
        os.rename(name, name + ".bak")
    except OSError:
        pass
    os.rename(tmp, name)


def _fetch_http(client, name):
    url = _base() + name
    print("GET", name)
    data = client.http_get(url, timeout_s=HTTP_TIMEOUT_S)
    _install_bytes(name, data)
    print("  ok", len(data), "bytes")
    return data


def _fetch_stream(client, name):
    url = _base() + name
    print("GET", name, "(stream)")
    nbytes = client.download_to_file(url, name, timeout_s=HTTP_TIMEOUT_S)
    print("  ok", nbytes, "bytes")
    return nbytes


def _ensure_stream_client(client):
    if hasattr(client, "download_to_file"):
        return client
    print("Updating wifi_uplink.py (needed to stream ble_service.py)")
    _fetch_http(client, "wifi_uplink.py")
    import sys

    sys.modules.pop("wifi_uplink", None)
    import wifi_uplink

    return wifi_uplink.WifiHttp()


def run(reboot=False, files=None):
    import gc

    gc.collect()
    import wifi_uplink

    names = files or FILES
    ssid = wifi_uplink.connect(timeout_s=WIFI_TIMEOUT_S)
    if not ssid:
        raise OSError("Wi-Fi did not connect")
    print("Wi-Fi:", ssid, "branch", BRANCH, "heap", gc.mem_free())

    client = wifi_uplink.WifiHttp()
    try:
        client = _ensure_stream_client(client)
        for name in names:
            gc.collect()
            print("heap", gc.mem_free(), end=" ")
            if name in STREAM_FILES and hasattr(client, "download_to_file"):
                _fetch_stream(client, name)
            else:
                _fetch_http(client, name)
                data = None
            gc.collect()
    finally:
        try:
            wifi_uplink.disconnect()
        except Exception:
            pass
        gc.collect()

    import sys

    for mod in ("version", "ble_policy", "ble_service", "resilience", "main"):
        sys.modules.pop(mod, None)

    import version

    print("VERSION", getattr(version, "VERSION", "?"))
    try:
        with open("ble_service.py") as f:
            has_fix = "_scheduled_on_connect" in f.read()
    except OSError:
        has_fix = False
    print("ble_service fix present:", has_fix)
    print("Done. Soft reboot recommended.")
    if reboot:
        import machine

        machine.soft_reset()


if __name__ == "__main__":
    run()
