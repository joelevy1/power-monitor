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
    logger.log_gps("boat-p2", 12.34, -98.76)                # known fix -- adds a maps_link column
    logger.log_gps_now("boat-p2")                           # acquires a fresh fix first (cellular only)
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


def maps_link_url(lat, lon):
    """Build a clickable Google Maps URL for a lat/lon pair, or "" if
    either is missing (e.g. no GPS fix yet) -- a blank cell looks cleaner
    in the sheet than a broken link with "None" baked into the query
    string. Google Sheets auto-links plain http(s):// text appended to a
    cell (the same behavior Apps Script's Code.gs sheet.appendRow() uses,
    same as typing a URL into a cell by hand), so no =HYPERLINK() formula
    is needed here -- this plain URL string renders as a clickable link
    on its own.
    """
    if lat is None or lon is None:
        return ""
    return "https://www.google.com/maps?q=%.7f,%.7f" % (lat, lon)


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
        self._used_cellular = False

    def uplink_label(self):
        """SSID string when on Wi-Fi, or 'cellular' after ensure_data()."""
        if self._wifi_ssid:
            return self._wifi_ssid
        if self._used_cellular:
            return "cellular"
        return ""

    def ensure_data(self, registration_timeout_s=60):
        """Bring up an internet connection: Wi-Fi first if configured and
        reachable (see wifi_uplink.py), cellular otherwise (cellular.py --
        checks the modem responds, checks the SIM, waits for network
        registration, then opens data; raises SheetsLogError with a
        specific reason on failure instead of one generic message).
        """
        if self._data_open:
            return

        try:
            import diag_log

            diag_log.log("ensure_data start prefer_wifi=%s" % self.prefer_wifi)
        except Exception:
            pass

        if self.prefer_wifi:
            import wifi_uplink

            nets = wifi_uplink.load_networks()
            if not nets:
                msg = (
                    "no Wi-Fi networks on Pico — need wifi_known_networks.py (OTA) "
                    "or wifi_credentials.py; see wifi_credentials.example.py"
                )
                print("SheetsLogger:", msg)
                try:
                    import diag_log

                    diag_log.log("ensure_data FAIL %s" % msg)
                except Exception:
                    pass
                raise SheetsLogError(msg)
            try:
                ssid = wifi_uplink.connect(timeout_s=15)
                if ssid:
                    print("SheetsLogger: using Wi-Fi (%s)" % ssid)
                    try:
                        import diag_log

                        diag_log.log("ensure_data wifi ok ssid=%s" % ssid)
                    except Exception:
                        pass
                    self._wifi_ssid = ssid
                    self._data_open = True
                    return
            except Exception as exc:
                print("SheetsLogger: Wi-Fi connect failed:", exc)
                try:
                    import diag_log

                    diag_log.log("ensure_data wifi failed %s" % exc)
                except Exception:
                    pass
            msg = "Wi-Fi configured (%d network(s)) but could not connect" % len(nets)
            try:
                import diag_log

                diag_log.log("ensure_data wifi miss %s" % msg)
            except Exception:
                pass
            allow_cell = True
            try:
                import config as cfg

                allow_cell = getattr(cfg, "ALLOW_CELLULAR_WIFI_FALLBACK", True)
            except ImportError:
                pass
            if allow_cell:
                print("SheetsLogger: %s — trying cellular fallback" % msg)
                try:
                    import diag_log

                    diag_log.log("ensure_data wifi miss -> cellular fallback")
                except Exception:
                    pass
            else:
                raise SheetsLogError(msg)

        else:
            try:
                import diag_log

                diag_log.log("ensure_data cellular start timeout=%ss" % registration_timeout_s)
            except Exception:
                pass

            from cellular import CellularError, Sim7600Modem

            self._cellular = Sim7600Modem()
            try:
                self._cellular.ensure_data(registration_timeout_s=registration_timeout_s)
            except CellularError as exc:
                try:
                    import diag_log

                    diag_log.log("ensure_data cellular FAIL %s" % exc)
                except Exception:
                    pass
                raise SheetsLogError(str(exc))
            self._used_cellular = True
            self._data_open = True
            try:
                import diag_log

                diag_log.log("ensure_data cellular ok")
            except Exception:
                pass
            return

        try:
            import diag_log

            diag_log.log("ensure_data cellular start timeout=%ss" % registration_timeout_s)
        except Exception:
            pass

        from cellular import CellularError, Sim7600Modem

        self._cellular = Sim7600Modem()
        try:
            self._cellular.ensure_data(registration_timeout_s=registration_timeout_s)
        except CellularError as exc:
            try:
                import diag_log

                diag_log.log("ensure_data cellular FAIL %s" % exc)
            except Exception:
                pass
            raise SheetsLogError(str(exc))
        self._used_cellular = True
        self._data_open = True
        try:
            import diag_log

            diag_log.log("ensure_data cellular ok")
        except Exception:
            pass

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

        try:
            import diag_log

            diag_log.log("log_row POST tab=%s via=%s" % (tab, self._wifi_ssid or "cellular"))
        except Exception:
            pass

        if self._wifi_ssid:
            import wifi_uplink

            try:
                response_text = wifi_uplink.WifiHttp().http_post_json(self.url, body_text)
            except wifi_uplink.WifiError as exc:
                try:
                    import diag_log

                    diag_log.log("log_row wifi POST FAIL %s" % exc)
                except Exception:
                    pass
                raise SheetsLogError(str(exc))
        else:
            from cellular import CellularError

            try:
                response_text = self._cellular.http_post_json(self.url, body_text.encode())
            except CellularError as exc:
                try:
                    import diag_log

                    diag_log.log("log_row cellular POST FAIL %s" % exc)
                except Exception:
                    pass
                raise SheetsLogError(str(exc))

        try:
            import diag_log

            diag_log.log("log_row POST ok tab=%s len=%d" % (tab, len(response_text or "")))
        except Exception:
            pass

        try:
            return json.loads(response_text)
        except Exception:
            return {"raw": response_text}

    def _apply_remote_from_response(self, response, device_id):
        try:
            from remote_control import apply_from_log_response

            actions, detail = apply_from_log_response(response, device_id=device_id)
            if detail:
                try:
                    self.log_event(device_id, "remote_config", detail)
                except Exception as exc:
                    print("SheetsLogger: remote_config event:", exc)
            return actions
        except Exception as exc:
            print("SheetsLogger: remote_control:", exc)
            return []

    def log_power(self, device, mode, engine, house, v50, note="", fw="", uplink=""):
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
                "v50_a": v50.get("a") if v50 else None,
                "fw": fw,
                "uplink": uplink,
                "note": note,
            },
        )

    def log_gps(self, device, lat, lon, status="fix", note=""):
        return self.log_row(
            "GPS_Log",
            {
                "device": device,
                "lat": lat,
                "lon": lon,
                "maps_link": maps_link_url(lat, lon),
                "status": status,
                "note": note,
            },
        )

    def log_power_and_gps(
        self,
        device,
        mode,
        engine,
        house,
        v50,
        note="",
        fw="",
        gps_timeout_s=20,
        on_progress=None,
    ):
        """One Power_Log row plus a best-effort GPS_Log row. Optional on_progress
        stage strings let BLE/UI show progress while cellular work runs."""
        try:
            import diag_log

            diag_log.log("log_power_and_gps start note=%s" % note)
        except Exception:
            pass
        if on_progress:
            on_progress("logging_modem")
        self.ensure_data()
        if on_progress:
            on_progress("logging_power")
        status_note = note
        power_outcome = "ok"
        last_response = None
        remote_actions = []
        try:
            import diag_log

            diag_log.log("log_power POST")
        except Exception:
            pass
        try:
            last_response = self.log_power(
                device=device,
                mode=mode,
                engine=engine,
                house=house,
                v50=v50,
                note=status_note,
                fw=fw,
                uplink=self.uplink_label(),
            )
            remote_actions = self._apply_remote_from_response(last_response, device)
        except Exception as exc:
            power_outcome = "failed: %s" % exc

        if on_progress:
            on_progress("logging_power_ok")

        gps_outcome = "no_fix"
        if power_outcome != "ok":
            gps_outcome = "skipped_power_failed"
            try:
                import diag_log

                diag_log.log("log_gps skipped (power log failed)")
            except Exception:
                pass
        else:
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            try:
                if on_progress:
                    on_progress("logging_gps")
                if self._wifi_ssid:
                    try:
                        import diag_log

                        diag_log.log("log_gps skipped (wifi uplink, no modem GPS)")
                    except Exception:
                        pass
                    gps_result = self.log_gps(
                        device, None, None, status="no_fix", note=status_note or "wifi uplink"
                    )
                    gps_outcome = "skipped_wifi"
                else:
                    try:
                        import diag_log

                        diag_log.log("log_gps_now start timeout=%ss" % gps_timeout_s)
                    except Exception:
                        pass
                    gps_result = self.log_gps_now(device, timeout_s=gps_timeout_s, note=status_note)
                    gps_outcome = "ok" if gps_result.get("ok") else gps_result.get("error", "no_fix")
                if isinstance(gps_result, dict) and gps_result.get("commands"):
                    remote_actions = self._apply_remote_from_response(gps_result, device)
            except Exception as exc:
                gps_outcome = "failed: %s" % exc

        self._last_remote_actions = remote_actions if power_outcome == "ok" else []
        summary = "power: %s, gps: %s" % (power_outcome, gps_outcome)
        try:
            import diag_log

            diag_log.log("log_power_and_gps done %s actions=%s" % (summary, remote_actions))
        except Exception:
            pass
        return summary

    def log_gps_now(self, device, timeout_s=20, poll_interval_s=2, note=""):
        """Get one GPS fix attempt over the modem's UART and log it to
        GPS_Log (blank lat/lon/maps_link + status="no_fix" if none was
        acquired in time) -- this is what was MISSING before: log_gps()
        existed but nothing ever called it, so GPS_Log stayed empty even
        while Power_Log kept getting rows from the same "log"/"log_now"
        command.

        Cellular-only: GPS is a SIM7600 AT-command feature (AT+CGPS/
        AT+CGPSINFO), not something Wi-Fi provides. Reuses the SAME UART
        object as self._cellular (rather than opening a second UART on
        the same physical pins, which would fight over one peripheral)
        -- safe to interleave with the HTTP AT commands already run by
        ensure_data()/log_row() since AT commands are always
        request/response, one at a time, never concurrent.

        timeout_s defaults to a short 20s (not gps.py's 90s default) so
        a "Log Now" button press stays reasonably responsive -- cold-start
        GPS acquisition, especially with a weak/no GPS antenna, can take
        much longer than that or never succeed at all; this is a quick
        best-effort attempt, not a guarantee of a fix.
        """
        if self._cellular is None:
            from cellular import CellularError, Sim7600Modem

            try:
                self._cellular = Sim7600Modem()
                self._cellular.ensure_awake()
                self._cellular.check_alive()
            except CellularError as exc:
                print("SheetsLogger: GPS skipped —", exc)
                return self.log_gps(
                    device, None, None, status="no_fix", note=note or "modem unavailable"
                )

        from gps import Gps

        gps = Gps(uart=self._cellular.uart)
        gps.on()
        try:
            fix = gps.read(timeout_s=timeout_s, poll_interval_s=poll_interval_s)
        finally:
            gps.off()

        if fix["ok"]:
            return self.log_gps(device, fix["lat"], fix["lon"], status="fix", note=note)
        return self.log_gps(
            device, None, None, status="no_fix", note=note or fix.get("error", "no fix")
        )

    def log_bilge(self, device, channel, state, note=""):
        return self.log_row(
            "Bilge_Log",
            {"device": device, "channel": channel, "state": state, "note": note},
        )

    def log_event(self, device, event, detail=""):
        return self.log_row("Events", {"device": device, "event": event, "detail": detail})
