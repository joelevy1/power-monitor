import struct
import time
import bluetooth
import machine
import micropython
from micropython import const

try:
    import ujson as json
except ImportError:
    import json

import auto_log
import ble_policy
from boat_status import (
    INA219,
    INA260,
    current_mode,
    i2c_bus,
    input_on,
    read_ina260,
    read_status,
    read_v50,
)
from log_session import _wifi_uplink_configured
from log_session import log_power_and_gps as _log_power_and_gps
from wifi_uplink import ensure_wifi_off


# Faster connectable advertising (µs). 128 ms is aggressive but helps iOS find/connect.
BLE_ADV_INTERVAL_US = 128000
BLE_ADV_REFRESH_MS = 15000
BLE_ADV_FAILURE_RESET_COUNT = 3
BLE_NOTIFY_FAILURE_LIMIT = 3
BLE_AUTO_LOG_RECYCLE_HEAP_BYTES = 40000
BLE_CONNECT_MIN_HEAP_BYTES = 40000
BLE_LOG_COMMAND_DEADLINE_MS = 180000
# Supervision timeout for connection parameter update (units of 10 ms).
BLE_SUPERVISION_TIMEOUT = 2000

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

_FLAG_READ = const(0x0002)
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

SERVICE_UUID = bluetooth.UUID("7e400001-b5a3-f393-e0a9-e50e24dcca9e")
STATUS_UUID = bluetooth.UUID("7e400002-b5a3-f393-e0a9-e50e24dcca9e")
COMMAND_UUID = bluetooth.UUID("7e400003-b5a3-f393-e0a9-e50e24dcca9e")


def log_power_and_gps(
    note,
    on_progress=None,
    gps_timeout_s=20,
    prefer_wifi=True,
    ble_monitor=None,
):
    """Backward-compatible BLE wrapper around the radio-independent logger."""
    wifi_handoff = None
    if ble_monitor is not None:
        wifi_handoff = lambda fn: _wifi_handoff_log(ble_monitor, fn)
    return _log_power_and_gps(
        note,
        on_progress=on_progress,
        gps_timeout_s=gps_timeout_s,
        prefer_wifi=prefer_wifi,
        ble_monitor=ble_monitor,
        wifi_handoff=wifi_handoff,
    )


def _wifi_handoff_log(ble_monitor, fn):
    """Drop BLE briefly so the shared radio can join Wi-Fi STA."""
    ble_monitor.ble.active(False)
    time.sleep_ms(300)
    try:
        return fn()
    finally:
        ensure_wifi_off()
        try:
            ble_monitor.ble.active(True)
        except OSError as exc:
            print("ERROR: ble.active(True) after Wi-Fi log failed:", exc)
            raise
        ble_monitor.advertise()
        ble_monitor.update_status()


def check_gps_fix(timeout_s=30, poll_interval_s=2):
    """Check the SIM7600 GPS receiver for a fix without opening cellular data.

    This is intentionally separate from the "signal" command: signal checks
    modem/SIM/network registration and CSQ; GPS checks AT+CGPSINFO and, on a
    fix, returns coordinates plus a Maps URL for the app to open.
    """
    from cellular import Sim7600Modem
    from gps import Gps
    from sheets_log import maps_link_url

    modem = Sim7600Modem()
    modem.ensure_awake()
    modem.check_alive()
    gps = Gps(uart=modem.uart)
    if not gps.on():
        modem.power_off()
        raise OSError("GPS did not start")

    try:
        fix = gps.read(timeout_s=timeout_s, poll_interval_s=poll_interval_s)
    finally:
        gps.off()
        modem.power_off()

    if fix.get("ok"):
        lat = fix.get("lat")
        lon = fix.get("lon")
        return "gps: fix (lat: %.7f, lon: %.7f, maps: %s)" % (lat, lon, maps_link_url(lat, lon))

    return "gps: no_fix (%s)" % (fix.get("error") or fix.get("raw") or "no fix")


def advertising_payload(name=None, service_uuid=None):
    """Build one AD packet (max 31 bytes). Raises ValueError if too long.

    Legacy BLE advertising PDUs are capped at 31 bytes. Flags (3) + a full
    128-bit service UUID (18) = 21 bytes, leaving no room for the device
    name in the same packet — name (13 bytes) would push the total to 34
    bytes, which silently breaks central-side name/UUID matching (generic
    scanners like LightBlue still show the device since they don't filter
    by name/UUID, which is why they can "see" a device the app can't find).
    Pass name and service_uuid in *separate* calls — one for adv_data
    (service_uuid), one for resp_data (name) — see BoatMonitorBle.__init__.
    """
    payload = bytearray()

    def append(adv_type, value):
        payload.extend(struct.pack("BB", len(value) + 1, adv_type))
        payload.extend(value)

    append(0x01, b"\x06")
    if service_uuid:
        append(0x07, bytes(bluetooth.UUID(service_uuid)))
    if name:
        append(0x09, name.encode())

    if len(payload) > 31:
        raise ValueError("adv payload %d bytes > 31" % len(payload))
    return payload


class BoatMonitorBle:
    def __init__(self):
        ensure_wifi_off()

        self.ble = bluetooth.BLE()
        try:
            self.ble.active(True)
        except OSError as exc:
            print("ERROR: ble.active(True) failed:", exc)
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise

        if not self.ble.active():
            print("ERROR: BLE radio did not activate (ble.active() is False)")
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise OSError("BLE radio did not activate")

        self.ble.irq(self.irq)
        self.connections = set()
        self.command_result = None
        self._cellular_busy = False
        self._last_advertise_ms = time.ticks_ms()
        self._advertise_failures = 0
        self._notify_failures = {}
        self._command_deadline_timer = None

        service = (
            SERVICE_UUID,
            (
                (STATUS_UUID, _FLAG_READ | _FLAG_NOTIFY),
                (COMMAND_UUID, _FLAG_WRITE),
            ),
        )

        try:
            ((self.status_handle, self.command_handle),) = self.ble.gatts_register_services((service,))
        except OSError as exc:
            print("ERROR: gatts_register_services failed:", exc)
            print("Try a full power cycle (unplug ~10s) -- a soft reboot may not clear radio state.")
            raise

        try:
            self.payload = advertising_payload(service_uuid="7e400001-b5a3-f393-e0a9-e50e24dcca9e")
            self.scan_resp_payload = advertising_payload(name="BoatMonitor")
        except ValueError as exc:
            print("ERROR: advertising payload:", exc)
            raise

        print(
            "BLE adv payload: %d bytes, scan response: %d bytes (limit 31 each)"
            % (len(self.payload), len(self.scan_resp_payload))
        )
        self.update_status()
        self.advertise()
        try:
            import status_led

            status_led.set_mode("ble")
        except Exception:
            pass

        # Auto-logging schedule
        # from boot rather than logging immediately -- avoids a cellular
        # round-trip firing on every single reboot during development
        # regardless of engine state. last_auto_log_mode stays None until
        # the first tick, which is what keeps should_log_now() from
        # forcing an immediate "log on engine start" the very first time
        # it's called (see auto_log.py's docstring).
        self._last_auto_log_ms = time.ticks_ms()
        self._last_auto_log_mode = None
        self._gpio_low_accum_s = 0

    def irq(self, event, data):
        # BLE IRQ callbacks must stay quick and must not re-enter the BLE
        # stack or do blocking hardware I/O (I2C reads, JSON work, etc) --
        # doing so can corrupt the stack's internal state and hard-crash the
        # board (seen on-device as Thonny's USB-serial link dying entirely:
        # "ConnectionError: EOF"). micropython.schedule() defers the actual
        # work to run outside the IRQ context, where all of that is safe.
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, addr_type, addr = data
            print("BLE connected", conn_handle)
            self.connections.add(conn_handle)
            self._gpio_low_accum_s = 0
            # Conn params before any I2C/status notify — iOS drops ~1–2s if the
            # link is busy with sensor reads before supervision is extended.
            self._schedule(self._scheduled_on_connect, conn_handle)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, addr_type, addr = data
            print("BLE disconnected", conn_handle)
            self.connections.discard(conn_handle)
            self._notify_failures.pop(conn_handle, None)
            try:
                import status_led

                status_led.set_mode("ble")
            except Exception:
                pass
            self.advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if value_handle == self.command_handle:
                raw = self.ble.gatts_read(self.command_handle)
                text = raw.decode("utf-8", "ignore").strip()
                self._schedule(self._scheduled_handle_command, text)

    def _schedule(self, fn, arg):
        try:
            micropython.schedule(fn, arg)
        except RuntimeError as exc:
            # Scheduler queue full or nested schedule call -- drop this one
            # rather than crash; the periodic run() loop will still update
            # status on its own 2s cadence.
            print("schedule failed (dropped):", exc)

    def _scheduled_on_connect(self, conn_handle):
        try:
            import status_led

            status_led.set_mode("ble_link")
        except Exception:
            pass
        self._request_conn_params(conn_handle)
        try:
            time.sleep_ms(600)
        except AttributeError:
            time.sleep(0.6)
        # Small notify before MTU/param settle can drop iOS/LightBlue in ~1–2 s.
        self.update_status(sensors=False)
        try:
            import gc

            gc.collect()
            heap_free = gc.mem_free()
        except Exception:
            heap_free = BLE_CONNECT_MIN_HEAP_BYTES
        if heap_free < BLE_CONNECT_MIN_HEAP_BYTES:
            self.command_result = "rebooting_low_heap:%s" % heap_free
            self.update_status(sensors=False)
            try:
                time.sleep_ms(500)
            except AttributeError:
                time.sleep(0.5)
            machine.reset()
            return
        try:
            time.sleep_ms(400)
        except AttributeError:
            time.sleep(0.4)
        self.update_status(sensors=True)

    def _scheduled_conn_params(self, conn_handle):
        self._request_conn_params(conn_handle)

    def _request_conn_params(self, conn_handle):
        """Ask for a longer supervision timeout so brief radio stalls do not drop the phone."""
        try:
            # conn_interval in 1.25 ms units; supervision_timeout in 10 ms units.
            self.ble.gap_conn_update(conn_handle, 16, 32, 0, BLE_SUPERVISION_TIMEOUT)
            print(
                "BLE conn params requested interval=16-32 latency=0 supervision=%ss"
                % (BLE_SUPERVISION_TIMEOUT * 0.01)
            )
        except Exception as exc:
            print("BLE gap_conn_update:", exc)

    def _scheduled_update_status(self, _arg):
        self.update_status()

    def _scheduled_handle_command(self, raw):
        self.handle_command(raw)

    def _command_deadline_expired(self, _timer):
        # Timer callback runs outside the blocked network call. Keep it
        # allocation-free: the next boot reports/recoveries provide evidence.
        machine.reset()

    def _arm_command_deadline(self, timeout_ms):
        self._cancel_command_deadline()
        try:
            try:
                timer = machine.Timer(-1)
            except TypeError:
                timer = machine.Timer()
            timer.init(
                mode=machine.Timer.ONE_SHOT,
                period=int(timeout_ms),
                callback=self._command_deadline_expired,
            )
            self._command_deadline_timer = timer
        except Exception as exc:
            print("BLE command deadline unavailable:", exc)

    def _cancel_command_deadline(self):
        timer = self._command_deadline_timer
        self._command_deadline_timer = None
        if timer is not None:
            try:
                timer.deinit()
            except Exception:
                pass

    def advertise(self, refresh=False):
        self._last_advertise_ms = time.ticks_ms()
        try:
            if refresh:
                self.ble.gap_advertise(None)
                try:
                    time.sleep_ms(20)
                except AttributeError:
                    time.sleep(0.02)
            self.ble.gap_advertise(
                BLE_ADV_INTERVAL_US,
                adv_data=self.payload,
                resp_data=self.scan_resp_payload,
            )
        except OSError as exc:
            self._advertise_failures += 1
            # Don't let a transient radio error crash the whole service — main.py's
            # blanket except would fall back to WiFi mode with no clear diagnostic.
            print(
                "ERROR: gap_advertise failed (%d/%d):"
                % (self._advertise_failures, BLE_ADV_FAILURE_RESET_COUNT),
                exc,
            )
            if self._advertise_failures >= BLE_ADV_FAILURE_RESET_COUNT:
                try:
                    import diag_log

                    diag_log.log("BLE advertising failed repeatedly; resetting")
                except Exception:
                    pass
                time.sleep(0.2)
                machine.reset()
            return False
        self._advertise_failures = 0
        print("BLE advertising as BoatMonitor")
        return True

    def update_status(self, sensors=None):
        if sensors is None:
            sensors = not self.connections
        status = read_status(self.command_result, sensors=sensors)
        data = json.dumps(status).encode()
        self.ble.gatts_write(self.status_handle, data)
        dropped_stale = False
        for conn in tuple(self.connections):
            try:
                self.ble.gatts_notify(conn, self.status_handle, data)
                self._notify_failures.pop(conn, None)
            except Exception as exc:
                print("Notify failed (%d bytes):" % len(data), exc)
                failures = self._notify_failures.get(conn, 0) + 1
                self._notify_failures[conn] = failures
                if failures >= BLE_NOTIFY_FAILURE_LIMIT:
                    print("BLE notify failed repeatedly; dropping stale handle", conn)
                    self.connections.discard(conn)
                    self._notify_failures.pop(conn, None)
                    dropped_stale = True
        if not self.connections and self._notify_failures:
            self._notify_failures = {}
        if dropped_stale and not self.connections:
            self.advertise()
        return status

    def handle_command(self, raw):
        print("BLE command:", raw)
        try:
            cmd = json.loads(raw).get("cmd", raw)
        except Exception:
            cmd = raw

        if cmd == "refresh":
            self.command_result = "refreshing"
            self.update_status(sensors=False)
            self.command_result = "refreshed"
            self.update_status(sensors=True)
        elif cmd == "reboot":
            self.command_result = "rebooting"
            self.update_status()
            time.sleep(0.5)
            machine.reset()
        elif cmd in ("wifi", "start_wifi"):
            with open("wifi_mode.txt", "w") as f:
                f.write("1")
            self.command_result = "starting_wifi"
            self.update_status()
            time.sleep(0.5)
            machine.reset()
        elif cmd in ("ota", "ota_check"):
            # Do not run the full downloader while BLE is active. The BLE
            # service and status JSON already consume enough heap that large
            # OTA files can fail with MemoryError. Reboot instead and let
            # main.py's AUTO_OTA_ON_BOOT run the update before BLE starts.
            self.command_result = "ota_rebooting"
            self.update_status()
            try:
                import remote_boot_config

                remote_boot_config.set_pending_ota(True)
            except Exception:
                pass
            time.sleep(0.5)
            machine.reset()
        elif cmd in ("log", "log_now"):
            if self._cellular_busy:
                self.command_result = "busy_logging"
                self.update_status()
                return
            self.command_result = "logging"
            self.update_status()

            def log_progress(stage):
                self.command_result = stage
                self.update_status()

            mode = read_status().get("mode", "key_on")
            outcome = None
            try:
                self._arm_command_deadline(BLE_LOG_COMMAND_DEADLINE_MS)
                try:
                    import resilience

                    resilience.set_service_hook(
                        lambda: self.update_status(sensors=False)
                    )
                except Exception:
                    pass
                summary = self._log_power_and_gps(
                    note="ble_log_now",
                    on_progress=log_progress,
                    gps_timeout_s=10,
                    prefer_wifi=False,
                )
                outcome = summary
                if "failed" in str(summary).lower():
                    self.command_result = "log_failed: %s" % summary
                else:
                    self.command_result = "logged (%s)" % summary
            except Exception as exc:
                outcome = exc
                self.command_result = "log_failed: %s" % exc
                try:
                    import diag_log

                    diag_log.log("ble_log_now exception %s" % exc)
                except Exception:
                    pass
            finally:
                self._cancel_command_deadline()
                try:
                    import resilience

                    resilience.set_service_hook(None)
                except Exception:
                    pass
            self._remote_after_log(mode, outcome)
            self.update_status()
        elif cmd in ("diag", "upload_diag"):
            if self._cellular_busy:
                self.command_result = "diag_busy: logging in progress"
                self.update_status()
                return
            self.command_result = "diag_uploading"
            self.update_status()
            try:
                import diag_log

                lines = diag_log.recent_lines(12)
                preview = " | ".join(lines[-4:])[:220]
                diag_log.upload_tail_to_events(
                    device=read_status().get("device", "boat-p2"),
                    lines=25,
                    event="ble_diag",
                    prefer_wifi=False,
                )
                self.command_result = "diag_ok: %s" % (preview or "(empty log)")
            except Exception as exc:
                self.command_result = "diag_failed: %s" % exc
            self.update_status()
        elif cmd in ("signal", "modem_status", "cell_status"):
            if self._cellular_busy:
                self.command_result = "signal_busy: logging in progress"
                self.update_status()
                return
            # A lightweight cellular diagnostic -- registration + signal
            # quality only, no AT+NETOPEN/data session -- so it's quick
            # (a few seconds, not the 30-60s a full "log"/"ota" cellular
            # session can take) and safe to run without disrupting
            # anything else. This is the app-side equivalent of the
            # "Waiting for network registration... CSQ: ..." lines Thonny
            # already shows during boot, surfaced through command_result
            # instead of requiring a laptop.
            self.command_result = "checking_signal"
            self.update_status()
            try:
                from cellular import CellularError, Sim7600Modem, one_line

                modem = Sim7600Modem()
                try:
                    modem.check_alive()
                    modem.check_sim()
                    try:
                        modem.wait_for_registration(seconds=15)
                        reg_state = "registered"
                    except CellularError:
                        reg_state = "not registered"
                    csq = one_line(modem.at("AT+CSQ", 2000, quiet=True))
                    self.command_result = "signal: %s (%s)" % (csq, reg_state)
                finally:
                    modem.close_data()
            except Exception as exc:
                self.command_result = "signal_failed: %s" % exc
                try:
                    import diag_log

                    diag_log.log("ble_signal_failed %s" % exc)
                except Exception:
                    pass
            self.update_status()
        elif cmd in ("gps", "check_gps", "gps_status"):
            self.command_result = "checking_gps"
            self.update_status()
            try:
                self.command_result = check_gps_fix()
            except Exception as exc:
                self.command_result = "gps_failed: %s" % exc
            self.update_status()
        else:
            self.command_result = "unknown_command: %s" % cmd
            self.update_status()

    def _remote_after_log(self, mode, outcome):
        try:
            import remote_telemetry

            device = read_status().get("device", "boat-p2")
            remote_telemetry.after_logging_session(
                device, mode, outcome, prefer_wifi=False
            )
        except Exception as exc:
            print("remote_after_log:", exc)

    def _log_power_and_gps(self, note, on_progress=None, gps_timeout_s=20, prefer_wifi=True):
        return log_power_and_gps(
            note,
            on_progress=on_progress,
            gps_timeout_s=gps_timeout_s,
            prefer_wifi=prefer_wifi,
            ble_monitor=self,
        )

    def _maybe_auto_log(self, mode):
        """Called once per run() tick (~2s cadence) with the mode from
        that tick's already-fetched status (avoids a second read_status()
        call -- and its I2C/GPIO reads -- purely to look up the mode again
        here). Checks auto_log.should_log_now() and, when due, performs
        the same Power_Log + GPS_Log cycle as a manual 'Log Now' press,
        just triggered automatically instead of by command.

        Frequent while the engine is on (mode == 'key_on'), much less
        frequent otherwise -- see auto_log.py for the actual intervals
        and reasoning. This intentionally blocks run()'s loop for the
        duration of the cellular round-trip (commonly 10-90s -- modem
        reset + registration + NETOPEN + 1-2 HTTPS POSTs), exactly like
        the manual 'log'/'ota' BLE commands already do: BLE status
        updates/command handling pause during that window rather than
        being skipped or run concurrently, since this codebase is
        single-threaded. If BLE is connected when this fires, the app's
        displayed status will simply look stale for that window instead
        of updating live -- a known, already-accepted trade-off (same as
        pressing "Log Now" or "OTA" manually), not a new one introduced
        here.

        Only runs from ble_service.py's main loop -- does NOT run while
        the Wi-Fi AP fallback console (field_console.py) is active, since
        that module's serve() loop blocks on a plain socket accept with
        no periodic hook to call this from.
        """
        now = time.ticks_ms()
        elapsed_s = time.ticks_diff(now, self._last_auto_log_ms) / 1000

        if not auto_log.should_log_now(mode, elapsed_s, self._last_auto_log_mode):
            self._last_auto_log_mode = mode
            return

        # Stability: do not start a long cellular session while the phone is
        # connected. Manual "Log Now" is fine (user-initiated, cellular-only);
        # background auto-log would block the single-threaded BLE loop for
        # minutes and can overlap scheduled BLE commands (signal/diag) that
        # would otherwise open a second modem session on the same UART.
        if self.connections:
            self._last_auto_log_mode = mode
            return

        self._last_auto_log_mode = mode

        print("Auto-log: mode=%s, elapsed=%.0fs" % (mode, elapsed_s))
        outcome = None
        try:
            # Cellular only while BLE service is up — same as manual "Log Now".
            # prefer_wifi=True would call _wifi_handoff_log(), turn the radio off,
            # and hunt home SSIDs (minutes on the water with no BLE advertising).
            summary = self._log_power_and_gps(note="auto_log", prefer_wifi=False)
            outcome = summary
            self.command_result = "auto_logged (%s)" % summary
            print("Auto-log result:", summary)
        except Exception as exc:
            outcome = exc
            self.command_result = "auto_log_failed: %s" % exc
            print("Auto-log failed:", exc)
        finally:
            # Interval is measured from end of each cycle (modem off), not start.
            self._last_auto_log_ms = time.ticks_ms()
            self._remote_after_log(mode, outcome)
            try:
                import ota_reboot

                ota_reboot.reboot_if_upgrade_pending(source="ble_auto_log")
            except Exception:
                pass
        self.update_status()
        if not self.connections:
            try:
                import gc

                gc.collect()
                heap_free = gc.mem_free()
            except Exception:
                heap_free = BLE_AUTO_LOG_RECYCLE_HEAP_BYTES
            if heap_free < BLE_AUTO_LOG_RECYCLE_HEAP_BYTES:
                try:
                    import diag_log

                    diag_log.log(
                        "BLE auto-log heap %s < %s; rebooting to reclaim modules"
                        % (heap_free, BLE_AUTO_LOG_RECYCLE_HEAP_BYTES)
                    )
                except Exception:
                    pass
                time.sleep(0.3)
                machine.reset()

    def run(self):
        while True:
            tick_s = 5 if self.connections else 2
            if (
                not self.connections
                and time.ticks_diff(
                    time.ticks_ms(), self._last_advertise_ms
                )
                >= BLE_ADV_REFRESH_MS
            ):
                self.advertise(refresh=True)
            hold_s = ble_policy.gpio_off_hold_s()
            if ble_policy.ble_latched():
                self._gpio_low_accum_s = 0
            elif not ble_policy.ble_inputs_on():
                self._gpio_low_accum_s += tick_s
            else:
                self._gpio_low_accum_s = 0

            if self._gpio_low_accum_s >= hold_s:
                print(
                    "BLE GPIO off for %.0fs (hold %ss) — rebooting to standby"
                    % (self._gpio_low_accum_s, hold_s)
                )
                time.sleep(0.3)
                machine.reset()

            status = self.update_status(sensors=not self.connections)
            self._maybe_auto_log(status["mode"])
            if not self.connections:
                try:
                    import remote_telemetry

                    remote_telemetry.maybe_boat_heartbeat(
                        status.get("device", "boat-p2"),
                        status["mode"],
                        prefer_wifi=False,
                    )
                except Exception:
                    pass
            try:
                import resilience

                resilience.feed_watchdog()
            except Exception:
                pass
            try:
                import status_led

                status_led.tick()
            except Exception:
                pass
            time.sleep(tick_s)


def main():
    try:
        import resilience

        resilience.enable_watchdog()
    except Exception as exc:
        print("BLE watchdog unavailable:", exc)
    BoatMonitorBle().run()


if __name__ == "__main__":
    main()
