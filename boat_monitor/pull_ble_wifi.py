"""
Pull main + BLE-related modules from GitHub over Wi-Fi (Thonny REPL).

  import pull_ble_wifi
  pull_ble_wifi.run()

Uses branch cursor/ble-connect-stable-5a55 by default (BLE stability + main).
Set BRANCH = "master" for shipped master only.

Does not stub main.py — safe to run from REPL while main is renamed off.
"""

BRANCH = "cursor/ble-connect-stable-5a55"
WIFI_TIMEOUT_S = 25
HTTP_TIMEOUT_S = 90

FILES = (
    "resilience.py",
    "ble_policy.py",
    "ble_service.py",
    "main.py",
)


def _base():
    return (
        "https://raw.githubusercontent.com/joelevy1/power-monitor/"
        "%s/boat_monitor/" % BRANCH
    )


def run(reboot=False, files=None):
    import gc

    gc.collect()
    import wifi_uplink

    names = files or FILES
    ssid = wifi_uplink.connect(timeout_s=WIFI_TIMEOUT_S)
    if not ssid:
        raise OSError("Wi-Fi did not connect")
    print("Wi-Fi:", ssid, "heap", gc.mem_free())

    client = wifi_uplink.WifiHttp()
    try:
        for name in names:
            gc.collect()
            url = _base() + name
            print("GET", name, "heap", gc.mem_free())
            data = client.http_get(url, timeout_s=HTTP_TIMEOUT_S)
            if len(data) < 50:
                raise OSError("%s too small (%d)" % (name, len(data)))
            tmp = name + ".new"
            with open(tmp, "w") as f:
                f.write(data)
            try:
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
            except Exception as exc:
                raise OSError("write %s: %s" % (name, exc)) from exc
            print("  ok", len(data), "bytes")
            data = None
            gc.collect()
    finally:
        try:
            wifi_uplink.disconnect()
        except Exception:
            pass
        gc.collect()

    import sys

    for mod in ("ble_policy", "ble_service", "resilience", "main"):
        sys.modules.pop(mod, None)

    import ble_policy

    print("ble_latched()", ble_policy.ble_latched())
    print("Done. Soft reboot recommended.")
    if reboot:
        import machine

        machine.soft_reset()


if __name__ == "__main__":
    run()
