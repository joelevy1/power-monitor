"""
Boat Monitor P2 - log rows to Google Sheets over cellular (Phase 2 in
BOAT_MONITOR_P2_PLAN.md), via the Apps Script Web App in
boat_monitor/apps_script/Code.gs (see APPS_SCRIPT_SETUP.md to deploy it).

Reuses the same SIM7600 AT-command patterns already proven in ota.py's
Sim7600Http (ensure_data/at/read_until), extended with the SIMCom HTTP
POST sequence (HTTPDATA + DOWNLOAD prompt) instead of just GET.

Usage from the Pico:

    from sheets_log import SheetsLogger
    logger = SheetsLogger()
    logger.ensure_data()                                    # AT+NETOPEN
    logger.log_row("Power_Log", {"device": "boat-p2", "engine_v": 12.6})
    logger.log_gps(12.34, -98.76)
    logger.close_data()                                     # AT+NETCLOSE

Always call close_data() when done (Phase 2.4/2.11) -- mirrors
modem_shutdown()/CPWROFF discipline used elsewhere in this codebase.
"""

import time

try:
    import ujson as json
except ImportError:
    import json

from machine import Pin, UART

import config as cfg
import ota_config

try:
    import secrets
except ImportError:
    secrets = None


class SheetsLogError(Exception):
    pass


def _config_value(name):
    if secrets is not None:
        value = getattr(secrets, name, "")
        if value:
            return value
    return ""


class SheetsLogger:
    def __init__(self, url=None, token=None):
        self.url = url if url is not None else _config_value("GOOGLE_APPS_SCRIPT_URL")
        self.token = token if token is not None else _config_value("SHEETS_POST_TOKEN")
        if not self.url:
            raise SheetsLogError(
                "Missing GOOGLE_APPS_SCRIPT_URL -- set it in boat_monitor/secrets.py "
                "(see APPS_SCRIPT_SETUP.md)"
            )

        self.uart = UART(
            1,
            baudrate=cfg.MODEM_BAUD,
            tx=Pin(cfg.PIN_UART_TX),
            rx=Pin(cfg.PIN_UART_RX),
        )
        self._data_open = False

    def flush(self):
        while self.uart.any():
            self.uart.read()

    def read_until(self, stop_tokens, timeout_ms):
        start = time.ticks_ms()
        buf = b""
        if isinstance(stop_tokens, str):
            stop_tokens = (stop_tokens,)
        stop_tokens = tuple(token.encode() for token in stop_tokens)

        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                buf += self.uart.read()
                for token in stop_tokens:
                    if token in buf:
                        return buf.decode("utf-8", "ignore")
            time.sleep(0.05)

        return buf.decode("utf-8", "ignore")

    def at(self, cmd, timeout_ms=3000, expect=("\r\nOK\r\n", "\r\nERROR\r\n")):
        print(">>>", cmd)
        self.flush()
        self.uart.write((cmd + "\r\n").encode())
        text = self.read_until(expect, timeout_ms)
        print(text.strip() or "(no response)")
        return text

    def ensure_data(self):
        """Bring up cellular data (same recipe as ota.py's Sim7600Http.ensure_data)."""
        if self._data_open:
            return

        apn = ota_config.OTA_APN
        cid = ota_config.OTA_CONTEXT_ID
        pdp_type = ota_config.OTA_SOCKET_PDP_TYPE

        self.at("AT", 2000)
        self.at("ATE0", 2000)
        self.at('AT+CGDCONT=%d,"IPV6","%s"' % (cid, apn), 3000)
        self.at("AT+CSOCKSETPN=%d,%d" % (cid, pdp_type), 3000)

        self.at("AT+NETOPEN", 30000, expect=("+NETOPEN:", "\r\nERROR\r\n"))
        ip = self.at("AT+IPADDR", 5000)
        if "+IP ERROR" in ip or "ERROR" in ip or not ip.strip():
            raise SheetsLogError("cellular data did not open")

        self._data_open = True

    def close_data(self):
        """Tear down cellular data. Always call this when done (Phase 2.4/2.11)."""
        try:
            self.at("AT+HTTPTERM", 3000)
        except Exception:
            pass
        try:
            self.at("AT+NETCLOSE", 10000)
        except Exception:
            pass
        self._data_open = False

    def _http_post_json(self, url, body_bytes, timeout_ms=60000):
        self.at("AT+HTTPTERM", 3000)
        self.at("AT+HTTPINIT", 5000)
        self.at('AT+HTTPPARA="CID",%d' % ota_config.OTA_CONTEXT_ID, 3000)

        if url.startswith("https://"):
            self.at("AT+HTTPSSL=1", 3000)
        else:
            self.at("AT+HTTPSSL=0", 3000)

        self.at('AT+HTTPPARA="URL","%s"' % url, 5000)
        self.at('AT+HTTPPARA="CONTENT","application/json"', 3000)

        download_prompt = self.at(
            "AT+HTTPDATA=%d,10000" % len(body_bytes),
            5000,
            expect=("DOWNLOAD", "\r\nERROR\r\n"),
        )
        if "DOWNLOAD" not in download_prompt:
            self.at("AT+HTTPTERM", 3000)
            raise SheetsLogError("modem did not prompt DOWNLOAD for HTTPDATA")

        print(">>> (writing %d bytes of JSON body)" % len(body_bytes))
        self.flush()
        self.uart.write(body_bytes)
        self.read_until(("\r\nOK\r\n", "\r\nERROR\r\n"), 5000)

        action = self.at("AT+HTTPACTION=1", timeout_ms, expect=("+HTTPACTION:", "\r\nERROR\r\n"))
        status, length = self._parse_http_action(action)
        if status != 200:
            self.at("AT+HTTPTERM", 3000)
            raise SheetsLogError("HTTP status %s posting to %s" % (status, url))

        if length <= 0:
            self.at("AT+HTTPTERM", 3000)
            return {}

        raw = self.at(
            "AT+HTTPREAD=0,%d" % length,
            max(10000, length * 4),
            expect=("\r\nOK\r\n", "\r\nERROR\r\n"),
        )
        self.at("AT+HTTPTERM", 3000)
        response_text = self._parse_http_read(raw)
        try:
            return json.loads(response_text)
        except Exception:
            return {"raw": response_text}

    def _parse_http_action(self, text):
        marker = "+HTTPACTION:"
        if marker not in text:
            raise SheetsLogError("missing HTTPACTION response")
        line = text.split(marker, 1)[1].splitlines()[0].strip()
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            raise SheetsLogError("bad HTTPACTION response: %s" % line)
        return int(parts[1]), int(parts[2])

    def _parse_http_read(self, text):
        marker = "+HTTPREAD:"
        if marker not in text:
            raise SheetsLogError("missing HTTPREAD response")

        after = text.split(marker, 1)[1]
        first_newline = after.find("\n")
        if first_newline < 0:
            raise SheetsLogError("bad HTTPREAD response")

        data = after[first_newline + 1 :]
        ok_pos = data.rfind("\r\nOK")
        if ok_pos >= 0:
            data = data[:ok_pos]
        return data.lstrip("\r\n")

    def log_row(self, tab, data):
        """POST one row to the given Sheets tab via the Apps Script Web App.

        `data` keys are matched by exact header name in that tab's row 1
        (see sheets_bootstrap.py's TABS) -- unmatched headers are left
        blank, unmatched keys are ignored. Returns the parsed JSON response
        (e.g. {"ok": True, "tab": ..., "row": N}); raises SheetsLogError on
        a non-200 HTTP status or a malformed modem response.
        """
        body = {"tab": tab, "token": self.token, "data": data}
        body_bytes = json.dumps(body).encode()
        return self._http_post_json(self.url, body_bytes)

    def log_power(self, device, mode, engine, house, v50, note=""):
        return self.log_row(
            "Power_Log",
            {
                "device": device,
                "mode": mode,
                "engine_v": engine.get("v") if engine else None,
                "engine_a": engine.get("a") if engine else None,
                "house_v": house.get("v") if house else None,
                "house_a": house.get("a") if house else None,
                "v50_v": v50.get("v") if v50 else None,
                "note": note,
            },
        )

    def log_gps(self, device, lat, lon, status="fix", note=""):
        return self.log_row(
            "GPS_Log",
            {"device": device, "lat": lat, "lon": lon, "status": status, "note": note},
        )

    def log_bilge(self, device, channel, state, note=""):
        return self.log_row(
            "Bilge_Log",
            {"device": device, "channel": channel, "state": state, "note": note},
        )

    def log_event(self, device, event, detail=""):
        return self.log_row("Events", {"device": device, "event": event, "detail": detail})
