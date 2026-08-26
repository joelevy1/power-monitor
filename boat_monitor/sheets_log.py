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
    logger.close_data()                                     # policy-aware Wi-Fi/cellular teardown

Always call close_data() when done (Phase 2.4/2.11) -- mirrors
modem_shutdown()/CPWROFF discipline used elsewhere in this codebase.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import secrets
except (ImportError, SyntaxError):
    secrets = None


REMOTE_CONFIG_STATE_PATH = "remote_config_event_state.json"
MAX_EVENT_DETAIL_CHARS = 1500


class SheetsLogError(Exception):
    pass


def _normalized_event_detail(detail):
    """Canonicalize generated semicolon details without changing their meaning."""
    parts = []
    for part in str(detail or "").split(";"):
        part = " ".join(part.strip().split())
        if part:
            parts.append(part)
    return "; ".join(parts)


def _bounded_detail_identity(detail):
    """Bound persistent state while still noticing changes in long details."""
    detail = _normalized_event_detail(detail)
    if len(detail) <= 1400:
        return detail
    checksum = 2166136261
    for char in detail:
        checksum = ((checksum ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return "%d:%08x:%s:%s" % (
        len(detail),
        checksum,
        detail[:600],
        detail[-600:],
    )


def _event_post_succeeded(result):
    if result is False:
        return False
    if isinstance(result, dict) and result.get("ok") is False:
        return False
    return True


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


def append_wifi_fallback_note(note, report, max_chars=600):
    """Append bounded Wi-Fi fallback telemetry to a Power_Log note."""
    if not report:
        return str(note or "")
    suffix = "wifi_fallback " + str(report)
    prefix = str(note or "")
    if not prefix:
        return suffix[:max_chars]
    separator = "; "
    # Reserve some room for the existing note even when a full scan report
    # reaches its bound. The reason leads the report, so tail truncation drops
    # lower-value scan entries first.
    suffix_limit = max_chars - len(separator) - min(40, max_chars // 4)
    suffix = suffix[:suffix_limit]
    room = max_chars - len(separator) - len(suffix)
    return prefix[:room] + separator + suffix


def _config_value(name):
    if secrets is not None:
        value = getattr(secrets, name, "")
        if value:
            return value
    return ""


class SheetsLogger:
    def __init__(
        self,
        url=None,
        token=None,
        prefer_wifi=True,
        keep_wifi_connected=None,
        cellular_control_sync=False,
    ):
        self.url = url if url is not None else _config_value("GOOGLE_APPS_SCRIPT_URL")
        self.token = token if token is not None else _config_value("SHEETS_POST_TOKEN")
        if not self.url:
            raise SheetsLogError(
                "Missing GOOGLE_APPS_SCRIPT_URL -- set it in boat_monitor/secrets.py "
                "(see APPS_SCRIPT_SETUP.md)"
            )

        self.prefer_wifi = prefer_wifi
        # None follows remote dock/standby policy. True/False is an explicit
        # caller request, useful for controlled non-standby sessions.
        self.keep_wifi_connected = keep_wifi_connected
        self._cellular = None  # created lazily, only if the cellular path is used
        self._data_open = False
        self._wifi_ssid = None
        self._used_cellular = False
        self._wifi_fallback_report = ""
        self.cellular_control_sync = bool(cellular_control_sync)
        self._last_power_success = False

    def uplink_label(self):
        """SSID string when on Wi-Fi, or 'cellular' after ensure_data()."""
        if self._wifi_ssid:
            return self._wifi_ssid
        if self._used_cellular:
            if self.cellular_control_sync:
                return "cellular_control_sync"
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
        self._wifi_fallback_report = ""
        if not self.prefer_wifi:
            # A previous dock session may intentionally have left STA up.
            # Cellular policy owns the shared-radio transition and tears it down.
            try:
                import wifi_uplink

                wifi_uplink.disconnect()
            except Exception:
                pass

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
            wifi_report = ""
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
            try:
                wifi_report = (
                    wifi_uplink.get_last_connection_report()
                    or "reason=connection failed"
                )
            except Exception:
                wifi_report = "reason=connection failed"
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

                    diag_log.log(
                        "ensure_data wifi miss -> cellular fallback (modem will wake; fix Wi-Fi on Pico if unintended)"
                    )
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
                import status_led

                status_led.set_cellular_active(True)
            except Exception:
                pass
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
        if self.prefer_wifi:
            self._wifi_fallback_report = wifi_report
        try:
            import status_led

            status_led.set_cellular_active(True)
        except Exception:
            pass
        try:
            import diag_log

            diag_log.log("ensure_data cellular ok")
        except Exception:
            pass

    def close_data(self, mode=None):
        """Tear down whichever transport is open. Always call this when
        done (Phase 2.4/2.11).

        When `mode` is underway (key_on / engine_on) and sheet policy allows,
        cellular stays powered (warm) so the next log skips PWRKEY + registration.
        """
        try:
            import status_led

            status_led.set_cellular_active(False)
        except Exception:
            pass
        if self._wifi_ssid:
            keep_wifi = False
            if self.keep_wifi_connected is not None:
                keep_wifi = bool(self.keep_wifi_connected)
            else:
                try:
                    import remote_boot_config

                    keep_wifi = (
                        self.prefer_wifi
                        and remote_boot_config.effective_keep_wifi_connected_docked(
                            mode
                        )
                    )
                except Exception:
                    keep_wifi = False
            try:
                import wifi_uplink

                if keep_wifi:
                    idle_pm = wifi_uplink.set_request_power_mode(idle=True)
                    print(
                        "SheetsLogger: keeping dock Wi-Fi associated pm=%s"
                        % idle_pm
                    )
                else:
                    wifi_uplink.disconnect()
            except Exception as exc:
                print("SheetsLogger: Wi-Fi close warning:", exc)
            self._wifi_ssid = None
            self._data_open = False
            actions = getattr(self, "_last_remote_actions", None) or []
            self._last_remote_actions = []
            try:
                import ota_events_flush

                ota_events_flush.flush_ota_events(self, device=getattr(self, "_last_device", None) or "boat-p2")
            except Exception as exc:
                print("SheetsLogger: ota events flush:", exc)
            if actions:
                try:
                    import ota_reboot

                    ota_reboot.maybe_reboot_for_ota(
                        actions, source="sheets_log.close_data", prefer_wifi=True
                    )
                except Exception as exc:
                    print("SheetsLogger: ota reboot:", exc)
            try:
                import ota_reboot

                ota_reboot.reboot_if_upgrade_pending(source="sheets_log.close_data_wifi")
            except Exception as exc:
                print("SheetsLogger: upgrade pending reboot:", exc)
            return

        actions = getattr(self, "_last_remote_actions", None) or []
        self._last_remote_actions = []
        device = getattr(self, "_last_device", None) or "boat-p2"
        if actions and ("ota" in actions or "reboot" in actions):
            pass
        try:
            import ota_events_flush

            ota_events_flush.flush_ota_events(self, device=device)
        except Exception as exc:
            print("SheetsLogger: ota events flush:", exc)
        if actions:
            try:
                import ota_reboot

                ota_reboot.maybe_reboot_for_ota(actions, source="sheets_log.close_data")
            except Exception as exc:
                print("SheetsLogger: ota reboot:", exc)
        if self._cellular is not None:
            power_off = True
            try:
                import modem_policy

                power_off = not modem_policy.keep_modem_awake_for_mode(mode)
            except Exception:
                pass
            self._cellular.close_data(power_off=power_off)
        self._data_open = False
        try:
            import ota_reboot

            ota_reboot.reboot_if_upgrade_pending(source="sheets_log.close_data")
        except Exception as exc:
            print("SheetsLogger: upgrade pending reboot:", exc)

    def log_row(self, tab, data):
        """POST one row to the given Sheets tab via the Apps Script Web App.

        `data` keys are matched by exact header name in that tab's row 1
        (see sheets_bootstrap.py's TABS) -- unmatched headers are left
        blank, unmatched keys are ignored. Returns the parsed JSON response
        (e.g. {"ok": True, "tab": ..., "row": N}); raises SheetsLogError on
        a non-200 HTTP status or a malformed transport-level response.
        """
        try:
            import mem_guard

            mem_guard.collect_aggressive()
        except Exception:
            pass

        body = {"tab": tab, "token": self.token, "data": data}
        last_exc = None
        for attempt in range(2):
            try:
                body_text = json.dumps(body)
                break
            except OSError as exc:
                last_exc = exc
                try:
                    import mem_guard

                    if mem_guard.is_enomem(exc) and attempt == 0:
                        mem_guard.collect_aggressive()
                        continue
                except Exception:
                    pass
                raise SheetsLogError(str(exc))
        else:
            raise SheetsLogError(str(last_exc or "json.dumps failed"))

        try:
            import diag_log

            diag_log.log("log_row POST tab=%s via=%s" % (tab, self._wifi_ssid or "cellular"))
        except Exception:
            pass

        for attempt in range(2):
            try:
                if self._wifi_ssid:
                    import wifi_uplink

                    response_text = wifi_uplink.WifiHttp().http_post_json(
                        self.url,
                        body_text,
                        accept_apps_script_redirect=True,
                    )
                else:
                    from cellular import CellularError

                    response_text = self._cellular.http_post_json(self.url, body_text.encode())
                break
            except Exception as exc:
                wrapped = exc
                if self._wifi_ssid:
                    import wifi_uplink

                    if isinstance(exc, wifi_uplink.WifiError):
                        wrapped = SheetsLogError(str(exc))
                else:
                    from cellular import CellularError

                    if isinstance(exc, CellularError):
                        wrapped = SheetsLogError(str(exc))
                try:
                    import mem_guard

                    if attempt == 0 and mem_guard.is_enomem(exc):
                        mem_guard.collect_aggressive()
                        continue
                except Exception:
                    pass
                try:
                    import diag_log

                    diag_log.log("log_row POST FAIL %s" % exc)
                except Exception:
                    pass
                if isinstance(wrapped, SheetsLogError):
                    raise wrapped
                raise SheetsLogError(str(exc))
        else:
            raise SheetsLogError("log_row POST failed after retry")

        try:
            import diag_log

            diag_log.log("log_row POST ok tab=%s len=%d" % (tab, len(response_text or "")))
        except Exception:
            pass

        if isinstance(response_text, dict):
            # Wi-Fi's accepted Apps Script redirect is intentionally bodyless.
            # Return the transport result without ever considering it commands.
            return response_text
        try:
            return json.loads(response_text)
        except Exception:
            return {"raw": response_text}

    @staticmethod
    def _current_fw_label():
        try:
            import version

            return getattr(version, "VERSION", "?")
        except Exception:
            return "?"

    @staticmethod
    def _merge_remote_actions(primary, secondary):
        merged = list(primary or [])
        for action in secondary or []:
            if action not in merged:
                merged.append(action)
        return merged

    def _emit_ota_lifecycle_from_detail(self, device_id, detail, response=None):
        """Post ota_lifecycle on the same open session as remote_config (always works)."""
        if not detail or ("ota_action=1" not in detail and "one_shot=ota" not in detail):
            if not response:
                return
            try:
                from remote_control import apply_from_log_response

                actions, _ = apply_from_log_response(response, device_id=device_id)
                if "ota" not in (actions or []):
                    return
            except Exception:
                return
        try:
            import version

            fw = getattr(version, "VERSION", "?")
        except Exception:
            fw = "?"
        min_fw = ""
        for part in str(detail or "").split(";"):
            part = part.strip()
            if part.startswith("min_fw_version="):
                min_fw = part.split("=", 1)[1].strip()
        if not min_fw and isinstance(response, dict):
            st = (response.get("commands") or {}).get("settings") or {}
            min_fw = str(st.get("min_fw_version") or st.get("target_fw_version") or "")
        lc_detail = "phase=aware; fw=%s; target_fw=%s; source=sheet_post" % (fw, min_fw)
        try:
            import ota_lifecycle

            ota_lifecycle.phase(
                "aware",
                logger=self,
                device=device_id,
                target_fw=min_fw,
                inline=True,
                source="sheet_post",
            )
        except Exception:
            try:
                self.log_event(device_id, "ota_lifecycle", lc_detail[:1500])
            except Exception as exc:
                print("SheetsLogger: ota_lifecycle aware:", exc)

    def _apply_remote_from_response(self, response, device_id, log_event=True):
        if isinstance(response, dict) and response.get(
            "_apps_script_redirect_accepted"
        ):
            return []
        try:
            from remote_control import apply_from_log_response

            actions, detail = apply_from_log_response(response, device_id=device_id)
            if detail and log_event:
                normalized = _normalized_event_detail(detail)
                identity = _bounded_detail_identity(normalized)
                try:
                    import telemetry_dedupe

                    post_remote = telemetry_dedupe.should_post(
                        REMOTE_CONFIG_STATE_PATH, identity
                    )
                except Exception:
                    post_remote = True
                if post_remote:
                    try:
                        result = self.log_event(
                            device_id,
                            "remote_config",
                            normalized[:MAX_EVENT_DETAIL_CHARS],
                        )
                        if _event_post_succeeded(result):
                            try:
                                telemetry_dedupe.mark_posted(
                                    REMOTE_CONFIG_STATE_PATH, identity
                                )
                            except Exception:
                                pass
                    except Exception as exc:
                        print("SheetsLogger: remote_config event:", exc)
                try:
                    self._emit_ota_lifecycle_from_detail(device_id, detail, response=response)
                except Exception as exc:
                    print("SheetsLogger: ota_lifecycle:", exc)
            elif log_event and response:
                self._emit_ota_lifecycle_from_detail(device_id, "", response=response)
            return actions
        except Exception as exc:
            print("SheetsLogger: remote_control:", exc)
            return []

    def log_power(self, device, mode, engine, house, v50, note="", fw="", uplink=""):
        extra = {}
        snap = None
        try:
            import v50_energy

            if v50:
                v50_energy.tick(v50)
            snap = v50_energy.snapshot()
            extra["v50_mah_used"] = snap.get("mah_used")
            extra["v50_pct_remain"] = snap.get("pct_remain")
        except Exception as exc:
            print("SheetsLogger: v50_energy:", exc)

        payload = {
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
            }
        if extra:
            for key, val in extra.items():
                payload[key] = val
        result = self.log_row(
            "Power_Log",
            payload,
        )
        try:
            import ota_lifecycle

            ota_lifecycle.maybe_confirm_after_log(self, device, fw)
        except Exception:
            pass
        if snap:
            try:
                import mem_guard

                if mem_guard.free_bytes() >= mem_guard.low_heap_threshold():
                    self.log_v50_bank(device, v50, snap, note=note)
                else:
                    print("SheetsLogger: skip V50_Bank row (low heap)")
            except Exception as exc:
                print("SheetsLogger: V50_Bank:", exc)
        return result

    def log_v50_bank(self, device, v50, snap, note=""):
        return self.log_row(
            "V50_Bank",
            {
                "device": device,
                "v50_v": v50.get("v") if v50 else None,
                "v50_a": v50.get("a") if v50 else None,
                "mah_used": snap.get("mah_used"),
                "mah_capacity": snap.get("mah_capacity"),
                "pct_remain": snap.get("pct_remain"),
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
        self._last_remote_actions = []
        self._last_power_success = False
        self._last_device = device
        self.ensure_data()
        try:
            import mem_guard

            if mem_guard.heap_ok_for_https_post():
                try:
                    import ota_telemetry

                    ota_telemetry.flush_pending_inline(self, device)
                except Exception:
                    pass
                try:
                    import ota_lifecycle

                    ota_lifecycle.flush_pending(self, device)
                except Exception:
                    pass
            else:
                print("SheetsLogger: skip OTA inline flush (low heap)")
        except Exception:
            pass
        if on_progress:
            on_progress("logging_power")
        status_note = note
        power_note = append_wifi_fallback_note(note, self._wifi_fallback_report)
        power_outcome = "ok"
        last_response = None
        remote_actions = []
        power_remote_actions = []
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
                note=power_note,
                fw=fw,
                uplink=self.uplink_label(),
            )
            self._last_power_success = True
            remote_actions = self._apply_remote_from_response(last_response, device)
            power_remote_actions = list(remote_actions or [])
            if "ota" in (remote_actions or []):
                min_fw = None
                if isinstance(last_response, dict):
                    cmds = (last_response.get("commands") or {})
                    st = cmds.get("settings") or {}
                    min_fw = st.get("min_fw_version") or st.get("target_fw_version")
                try:
                    import ota_lifecycle

                    ota_lifecycle.phase(
                        "aware",
                        logger=self,
                        device=device,
                        target_fw=min_fw,
                        inline=True,
                        source="power_post",
                    )
                except Exception:
                    pass
            if "ota" in (remote_actions or []):
                try:
                    import diag_log

                    diag_log.log("log_power_and_gps skip GPS (OTA pending)")
                except Exception:
                    pass
                self._last_remote_actions = remote_actions
                summary = "power: %s, gps: skipped_ota_pending" % power_outcome
                try:
                    import diag_log

                    diag_log.log("log_power_and_gps done %s actions=%s" % (summary, remote_actions))
                except Exception:
                    pass
                return summary
        except Exception as exc:
            power_outcome = "failed: %s" % exc
            try:
                import diag_log

                diag_log.log("log_power FAILED %s" % exc)
            except Exception:
                pass

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
                    gps_actions = self._apply_remote_from_response(
                        gps_result, device, log_event=False
                    )
                    remote_actions = self._merge_remote_actions(
                        power_remote_actions, gps_actions
                    )
            except Exception as exc:
                gps_outcome = "failed: %s" % exc

        self._last_remote_actions = remote_actions if power_outcome == "ok" else []
        summary = "power: %s, gps: %s" % (power_outcome, gps_outcome)
        try:
            import diag_log

            diag_log.log("log_power_and_gps done %s actions=%s" % (summary, remote_actions))
        except Exception:
            pass
        if power_outcome == "ok":
            try:
                import remote_telemetry

                remote_telemetry.maybe_inline_session_diag(self, device, mode, summary)
            except Exception as exc:
                try:
                    import diag_log

                    diag_log.log("inline session diag skip: %s" % exc)
                except Exception:
                    pass
            try:
                import ota_capability

                ota_capability.report_after_log(
                    device=device,
                    prefer_wifi=bool(self._wifi_ssid),
                    logger=self,
                )
            except Exception as exc:
                try:
                    import diag_log

                    diag_log.log("ota_capability skip: %s" % exc)
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
