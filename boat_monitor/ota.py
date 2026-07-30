"""
Boat Monitor P2 - manifest-driven OTA updater for MicroPython / SIM7600.

Run manually from the Pico:

    import ota
    ota.update()

The updater downloads ota_manifest.json over the cellular modem, then fetches
each listed file from GitHub raw URLs. Files are written as .new first, then the
previous copy is kept as .bak where possible.
"""

import time

try:
    import ujson as json
except ImportError:
    import json

from machine import Pin, UART

import config as cfg
import ota_config


class OtaError(Exception):
    pass


class Sim7600Http:
    def __init__(self):
        self.uart = UART(
            1,
            baudrate=cfg.MODEM_BAUD,
            tx=Pin(cfg.PIN_UART_TX),
            rx=Pin(cfg.PIN_UART_RX),
        )
        self.rst = Pin(cfg.PIN_MODEM_RESET, Pin.OUT, value=1)

    def reset(self):
        print("Resetting modem...")
        self.rst.value(0)
        time.sleep(0.3)
        self.rst.value(1)
        time.sleep(3)

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
        apn = ota_config.OTA_APN
        cid = ota_config.OTA_CONTEXT_ID
        pdp_type = ota_config.OTA_SOCKET_PDP_TYPE

        self.at("AT", 2000)
        self.at("ATE0", 2000)
        self.at('AT+CGDCONT=%d,"IPV6","%s"' % (cid, apn), 3000)
        self.at("AT+CSOCKSETPN=%d,%d" % (cid, pdp_type), 3000)

        # NETOPEN returns ERROR if already in some states; IPADDR below is the
        # real check that data is available.
        self.at("AT+NETOPEN", 30000, expect=("+NETOPEN:", "\r\nERROR\r\n"))
        ip = self.at("AT+IPADDR", 5000)
        if "+IP ERROR" in ip or "ERROR" in ip or not ip.strip():
            raise OtaError("cellular data did not open")

    def http_get(self, url):
        print("HTTP GET", url)
        self.at("AT+HTTPTERM", 3000)
        self.at("AT+HTTPINIT", 5000)
        self.at('AT+HTTPPARA="CID",%d' % ota_config.OTA_CONTEXT_ID, 3000)

        if url.startswith("https://"):
            self.at("AT+HTTPSSL=1", 3000)
        else:
            self.at("AT+HTTPSSL=0", 3000)

        self.at('AT+HTTPPARA="URL","%s"' % url, 5000)
        action = self.at("AT+HTTPACTION=0", 60000, expect=("+HTTPACTION:", "\r\nERROR\r\n"))
        status, length = self._parse_http_action(action)
        if status != 200:
            self.at("AT+HTTPTERM", 3000)
            raise OtaError("HTTP status %s for %s" % (status, url))

        if length <= 0:
            self.at("AT+HTTPTERM", 3000)
            raise OtaError("empty HTTP response for %s" % url)

        raw = self.at(
            "AT+HTTPREAD=0,%d" % length,
            max(10000, length * 4),
            expect=("\r\nOK\r\n", "\r\nERROR\r\n"),
        )
        self.at("AT+HTTPTERM", 3000)
        return self._parse_http_read(raw)

    def _parse_http_action(self, text):
        marker = "+HTTPACTION:"
        if marker not in text:
            raise OtaError("missing HTTPACTION response")
        line = text.split(marker, 1)[1].splitlines()[0].strip()
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            raise OtaError("bad HTTPACTION response: %s" % line)
        return int(parts[1]), int(parts[2])

    def _parse_http_read(self, text):
        marker = "+HTTPREAD:"
        if marker not in text:
            raise OtaError("missing HTTPREAD response")

        after = text.split(marker, 1)[1]
        first_newline = after.find("\n")
        if first_newline < 0:
            raise OtaError("bad HTTPREAD response")

        data = after[first_newline + 1 :]
        ok_pos = data.rfind("\r\nOK")
        if ok_pos >= 0:
            data = data[:ok_pos]
        return data.lstrip("\r\n")


def current_version():
    try:
        import version

        return getattr(version, "VERSION", "unknown")
    except Exception:
        return "unknown"


def load_manifest(client):
    data = client.http_get(ota_config.OTA_MANIFEST_URL)
    return json.loads(data)


def write_file(path, data):
    tmp_path = path + ".new"
    bak_path = path + ".bak"

    print("Writing", tmp_path)
    with open(tmp_path, "w") as f:
        f.write(data)

    try:
        # Remove stale backup before replacing current file.
        import os

        try:
            os.remove(bak_path)
        except OSError:
            pass
        try:
            os.rename(path, bak_path)
        except OSError:
            pass
        os.rename(tmp_path, path)
    except Exception as exc:
        raise OtaError("failed replacing %s: %s" % (path, exc))


def apply_manifest(client, manifest):
    files = manifest.get("files", [])
    if not files:
        raise OtaError("manifest has no files")

    for entry in files:
        path = entry["path"]
        url = entry["url"]
        min_size = entry.get("min_size", 1)

        print("Updating", path)
        data = client.http_get(url)
        if len(data) < min_size:
            raise OtaError("%s was too small (%d bytes)" % (path, len(data)))
        write_file(path, data)


def update(reset_modem=False, reboot=False):
    print("Boat Monitor OTA update")
    print("Current version:", current_version())
    print("Manifest:", ota_config.OTA_MANIFEST_URL)

    client = Sim7600Http()
    if reset_modem:
        client.reset()

    client.ensure_data()
    manifest = load_manifest(client)
    target_version = manifest.get("version", "unknown")
    print("Target version:", target_version)

    if target_version == current_version():
        print("Already at target version.")
        return False

    apply_manifest(client, manifest)
    print("Update complete.")
    print("Reboot required to run new files.")

    if reboot:
        import machine

        time.sleep(1)
        machine.reset()

    return True


def check():
    client = Sim7600Http()
    client.ensure_data()
    manifest = load_manifest(client)
    print("Current:", current_version())
    print("Available:", manifest.get("version", "unknown"))
    print("Notes:", manifest.get("notes", ""))
    return manifest
