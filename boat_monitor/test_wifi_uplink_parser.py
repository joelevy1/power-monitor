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

from wifi_uplink import WifiHttp, _decode_chunked, split_url  # noqa: E402


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

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
