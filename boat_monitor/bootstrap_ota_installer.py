"""
One-time installer for enabling Boat Monitor OTA from a phone.

Usage:
1. Save this file's contents on the Pico as main.py.
2. Reboot the Pico with modem power available.
3. It downloads the OTA-capable files from GitHub and reboots.
"""

import time
from machine import Pin, UART

import config as cfg

BRANCH_RAW = (
    "https://raw.githubusercontent.com/joelevy1/power-monitor/"
    "cursor/add-ina-check-script-106f/boat_monitor/"
)

FILES = (
    "ota_config.py",
    "ota.py",
    "version.py",
    "ble_service.py",
    "field_console.py",
    "main.py",
)

APN = "iot.t-mobile.com"


class InstallError(Exception):
    pass


class Sim7600Http:
    def __init__(self):
        self.uart = UART(
            1,
            baudrate=cfg.MODEM_BAUD,
            tx=Pin(cfg.PIN_UART_TX),
            rx=Pin(cfg.PIN_UART_RX),
        )

    def flush(self):
        while self.uart.any():
            self.uart.read()

    def read_until(self, tokens, timeout_ms):
        if isinstance(tokens, str):
            tokens = (tokens,)
        tokens = tuple(t.encode() for t in tokens)
        start = time.ticks_ms()
        buf = b""
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                buf += self.uart.read()
                for token in tokens:
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
        self.at("AT", 2000)
        self.at("ATE0", 2000)
        self.at('AT+CGDCONT=1,"IPV6","%s"' % APN, 3000)
        self.at("AT+CSOCKSETPN=1,6", 3000)
        self.at("AT+NETOPEN", 30000, expect=("+NETOPEN:", "\r\nERROR\r\n"))
        ip = self.at("AT+IPADDR", 5000)
        if "+IP ERROR" in ip or "ERROR" in ip or not ip.strip():
            raise InstallError("cell data did not open")

    def http_get(self, url):
        print("Downloading", url)
        self.at("AT+HTTPTERM", 3000)
        self.at("AT+HTTPINIT", 5000)
        self.at('AT+HTTPPARA="CID",1', 3000)
        self.at("AT+HTTPSSL=1" if url.startswith("https://") else "AT+HTTPSSL=0", 3000)
        self.at('AT+HTTPPARA="URL","%s"' % url, 5000)

        action = self.at("AT+HTTPACTION=0", 60000, expect=("+HTTPACTION:", "\r\nERROR\r\n"))
        status, length = self.parse_action(action)
        if status != 200:
            self.at("AT+HTTPTERM", 3000)
            raise InstallError("HTTP status %s" % status)

        raw = self.at(
            "AT+HTTPREAD=0,%d" % length,
            max(10000, length * 4),
            expect=("\r\nOK\r\n", "\r\nERROR\r\n"),
        )
        self.at("AT+HTTPTERM", 3000)
        return self.parse_read(raw)

    def parse_action(self, text):
        marker = "+HTTPACTION:"
        if marker not in text:
            raise InstallError("missing HTTPACTION")
        line = text.split(marker, 1)[1].splitlines()[0].strip()
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            raise InstallError("bad HTTPACTION: " + line)
        return int(parts[1]), int(parts[2])

    def parse_read(self, text):
        marker = "+HTTPREAD:"
        if marker not in text:
            raise InstallError("missing HTTPREAD")
        after = text.split(marker, 1)[1]
        first_newline = after.find("\n")
        if first_newline < 0:
            raise InstallError("bad HTTPREAD")
        data = after[first_newline + 1 :]
        ok_pos = data.rfind("\r\nOK")
        if ok_pos >= 0:
            data = data[:ok_pos]
        return data.lstrip("\r\n")


def save_file(path, data):
    print("Saving", path, len(data), "bytes")
    with open(path + ".new", "w") as f:
        f.write(data)

    try:
        import os

        try:
            os.remove(path + ".bak")
        except OSError:
            pass
        try:
            os.rename(path, path + ".bak")
        except OSError:
            pass
        os.rename(path + ".new", path)
    except Exception as exc:
        raise InstallError("replace failed for %s: %s" % (path, exc))


def main():
    print("Boat Monitor one-time OTA installer")
    modem = Sim7600Http()
    modem.ensure_data()

    for filename in FILES:
        data = modem.http_get(BRANCH_RAW + filename)
        if len(data) < 10:
            raise InstallError("%s downloaded too small" % filename)
        save_file(filename, data)

    print("Install complete. Rebooting...")
    time.sleep(2)
    import machine

    machine.reset()


main()
