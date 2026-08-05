"""
Boat Monitor P2 - shared, hardened SIM7600 cellular data + HTTP client.

Used by ota.py (OTA over cellular) and sheets_log.py (Sheets logging over
cellular) instead of each keeping its own copy of the same AT-command
sequence. Every "cellular data did not open" failure seen so far skipped
straight to AT+NETOPEN with no check that the modem was even responding,
no SIM check, and -- the most likely actual cause -- no wait for network
registration first. AT+NETOPEN commonly fails/errors if the modem hasn't
attached to the tower yet, which can take anywhere from a few seconds to
over a minute after power-on, especially on IoT SIMs.

Ports the registration-wait pattern already proven in modem_check.py's
wait_for_registration() into a reusable class both callers share.

Usage:
    from cellular import Sim7600Modem, CellularError

    modem = Sim7600Modem()
    modem.ensure_data()          # raises CellularError with a SPECIFIC
                                  # reason (not responding / no SIM / not
                                  # registered / NETOPEN failed / IPADDR
                                  # failed) instead of one generic message
    text = modem.http_get(url)
    modem.close_data()
"""

import time

import ota_config


class CellularError(Exception):
    pass


def one_line(text):
    text = text.replace("\r", "\n")
    parts = [line.strip() for line in text.split("\n") if line.strip() and line.strip() != "OK"]
    return " | ".join(parts) if parts else "(none)"


def parse_http_action(text):
    marker = "+HTTPACTION:"
    if marker not in text:
        raise CellularError("missing HTTPACTION response")
    line = text.split(marker, 1)[1].splitlines()[0].strip()
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        raise CellularError("bad HTTPACTION response: %s" % line)
    return int(parts[1]), int(parts[2])


def parse_http_read(text, expected_length=None, debug=True):
    """Parse one or more '+HTTPREAD: DATA,<n>\\r\\n<n bytes>' chunks.

    Observed on-device: large AT+HTTPREAD responses get split into
    multiple ~1024-byte chunks, each with its own '+HTTPREAD: DATA,<n>'
    header -- not the single '+HTTPREAD: <n>\\r\\n<data>\\r\\nOK' shape some
    SIM7600 docs describe. Extracting each chunk by its declared byte
    length (rather than scanning for the next marker/OK/newline) is
    required because the data itself can contain those substrings --
    scanning for them corrupted real content the first time this ran on
    real hardware (a big chunk of text silently vanished because the
    second chunk's own marker line was left embedded instead of stripped).

    expected_length: if given (the byte count already known from
    AT+HTTPACTION's response), raise CellularError with the exact
    shortfall/mismatch instead of silently returning truncated data --
    exactly one chunk went missing (with no error at all) the second time
    this ran on real hardware, for a reason not yet understood; this at
    least turns silent corruption into a diagnosable error, and debug=True
    prints each chunk found (index/declared length/position) so the next
    real run's Thonny output shows exactly what happened.

    Note: operates on the already-decoded text string, so chunk lengths
    are treated as character counts. Fine for the ASCII JSON payloads this
    codebase actually transfers (OTA manifest, Sheets POST bodies); would
    need byte-precise slicing on raw bytes for arbitrary UTF-8 content.
    """
    marker = "+HTTPREAD: DATA,"
    if marker not in text:
        raise CellularError("missing HTTPREAD DATA response")

    chunks = []
    pos = 0
    chunk_index = 0
    while True:
        idx = text.find(marker, pos)
        if idx < 0:
            break

        header_start = idx + len(marker)
        newline_idx = text.find("\n", header_start)
        if newline_idx < 0:
            raise CellularError("bad HTTPREAD chunk header (no newline after length)")

        length_str = text[header_start:newline_idx].strip().rstrip("\r")
        try:
            chunk_len = int(length_str)
        except ValueError:
            raise CellularError("bad HTTPREAD chunk length: %r" % length_str)

        data_start = newline_idx + 1
        chunk = text[data_start : data_start + chunk_len]
        chunks.append(chunk)
        if debug:
            print(
                "  HTTPREAD chunk %d: marker at %d, declared %d bytes, got %d"
                % (chunk_index, idx, chunk_len, len(chunk))
            )
        pos = data_start + chunk_len
        chunk_index += 1

    if not chunks:
        raise CellularError("no HTTPREAD DATA chunks found")

    result = "".join(chunks)

    if expected_length is not None and len(result) != expected_length:
        raise CellularError(
            "HTTPREAD reassembled %d bytes but AT+HTTPACTION declared %d -- "
            "%d chunk(s) found, likely one was skipped or truncated"
            % (len(result), expected_length, len(chunks))
        )

    return result


class Sim7600Modem:
    # MicroPython's default UART RX buffer (rp2 port) is small -- far
    # smaller than a burst of several KB the modem can send back-to-back
    # for a chunked AT+HTTPREAD response. If the hardware/driver buffer
    # fills faster than read_until()'s Python-level loop drains it
    # (time.sleep(0.05) between checks -- at 115200 baud that's ~576 bytes
    # per interval), excess bytes are silently DROPPED at the driver level
    # before Python ever sees them. This matches exactly what was observed
    # on real hardware: a DIFFERENT, RANDOM amount of data missing on each
    # run (1024 bytes once, 160 another time), at essentially random
    # positions, and never reproducible in a pure-string simulation (no
    # real hardware buffer to overflow there). A generous explicit rxbuf
    # is cheap insurance against this class of loss.
    RX_BUFFER_SIZE = 4096

    def __init__(self):
        # Imported here, not at module level, so one_line()/parse_http_action()/
        # parse_http_read() above stay importable and unit-testable on a PC
        # without MicroPython's machine module -- see test_cellular_parser.py.
        from machine import Pin, UART
        import config as cfg

        self.uart = UART(
            1,
            baudrate=cfg.MODEM_BAUD,
            tx=Pin(cfg.PIN_UART_TX),
            rx=Pin(cfg.PIN_UART_RX),
            rxbuf=self.RX_BUFFER_SIZE,
        )
        self.rst = Pin(cfg.PIN_MODEM_RESET, Pin.OUT, value=1)
        self._cfg = cfg
        self._data_open = False

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
            # Drain frequently (not just rely on RX_BUFFER_SIZE) -- defense
            # in depth against the buffer-overflow data loss described on
            # Sim7600Modem.RX_BUFFER_SIZE, in case a future response
            # exceeds even that buffer.
            time.sleep(0.01)

        return buf.decode("utf-8", "ignore")

    def at(self, cmd, timeout_ms=3000, expect=("\r\nOK\r\n", "\r\nERROR\r\n"), quiet=False):
        if not quiet:
            print(">>>", cmd)
        self.flush()
        self.uart.write((cmd + "\r\n").encode())
        text = self.read_until(expect, timeout_ms)
        if not quiet:
            print(text.strip() or "(no response)")
        return text

    def read_http_data(self, expected_length, timeout_ms):
        """Send/read AT+HTTPREAD without relying on read_until()'s
        "\\r\\nOK\\r\\n" stop-token match at all.

        On real hardware, that pattern-matching approach cut a real
        response short mid-chunk at least twice, at different byte
        offsets each time -- and the actual JSON payload from GitHub
        contains zero \\r bytes (confirmed directly), which rules out a
        coincidental match inside the real data. Something about the AT
        protocol framing itself appears to produce a false-positive match
        occasionally. Rather than depend on figuring out exactly why,
        this reads raw bytes and tracks how many bytes of ACTUAL chunk
        data ("+HTTPREAD: DATA,<n>" payloads) have arrived, stopping only
        once that total reaches expected_length (or on \\r\\nERROR\\r\\n,
        or timeout) -- never based on an OK/ERROR text match that could
        be a false positive partway through real data.
        """
        cmd = "AT+HTTPREAD=0,%d" % expected_length
        print(">>>", cmd)
        self.flush()
        self.uart.write((cmd + "\r\n").encode())

        marker = b"+HTTPREAD: DATA,"
        start = time.ticks_ms()
        buf = b""
        accounted_for = 0
        scan_pos = 0

        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                buf += self.uart.read()

                while True:
                    idx = buf.find(marker, scan_pos)
                    if idx < 0:
                        break
                    header_start = idx + len(marker)
                    newline_idx = buf.find(b"\n", header_start)
                    if newline_idx < 0:
                        break  # header not fully arrived yet
                    try:
                        chunk_len = int(buf[header_start:newline_idx].strip())
                    except ValueError:
                        break
                    data_start = newline_idx + 1
                    if len(buf) < data_start + chunk_len:
                        break  # this chunk's data hasn't fully arrived yet
                    accounted_for += chunk_len
                    scan_pos = data_start + chunk_len

                if accounted_for >= expected_length:
                    # Briefly drain any trailing "+HTTPREAD: 0\r\n\r\nOK\r\n"
                    # terminator, then stop -- we have everything we need.
                    time.sleep(0.2)
                    if self.uart.any():
                        buf += self.uart.read()
                    break

                if b"\r\nERROR\r\n" in buf:
                    break

            time.sleep(0.01)

        text = buf.decode("utf-8", "ignore")
        print(text.strip() or "(no response)")
        return text

    def check_alive(self):
        """Verify the modem responds to a basic AT at all, instead of
        silently continuing through the rest of the sequence regardless.
        Distinguishes "not wired/powered" from every other failure mode.
        """
        resp = self.at("AT", 2000)
        if "OK" not in resp:
            cfg = self._cfg
            raise CellularError(
                "Modem not responding to AT -- check power/wiring/baud "
                "(config.py: PIN_UART_TX=%d, PIN_UART_RX=%d, PIN_MODEM_RESET=%d, MODEM_BAUD=%d)"
                % (cfg.PIN_UART_TX, cfg.PIN_UART_RX, cfg.PIN_MODEM_RESET, cfg.MODEM_BAUD)
            )
        self.at("ATE0", 2000)

    def check_sim(self):
        resp = self.at("AT+CPIN?", 3000)
        if "READY" in resp:
            return
        if "SIM PIN" in resp or "SIM PUK" in resp:
            raise CellularError("SIM is PIN/PUK locked (AT+CPIN? -> %s)" % _one_line(resp))
        raise CellularError("No SIM detected or not ready (AT+CPIN? -> %s)" % _one_line(resp))

    def wait_for_registration(self, seconds=60):
        print("Waiting for network registration (up to %ds)..." % seconds)
        start = time.ticks_ms()
        last_csq = "(none)"

        while time.ticks_diff(time.ticks_ms(), start) < seconds * 1000:
            creg = self.at("AT+CREG?", 2000, quiet=True)
            cgreg = self.at("AT+CGREG?", 2000, quiet=True)
            cereg = self.at("AT+CEREG?", 2000, quiet=True)
            csq = self.at("AT+CSQ", 2000, quiet=True)
            last_csq = one_line(csq)

            print(
                "CREG:", one_line(creg),
                " CGREG:", one_line(cgreg),
                " CEREG:", one_line(cereg),
                " CSQ:", last_csq,
            )

            combined = creg + cgreg + cereg
            if ",1" in combined or ",5" in combined:
                print("Registered. Signal:", last_csq)
                return

            time.sleep(3)

        raise CellularError(
            "Not registered on the cellular network after %ds (last signal: %s) -- "
            "check antenna connection, SIM activation, and coverage" % (seconds, last_csq)
        )

    def ensure_data(self, registration_timeout_s=60):
        if self._data_open:
            return

        # Always reset first -- the modem needs several seconds after
        # power-on/reset before it reliably responds to AT at all. This was
        # previously opt-in via a reset_modem flag that defaulted to False,
        # which is almost certainly why every earlier attempt failed at the
        # very first "AT" command with zero response. modem_check.py's
        # already-proven bench test resets first by default for the same
        # reason (main(reset_modem=True, ...)) -- match that here instead
        # of leaving it as a flag someone has to remember to pass.
        self.reset()

        self.check_alive()
        self.check_sim()
        self.wait_for_registration(seconds=registration_timeout_s)

        apn = ota_config.OTA_APN
        cid = ota_config.OTA_CONTEXT_ID
        pdp_type = ota_config.OTA_SOCKET_PDP_TYPE

        self.at('AT+CGDCONT=%d,"IPV6","%s"' % (cid, apn), 3000)
        self.at("AT+CSOCKSETPN=%d,%d" % (cid, pdp_type), 3000)

        netopen = self.at("AT+NETOPEN", 30000, expect=("+NETOPEN:", "\r\nERROR\r\n"))
        if "+NETOPEN:" not in netopen:
            # Documented SIM7600 quirk: NETOPEN can ERROR if a previous
            # session wasn't cleanly closed. One NETCLOSE + retry recovers
            # most of the time.
            print("NETOPEN did not confirm, retrying after NETCLOSE...")
            self.at("AT+NETCLOSE", 10000)
            time.sleep(1)
            netopen = self.at("AT+NETOPEN", 30000, expect=("+NETOPEN:", "\r\nERROR\r\n"))
            if "+NETOPEN:" not in netopen:
                raise CellularError("AT+NETOPEN failed twice: %s" % one_line(netopen))

        ip = self.at("AT+IPADDR", 5000)
        if "+IP ERROR" in ip or "ERROR" in ip or not ip.strip():
            raise CellularError(
                "AT+NETOPEN reported success but AT+IPADDR failed: %s" % one_line(ip)
            )

        print("Cellular data open. IP:", one_line(ip))
        self._data_open = True

    def close_data(self):
        try:
            self.at("AT+HTTPTERM", 3000)
        except Exception:
            pass
        try:
            self.at("AT+NETCLOSE", 10000)
        except Exception:
            pass
        self._data_open = False

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
        status, length = parse_http_action(action)
        if status != 200:
            self.at("AT+HTTPTERM", 3000)
            raise CellularError("HTTP status %s for %s" % (status, url))

        if length <= 0:
            self.at("AT+HTTPTERM", 3000)
            raise CellularError("empty HTTP response for %s" % url)

        raw = self.read_http_data(length, max(10000, length * 4))
        self.at("AT+HTTPTERM", 3000)
        return parse_http_read(raw, expected_length=length)

    def http_post_json(self, url, body_bytes, timeout_ms=60000):
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
            raise CellularError("modem did not prompt DOWNLOAD for HTTPDATA")

        print(">>> (writing %d bytes of JSON body)" % len(body_bytes))
        self.flush()
        self.uart.write(body_bytes)
        self.read_until(("\r\nOK\r\n", "\r\nERROR\r\n"), 5000)

        action = self.at("AT+HTTPACTION=1", timeout_ms, expect=("+HTTPACTION:", "\r\nERROR\r\n"))
        status, length = parse_http_action(action)
        if status != 200:
            self.at("AT+HTTPTERM", 3000)
            raise CellularError("HTTP status %s posting to %s" % (status, url))

        if length <= 0:
            self.at("AT+HTTPTERM", 3000)
            return ""

        raw = self.read_http_data(length, max(10000, length * 4))
        self.at("AT+HTTPTERM", 3000)
        return parse_http_read(raw, expected_length=length)
