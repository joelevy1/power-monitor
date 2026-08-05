"""
Boat Monitor P2 - SIM7600 GPS helper (Phase 3 in BOAT_MONITOR_P2_PLAN.md).

Refactored out of field_console.py's already-working AT+CGPS / AT+CGPSINFO
handling into a standalone module so other code (sheets_log.py, future BLE
commands, Phase 7 anchor watch) can reuse one tested parser instead of
copy-pasting it. field_console.py's own inline copy is left as-is and
unchanged by this file, to avoid risking its already-working Wi-Fi console.

Usage from the Pico REPL or another module:

    from gps import Gps
    g = Gps()
    g.on()
    fix = g.read(timeout_s=90)   # blocks polling AT+CGPSINFO until a fix or timeout
    print(fix)                  # {"ok": True, "lat": .., "lon": .., "raw": "..."}
    g.off()

read() never raises -- on timeout/no fix it returns {"ok": False, ...},
matching the {"ok": False, "error": ...} shape read_ina260()/read_v50()
already use in ble_service.py, so callers can json.dumps() the result
directly without extra try/except.
"""

import time


def gps_to_decimal(value, hemi):
    """Convert one NMEA-style ddmm.mmmm(mm) field + hemisphere to decimal degrees."""
    if not value:
        return None
    dot = value.find(".")
    if dot < 0:
        return None
    deg_digits = dot - 2
    try:
        deg = int(value[:deg_digits])
        mins = float(value[deg_digits:])
    except ValueError:
        return None
    dec = deg + mins / 60.0
    if hemi in ("S", "W"):
        dec = -dec
    return dec


def parse_cgpsinfo(text):
    """Parse one AT+CGPSINFO response. Returns (lat, lon, raw_line)."""
    text = text.replace("\r", "\n")
    line = ""
    for candidate in text.split("\n"):
        candidate = candidate.strip()
        if candidate.startswith("+CGPSINFO:"):
            line = candidate
            break

    if not line:
        return None, None, ""

    payload = line.split(":", 1)[1].strip()
    parts = payload.split(",")
    if len(parts) < 4 or not parts[0] or not parts[2]:
        return None, None, line

    lat = gps_to_decimal(parts[0], parts[1])
    lon = gps_to_decimal(parts[2], parts[3])
    return lat, lon, line


class Gps:
    def __init__(self, uart=None):
        # Imported here (not at module level) so gps_to_decimal()/parse_cgpsinfo()
        # above stay importable and unit-testable on a PC without MicroPython's
        # machine module -- see test_gps_parser.py.
        if uart is None:
            from machine import Pin, UART
            import config as cfg

            uart = UART(1, baudrate=cfg.MODEM_BAUD, tx=Pin(cfg.PIN_UART_TX), rx=Pin(cfg.PIN_UART_RX))
        self.uart = uart
        self.started = False

    def _send(self, cmd, timeout_ms=5000):
        while self.uart.any():
            self.uart.read()
        self.uart.write((cmd + "\r\n").encode())
        start = time.ticks_ms()
        buf = b""
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                buf += self.uart.read()
                if b"\r\nOK\r\n" in buf or b"\r\nERROR\r\n" in buf:
                    break
            time.sleep(0.05)
        return buf.decode("utf-8", "ignore").strip()

    def on(self):
        """Start the GPS receiver. Safe to call again if already started."""
        resp = self._send("AT+CGPS=1,1")
        self.started = "OK" in resp
        return self.started

    def off(self):
        self._send("AT+CGPS=0")
        self.started = False

    def read(self, timeout_s=90, poll_interval_s=5):
        """Poll AT+CGPSINFO until a fix is found or timeout_s elapses.

        Does not call on() itself -- call it first (Phase 3.5/3.6: turn GPS
        on once after NETOPEN, read, then off() before CPWROFF/sleep).
        """
        start = time.ticks_ms()
        raw = ""
        while time.ticks_diff(time.ticks_ms(), start) < timeout_s * 1000:
            raw = self._send("AT+CGPSINFO")
            lat, lon, line = parse_cgpsinfo(raw)
            if lat is not None and lon is not None:
                return {"ok": True, "lat": lat, "lon": lon, "raw": line}
            time.sleep(poll_interval_s)
        return {"ok": False, "lat": None, "lon": None, "raw": raw, "error": "no fix within %ds" % timeout_s}
