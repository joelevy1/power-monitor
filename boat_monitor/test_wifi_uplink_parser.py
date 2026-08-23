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
import inspect
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wifi_uplink  # noqa: E402
from wifi_uplink import (  # noqa: E402
    WifiError,
    WifiHttp,
    _configured_scan_selection,
    _decode_chunked,
    _negative_status_retry,
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

    download_source = inspect.getsource(WifiHttp.download_to_file)
    check(
        "download prepares heap before TLS",
        download_source.index("_prepare_tls_heap()")
        < download_source.index("ssl.wrap_socket"),
    )
    check("download bounds body recv to 512 bytes", "sock.recv(min(512," in download_source)
    check(
        "download reclaims TLS socket in finally",
        "sock = None" in download_source
        and download_source.rindex("_prepare_tls_heap()")
        > download_source.index("finally:"),
    )

    # Redirects must run in one _request frame and release each closed response
    # before the next TLS socket is allocated.
    redirect_responses = [
        (
            b"HTTP/1.1 307 Temporary Redirect\r\n"
            b"Location: https://hop-two.example/keep\r\n"
            b"Set-Cookie: sid=one; Path=/\r\nContent-Length: 0\r\n\r\n"
        ),
        (
            b"HTTP/1.1 308 Permanent Redirect\r\n"
            b"Location: https://hop-three.example/keep\r\n"
            b"Set-Cookie: sid=two; Path=/\r\nContent-Length: 0\r\n\r\n"
        ),
        (
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Location: https://hop-four.example/get\r\n"
            b"Set-Cookie: sid=three; Path=/\r\nContent-Length: 0\r\n\r\n"
        ),
        (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: https://hop-five.example/get\r\n"
            b"Set-Cookie: sid=four; Path=/\r\nContent-Length: 0\r\n\r\n"
        ),
        (
            b"HTTP/1.1 303 See Other\r\n"
            b"Location: https://hop-six.example/done\r\n"
            b"Set-Cookie: sid=five; Path=/\r\nContent-Length: 0\r\n\r\n"
        ),
        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK",
    ]
    redirect_sockets = []
    redirect_events = []
    request_depths = []

    class RedirectSocket:
        def __init__(self, response):
            self.response = response
            self.sent = []
            self.recv_count = 0

        def settimeout(self, value):
            self.timeout = value

        def connect(self, addr):
            self.addr = addr
            request_depths.append(
                sum(1 for frame in inspect.stack() if frame.function == "_request")
            )

        def write(self, data):
            self.sent.append(data)

        def recv(self, _size):
            self.recv_count += 1
            return self.response if self.recv_count == 1 else b""

        def close(self):
            redirect_events.append("close")

    def redirect_socket_factory():
        redirect_events.append("socket")
        sock = RedirectSocket(redirect_responses[len(redirect_sockets)])
        redirect_sockets.append(sock)
        return sock

    fake_socket_module = types.SimpleNamespace(
        getaddrinfo=lambda host, port: [(None, None, None, None, (host, port))],
        socket=redirect_socket_factory,
    )
    fake_ssl_module = types.SimpleNamespace(wrap_socket=lambda sock, **_kwargs: sock)
    fake_gc_module = types.SimpleNamespace(
        collect=lambda: redirect_events.append("gc")
    )
    original_socket_module = sys.modules.get("socket")
    original_ussl_module = sys.modules.get("ussl")
    original_gc_module = sys.modules.get("gc")
    original_power_mode = wifi_uplink.set_request_power_mode
    original_feed = wifi_uplink._feed_watchdog_if_due
    try:
        sys.modules["socket"] = fake_socket_module
        sys.modules["ussl"] = fake_ssl_module
        sys.modules["gc"] = fake_gc_module
        wifi_uplink.set_request_power_mode = lambda idle=False: None
        wifi_uplink._feed_watchdog_if_due = lambda: None
        status, body, final_url = WifiHttp()._request(
            "POST",
            "https://hop-one.example/start",
            body="payload",
            headers={"Content-Type": "text/plain"},
        )
        requests = [b"".join(sock.sent) for sock in redirect_sockets]
        check("multi-hop redirect reaches final response", (status, body) == (200, "OK"))
        check("multi-hop redirect reports final URL", final_url == "https://hop-six.example/done")
        check("307 preserves POST method and body", requests[1].startswith(b"POST /keep ") and requests[1].endswith(b"payload"))
        check("308 preserves POST method and body", requests[2].startswith(b"POST /keep ") and requests[2].endswith(b"payload"))
        check("301 changes method to GET and drops body", requests[3].startswith(b"GET /get ") and not requests[3].endswith(b"payload"))
        check("302 keeps redirected request as GET", requests[4].startswith(b"GET /get ") and not requests[4].endswith(b"payload"))
        check("303 keeps redirected request as GET", requests[5].startswith(b"GET /done ") and not requests[5].endswith(b"payload"))
        check(
            "redirect cookies update across hops",
            b"Cookie: sid=one" in requests[1]
            and b"Cookie: sid=two" in requests[2]
            and b"Cookie: sid=three" in requests[3]
            and b"Cookie: sid=four" in requests[4]
            and b"Cookie: sid=five" in requests[5],
        )
        check("redirect Host follows destination", b"Host: hop-two.example" in requests[1] and b"Host: hop-six.example" in requests[5])
        check("redirect handling is non-recursive", request_depths == [1, 1, 1, 1, 1, 1])
        socket_positions = [
            i for i, event in enumerate(redirect_events) if event == "socket"
        ]
        close_positions = [
            i for i, event in enumerate(redirect_events) if event == "close"
        ]
        reclaimed_between = all(
            close_positions[i - 1] < socket_positions[i]
            and "gc"
            in redirect_events[close_positions[i - 1] + 1 : socket_positions[i]]
            for i in range(1, len(socket_positions))
        )
        check(
            "redirect collects before each next socket",
            len(socket_positions) == 6
            and len(close_positions) == 6
            and reclaimed_between,
        )
    finally:
        wifi_uplink.set_request_power_mode = original_power_mode
        wifi_uplink._feed_watchdog_if_due = original_feed
        if original_socket_module is None:
            sys.modules.pop("socket", None)
        else:
            sys.modules["socket"] = original_socket_module
        if original_ussl_module is None:
            sys.modules.pop("ussl", None)
        else:
            sys.modules["ussl"] = original_ussl_module
        if original_gc_module is None:
            sys.modules.pop("gc", None)
        else:
            sys.modules["gc"] = original_gc_module

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

    check("negative status requests first retry", _negative_status_retry(-3, False))
    check("negative status does not request second retry", not _negative_status_retry(-3, True))
    check("non-negative status does not retry", not _negative_status_retry(1, False))

    class FakeWlan:
        def __init__(self, attempt_results):
            self.attempt_results = list(attempt_results)
            self.current = None
            self.connect_calls = []
            self.active_calls = []
            self.disconnect_calls = 0

        def active(self, value=None):
            if value is not None:
                self.active_calls.append(value)
            return self.active_calls[-1] if self.active_calls else False

        def scan(self):
            return [(b"Levy-Guest", b"hidden-bssid", 1, -38, 3, 0)]

        def connect(self, ssid, password):
            self.connect_calls.append((ssid, password))
            self.current = self.attempt_results[len(self.connect_calls) - 1]

        def isconnected(self):
            return self.current == "connected"

        def status(self, *args):
            if args:
                return -38
            return self.current

        def disconnect(self):
            self.disconnect_calls += 1
            self.current = None

        def ifconfig(self):
            return ("192.0.2.1", "255.255.255.0", "192.0.2.254", "192.0.2.254")

    original_load = wifi_uplink._load_networks
    original_wlan = wifi_uplink._wlan
    original_sleep = wifi_uplink._sleep_with_watchdog
    try:
        wifi_uplink._load_networks = lambda: [("Levy-Guest", "do-not-report")]
        wifi_uplink._sleep_with_watchdog = lambda _seconds: None

        retry_success = FakeWlan([-3, "connected"])
        wifi_uplink._wlan = lambda: retry_success
        check("negative status retry succeeds on same SSID", wifi_uplink.connect(timeout_s=1) == "Levy-Guest")
        check("successful retry occurs exactly once", len(retry_success.connect_calls) == 2)
        check("retry fully disconnects STA", retry_success.disconnect_calls == 1)
        check("retry deactivates and reactivates STA", retry_success.active_calls[:3] == [True, False, True])
        success_report = wifi_uplink.get_last_connection_report()
        check(
            "successful retry report has both statuses and outcome",
            "first_status=-3" in success_report
            and "retry_status=connected" in success_report
            and "outcome=wifi" in success_report,
        )
        check("successful retry report excludes password", "do-not-report" not in success_report)

        retry_failure = FakeWlan([-3, -3])
        wifi_uplink._wlan = lambda: retry_failure
        check("double negative status falls back", wifi_uplink.connect(timeout_s=1) is None)
        check("failed retry occurs exactly once", len(retry_failure.connect_calls) == 2)
        failure_report = wifi_uplink.get_last_connection_report()
        check(
            "failed retry report has both statuses and fallback",
            "first_status=-3" in failure_report
            and "retry_status=-3" in failure_report
            and "outcome=fallback" in failure_report,
        )
        check("connection report remains bounded", len(failure_report) <= wifi_uplink.CONNECTION_REPORT_MAX_CHARS)
    finally:
        wifi_uplink._load_networks = original_load
        wifi_uplink._wlan = original_wlan
        wifi_uplink._sleep_with_watchdog = original_sleep

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
