"""
Boat Monitor P2 - Wi-Fi STA uplink, tried before cellular for internet
access (OTA checks in ota.py, Sheets logging in sheets_log.py).

IMPORTANT hardware constraint: Wi-Fi and BLE share one radio on the Pico W
(CYW43439) and cannot run at the same time -- this is why ble_service.py
has ensure_wifi_off() before it enables BLE. Only call connect() here when
BLE is NOT active. main.py's boot flow already satisfies this for OTA (the
boot-time update check runs before ble_service.main() ever starts). Do not
call this while a phone is connected over BLE without stopping BLE first.

Configure known networks (see wifi_known_networks.py in GitHub and Config tab
`wifi_networks` on the sheet). Local overrides: wifi_credentials.py (copy from
wifi_credentials.example.py -- gitignored).

Usage:
    import wifi_uplink
    ssid = wifi_uplink.connect(timeout_s=15)   # None if nothing connected
    if ssid:
        http = wifi_uplink.WifiHttp()
        status, body = http.http_get("https://raw.githubusercontent.com/...")
        wifi_uplink.disconnect()

No external dependencies (no urequests/mip install) -- HTTP/HTTPS requests
are built by hand over a raw socket, using MicroPython's built-in ssl
module for TLS. This is the least-tested part of this codebase's networking
code (no way to run MicroPython here to verify it) -- bench-test with
wifi_uplink_test.py before relying on it.
"""

import time


class WifiError(Exception):
    pass


def _wlan():
    import network

    return network.WLAN(network.STA_IF)


def load_networks():
    """(ssid, password) list — works with only wifi_known_networks.py on the Pico."""
    try:
        import wifi_networks

        nets = wifi_networks.load_networks()
        if nets:
            return nets
    except ImportError:
        pass

    result = []
    seen = set()

    def add(entries):
        for ssid, password in entries or []:
            if not ssid or not password or ssid in seen:
                continue
            seen.add(ssid)
            result.append((ssid, password))

    try:
        import wifi_credentials

        add(getattr(wifi_credentials, "WIFI_NETWORKS", []))
    except ImportError:
        pass

    try:
        import wifi_known_networks

        add(getattr(wifi_known_networks, "WIFI_NETWORKS", []))
    except ImportError:
        pass

    return result


def _load_networks():
    return load_networks()


def connect(timeout_s=15):
    """Try each configured network in wifi_credentials.py, in order, with
    up to timeout_s seconds per network. Returns the SSID that connected,
    or None if none did (including if none are configured).
    """
    networks = _load_networks()
    if not networks:
        print(
            "wifi_uplink: no networks configured "
            "(wifi_credentials.py, wifi_sheet.json, or wifi_known_networks.py)"
        )
        return None

    try:
        import diag_log

        diag_log.log("wifi connect start networks=%d timeout=%ss" % (len(networks), timeout_s))
    except Exception:
        pass

    wlan = _wlan()
    wlan.active(True)

    for ssid, password in networks:
        if wlan.isconnected():
            wlan.disconnect()
            time.sleep(0.2)

        print("wifi_uplink: trying", ssid)
        try:
            import diag_log

            diag_log.log("wifi trying %s" % ssid)
        except Exception:
            pass
        try:
            wlan.connect(ssid, password)
        except OSError as exc:
            print("wifi_uplink: connect() raised for %s: %s" % (ssid, exc))
            try:
                import diag_log

                diag_log.log("wifi connect() error %s: %s" % (ssid, exc))
            except Exception:
                pass
            continue

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_s * 1000:
            if wlan.isconnected():
                print("wifi_uplink: connected to", ssid, wlan.ifconfig())
                try:
                    import diag_log

                    diag_log.log("wifi connected %s ip=%s" % (ssid, wlan.ifconfig()[0]))
                except Exception:
                    pass
                return ssid
            # status() < 0 means the connect attempt already failed (wrong
            # password, not found, etc) -- no point waiting out the timeout.
            if hasattr(wlan, "status") and wlan.status() < 0:
                print("wifi_uplink: %s failed early (status %s)" % (ssid, wlan.status()))
                try:
                    import diag_log

                    diag_log.log("wifi early fail %s status=%s" % (ssid, wlan.status()))
                except Exception:
                    pass
                break
            time.sleep(0.5)
        else:
            print("wifi_uplink: timed out connecting to", ssid)
            try:
                import diag_log

                diag_log.log("wifi timeout %s" % ssid)
            except Exception:
                pass

    wlan.active(False)
    try:
        import diag_log

        diag_log.log("wifi connect failed (no network)")
    except Exception:
        pass
    return None


def disconnect():
    wlan = _wlan()
    try:
        if wlan.isconnected():
            wlan.disconnect()
    except OSError:
        pass
    wlan.active(False)


def is_connected():
    try:
        return _wlan().isconnected()
    except Exception:
        return False


def split_url(url):
    """Parse a URL into (host, port, path, is_https). Pure/no imports
    beyond stdlib, so it's unit-testable on a PC -- see
    test_wifi_uplink_parser.py.
    """
    if url.startswith("https://"):
        is_https = True
        rest = url[len("https://"):]
        default_port = 443
    elif url.startswith("http://"):
        is_https = False
        rest = url[len("http://"):]
        default_port = 80
    else:
        raise ValueError("URL must start with http:// or https://")

    if "/" in rest:
        host_port, path = rest.split("/", 1)
        path = "/" + path
    else:
        host_port, path = rest, "/"

    if ":" in host_port:
        host, port_text = host_port.split(":", 1)
        port = int(port_text)
    else:
        host, port = host_port, default_port

    if not host:
        raise ValueError("URL missing host: %s" % url)

    return host, port, path, is_https


# A GET/POST to a URL answering with one of these should be re-requested
# against its Location header instead of treated as the final response --
# same convention cellular.py's Sim7600Modem client now follows, added for
# the identical reason: Google Apps Script Web Apps (script.google.com/
# .../exec, used by sheets_log.py) ALWAYS answer with a 302 to a
# script.googleusercontent.com URL carrying the real response. This path
# is currently untested on real hardware (no Wi-Fi network configured yet
# -- see wifi_uplink: no networks configured in the boot log) but would
# hit the exact same bug the moment it were used, so it's fixed here too
# rather than waiting to rediscover it later.
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5


def _cookie_from_set_cookie(set_cookie):
    if not set_cookie:
        return ""
    # First name=value pair only (enough for Apps Script redirect session).
    return set_cookie.split(";")[0].strip()


def _decode_chunked(body_bytes):
    out = b""
    pos = 0
    while pos < len(body_bytes):
        line_end = body_bytes.find(b"\r\n", pos)
        if line_end < 0:
            break
        size_line = body_bytes[pos:line_end].decode("utf-8", "ignore").split(";", 1)[0].strip()
        try:
            chunk_size = int(size_line, 16)
        except ValueError:
            break
        pos = line_end + 2
        if chunk_size == 0:
            break
        out += body_bytes[pos : pos + chunk_size]
        pos += chunk_size + 2
    return out.decode("utf-8", "ignore")


class WifiHttp:
    """Minimal HTTP/HTTPS client over a raw socket, no urequests needed.

    Exposes http_get(url) -> text (same shape as cellular.py's
    Sim7600Modem, so ota.load_manifest()/apply_manifest() can use either
    interchangeably), plus http_post_json() for sheets_log.py.
    """

    def _request(
        self,
        method,
        url,
        body=None,
        headers=None,
        timeout_s=20,
        _redirect_count=0,
        _cookie="",
    ):
        import socket

        host, port, path, is_https = split_url(url)

        headers = dict(headers or {})
        headers.setdefault("Host", host)
        headers.setdefault("Connection", "close")
        headers.setdefault("User-Agent", "boat-monitor-pico")
        if _cookie:
            headers.setdefault("Cookie", _cookie)

        body_bytes = b""
        if body is not None:
            body_bytes = body if isinstance(body, bytes) else body.encode()
            headers.setdefault("Content-Length", str(len(body_bytes)))

        request_lines = ["%s %s HTTP/1.1" % (method, path)]
        for key, value in headers.items():
            request_lines.append("%s: %s" % (key, value))
        request_text = "\r\n".join(request_lines) + "\r\n\r\n"

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

            sock.write(request_text.encode())
            if body_bytes:
                sock.write(body_bytes)

            response = b""
            while True:
                try:
                    chunk = sock.recv(1024)
                except OSError:
                    break
                if not chunk:
                    break
                response += chunk
        finally:
            sock.close()

        status, resp_headers, response_body = self._parse_response(response)

        if status in REDIRECT_STATUSES:
            if _redirect_count >= MAX_REDIRECTS:
                raise WifiError("too many redirects starting from %s" % url)
            location = resp_headers.get("location")
            if not location:
                raise WifiError("redirect (status %s) with no Location header from %s" % (status, url))
            print("wifi_uplink: following redirect ->", location)
            next_cookie = _cookie
            set_cookie = resp_headers.get("set-cookie")
            if set_cookie:
                next_cookie = _cookie_from_set_cookie(set_cookie)
            if status in (307, 308):
                next_method, next_body, next_headers = method, body, headers
            else:
                next_method, next_body, next_headers = "GET", None, {}
            return self._request(
                next_method,
                location,
                body=next_body,
                headers=next_headers,
                timeout_s=timeout_s,
                _redirect_count=_redirect_count + 1,
                _cookie=next_cookie,
            )

        return status, response_body, url

    def _parse_response(self, response):
        header_end = response.find(b"\r\n\r\n")
        if header_end < 0:
            raise WifiError("malformed HTTP response (no header terminator)")

        header_text = response[:header_end].decode("utf-8", "ignore")
        header_lines = header_text.split("\r\n")
        status_line = header_lines[0]
        try:
            status = int(status_line.split(" ")[1])
        except (IndexError, ValueError):
            raise WifiError("could not parse HTTP status line: %s" % status_line)

        resp_headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                resp_headers[key.strip().lower()] = value.strip()

        raw_body = response[header_end + 4:]

        te = resp_headers.get("transfer-encoding", "").lower()
        if "chunked" in te:
            response_body = _decode_chunked(raw_body)
        else:
            cl = resp_headers.get("content-length")
            if cl is not None:
                try:
                    n = int(cl)
                    raw_body = raw_body[:n]
                except ValueError:
                    pass
            response_body = raw_body.decode("utf-8", "ignore")

        return status, resp_headers, response_body

    def http_get(self, url, timeout_s=20):
        """Matches cellular.Sim7600Modem.http_get()'s signature/return
        shape (raises on non-200 or malformed response, returns body text
        on success) so ota.py's load_manifest()/apply_manifest() work with
        either client unchanged.
        """
        status, body, final_url = self._request("GET", url, timeout_s=timeout_s)
        if status != 200:
            raise WifiError(
                "HTTP status %s for %s body=%s" % (status, final_url, (body or "")[:120])
            )
        return body

    def http_post_json(self, url, body_text, timeout_s=20):
        headers = {"Content-Type": "application/json"}
        status, body, final_url = self._request(
            "POST", url, body=body_text, headers=headers, timeout_s=timeout_s
        )
        if status != 200:
            raise WifiError(
                "HTTP status %s after POST (final URL %s) body=%s"
                % (status, final_url, (body or "")[:120])
            )
        return body
