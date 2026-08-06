import time
import socket
import network
import machine
from machine import I2C, Pin, UART
import config as cfg

try:
    import _thread
except Exception:
    _thread = None

AP_NAME = "BoatMonitor"
AP_PASSWORD = "boatmonitor"


class INA260:
    REG_CURRENT = 0x01
    REG_VOLTAGE = 0x02
    REG_POWER = 0x03

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address

    def _read16(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 32767:
            raw -= 65536
        return raw

    def read_current_a(self):
        return self._read16(self.REG_CURRENT) * 1.25 / 1000

    def read_voltage_v(self):
        return self._read16(self.REG_VOLTAGE) * 1.25 / 1000

    def read_power_w(self):
        raw = self._read16(self.REG_POWER)
        if raw < 0:
            raw = (raw + 65536) % 65536
        return raw * 10 / 1000


class INA219:
    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address
        self._write(0x00, 0x399F)
        self._write(0x05, 4096)

    def _write(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, value.to_bytes(2, "big"))

    def _read(self, reg):
        return int.from_bytes(self.i2c.readfrom_mem(self.addr, reg, 2), "big")

    def read_bus_voltage_v(self):
        return (self._read(0x02) >> 3) * 0.004

    def read_current_ma(self):
        raw = self._read(0x04)
        if raw > 32767:
            raw -= 65536
        return abs(raw * 0.1)


def i2c_bus(sda, scl, bus_id):
    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=100000)


def safe(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def url_decode(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1 : i + 3], 16))
                i += 3
            except Exception:
                out += s[i]
                i += 1
        else:
            out += s[i]
            i += 1
    return out


def parse_urlencoded(body):
    data = {}
    for part in body.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            data[url_decode(k)] = url_decode(v)
    return data


def read_ina260_values(label, sda, scl, bus_id, addr):
    try:
        sensor = INA260(i2c_bus(sda, scl, bus_id), addr)
        v = sensor.read_voltage_v()
        a = sensor.read_current_a()
        w = sensor.read_power_w()
        return label, v, a, w, None
    except Exception as e:
        return label, None, None, None, e


def format_ina(label, v, a, w, err):
    if err:
        return "%s: ERROR %s" % (label, err)

    ma = a * 1000
    if v > 1.0 and abs(ma) < 5.0 and w < 0.05:
        return "%s: %.2f V, no load / possibly floating" % (label, v)
    return "%s: %.2f V, %.1f mA, %.2f W" % (label, v, ma, w)


def read_v50():
    try:
        sensor = INA219(i2c_bus(cfg.I2C_V50_SDA, cfg.I2C_V50_SCL, 0), cfg.INA219_V50_ADDR)
        return "V50 USB: %.2f V, %.1f mA" % (
            sensor.read_bus_voltage_v(),
            sensor.read_current_ma(),
        )
    except Exception as e:
        return "V50 USB: ERROR %s" % e


def modem_send(cmd, timeout_ms=1200):
    try:
        uart = UART(1, baudrate=cfg.MODEM_BAUD, tx=Pin(cfg.PIN_UART_TX), rx=Pin(cfg.PIN_UART_RX))
        while uart.any():
            uart.read()
        uart.write((cmd + "\r\n").encode())
        start = time.ticks_ms()
        buf = b""
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if uart.any():
                buf += uart.read()
                if b"\r\nOK\r\n" in buf or b"\r\nERROR\r\n" in buf:
                    break
            time.sleep(0.05)
        return buf.decode("utf-8", "ignore").strip()
    except Exception as e:
        return "ERROR: %s" % e


def line_value(text, prefix):
    text = text.replace("\r", "\n")
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith(prefix):
            return line
    return ""


def gps_to_decimal(value, hemi):
    if not value:
        return None
    dot = value.find(".")
    if dot < 0:
        return None
    deg_digits = dot - 2
    deg = int(value[:deg_digits])
    mins = float(value[deg_digits:])
    dec = deg + mins / 60.0
    if hemi in ("S", "W"):
        dec = -dec
    return dec


def parse_cgpsinfo(text):
    line = line_value(text, "+CGPSINFO:")
    if not line:
        return None, None, ""
    payload = line.split(":", 1)[1].strip()
    parts = payload.split(",")
    if len(parts) < 4 or not parts[0] or not parts[2]:
        return None, None, line
    return gps_to_decimal(parts[0], parts[1]), gps_to_decimal(parts[2], parts[3]), line


MODEM = {
    "last_basic_ms": -999999,
    "last_gps_ms": -999999,
    "last_gps_start_ms": -999999,
    "last_updated_ms": 0,
    "gps_started": False,
    "gps_status": "not started",
    "csq": "unknown",
    "operator": "unknown",
    "registered": "unknown",
    "ip": "not checked",
    "gps_raw": "not checked",
    "lat": None,
    "lon": None,
}

JOB = {
    "kind": "",
    "label": "",
    "state": "idle",
    "started_ms": 0,
    "finished_ms": 0,
    "result": "",
    "error": "",
}
JOB_LOCK = _thread.allocate_lock() if _thread else None
MODEM_LOCK = _thread.allocate_lock() if _thread else None
_modem_worker_started = False

# Background modem polling (see start_modem_background()) -- keep HTTP fast.
MODEM_BASIC_INTERVAL_MS = 45000
MODEM_GPS_POLL_INTERVAL_MS = 20000
MODEM_GPS_RESTART_INTERVAL_MS = 300000
STATUS_PAGE_REFRESH_S = 30

VERSION_CACHE = {
    "checked_ms": 0,
    "current": "",
    "latest": "",
    "notes": "",
    "error": "",
}


def _job_snapshot():
    if JOB_LOCK:
        JOB_LOCK.acquire()
    try:
        return dict(JOB)
    finally:
        if JOB_LOCK:
            JOB_LOCK.release()


def _set_job(**kwargs):
    if JOB_LOCK:
        JOB_LOCK.acquire()
    try:
        for key, value in kwargs.items():
            JOB[key] = value
    finally:
        if JOB_LOCK:
            JOB_LOCK.release()


def _job_running():
    return _job_snapshot().get("state") == "running"


def _elapsed_s(start_ms, end_ms=0):
    if not start_ms:
        return 0
    end_ms = end_ms or time.ticks_ms()
    return max(0, int(time.ticks_diff(end_ms, start_ms) / 1000))


def current_fw():
    try:
        import version

        return getattr(version, "VERSION", "unknown")
    except Exception:
        return "unknown"


def start_job(kind, label, func):
    snap = _job_snapshot()
    if snap.get("state") == "running":
        return False, "%s is already running (%ds)." % (
            snap.get("label") or "A command",
            _elapsed_s(snap.get("started_ms", 0)),
        )

    started_ms = time.ticks_ms()
    _set_job(
        kind=kind,
        label=label,
        state="running",
        started_ms=started_ms,
        finished_ms=0,
        result="",
        error="",
    )

    def run():
        try:
            result = func()
            _set_job(state="done", finished_ms=time.ticks_ms(), result=str(result), error="")
        except Exception as exc:
            _set_job(state="error", finished_ms=time.ticks_ms(), error=str(exc), result="")

    if _thread:
        _thread.start_new_thread(run, ())
        return True, "%s started. This page will refresh while it runs." % label

    # Desktop fallback; Pico W firmware has _thread, but this keeps the page usable if it is absent.
    run()
    return True, "%s finished." % label


def job_status_html():
    snap = _job_snapshot()
    state = snap.get("state", "idle")
    if state == "idle":
        return "<div class='card'><h2>Command Status</h2><p>No command running.</p></div>"

    label = safe(snap.get("label") or "Command")
    if state == "running":
        return (
            "<div class='card'><h2>Command Status</h2>"
            "<p><span class='warn'>%s running...</span> %ds elapsed.</p>"
            "<p class='small'>Log and OTA use the cellular modem, so 10-90 seconds is normal. "
            "This page refreshes automatically and the modem status check is paused while the command runs.</p>"
            "</div>"
        ) % (label, _elapsed_s(snap.get("started_ms", 0)))

    elapsed = _elapsed_s(snap.get("started_ms", 0), snap.get("finished_ms", 0))
    if state == "done":
        return (
            "<div class='card'><h2>Command Status</h2>"
            "<p><span class='good'>%s complete</span> in %ds.</p><pre>%s</pre></div>"
        ) % (label, elapsed, safe(snap.get("result", "")))

    return (
        "<div class='card'><h2>Command Status</h2>"
        "<p><span class='on'>%s failed</span> after %ds.</p><pre>%s</pre></div>"
    ) % (label, elapsed, safe(snap.get("error", "")))


def update_modem_cache():
    """Refresh MODEM dict from AT commands. Slow (seconds). Never call from the
    HTTP handler for '/' -- use the background worker instead."""
    now = time.ticks_ms()

    if time.ticks_diff(now, MODEM["last_basic_ms"]) > MODEM_BASIC_INTERVAL_MS:
        MODEM["last_basic_ms"] = now
        at = modem_send("AT", 1200)
        if "OK" not in at:
            MODEM["registered"] = "modem not responding"
            MODEM["last_updated_ms"] = now
            return

        csq = modem_send("AT+CSQ", 1500)
        cops = modem_send("AT+COPS?", 2000)
        creg = modem_send("AT+CREG?", 1500)
        cgreg = modem_send("AT+CGREG?", 1500)
        cereg = modem_send("AT+CEREG?", 1500)
        ip = modem_send("AT+IPADDR", 1500)

        MODEM["csq"] = line_value(csq, "+CSQ:") or csq
        MODEM["operator"] = line_value(cops, "+COPS:") or cops
        MODEM["registered"] = "registered" if (",1" in creg + cgreg + cereg or ",5" in creg + cgreg + cereg) else "not registered"

        if "+IP ERROR" in ip:
            MODEM["ip"] = "data idle"
        else:
            lines = []
            for line in ip.replace("\r", "\n").split("\n"):
                line = line.strip()
                if line and line != "OK" and not line.startswith("AT+"):
                    lines.append(line)
            MODEM["ip"] = lines[0] if lines else "none"

    if MODEM["lat"] is None and time.ticks_diff(now, MODEM["last_gps_start_ms"]) > MODEM_GPS_RESTART_INTERVAL_MS:
        MODEM["last_gps_start_ms"] = now
        MODEM["gps_status"] = "restarting GPS"
        modem_send("AT+CGPS=0", 3000)
        time.sleep(0.5)
        resp = modem_send("AT+CGPS=1,1", 5000)
        MODEM["gps_started"] = "OK" in resp
        MODEM["gps_status"] = "GPS on, searching for fix" if MODEM["gps_started"] else "GPS start failed"
        MODEM["gps_raw"] = "GPS start: " + (resp or "no response")

    if time.ticks_diff(now, MODEM["last_gps_ms"]) > MODEM_GPS_POLL_INTERVAL_MS:
        MODEM["last_gps_ms"] = now
        gps = modem_send("AT+CGPSINFO", 5000)
        lat, lon, raw = parse_cgpsinfo(gps)
        MODEM["gps_raw"] = raw or gps or "no response"
        if lat is not None and lon is not None:
            MODEM["lat"] = lat
            MODEM["lon"] = lon
            MODEM["gps_status"] = "GPS fix acquired"
        else:
            MODEM["gps_status"] = "GPS on, searching for fix" if MODEM["gps_started"] else "GPS not started"

    MODEM["last_updated_ms"] = time.ticks_ms()


def _modem_snapshot():
    if MODEM_LOCK:
        MODEM_LOCK.acquire()
    try:
        return dict(MODEM)
    finally:
        if MODEM_LOCK:
            MODEM_LOCK.release()


def _modem_worker():
    while True:
        if not _job_running():
            try:
                if MODEM_LOCK:
                    MODEM_LOCK.acquire()
                try:
                    update_modem_cache()
                finally:
                    if MODEM_LOCK:
                        MODEM_LOCK.release()
            except Exception as exc:
                print("modem worker:", exc)
        time.sleep(2)


def start_modem_background():
    global _modem_worker_started
    if _modem_worker_started or not _thread:
        return
    _modem_worker_started = True
    _thread.start_new_thread(_modem_worker, ())
    print("Modem status: background updates (HTTP stays fast)")


def page(title, body, refresh=False, refresh_url=None):
    if refresh:
        seconds = 10 if refresh is True else int(refresh)
        if refresh_url:
            refresh_tag = '<meta http-equiv="refresh" content="%d; url=%s">' % (seconds, refresh_url)
        else:
            refresh_tag = '<meta http-equiv="refresh" content="%d">' % seconds
    else:
        refresh_tag = ""
    return """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
%s
<title>%s</title>
<style>
body { font-family: Arial, sans-serif; background:#111; color:#eee; margin:18px; }
.card { background:#222; padding:12px; margin:12px 0; border-radius:8px; }
.on { color:#ff7777; font-weight:bold; }
.off { color:#aaa; }
.good { color:#7CFC7C; font-weight:bold; }
.warn { color:#ffd166; font-weight:bold; }
a { color:#8cf; font-size:18px; }
button, input { font-size:18px; margin:8px 0; max-width:100%%; }
textarea { width:100%%; height:280px; font-family:monospace; }
pre { white-space:pre-wrap; }
.small { color:#aaa; font-size:14px; }
</style>
</head>
<body>
%s
</body>
</html>
""" % (refresh_tag, safe(title), body)


def status_html(blocking_modem_poll=False):
    running = _job_running()
    if blocking_modem_poll and not running:
        if MODEM_LOCK:
            MODEM_LOCK.acquire()
        try:
            update_modem_cache()
        finally:
            if MODEM_LOCK:
                MODEM_LOCK.release()

    modem = _modem_snapshot()
    engine = format_ina(*read_ina260_values("Engine", cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0, cfg.INA260_ENGINE_ADDR))
    house = format_ina(*read_ina260_values("House", cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1, cfg.INA260_HOUSE_ADDR))
    v50 = read_v50()
    tps_stat = Pin(cfg.PIN_TPS_STAT, Pin.IN).value()
    vsns = Pin(cfg.PIN_TPS_VSNS, Pin.OUT, value=0).value()

    optos = ""
    for label, gpio, harness in cfg.HARNESS_SIGNALS:
        raw = Pin(gpio, Pin.IN, Pin.PULL_UP).value()
        on = raw == 0
        optos += "<li class='%s'>%s: %s (raw=%d)</li>" % (
            "on" if on else "off",
            safe(label),
            "ON" if on else "off",
            raw,
        )

    if modem.get("lat") is not None and modem.get("lon") is not None:
        maps = "https://www.google.com/maps?q=%.7f,%.7f" % (modem["lat"], modem["lon"])
        gps_html = "<span class='good'>GPS fix</span>: %.7f, %.7f<br><span>Status: %s</span><br><a href='%s'>Open in Google Maps</a>" % (
            modem["lat"],
            modem["lon"],
            safe(modem.get("gps_status", "")),
            maps,
        )
    else:
        gps_html = "<span class='warn'>No GPS fix yet</span><br><span>Status: %s</span><br><span class='small'>%s</span>" % (
            safe(modem.get("gps_status", "")),
            safe(modem.get("gps_raw", "")),
        )

    reg_cls = "good" if modem.get("registered") == "registered" else "warn"
    modem_age_s = 0
    if modem.get("last_updated_ms"):
        modem_age_s = max(0, int(time.ticks_diff(time.ticks_ms(), modem["last_updated_ms"]) / 1000))
    modem_note = (
        " Modem/GPS polled in background (~%ds refresh)."
        % (MODEM_BASIC_INTERVAL_MS // 1000)
    )
    if modem_age_s == 0 and not blocking_modem_poll:
        modem_note += " First poll may take a few seconds after Wi-Fi starts."
    elif modem_age_s:
        modem_note += " Last modem poll %ds ago." % modem_age_s
    if running:
        modem_note = " Modem status is paused while a command is running."
    modem_note += ' <a href="/modem-poll">Poll modem now</a> (slow).'
    current = current_fw()
    latest = VERSION_CACHE.get("latest") or ""
    version_error = VERSION_CACHE.get("error") or ""
    if latest:
        if latest != current:
            version_html = (
                "<p>Pico firmware: <b>%s</b></p>"
                "<p>GitHub firmware: <span class='warn'>%s available</span></p>"
                "<p><a href='/ota'>OTA from GitHub</a></p>"
            ) % (safe(current), safe(latest))
        else:
            version_html = (
                "<p>Pico firmware: <b>%s</b></p>"
                "<p>GitHub firmware: <span class='good'>current (%s)</span></p>"
            ) % (safe(current), safe(latest))
    elif version_error:
        version_html = (
            "<p>Pico firmware: <b>%s</b></p><p>GitHub firmware: <span class='on'>check failed</span></p>"
            "<pre>%s</pre>"
        ) % (safe(current), safe(version_error))
    else:
        version_html = "<p>Pico firmware: <b>%s</b></p><p>GitHub firmware: not checked yet.</p>" % safe(current)

    body = """
<h1>Boat Monitor</h1>
<p><a href="/">Refresh</a> | <a href="/log">Log Now</a> | <a href="/ota-check">Check GitHub Version</a> | <a href="/ota">OTA from GitHub</a> | <a href="/update">Update Files</a> | <a href="/reboot">Reboot</a></p>
%s
<div class="card"><h2>Firmware</h2>%s<p class="small">"Update Files" is the manual paste editor. "OTA from GitHub" downloads the manifest and files from GitHub over cellular.</p></div>
<div class="card"><h2>Power / Sensors</h2><p>%s</p><p>%s</p><p>%s</p><p>TPS STAT=%d, VSNS=%d</p></div>
<div class="card"><h2>Inputs</h2><ul>%s</ul></div>
<div class="card"><h2>Cell / GPS</h2><p>LTE: <span class="%s">%s</span></p><p>Signal: %s</p><p>Operator: %s</p><p>IP: %s</p><p>%s</p><p class="small">%s</p></div>
<div class="card"><p>Note: solar charging current currently reads negative on Engine/House INAs.</p><p class="small">Auto-refresh every %d seconds (power/sensors only; modem is not polled on each load).</p></div>
""" % (
        job_status_html(),
        version_html,
        safe(engine),
        safe(house),
        safe(v50),
        tps_stat,
        vsns,
        optos,
        reg_cls,
        safe(modem.get("registered", "")),
        safe(modem.get("csq", "")),
        safe(modem.get("operator", "")),
        safe(modem.get("ip", "")),
        gps_html,
        safe(modem_note),
        5 if running else STATUS_PAGE_REFRESH_S,
    )
    return page("Boat Monitor", body, refresh=5 if running else STATUS_PAGE_REFRESH_S)


def update_html(message=""):
    body = """
<h1>Update Files</h1><p><a href="/">Back</a></p>
<div class="card"><h2>Paste file</h2>
<form method="POST" action="/save">
<label>Filename</label><br><input name="filename" value="field_console.py"><br>
<label>Contents</label><br><textarea name="content"></textarea><br>
<button type="submit">Save pasted file</button>
</form></div>
<div class="card"><p>%s</p></div>
""" % safe(message)
    return page("Update", body)


def save_pasted(body):
    form = parse_urlencoded(body)
    filename = form.get("filename", "").strip()
    content = form.get("content", "")
    if not filename or "/" in filename or ".." in filename:
        return update_html("Invalid filename.")
    try:
        with open(filename, "w") as f:
            f.write(content)
        return update_html("Saved %s. Reboot when ready." % filename)
    except Exception as e:
        return update_html("Save failed: %s" % e)


def ota_html():
    def run_ota():
        import ota

        # prefer_wifi=False: this page is being served BY the Pico's own
        # Wi-Fi access point (start_ap() below) -- the Wi-Fi radio is
        # already busy as an AP. Also connecting it as a Wi-Fi client
        # (STA) to reach GitHub risks disrupting the very AP connection
        # you're using to view this page right now. Cellular uses separate
        # UART hardware and has no such conflict -- same reasoning as the
        # BLE "ota" command in ble_service.py.
        changed = ota.update(prefer_wifi=False)
        return "OTA update applied. Reboot when ready." if changed else "Already current."

    started, msg = start_job("ota", "OTA from GitHub", run_ota)
    body = "<h1>OTA from GitHub</h1><p><a href='/'>Status</a></p><div class='card'><p>%s</p></div>%s" % (
        safe(msg),
        job_status_html(),
    )
    refresh = started or _job_running()
    return page("OTA", body, refresh=3 if refresh else False, refresh_url="/" if refresh else None)


def ota_check_html():
    def run_check():
        try:
            import ota

            manifest = ota.check(prefer_wifi=False)
            current = ota.current_version()
            latest = manifest.get("version", "unknown")
            notes = manifest.get("notes", "")
            VERSION_CACHE["checked_ms"] = time.ticks_ms()
            VERSION_CACHE["current"] = current
            VERSION_CACHE["latest"] = latest
            VERSION_CACHE["notes"] = notes
            VERSION_CACHE["error"] = ""
            if latest == current:
                status = "Already current."
            else:
                status = "Update available."
            return "Current: %s\nGitHub: %s\nStatus: %s\n\nNotes:\n%s" % (current, latest, status, notes)
        except Exception as exc:
            VERSION_CACHE["checked_ms"] = time.ticks_ms()
            VERSION_CACHE["current"] = current_fw()
            VERSION_CACHE["latest"] = ""
            VERSION_CACHE["notes"] = ""
            VERSION_CACHE["error"] = str(exc)
            raise

    started, msg = start_job("ota_check", "Check GitHub Version", run_check)
    body = "<h1>Check GitHub Version</h1><p><a href='/'>Status</a></p><div class='card'><p>%s</p></div>%s" % (
        safe(msg),
        job_status_html(),
    )
    refresh = started or _job_running()
    return page("Check GitHub Version", body, refresh=3 if refresh else False, refresh_url="/" if refresh else None)


def log_html():
    def run_log():
        # prefer_wifi=False handled inside log_power_and_gps() for the
        # same reason as ota_html() above -- the Wi-Fi radio here is
        # already busy serving this page as an AP. Shared with
        # ble_service.py's manual 'log' command and its automatic
        # background logging -- previously this page had its own
        # separate (near-identical) copy of this logic.
        from ble_service import log_power_and_gps

        return "Logged: %s" % log_power_and_gps(note="wifi_console_log_now")

    started, msg = start_job("log", "Log Now", run_log)
    body = "<h1>Log Now</h1><p><a href='/'>Status</a></p><div class='card'><p>%s</p></div>%s" % (
        safe(msg),
        job_status_html(),
    )
    refresh = started or _job_running()
    return page("Log Now", body, refresh=3 if refresh else False, refresh_url="/" if refresh else None)


def http_response(html, content_type="text/html"):
    return "HTTP/1.1 200 OK\r\nContent-Type: %s\r\nConnection: close\r\n\r\n%s" % (content_type, html)


def http_response_bytes(status_line, headers, body=b""):
    lines = [status_line]
    for key, value in headers:
        lines.append("%s: %s" % (key, value))
    lines.append("Connection: close")
    lines.append("")
    head = "\r\n".join(lines).encode()
    if body:
        return head + b"\r\n" + body
    return head + b"\r\n"


def path_only(path):
    return (path or "/").split("?", 1)[0] or "/"


# iOS/Safari probe these while joined to a Wi-Fi AP with no internet. Our
# server is single-threaded; treating every unknown URL like "/" used to run
# update_modem_cache() (many AT commands) and could make http://192.168.4.1
# look "dead" even though the AP was still up.
CAPTIVE_PROBE_PATHS = frozenset(
    (
        "/generate_204",
        "/hotspot-detect.html",
        "/library/test/success.html",
        "/success.txt",
        "/canonical.html",
        "/redirect",
        "/ncsi.txt",
        "/connecttest.txt",
    )
)


def ensure_ble_off():
    """Pico W: CYW43439 cannot reliably run WiFi AP while BLE is active --
    same shared-radio constraint as ble_service.py's ensure_wifi_off(),
    mirrored here for the AP side. This module is typically reached right
    after machine.reset() from the BLE "wifi"/"start_wifi" command
    (ble_service.py's handle_command()), i.e. moments after the CYW43439
    was actively doing BLE work. A software reset of the RP2040 resets
    the MCU but does not reliably reset the separate CYW43439 chip's
    internal radio/firmware state -- the exact same caveat already
    documented on ensure_wifi_off() -- so this settles it before
    ap.active(True) instead of assuming a clean slate.
    """
    try:
        import bluetooth

        ble = bluetooth.BLE()
        if ble.active():
            ble.active(False)
            print("BLE disabled for WiFi AP")
    except Exception as exc:
        print("BLE off: %s" % exc)
    time.sleep_ms(250)


# How long to wait for the AP interface to report active() before giving
# up. The previous "while not ap.active(): time.sleep(0.2)" loop had NO
# timeout -- if the radio didn't come up (e.g. still settling right after
# the machine.reset() that got here), it hung forever with zero output:
# no error, no AP, no console output, nothing to debug from. That silent
# hang matches exactly what was reported ("I don't see boatmonitor
# broadcast", no further Thonny output after the reset).
AP_ACTIVE_TIMEOUT_MS = 8000


def start_ap():
    ensure_ble_off()

    ap = network.WLAN(network.AP_IF)
    try:
        ap.active(True)
        ap.config(essid=AP_NAME, password=AP_PASSWORD)
    except OSError as exc:
        print("ERROR: WiFi AP activation failed:", exc)
        print("Try a full power cycle (unplug ~10s) -- a soft/hard reset may not clear radio state.")
        raise

    start = time.ticks_ms()
    while not ap.active():
        if time.ticks_diff(time.ticks_ms(), start) > AP_ACTIVE_TIMEOUT_MS:
            print("ERROR: WiFi AP did not become active within %dms" % AP_ACTIVE_TIMEOUT_MS)
            print("Try a full power cycle (unplug ~10s) -- a soft/hard reset may not clear radio state.")
            raise OSError("WiFi AP did not become active")
        time.sleep(0.2)

    print("AP active:", AP_NAME)
    print("Open http://192.168.4.1")
    print("Config:", ap.ifconfig())


CLIENT_SOCKET_TIMEOUT_S = 120


def handle_request(method, path, body):
    path = path_only(path)
    if path == "/ping":
        return http_response("ok\n", content_type="text/plain; charset=utf-8")
    if path == "/favicon.ico":
        return http_response_bytes("HTTP/1.1 404 Not Found", [("Content-Type", "text/plain")], b"")
    if path in CAPTIVE_PROBE_PATHS:
        return http_response_bytes("HTTP/1.1 204 No Content", [("Content-Type", "text/plain")], b"")

    if path.startswith("/update"):
        html = update_html()
    elif path.startswith("/save") and method == "POST":
        html = save_pasted(body)
    elif path.startswith("/ota-check"):
        html = ota_check_html()
    elif path.startswith("/ota"):
        html = ota_html()
    elif path.startswith("/log"):
        html = log_html()
    elif path == "/reboot":
        return "REBOOT"
    elif path == "/":
        html = status_html()
    elif path == "/modem-poll":
        html = status_html(blocking_modem_poll=True)
    else:
        html = page(
            "Not found",
            "<h1>Boat Monitor</h1><p>Unknown path <code>%s</code>.</p><p><a href='/'>Open status</a> | "
            "<a href='/ping'>Ping (health check)</a></p>" % safe(path),
        )
    return http_response(html)


def serve():
    start_ap()
    start_modem_background()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 80))
    s.listen(5)
    print("Web server listening (try http://192.168.4.1/ping first)")

    while True:
        try:
            cl, addr = s.accept()
        except Exception as exc:
            print("accept failed:", exc)
            time.sleep(0.5)
            continue
        try:
            cl.settimeout(CLIENT_SOCKET_TIMEOUT_S)
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = cl.recv(1024)
                if not chunk:
                    break
                req += chunk
            req_text = req.decode("utf-8", "ignore")
            first = req_text.split("\r\n", 1)[0]
            parts = first.split(" ")
            method = parts[0] if len(parts) > 0 else "GET"
            path = parts[1] if len(parts) > 1 else "/"
            content_length = 0
            for line in req_text.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":", 1)[1].strip())
            body_bytes = b""
            if b"\r\n\r\n" in req:
                body_bytes = req.split(b"\r\n\r\n", 1)[1]
            while len(body_bytes) < content_length:
                chunk = cl.recv(1024)
                if not chunk:
                    break
                body_bytes += chunk
            body = body_bytes.decode("utf-8", "ignore")
            print("HTTP", method, path_only(path), "from", addr)

            resp = handle_request(method, path, body)
            if resp == "REBOOT":
                cl.send(http_response(page("Reboot", "<h1>Rebooting...</h1>")).encode())
                cl.close()
                time.sleep(1)
                machine.reset()
                continue
            payload = resp.encode() if isinstance(resp, str) else resp
            cl.send(payload)
        except Exception as e:
            print("HTTP error:", e)
            try:
                cl.send(http_response(page("Error", "<pre>%s</pre>" % safe(e))).encode())
            except Exception:
                pass
        try:
            cl.close()
        except Exception:
            pass


serve()
