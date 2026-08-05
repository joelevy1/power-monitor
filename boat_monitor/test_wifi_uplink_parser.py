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

from wifi_uplink import split_url  # noqa: E402


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

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
