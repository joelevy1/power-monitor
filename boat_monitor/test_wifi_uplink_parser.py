"""
Pure-Python unit test for wifi_uplink.split_url() -- the URL-parsing logic
used by WifiHttp before it ever opens a socket. No MicroPython/hardware
dependency, run directly with:

    python3 boat_monitor/test_wifi_uplink_parser.py

Covers the two real URLs this codebase actually needs to fetch over
Wi-Fi: GitHub raw content (OTA) and an Apps Script /exec URL (Sheets
logging) -- plus edge cases (explicit port, no path, bad scheme).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wifi_uplink  # noqa: E402
from wifi_uplink import (  # noqa: E402
    WifiError,
    WifiHttp,
    _configured_scan_selection,
    _decode_chunked,
    _recv_response,
    format_configured_scan,
    split_url,
)


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # 1. Real OTA manifest URL (GitHub raw, HTTPS, no explicit port).
    host, port, path, https = split_url(
        "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json"
    )
    check("github host", host == "raw.githubusercontent.com")
    check("github https port defaults 443", port == 443)
    check("github path", path == "/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json")
    check("github is_https True", https is True)

    # 2. Real Apps Script Web App URL shape (HTTPS, long path, no port).
    host, port, path, https = split_url(
        "https://script.google.com/macros/s/AKfycbXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/exec"
    )
    check("apps script host", host == "script.google.com")
    check("apps script https port defaults 443", port == 443)
    check("apps script path", path == "/macros/s/AKfycbXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX/exec")

    # 3. Plain HTTP, explicit port, root path.
    host, port, path, https = split_url("http://192.168.4.1:8080/")
    check("http host", host == "192.168.4.1")
    check("http explicit port", port == 8080)
    check("http root path", path == "/")
    check("http is_https False", https is False)

    # 4. No path at all -- should default to "/".
    host, port, path, https = split_url("http://example.com")
    check("no-path host", host == "example.com")
    check("no-path defaults to root", path == "/")
    check("no-path http default port 80", port == 80)

    # 5. Bad scheme should raise, not silently misparse.
    try:
        split_url("ftp://example.com/file")
        check("bad scheme raises ValueError", False)
    except ValueError:
        check("bad scheme raises ValueError", True)

    # 6. Missing host should raise.
    try:
        split_url("https:///no-host")
        check("missing host raises ValueError", False)
    except ValueError:
        check("missing host raises ValueError", True)

    # 7. WifiHttp._parse_response() -- pure header/body parsing, no socket
    # needed. Covers the same redirect scenario cellular.py now handles:
    # Google Apps Script's /exec URL always answers with a 302 carrying a
    # Location header, and the real response body is 0 bytes here too.
    http = WifiHttp()

    status, headers, body = http._parse_response(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 13\r\n\r\n"
        b'{"ok": true}\n'
    )
    check("parse_response 200 status", status == 200)
    check("parse_response 200 body", body == '{"ok": true}\n')
    check("parse_response 200 header lookup", headers.get("content-type") == "application/json")

    status, headers, body = http._parse_response(
        b"HTTP/1.1 302 Found\r\n"
        b"Location: https://script.googleusercontent.com/macros/echo?user_content_key=abc\r\n"
        b"Content-Length: 0\r\n\r\n"
    )
    check("parse_response 302 status", status == 302)
    check(
        "parse_response 302 location header (case-insensitive key)",
        headers.get("location") == "https://script.googleusercontent.com/macros/echo?user_content_key=abc",
    )
    check("parse_response 302 empty body", body == "")

    try:
        http._parse_response(b"not a valid http response, no header terminator")
        check("parse_response malformed response raises", False)
    except Exception:
        check("parse_response malformed response raises", True)

    payload = b'{"ok": true, "tab": "x"}'
    chunked = ("%x\r\n" % len(payload)).encode() + payload + b"\r\n0\r\n\r\n"
    decoded = _decode_chunked(chunked)
    check("chunked decode json", decoded == '{"ok": true, "tab": "x"}')

    status, headers, body = http._parse_response(
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n" + chunked
    )
    check("parse_response chunked 200", status == 200)
    check("parse_response chunked body", body == '{"ok": true, "tab": "x"}')

    class FakeTime:
        def __init__(self):
            self.now = 0

        def ticks_ms(self):
            self.now += 1000
            return self.now

        @staticmethod
        def ticks_diff(new, old):
            return new - old

    class FakeSocket:
        def __init__(self, results):
            self.results = list(results)

        def recv(self, _size):
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    original_time = wifi_uplink.time
    try:
        wifi_uplink.time = FakeTime()
        response = _recv_response(
            FakeSocket(
                [
                    OSError("slice timeout"),
                    OSError("slice timeout"),
                    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK",
                    b"",
                ]
            ),
            timeout_s=10,
        )
        check("recv_response survives timeout slices", response.endswith(b"\r\n\r\nOK"))

        wifi_uplink.time = FakeTime()
        try:
            _recv_response(
                FakeSocket([OSError("slice timeout")] * 10),
                timeout_s=3,
            )
            check("recv_response raises after overall timeout", False)
        except WifiError:
            check("recv_response raises after overall timeout", True)
    finally:
        wifi_uplink.time = original_time

    networks = [("Dock WiFi", "secret"), (b"BoatNet", "other-secret"), ("Hidden", "pw")]
    scans = [
        (b"Neighbor", b"\x01\x02\x03\x04\x05\x06", 1, -20, 3, 0),
        (b"Dock WiFi", b"\x10\x11\x12\x13\x14\x15", 6, -71, 3),
        (b"BoatNet", b"\x20\x21\x22\x23\x24\x25", 11, -80),
        (b"Dock WiFi", b"\x30\x31\x32\x33\x34\x35", 6, -43, 3, 0),
        (b"BoatNet", b"\x40\x41\x42\x43\x44\x45", 11, -62, 3, 0),
        (b"malformed",),
    ]
    selection = _configured_scan_selection(networks, scans)
    check(
        "configured scan chooses strongest duplicate BSSID",
        selection == [("Dock WiFi", -43), ("BoatNet", -62), ("Hidden", None)],
    )
    scan_text = format_configured_scan(networks, scans)
    check(
        "configured scan formats bytes and missing SSIDs",
        scan_text == "scan=Dock WiFi:-43,BoatNet:-62,Hidden:missing",
    )
    check("configured scan excludes unrelated neighboring SSIDs", "Neighbor" not in scan_text)
    check("configured scan excludes passwords and BSSIDs", "secret" not in scan_text and "\\x" not in scan_text)
    collision_text = format_configured_scan(
        [("Dock,Main", "pw")],
        [(b"Dock;Main", b"other", 1, -20), (b"Dock,Main", b"configured", 1, -70)],
    )
    check("SSID telemetry sanitizing does not alter exact matching", collision_text == "scan=Dock_Main:-70")
    many_networks = [("configured-%02d" % i, "pw") for i in range(30)]
    check(
        "configured scan report stays bounded",
        len(format_configured_scan(many_networks, [])) <= wifi_uplink.SCAN_TEXT_MAX_CHARS,
    )

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
