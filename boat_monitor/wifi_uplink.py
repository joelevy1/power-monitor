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
WIFI_DRIVER_SETTLE_S = 1.0
CONNECTION_REPORT_MAX_CHARS = 512
SCAN_TEXT_MAX_CHARS = 160
_last_connection_report = ""
RP2_PM_NONE = 0xA11140
RP2_PM_POWERSAVE = 0xA11142


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
    """Fully disable/deinitialize STA/AP and settle the radio for BLE."""
    try:
        import network
    except ImportError:
        return

    disabled_any = False
    for label, iface in (("STA", network.STA_IF), ("AP", network.AP_IF)):
        try:
            wlan = network.WLAN(iface)
            was_active = False
            try:
                was_active = bool(wlan.active())
            except Exception:
                pass
            if label == "STA":
                try:
                    wlan.disconnect()
                except Exception:
                    pass
            try:
                wlan.active(False)
            except Exception:
                pass
            if hasattr(wlan, "deinit"):
                try:
                    wlan.deinit()
                except Exception:
                    pass
            # Some ports leave the interface active after a partial deinit.
            try:
                wlan.active(False)
            except Exception:
                pass
            if was_active:
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


def _prepare_tls_heap():
    """Reclaim short-lived response/socket objects before a TLS handshake."""
    try:
        import gc

        gc.collect()
        gc.collect()
    except Exception:
        pass
    _feed_watchdog_if_due()


_TLS_CONTEXT = None


def _wrap_tls_socket(sock, host):
    """Use one modern SSLContext when available; retain old-port fallback."""
    try:
        import ussl as ssl
    except ImportError:
        import ssl

    global _TLS_CONTEXT
    context_type = getattr(ssl, "SSLContext", None)
    protocol = getattr(ssl, "PROTOCOL_TLS_CLIENT", None)
    if context_type is not None and protocol is not None:
        if _TLS_CONTEXT is None:
            _TLS_CONTEXT = context_type(protocol)
        try:
            return _TLS_CONTEXT.wrap_socket(sock, server_hostname=host)
        except TypeError:
            return _TLS_CONTEXT.wrap_socket(sock)
    try:
        return ssl.wrap_socket(sock, server_hostname=host)
    except TypeError:
        return ssl.wrap_socket(sock)


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


def _valid_ipv4(value):
    """Reject unset/link-local addresses without doing an internet request."""
    try:
        parts = str(value or "").split(".")
        if len(parts) != 4:
            return False
        nums = [int(part) for part in parts]
        if any(part < 0 or part > 255 for part in nums):
            return False
        return (
            nums[0] not in (0, 127)
            and nums[:2] != [169, 254]
            and nums != [255, 255, 255, 255]
        )
    except Exception:
        return False


def _status_value(wlan):
    try:
        return wlan.status()
    except Exception:
        return None


def _association_healthy(wlan):
    """Validate driver state and local DHCP state before reusing association."""
    try:
        if not wlan.active() or not wlan.isconnected():
            return False
        status = _status_value(wlan)
        try:
            import network

            got_ip = getattr(network, "STAT_GOT_IP", 3)
        except Exception:
            got_ip = 3
        if status != got_ip:
            return False
        config = wlan.ifconfig()
        return bool(config) and _valid_ipv4(config[0])
    except Exception:
        return False


def _associated_ssid(wlan, networks):
    for getter in (
        lambda: wlan.config("ssid"),
        lambda: wlan.status("ssid"),
    ):
        try:
            value = getter()
            if value:
                return _ssid_value(value)
        except Exception:
            pass
    # RP2 builds have not always exposed the current SSID. Persistence is only
    # entered after connecting one of these configured networks.
    return _ssid_value(networks[0][0]) if networks else "<associated>"


def _rssi(wlan):
    try:
        return int(wlan.status("rssi"))
    except Exception:
        return None


def _set_pm(wlan, idle=False):
    """Best-effort RP2 PM selection; return a bounded telemetry label."""
    try:
        import network

        if idle:
            value = getattr(network, "PM_POWERSAVE", RP2_PM_POWERSAVE)
            label = "powersave"
        else:
            value = getattr(network, "PM_NONE", RP2_PM_NONE)
            label = "none"
        wlan.config(pm=value)
        return label
    except Exception:
        return "unsupported"


def _configure_association(wlan):
    """Apply supported reconnect/performance controls before association."""
    reconnects = "unsupported"
    try:
        wlan.config(reconnects=3)
        reconnects = "3"
    except Exception:
        pass
    return _set_pm(wlan, idle=False), reconnects


def _scan_configured_after_failure(wlan, networks):
    """Collect diagnostics only after direct association attempts have failed."""
    details = []
    text = "scan=failed"
    results = None
    try:
        _feed_watchdog_if_due()
        results = wlan.scan()
        details = _configured_scan_details(networks, results)
        text = _format_scan_selection(
            [(label, rssi) for _key, label, rssi in details]
        )
    except Exception as exc:
        print("wifi_uplink: diagnostic scan failed:", exc)
    finally:
        results = None
        try:
            import gc

            gc.collect()
        except Exception:
            pass
        _feed_watchdog_if_due()
    return details, text


def set_request_power_mode(idle=False):
    """Best-effort power mode change for an active HTTP request/session."""
    try:
        wlan = _wlan()
        if not _association_healthy(wlan):
            return "unavailable"
        mode = _set_pm(wlan, idle=idle)
        try:
            import diag_log

            diag_log.log("wifi pm=%s phase=%s" % (mode, "idle" if idle else "request"))
        except Exception:
            pass
        return mode
    except Exception:
        return "unsupported"


def _reset_sta_for_retry(wlan):
    """Fully reset STA between a failed association and its sole retry."""
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
    except Exception:
        pass
    if hasattr(wlan, "deinit"):
        try:
            wlan.deinit()
        except Exception:
            pass
    _sleep_with_watchdog(WIFI_DRIVER_SETTLE_S)
    try:
        wlan = _wlan()
    except Exception:
        pass
    wlan.active(True)
    _feed_watchdog_if_due()
    return wlan


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
    try:
        import gc
        import machine

        start_context = "reset=%s heap=%s" % (
            machine.reset_cause(),
            gc.mem_free(),
        )
    except Exception:
        start_context = "reset=? heap=?"
    if not networks:
        _set_connection_report("%s reason=no configured networks" % start_context)
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
    if _association_healthy(wlan):
        ssid = _associated_ssid(wlan, networks)
        rssi = _rssi(wlan)
        pm = _set_pm(wlan, idle=False)
        _set_connection_report(
            "%s outcome=reused connected=%s rssi=%s pm=%s"
            % (
                start_context,
                _ssid_text(ssid),
                rssi if rssi is not None else "unknown",
                pm,
            )
        )
        print("wifi_uplink: reusing", ssid, wlan.ifconfig())
        return ssid

    # isconnected() can remain true after DHCP/driver state has gone stale.
    stale = False
    try:
        stale = bool(wlan.isconnected())
    except Exception:
        pass
    if stale:
        print("wifi_uplink: stale association; resetting STA")
        wlan = _reset_sta_for_retry(wlan)
    else:
        was_active = False
        try:
            was_active = bool(wlan.active())
        except Exception:
            pass
        wlan.active(True)
        if not was_active:
            _sleep_with_watchdog(WIFI_DRIVER_SETTLE_S)
    pm_mode, reconnects = _configure_association(wlan)

    scan_details = []
    scan_text = ""
    visible_rssi = {}
    any_configured_visible = False
    last_failure = "reason=connection failed"
    retry_detail = ""
    attempt_history = []

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
                outcome, status = "connect_error", None
            else:
                outcome, status = _wait_for_connection(wlan, timeout_s)
            attempt_history.append(
                "%s:%s:%s"
                % (
                    _ssid_text(ssid),
                    "retry" if retry_used else "first",
                    status if status is not None else outcome,
                )
            )

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
                    status_detail = (
                        " first_status=%s retry_status=connected outcome=wifi path=retry"
                        % first_status
                    )
                elif retry_detail:
                    status_detail = " " + retry_detail + " outcome=wifi path=fresh"
                else:
                    status_detail = " outcome=wifi path=fresh"
                _set_connection_report(
                    "%s connected=%s rssi=%s%s pm=%s reconnects=%s attempts=%s"
                    % (
                        start_context,
                        report_ssid,
                        rssi if rssi is not None else "unknown",
                        status_detail,
                        pm_mode,
                        reconnects,
                        ",".join(attempt_history),
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

            if not retry_used:
                first_status = status if status is not None else outcome
                print(
                    "wifi_uplink: %s failed (%s); resetting STA for retry"
                    % (ssid, first_status)
                )
                try:
                    import diag_log

                    diag_log.log(
                        "wifi fail %s status=%s retrying once"
                        % (ssid, first_status)
                    )
                except Exception:
                    pass
                wlan = _reset_sta_for_retry(wlan)
                pm_mode, reconnects = _configure_association(wlan)
                retry_used = True
                continue

            if outcome == "negative":
                if _negative_status_retry(status, retry_used):
                    try:
                        import diag_log

                        diag_log.log("wifi early fail %s status=%s" % (ssid, status))
                    except Exception:
                        pass
                if retry_used:
                    retry_detail = "retry_ssid=%s first_status=%s retry_status=%s" % (
                        _ssid_text(ssid),
                        first_status,
                        status,
                    )
                    last_failure = (
                        "reason=status failure %s outcome=fallback pm=%s"
                        % (retry_detail, pm_mode)
                    )
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

            retry_detail = "retry_ssid=%s first_status=%s retry_status=%s" % (
                _ssid_text(ssid),
                first_status,
                outcome,
            )
            last_failure = (
                "reason=%s %s outcome=fallback pm=%s"
                % (outcome, retry_detail, pm_mode)
            )
            print("wifi_uplink: failed connecting to", ssid, outcome)
            try:
                import diag_log

                diag_log.log("wifi timeout %s" % ssid)
            except Exception:
                pass
            break

    scan_details, scan_text = _scan_configured_after_failure(wlan, networks)
    for scanned_key, _scanned_label, scanned_rssi in scan_details:
        visible_rssi[scanned_key] = scanned_rssi
    any_configured_visible = any(
        rssi is not None for rssi in visible_rssi.values()
    )
    try:
        if hasattr(wlan, "deinit"):
            wlan.deinit()
        else:
            wlan.active(False)
    except Exception:
        try:
            wlan.active(False)
        except Exception:
            pass
    if scan_text != "scan=failed" and not any_configured_visible and not retry_detail:
        last_failure = "reason=no configured network visible"
    if attempt_history:
        last_failure += " attempts=" + ",".join(attempt_history)
    _set_connection_report(start_context + " " + last_failure, scan_text)
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
    try:
        if hasattr(wlan, "deinit"):
            wlan.deinit()
        else:
            wlan.active(False)
    except Exception:
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
APPS_SCRIPT_ACCEPTED_REDIRECT_KEY = "_apps_script_redirect_accepted"
SYNTHETIC_LOCATION_MAX_CHARS = 256


def _trusted_apps_script_redirect(method, original_url, status, location):
    """True only for the one TLS hop known to have committed a Sheets POST."""
    if method != "POST" or status not in (301, 302, 303) or not location:
        return False
    try:
        original_host, original_port, _path, original_https = split_url(original_url)
        target_host, target_port, _path, target_https = split_url(location)
    except (TypeError, ValueError):
        return False
    target_host = target_host.lower()
    return (
        original_https
        and original_port == 443
        and original_host.lower() == "script.google.com"
        and target_https
        and target_port == 443
        and target_host == "script.googleusercontent.com"
    )


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
        accept_apps_script_post_redirect=False,
    ):
        import socket

        redirect_count = _redirect_count
        cookie = _cookie
        current_headers = dict(headers or {})
        original_url = url
        original_method = method

        while True:
            _prepare_tls_heap()
            set_request_power_mode(idle=False)
            host, port, path, is_https = split_url(url)

            request_headers = dict(current_headers)
            request_headers["Host"] = host
            request_headers.setdefault("Connection", "close")
            request_headers.setdefault("User-Agent", "boat-monitor-pico")
            if cookie:
                request_headers["Cookie"] = cookie

            body_bytes = b""
            if body is not None:
                body_bytes = body if isinstance(body, bytes) else body.encode()
                request_headers["Content-Length"] = str(len(body_bytes))

            request_lines = ["%s %s HTTP/1.1" % (method, path)]
            for key, value in request_headers.items():
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
                    sock = _wrap_tls_socket(sock, host)
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
            # HTTP sockets are per-request. Leave the association up in an idle
            # power mode so dock standby can reuse it without a cold association.
            set_request_power_mode(idle=True)

            if status not in REDIRECT_STATUSES:
                return status, response_body, url
            location = resp_headers.get("location")
            if not location:
                raise WifiError(
                    "redirect (status %s) with no Location header from %s"
                    % (status, url)
                )
            if (
                accept_apps_script_post_redirect
                and redirect_count == 0
                and _trusted_apps_script_redirect(
                    original_method, original_url, status, location
                )
            ):
                return status, {
                    APPS_SCRIPT_ACCEPTED_REDIRECT_KEY: True,
                    "status": status,
                    "location": location[:SYNTHETIC_LOCATION_MAX_CHARS],
                }, url
            if redirect_count >= MAX_REDIRECTS:
                raise WifiError("too many redirects starting from %s" % url)
            print("wifi_uplink: following redirect ->", location)

            set_cookie = resp_headers.get("set-cookie")
            if set_cookie:
                cookie = _cookie_from_set_cookie(set_cookie)
            if status in (307, 308):
                current_headers = dict(current_headers)
            else:
                method, body, current_headers = "GET", None, {}

            url = location
            redirect_count += 1

            # A redirect can leave a complete response, parsed header strings,
            # request bytes, and a closed TLS wrapper live at once. Release all
            # per-hop references and reclaim them before opening the next TLS
            # connection on the constrained Pico heap.
            sock = None
            response = None
            response_body = None
            resp_headers = None
            request_text = None
            request_lines = None
            request_headers = None
            body_bytes = None
            addr = None
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            _feed_watchdog_if_due()

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

        _prepare_tls_heap()
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
                sock = _wrap_tls_socket(sock, host)
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
                    chunk = sock.recv(min(512, need - got))
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
            sock = None
            _prepare_tls_heap()

    def http_post_json(
        self, url, body_text, timeout_s=20, accept_apps_script_redirect=False
    ):
        """POST JSON, optionally accepting Apps Script's trusted commit redirect.

        The option deliberately returns a synthetic dict with no response body;
        callers must not treat it as a source of commands.
        """
        headers = {"Content-Type": "application/json"}
        status, body, final_url = self._request(
            "POST",
            url,
            body=body_text,
            headers=headers,
            timeout_s=timeout_s,
            accept_apps_script_post_redirect=accept_apps_script_redirect,
        )
        if isinstance(body, dict) and body.get(APPS_SCRIPT_ACCEPTED_REDIRECT_KEY):
            return body
        if status != 200:
            raise WifiError(
                "HTTP status %s after POST (final URL %s) body=%s"
                % (status, final_url, (body or "")[:120])
            )
        return body
