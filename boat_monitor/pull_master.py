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


def _parse_url(url):
    if url.startswith("https://"):
        is_https = True
        rest = url[8:]
        default_port = 443
    elif url.startswith("http://"):
        is_https = False
        rest = url[7:]
        default_port = 80
    else:
        raise ValueError("bad url")
    if "/" in rest:
        host_port, path = rest.split("/", 1)
        path = "/" + path
    else:
        host_port, path = rest, "/"
    if ":" in host_port:
        host, port_s = host_port.split(":", 1)
        port = int(port_s)
    else:
        host, port = host_port, default_port
    return host, port, path, is_https


def _raw_https_to_file(url, dest_path, timeout_s=90):
    """Bootstrap download when wifi_uplink has no WifiHttp (streams to disk)."""
    import os
    import socket

    host, port, req_path, is_https = _parse_url(url)
    addr = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout_s)
    try:
        sock.connect(addr)
        if is_https:
            try:
                import ussl as ssl
            except ImportError:
                import ssl
            try:
                sock = ssl.wrap_socket(sock, server_hostname=host)
            except TypeError:
                sock = ssl.wrap_socket(sock)
        req = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
            % (req_path, host)
        )
        sock.write(req.encode())
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(256)
            if not chunk:
                raise OSError("no headers")
            header += chunk
        end = header.find(b"\r\n\r\n")
        status_line = header[: end].split(b"\r\n", 1)[0]
        status = int(status_line.split(b" ")[1])
        if status != 200:
            raise OSError("HTTP %s" % status)
        body = header[end + 4 :]
        tmp = dest_path + ".new"
        with open(tmp, "w") as out:
            if body:
                out.write(body.decode("utf-8", "ignore"))
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                out.write(chunk.decode("utf-8", "ignore"))
        try:
            os.remove(dest_path + ".bak")
        except OSError:
            pass
        try:
            os.rename(dest_path, dest_path + ".bak")
        except OSError:
            pass
        os.rename(tmp, dest_path)
        return os.stat(dest_path)[6]
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _ensure_http_client():
    import sys

    sys.modules.pop("wifi_uplink", None)
    import wifi_uplink

    if hasattr(wifi_uplink, "WifiHttp"):
        return wifi_uplink.WifiHttp(), wifi_uplink
    print("wifi_uplink is old (no WifiHttp) — bootstrapping from GitHub")
    url = _base() + "wifi_uplink.py"
    nbytes = _raw_https_to_file(url, "wifi_uplink.py", timeout_s=HTTP_TIMEOUT_S)
    print("  wifi_uplink.py", nbytes, "bytes")
    sys.modules.pop("wifi_uplink", None)
    import wifi_uplink

    if not hasattr(wifi_uplink, "WifiHttp"):
        raise OSError("wifi_uplink.py still has no WifiHttp after bootstrap")
    return wifi_uplink.WifiHttp(), wifi_uplink


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


def _wifi_connect(timeout_s):
    import sys

    sys.modules.pop("wifi_uplink", None)
    try:
        import wifi_uplink

        if hasattr(wifi_uplink, "connect"):
            return wifi_uplink.connect(timeout_s=timeout_s), wifi_uplink
    except Exception:
        pass

    import network
    import time

    networks = []
    try:
        import wifi_known_networks

        networks = getattr(wifi_known_networks, "WIFI_NETWORKS", []) or []
    except ImportError:
        pass
    if not networks:
        try:
            import wifi_credentials

            networks = getattr(wifi_credentials, "WIFI_NETWORKS", []) or []
        except ImportError:
            pass
    if not networks:
        raise OSError("no Wi-Fi networks configured")

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    deadline = time.time() + timeout_s
    for ssid, password in networks:
        if wlan.isconnected():
            wlan.disconnect()
            time.sleep(0.2)
        wlan.connect(ssid, password)
        while time.time() < deadline:
            if wlan.isconnected():
                print("wifi (fallback):", ssid)
                return ssid, None
            time.sleep(0.25)
    return None, None


def run(reboot=False, files=None):
    import gc
    import sys

    gc.collect()
    sys.modules.pop("wifi_uplink", None)

    names = files or FILES
    ssid, wifi_uplink = _wifi_connect(WIFI_TIMEOUT_S)
    if not ssid:
        raise OSError("Wi-Fi did not connect")
    print("Wi-Fi:", ssid, "branch", BRANCH, "heap", gc.mem_free())

    client, wifi_uplink = _ensure_http_client()
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
            if wifi_uplink is not None:
                wifi_uplink.disconnect()
            else:
                import network

                network.WLAN(network.STA_IF).disconnect()
        except Exception:
            pass
        gc.collect()

    import sys

    for mod in ("version", "ble_policy", "ble_service", "resilience", "main"):
        sys.modules.pop(mod, None)

    import version

    ver = getattr(version, "VERSION", None)
    if ver is None:
        try:
            ver = open("version.py").read().strip().split("=")[-1].strip().strip('"').strip("'")
        except Exception:
            ver = "?"
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
