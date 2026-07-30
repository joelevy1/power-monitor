import time
import socket
import network
import machine
from machine import I2C, Pin, UART
import config as cfg

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


def update_modem_cache():
    now = time.ticks_ms()

    if time.ticks_diff(now, MODEM["last_basic_ms"]) > 30000:
        MODEM["last_basic_ms"] = now
        at = modem_send("AT", 1200)
        if "OK" not in at:
            MODEM["registered"] = "modem not responding"
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

    if MODEM["lat"] is None and time.ticks_diff(now, MODEM["last_gps_start_ms"]) > 60000:
        MODEM["last_gps_start_ms"] = now
        MODEM["gps_status"] = "restarting GPS"
        modem_send("AT+CGPS=0", 3000)
        time.sleep(0.5)
        resp = modem_send("AT+CGPS=1,1", 5000)
        MODEM["gps_started"] = "OK" in resp
        MODEM["gps_status"] = "GPS on, searching for fix" if MODEM["gps_started"] else "GPS start failed"
        MODEM["gps_raw"] = "GPS start: " + (resp or "no response")

    if time.ticks_diff(now, MODEM["last_gps_ms"]) > 5000:
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


def page(title, body, refresh=False):
    refresh_tag = '<meta http-equiv="refresh" content="10">' if refresh else ""
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


def status_html():
    update_modem_cache()

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

    if MODEM["lat"] is not None and MODEM["lon"] is not None:
        maps = "https://www.google.com/maps?q=%.7f,%.7f" % (MODEM["lat"], MODEM["lon"])
        gps_html = "<span class='good'>GPS fix</span>: %.7f, %.7f<br><span>Status: %s</span><br><a href='%s'>Open in Google Maps</a>" % (
            MODEM["lat"],
            MODEM["lon"],
            safe(MODEM["gps_status"]),
            maps,
        )
    else:
        gps_html = "<span class='warn'>No GPS fix yet</span><br><span>Status: %s</span><br><span class='small'>%s</span>" % (
            safe(MODEM["gps_status"]),
            safe(MODEM["gps_raw"]),
        )

    reg_cls = "good" if MODEM["registered"] == "registered" else "warn"
    body = """
<h1>Boat Monitor</h1>
<p><a href="/">Refresh</a> | <a href="/update">Update</a> | <a href="/ota">OTA from GitHub</a> | <a href="/reboot">Reboot</a></p>
<div class="card"><h2>Power / Sensors</h2><p>%s</p><p>%s</p><p>%s</p><p>TPS STAT=%d, VSNS=%d</p></div>
<div class="card"><h2>Inputs</h2><ul>%s</ul></div>
<div class="card"><h2>Cell / GPS</h2><p>LTE: <span class="%s">%s</span></p><p>Signal: %s</p><p>Operator: %s</p><p>IP: %s</p><p>%s</p></div>
<div class="card"><p>Note: solar charging current currently reads negative on Engine/House INAs.</p><p class="small">Auto-refresh every 10 seconds.</p></div>
""" % (
        safe(engine),
        safe(house),
        safe(v50),
        tps_stat,
        vsns,
        optos,
        reg_cls,
        safe(MODEM["registered"]),
        safe(MODEM["csq"]),
        safe(MODEM["operator"]),
        safe(MODEM["ip"]),
        gps_html,
    )
    return page("Boat Monitor", body, refresh=True)


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
    try:
        import ota

        changed = ota.update()
        msg = "OTA update applied. Reboot when ready." if changed else "Already current."
    except Exception as e:
        msg = "OTA failed: %s" % e
    return page("OTA", "<h1>OTA from GitHub</h1><p><a href='/'>Back</a></p><div class='card'><pre>%s</pre></div>" % safe(msg))


def http_response(html):
    return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n%s" % html


def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_NAME, password=AP_PASSWORD)
    while not ap.active():
        time.sleep(0.2)
    print("AP active:", AP_NAME)
    print("Open http://192.168.4.1")
    print("Config:", ap.ifconfig())


def serve():
    start_ap()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 80))
    s.listen(1)
    print("Web server listening")

    while True:
        cl, addr = s.accept()
        try:
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

            if path.startswith("/update"):
                html = update_html()
            elif path.startswith("/save") and method == "POST":
                html = save_pasted(body)
            elif path.startswith("/ota"):
                html = ota_html()
            elif path.startswith("/reboot"):
                cl.send(http_response(page("Reboot", "<h1>Rebooting...</h1>")).encode())
                cl.close()
                time.sleep(1)
                machine.reset()
                continue
            else:
                html = status_html()
            cl.send(http_response(html).encode())
        except Exception as e:
            try:
                cl.send(http_response(page("Error", "<pre>%s</pre>" % safe(e))).encode())
            except Exception:
                pass
        cl.close()


serve()
