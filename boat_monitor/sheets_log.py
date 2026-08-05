"""
Boat Monitor P2 - log rows to Google Sheets (Phase 2 in
BOAT_MONITOR_P2_PLAN.md), via the Apps Script Web App in
boat_monitor/apps_script/Code.gs (see APPS_SCRIPT_SETUP.md to deploy it).

Prefers Wi-Fi (wifi_uplink.py) when a known network is configured and
reachable, falling back to the cellular SIM7600 modem (cellular.py)
otherwise -- same fallback pattern as ota.py, and the same hardware
caveat: Wi-Fi and BLE share one radio on the Pico W and cannot run at the
same time. Only call ensure_data() here when BLE is NOT active (bench
testing via sheets_log_test.py, or before ble_service.main() starts -- do
not call this from a live BLE session without stopping BLE first).

Usage from the Pico:

    from sheets_log import SheetsLogger
    logger = SheetsLogger()
    logger.ensure_data()                                    # Wi-Fi or cellular
    logger.log_row("Power_Log", {"device": "boat-p2", "engine_v": 12.6})
    logger.log_gps("boat-p2", 12.34, -98.76)
    logger.close_data()                                     # Wi-Fi disconnect or cellular teardown

Always call close_data() when done (Phase 2.4/2.11) -- mirrors
modem_shutdown()/CPWROFF discipline used elsewhere in this codebase.
"""

try:
    import ujson as json
except ImportError:
    import json

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
    def __init__(self, url=None, token=None, prefer_wifi=True):
        self.url = url if url is not None else _config_value("GOOGLE_APPS_SCRIPT_URL")
        self.token = token if token is not None else _config_value("SHEETS_POST_TOKEN")
        if not self.url:
            raise SheetsLogError(
                "Missing GOOGLE_APPS_SCRIPT_URL -- set it in boat_monitor/secrets.py "
                "(see APPS_SCRIPT_SETUP.md)"
            )

        self.prefer_wifi = prefer_wifi
        self._cellular = None  # created lazily, only if the cellular path is used
        self._data_open = False
        self._wifi_ssid = None

    def ensure_data(self, registration_timeout_s=60):
        """Bring up an internet connection: Wi-Fi first if configured and
        reachable (see wifi_uplink.py), cellular otherwise (cellular.py --
        checks the modem responds, checks the SIM, waits for network
        registration, then opens data; raises SheetsLogError with a
        specific reason on failure instead of one generic message).
        """
        if self._data_open:
            return

        if self.prefer_wifi:
            try:
                import wifi_uplink

                ssid = wifi_uplink.connect(timeout_s=15)
                if ssid:
                    print("SheetsLogger: using Wi-Fi (%s)" % ssid)
                    self._wifi_ssid = ssid
                    self._data_open = True
                    return
            except Exception as exc:
                print("SheetsLogger: Wi-Fi attempt failed, falling back to cellular:", exc)

        from cellular import CellularError, Sim7600Modem

        self._cellular = Sim7600Modem()
        try:
            self._cellular.ensure_data(registration_timeout_s=registration_timeout_s)
        except CellularError as exc:
            raise SheetsLogError(str(exc))
        self._data_open = True

    def close_data(self):
        """Tear down whichever transport is open. Always call this when
        done (Phase 2.4/2.11).
        """
        if self._wifi_ssid:
            try:
                import wifi_uplink

                wifi_uplink.disconnect()
            except Exception as exc:
                print("SheetsLogger: wifi_uplink.disconnect() warning:", exc)
            self._wifi_ssid = None
            self._data_open = False
            return

        if self._cellular is not None:
            self._cellular.close_data()
        self._data_open = False

    def log_row(self, tab, data):
        """POST one row to the given Sheets tab via the Apps Script Web App.

        `data` keys are matched by exact header name in that tab's row 1
        (see sheets_bootstrap.py's TABS) -- unmatched headers are left
        blank, unmatched keys are ignored. Returns the parsed JSON response
        (e.g. {"ok": True, "tab": ..., "row": N}); raises SheetsLogError on
        a non-200 HTTP status or a malformed transport-level response.
        """
        body = {"tab": tab, "token": self.token, "data": data}
        body_text = json.dumps(body)

        if self._wifi_ssid:
            import wifi_uplink

            try:
                response_text = wifi_uplink.WifiHttp().http_post_json(self.url, body_text)
            except wifi_uplink.WifiError as exc:
                raise SheetsLogError(str(exc))
        else:
            from cellular import CellularError

            try:
                response_text = self._cellular.http_post_json(self.url, body_text.encode())
            except CellularError as exc:
                raise SheetsLogError(str(exc))

        try:
            return json.loads(response_text)
        except Exception:
            return {"raw": response_text}

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
