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


WIFI_IO_SLICE_TIMEOUT_S = 5
CONNECTION_REPORT_MAX_CHARS = 146
SCAN_TEXT_MAX_CHARS = 108
_last_connection_report = ""


def _ssid_value(value):
    """Normalize bytes/text SSIDs for exact configured-network matching."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            try:
                return value.decode()
            except Exception:
                return "<bytes>"
    return str(value)


def _ssid_text(value):
    """Return a short, delimiter-safe SSID string for telemetry."""
    value = _ssid_value(value)
    out = ""
    for char in value:
        if char in ",;=@\r\n\t" or ord(char) < 32:
            char = "_"
        out += char
        if len(out) >= 32:
            break
    return out or "<empty>"


def _configured_scan_details(networks, scan_results):
    """Return exact key, safe label, and strongest RSSI for configured SSIDs."""
    ordered = []
    strongest = {}
    labels = {}
    for item in networks or []:
        if not item:
            continue
        key = _ssid_value(item[0])
        if key not in strongest:
            strongest[key] = None
            labels[key] = _ssid_text(key)
            ordered.append(key)

    for row in scan_results or []:
        try:
            if len(row) < 4:
                continue
            key = _ssid_value(row[0])
            if key not in strongest:
                continue
            rssi = int(row[3])
            if strongest[key] is None or rssi > strongest[key]:
                strongest[key] = rssi
        except (TypeError, ValueError, IndexError):
            continue
    return [(key, labels[key], strongest[key]) for key in ordered]


def _configured_scan_selection(networks, scan_results):
    """Return configured SSID labels and strongest RSSI, in config order."""
    return [
        (label, rssi)
        for _key, label, rssi in _configured_scan_details(networks, scan_results)
    ]


def _format_scan_selection(selection):
    """Bound scan text while keeping entries whole where possible."""
    text = "scan="
    added = False
    for ssid, rssi in selection:
        part = "%s:%s" % (ssid, rssi if rssi is not None else "missing")
        candidate = text + ("," if added else "") + part
        if len(candidate) > SCAN_TEXT_MAX_CHARS:
            if len(text) + 4 <= SCAN_TEXT_MAX_CHARS:
                text += ",..." if added else "..."
            break
        text = candidate
        added = True
    return text if added else "scan=none"


def format_configured_scan(networks, scan_results):
    """Compact configured-only scan text; never exposes BSSIDs or neighbors."""
    return _format_scan_selection(_configured_scan_selection(networks, scan_results))


def _set_connection_report(detail, scan_text=""):
    global _last_connection_report
    text = str(detail or "reason=unknown")
    if scan_text:
        text += " " + scan_text
    _last_connection_report = text[:CONNECTION_REPORT_MAX_CHARS]


def get_last_connection_report():
    """Return the bounded report produced by the most recent connect() call."""
    return _last_connection_report


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _ticks_diff(new, old):
    try:
        return time.ticks_diff(new, old)
    except AttributeError:
        return new - old


def ensure_wifi_off():
    """Disable STA/AP and settle the shared radio before BLE starts."""
    try:
        import network
    except ImportError:
        return

    disabled_any = False
    for label, iface in (("STA", network.STA_IF), ("AP", network.AP_IF)):
        try:
            wlan = network.WLAN(iface)
            if wlan.active():
                wlan.active(False)
                disabled_any = True
                print("WiFi %s disabled for BLE" % label)
        except Exception as exc:
            print("WiFi %s off: %s" % (label, exc))

    if disabled_any:
        time.sleep_ms(250)


def _feed_watchdog_if_due():
    try:
        import resilience

        resilience.feed_watchdog_if_due()
    except Exception:
        pass


def _sleep_with_watchdog(seconds):
    try:
        import resilience

        resilience.sleep_with_watchdog(seconds, sleep_fn=time.sleep)
    except Exception:
        time.sleep(seconds)


def _negative_status_retry(status, retry_used):
    """Pure retry decision: one retry only for a negative WLAN status."""
    return status is not None and status < 0 and not retry_used


def _wait_for_connection(wlan, timeout_s):
    """Return (outcome, status) for one bounded WLAN connection attempt."""
    start = _ticks_ms()
    while _ticks_diff(_ticks_ms(), start) < timeout_s * 1000:
        _feed_watchdog_if_due()
        if wlan.isconnected():
            return "connected", None
        status = None
        if hasattr(wlan, "status"):
            try:
                status = wlan.status()
            except Exception:
                pass
        if status is not None and status < 0:
            return "negative", status
        _sleep_with_watchdog(0.5)
    return "timeout", None


def _reset_sta_for_retry(wlan):
    """Fully reset STA between a failed auth/connection and its sole retry."""
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
    except Exception:
        pass
    _sleep_with_watchdog(0.5)
    wlan.active(True)
    _feed_watchdog_if_due()


def _recv_response(sock, timeout_s):
    """Read until peer close, tolerating bounded socket timeout slices."""
    start = _ticks_ms()
    response = b""
    last_error = None
    while _ticks_diff(_ticks_ms(), start) < int(timeout_s * 1000):
        _feed_watchdog_if_due()
        try:
            chunk = sock.recv(1024)
        except OSError as exc:
            # A 5s socket timeout is only a watchdog-safe polling slice, not
            # the overall HTTP deadline. Apps Script cold starts can exceed it.
            last_error = exc
            continue
        if not chunk:
            return response
        response += chunk
    if response:
        return response
    raise WifiError("HTTP response timeout: %s" % (last_error or "no data"))


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
        _set_connection_report("reason=no configured networks")
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

    scan_details = []
    scan_selection = []
    scan_text = "scan=failed"
    scan_results = None
    try:
        _feed_watchdog_if_due()
        scan_results = wlan.scan()
        scan_details = _configured_scan_details(networks, scan_results)
        scan_selection = [(label, rssi) for _key, label, rssi in scan_details]
        scan_text = _format_scan_selection(scan_selection)
    except Exception as exc:
        print("wifi_uplink: scan failed:", exc)
    finally:
        # WLAN scans can allocate a large tuple list. Drop it before any
        # subsequent HTTPS/TLS work and opportunistically reclaim the heap.
        scan_results = None
        try:
            import gc

            gc.collect()
        except Exception:
            pass
        _feed_watchdog_if_due()

    visible_rssi = {}
    for scanned_key, _scanned_label, scanned_rssi in scan_details:
        visible_rssi[scanned_key] = scanned_rssi
    any_configured_visible = any(rssi is not None for rssi in visible_rssi.values())
    last_failure = "reason=connection failed"
    retry_detail = ""

    for ssid, password in networks:
        if wlan.isconnected():
            wlan.disconnect()
            time.sleep(0.2)

        retry_used = False
        first_status = None
        while True:
            print("wifi_uplink: trying", ssid, "(retry)" if retry_used else "")
            try:
                import diag_log

                diag_log.log("wifi trying %s retry=%s" % (ssid, retry_used))
            except Exception:
                pass
            try:
                wlan.connect(ssid, password)
            except OSError as exc:
                last_failure = "reason=connect error ssid=%s" % _ssid_text(ssid)
                print("wifi_uplink: connect() raised for %s: %s" % (ssid, exc))
                try:
                    import diag_log

                    diag_log.log("wifi connect() error %s: %s" % (ssid, exc))
                except Exception:
                    pass
                break

            outcome, status = _wait_for_connection(wlan, timeout_s)
            if outcome == "connected":
                report_ssid = _ssid_text(ssid)
                rssi = visible_rssi.get(_ssid_value(ssid))
                if rssi is None and hasattr(wlan, "status"):
                    try:
                        rssi = int(wlan.status("rssi"))
                    except Exception:
                        pass
                status_detail = ""
                if retry_used:
                    status_detail = " first_status=%s retry_status=connected outcome=wifi" % first_status
                elif retry_detail:
                    status_detail = " " + retry_detail + " outcome=wifi"
                _set_connection_report(
                    "connected=%s rssi=%s%s"
                    % (
                        report_ssid,
                        rssi if rssi is not None else "unknown",
                        status_detail,
                    ),
                    scan_text,
                )
                print("wifi_uplink: connected to", ssid, wlan.ifconfig())
                try:
                    import diag_log

                    diag_log.log("wifi connected %s ip=%s" % (ssid, wlan.ifconfig()[0]))
                except Exception:
                    pass
                return ssid

            if outcome == "negative":
                if _negative_status_retry(status, retry_used):
                    first_status = status
                    print("wifi_uplink: %s failed early (status %s); resetting STA for retry" % (ssid, status))
                    try:
                        import diag_log

                        diag_log.log("wifi early fail %s status=%s retrying once" % (ssid, status))
                    except Exception:
                        pass
                    _reset_sta_for_retry(wlan)
                    retry_used = True
                    continue
                if retry_used:
                    retry_detail = "retry_ssid=%s first_status=%s retry_status=%s" % (
                        _ssid_text(ssid),
                        first_status,
                        status,
                    )
                    last_failure = "reason=status failure %s outcome=fallback" % retry_detail
                else:
                    last_failure = "reason=early status failure ssid=%s status=%s" % (
                        _ssid_text(ssid),
                        status,
                    )
                print("wifi_uplink: %s failed early (status %s)" % (ssid, status))
                try:
                    import diag_log

                    diag_log.log("wifi early fail %s status=%s" % (ssid, status))
                except Exception:
                    pass
                break

            last_failure = "reason=timeout ssid=%s" % _ssid_text(ssid)
            print("wifi_uplink: timed out connecting to", ssid)
            try:
                import diag_log

                diag_log.log("wifi timeout %s" % ssid)
            except Exception:
                pass
            break

    wlan.active(False)
    if scan_text != "scan=failed" and not any_configured_visible and not retry_detail:
        last_failure = "reason=no configured network visible"
    _set_connection_report(last_failure, scan_text)
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
        sock.settimeout(min(timeout_s, WIFI_IO_SLICE_TIMEOUT_S))
        try:
            _feed_watchdog_if_due()
            sock.connect(addr)
            _feed_watchdog_if_due()
            if is_https:
                try:
                    import ussl as ssl
                except ImportError:
                    import ssl
                try:
                    sock = ssl.wrap_socket(sock, server_hostname=host)
                except TypeError:
                    sock = ssl.wrap_socket(sock)
                _feed_watchdog_if_due()

            sock.write(request_text.encode())
            _feed_watchdog_if_due()
            if body_bytes:
                sock.write(body_bytes)
                _feed_watchdog_if_due()

            response = _recv_response(sock, timeout_s)
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

    def download_to_file(self, url, path, timeout_s=20):
        """Stream HTTP GET body to a file (lower peak RAM than http_get)."""
        import socket

        host, port, req_path, is_https = split_url(url)
        request_text = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nUser-Agent: boat-monitor-pico\r\n\r\n"
            % (req_path, host)
        )
        addr = socket.getaddrinfo(host, port)[0][-1]
        sock = socket.socket()
        sock.settimeout(min(timeout_s, WIFI_IO_SLICE_TIMEOUT_S))
        try:
            _feed_watchdog_if_due()
            sock.connect(addr)
            _feed_watchdog_if_due()
            if is_https:
                try:
                    import ussl as ssl
                except ImportError:
                    import ssl
                try:
                    sock = ssl.wrap_socket(sock, server_hostname=host)
                except TypeError:
                    sock = ssl.wrap_socket(sock)
                _feed_watchdog_if_due()

            sock.write(request_text.encode())
            _feed_watchdog_if_due()

            header = b""
            while b"\r\n\r\n" not in header:
                _feed_watchdog_if_due()
                chunk = sock.recv(256)
                if not chunk:
                    raise WifiError("connection closed before HTTP headers")
                header += chunk
                if len(header) > 8192:
                    raise WifiError("HTTP headers too large")

            header_end = header.find(b"\r\n\r\n")
            header_text = header[:header_end].decode("utf-8", "ignore")
            status_line = header_text.split("\r\n", 1)[0]
            try:
                status = int(status_line.split(" ")[1])
            except (IndexError, ValueError):
                raise WifiError("bad status line: %s" % status_line)
            if status != 200:
                raise WifiError("HTTP %s for %s" % (status, url))

            resp_headers = {}
            for line in header_text.split("\r\n")[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    resp_headers[k.strip().lower()] = v.strip()

            body = header[header_end + 4 :]
            te = resp_headers.get("transfer-encoding", "").lower()
            if "chunked" in te:
                raise WifiError("chunked response — use BOOTSEL or update wifi_uplink on PC")
            cl = resp_headers.get("content-length")
            if cl is None:
                raise WifiError("no Content-Length — use BOOTSEL copy")
            try:
                need = int(cl)
            except ValueError:
                raise WifiError("bad Content-Length")

            tmp_path = path + ".new"
            got = len(body)
            with open(tmp_path, "wb") as out:
                if body:
                    out.write(body)
                while got < need:
                    _feed_watchdog_if_due()
                    chunk = sock.recv(min(1024, need - got))
                    if not chunk:
                        raise WifiError("short read %d/%d" % (got, need))
                    got += len(chunk)
                    out.write(chunk)

            import os

            try:
                os.remove(path + ".bak")
            except OSError:
                pass
            try:
                os.rename(path, path + ".bak")
            except OSError:
                pass
            os.rename(tmp_path, path)
            return os.stat(path)[6]
        finally:
            try:
                sock.close()
            except Exception:
                pass

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
