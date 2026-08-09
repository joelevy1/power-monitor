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

HTTP AT command behavior (chunked "+HTTPREAD: DATA,<n>" responses,
"Maximum Response Time: 120000ms" for HTTPINIT/HTTPTERM/HTTPACTION/
HTTPREAD) is per SIMCom's official SIM7500_SIM7600 Series AT Command
Manual (HTTP(S) AT Commands chapter) -- confirms the chunked format this
code parses was correct from the start; the actual bugs were an
undersized UART RX buffer and timeouts far shorter than the documented
maximum, both fixed below.
"""

import time

import ota_config


class CellularError(Exception):
    pass


def _diag(msg):
    try:
        import diag_log

        diag_log.log("cell %s" % msg)
    except Exception:
        pass


# SIMCom's official SIM7500_SIM7600 Series AT Command Manual (HTTP(S) AT
# Commands chapter) documents "Maximum Response Time: 120000ms" for
# AT+HTTPINIT, AT+HTTPTERM, AT+HTTPACTION, and AT+HTTPREAD. This code was
# previously using much shorter guessed timeouts (3-5s for INIT/TERM,
# ~10-15s for a response this size) -- all well under what the modem is
# officially allowed to take under real-world/adverse network conditions.
# Under good conditions responses come back in a couple seconds regardless;
# this only matters when the network is slow, which is exactly when a
# too-short timeout would cause a real, in-progress transfer to be cut off.
HTTP_CMD_TIMEOUT_MS = 120000

# Google Apps Script Web Apps (the script.google.com/.../exec URL used by
# sheets_log.py) ALWAYS answer with an HTTP redirect to a
# script.googleusercontent.com URL that serves the actual doPost()/doGet()
# response body -- confirmed on real hardware: AT+HTTPACTION returned
# "1,302,0" (status 302, zero-length body -- nothing for AT+HTTPREAD to
# read). This is normal, expected Apps Script behavior, not an error. It
# was invisible from the PC-side test (apps_script_test.py) because
# Python's urllib follows redirects automatically; the SIM7600's own HTTP
# client does not (its AT+HTTPPARA options have no auto-redirect toggle --
# checked against SIMCom's official AT command manual). The fix mirrors
# what a browser/urllib already does: read the Location header via
# AT+HTTPHEAD (the response body isn't where redirect targets live) and
# re-request it.
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5


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


def extract_location(header_text):
    """Pull the value of a "Location:" header out of AT+HTTPHEAD's raw
    response text (the header block SIMCom's manual example shows as
    "HTTP/1.1 200 OK\\r\\nDate: ...\\r\\n..."). Case-insensitive since HTTP
    header names aren't guaranteed a specific case. Returns None if no
    Location header is present (e.g. a non-redirect status).
    """
    if isinstance(header_text, bytes):
        header_text = header_text.decode("utf-8", "ignore")
    for line in header_text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line[:9].lower() == "location:":
            return line.split(":", 1)[1].strip()
    return None


def parse_http_read(data, expected_length=None, debug=True):
    """Parse one or more '+HTTPREAD: DATA,<n>\\r\\n<n bytes>' chunks.

    Observed on-device: large AT+HTTPREAD responses get split into
    multiple ~1024-byte chunks, each with its own '+HTTPREAD: DATA,<n>'
    header -- not the single '+HTTPREAD: <n>\\r\\n<data>\\r\\nOK' shape some
    SIM7600 docs describe (SIMCom's official manual confirms this exact
    repeated-chunk format is correct). Extracting each chunk by its
    declared byte length (rather than scanning for the next marker/OK/
    newline) is required because the data itself can contain those
    substrings.

    Operates on RAW BYTES, not a decoded string -- <n> is a byte count
    declared by the modem, and this codebase's own Python source files
    can contain multi-byte UTF-8 characters (e.g. the em dash "\u2014" in
    config.py's header comment: 3 bytes, 1 character after decoding).
    Slicing an already-decoded string by that byte count corrupted a real
    chunk boundary on real hardware the moment such a character landed
    before it -- config.py was exactly the file that triggered this,
    since the OTA manifest (pure ASCII JSON) never contains one. Decoding
    to UTF-8 only once, after all chunks are correctly reassembled as
    bytes, avoids this entirely.

    expected_length: if given (the byte count already known from
    AT+HTTPACTION's response), raise CellularError with the exact
    shortfall/mismatch instead of silently returning truncated data.
    debug=True prints each chunk found (index/declared length/position)
    for diagnosing any future issue directly from Thonny output.

    Returns a decoded UTF-8 string (same external type as before).
    """
    if isinstance(data, str):
        data = data.encode("utf-8", "ignore")

    marker = b"+HTTPREAD: DATA,"
    if marker not in data:
        raise CellularError("missing HTTPREAD DATA response")

    chunks = []
    pos = 0
    chunk_index = 0
    while True:
        idx = data.find(marker, pos)
        if idx < 0:
            break

        header_start = idx + len(marker)
        newline_idx = data.find(b"\n", header_start)
        if newline_idx < 0:
            raise CellularError("bad HTTPREAD chunk header (no newline after length)")

        length_str = data[header_start:newline_idx].strip().rstrip(b"\r")
        try:
            chunk_len = int(length_str)
        except ValueError:
            raise CellularError("bad HTTPREAD chunk length: %r" % length_str)

        data_start = newline_idx + 1
        chunk = data[data_start : data_start + chunk_len]
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

    result_bytes = b"".join(chunks)

    if expected_length is not None and len(result_bytes) != expected_length:
        raise CellularError(
            "HTTPREAD reassembled %d bytes but AT+HTTPACTION declared %d -- "
            "%d chunk(s) found, likely one was skipped or truncated"
            % (len(result_bytes), expected_length, len(chunks))
        )

    return result_bytes.decode("utf-8", "ignore")


def modem_uart_responds():
    """True if the SIM7600 answers AT on UART (not in AT+CPOF sleep).

    Does not pulse PWRKEY — only observes. Safe to call from standby when
    no logging session should be using the modem.
    """
    try:
        modem = Sim7600Modem()
        return "OK" in modem.at("AT", 900, quiet=True)
    except Exception:
        return False


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
        # Waveshare HAT PWR selector input. The HAT translates this 3.3V
        # active-HIGH control into the SIM7600 module's active-LOW PWRKEY.
        # LOW is released; a ~1.2s HIGH pulse starts a powered-off modem.
        self.pwrkey = Pin(cfg.PIN_MODEM_PWRKEY, Pin.OUT, value=0)
        self._cfg = cfg
        self._data_open = False

    def reset(self):
        print("Resetting modem...")
        self.rst.value(0)
        time.sleep(0.3)
        self.rst.value(1)
        time.sleep(3)

    def ensure_awake(self, boot_timeout_s=30):
        """Wake a modem shut down by AT+CPOF; return True if newly started.

        GP10/RST cannot wake this HAT after a true power-off. GP7 drives the
        HAT's buffered PWR input and was confirmed on real hardware to wake
        the modem after AT+CPOF. Avoid pulsing PWR when AT already responds:
        PWRKEY is a state control, not a reset line.
        """
        if "OK" in self.at("AT", 1200, quiet=True):
            return False

        print("Modem is off; pulsing PWRKEY on GP%d..." % self._cfg.PIN_MODEM_PWRKEY)
        self.pwrkey.value(1)
        time.sleep(1.2)
        self.pwrkey.value(0)

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < boot_timeout_s * 1000:
            time.sleep(1)
            if "OK" in self.at("AT", 900, quiet=True):
                print("Modem woke via PWRKEY.")
                return True

        raise CellularError(
            "Modem did not wake after GP%d PWRKEY pulse within %ds"
            % (self._cfg.PIN_MODEM_PWRKEY, boot_timeout_s)
        )

    def power_off(self):
        """Gracefully power the modem off, leaving 5V present at the HAT."""
        if "OK" not in self.at("AT", 1200, quiet=True):
            print("Modem already off.")
            return True

        print("Powering modem off with AT+CPOF...")
        resp = self.at("AT+CPOF", 15000)
        if "OK" not in resp or "ERROR" in resp:
            print("WARNING: modem refused AT+CPOF; leaving it powered.")
            return False

        # The bench test showed current returning to the Pico-only baseline
        # after shutdown. Five seconds is ample before the next 5+ minute
        # logging cycle and avoids blocking for the full UART-off interval.
        time.sleep(5)
        print("Modem power-off accepted.")
        return True

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

    # Read cap used when AT+HTTPACTION declared length is 0/unknown (see
    # read_http_data()'s expected_length=None mode) -- Apps Script JSON
    # responses this codebase actually reads back are well under 1KB, so
    # this is generous headroom, not a tight fit.
    UNKNOWN_LENGTH_READ_CAP = 8192

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

        expected_length=None (or <= 0): the response's real length isn't
        known in advance -- confirmed on real hardware against
        script.googleusercontent.com's Apps Script redirect target, which
        answers with Transfer-Encoding: chunked (no Content-Length
        header). This modem/firmware reports THAT as declared length 0
        via AT+HTTPACTION (immediately followed by an unsolicited
        "+HTTP_PEER_CLOSED", which per SIMCom's manual just means the
        server closed the TCP connection -- not that the response was
        lost; the modem still buffers it internally for AT+HTTPREAD).
        In this mode, request UNKNOWN_LENGTH_READ_CAP bytes and rely on
        the modem's own "+HTTPREAD: 0" (zero-more-bytes) terminator to
        know when the response is complete, instead of a byte count
        known in advance -- every prior successful transfer (known-length
        or not) has ended with this exact terminator right after its
        last real chunk, so this is the same signal the modem already
        gives, just used as the primary stop condition instead of an
        afterthought drain.
        """
        known_length = expected_length is not None and expected_length > 0
        read_cap = expected_length if known_length else self.UNKNOWN_LENGTH_READ_CAP
        cmd = "AT+HTTPREAD=0,%d" % read_cap
        print(">>>", cmd)
        self.flush()
        self.uart.write((cmd + "\r\n").encode())

        marker = b"+HTTPREAD: DATA,"
        terminator = b"+HTTPREAD: 0"
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

                if known_length:
                    done = accounted_for >= expected_length
                else:
                    # Only search past the last parsed chunk, matching the
                    # same defensive posture as the marker search above --
                    # avoids a false positive if this literal substring
                    # ever appeared inside real chunk data.
                    done = terminator in buf[scan_pos:]

                if done:
                    # Briefly drain any trailing "\r\nOK\r\n", then stop --
                    # we have everything we need.
                    time.sleep(0.2)
                    if self.uart.any():
                        buf += self.uart.read()
                    break

                if b"\r\nERROR\r\n" in buf:
                    break

            time.sleep(0.01)

        # Print a decoded preview for diagnostics only -- the actual return
        # value stays as raw bytes. Decoding here and returning that string
        # (instead of bytes) previously risked losing a multi-byte UTF-8
        # character split across a UART read boundary (errors="ignore"
        # silently drops incomplete sequences); parse_http_read() does the
        # one real decode, after chunks are correctly reassembled by byte
        # length.
        print(buf.decode("utf-8", "ignore").strip() or "(no response)")
        return buf

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
        """Retries a few times on "SIM busy" specifically -- confirmed on
        real hardware right after AT+CFUN=1 (restoring full functionality
        from the low-power AT+CFUN=0 mode): the SIM subsystem needs a
        moment to reinitialize and can transiently answer AT+CPIN? with
        "+CME ERROR: SIM busy" before settling to "+CPIN: READY" a moment
        later. Any other non-ready response fails immediately as before --
        this isn't a blanket retry, just covering this one specific,
        already-observed transient.

        Also fixes a real pre-existing bug: both error branches below
        called an undefined _one_line() (the actual module-level function
        is one_line(), no underscore) -- meaning check_sim() would have
        raised a confusing NameError instead of the intended CellularError
        with a clear diagnostic, the moment either branch was ever
        actually hit. Never caught before now because the SIM had always
        responded "READY" on the very first attempt in every prior test.
        """
        for attempt in range(3):
            resp = self.at("AT+CPIN?", 3000)
            if "READY" in resp:
                return
            if "SIM PIN" in resp or "SIM PUK" in resp:
                raise CellularError("SIM is PIN/PUK locked (AT+CPIN? -> %s)" % one_line(resp))
            if "SIM busy" in resp and attempt < 2:
                print("SIM busy, retrying...")
                time.sleep(1)
                continue
            raise CellularError("No SIM detected or not ready (AT+CPIN? -> %s)" % one_line(resp))

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

        # A modem deliberately shut down after the prior logging cycle needs
        # PWRKEY, not RST. Preserve the established reset-first behavior only
        # when the modem was already running; a freshly PWRKEY-started module
        # has just completed its own clean boot.
        newly_started = self.ensure_awake()
        _diag("ensure_awake newly_started=%s" % newly_started)
        if not newly_started:
            self.reset()
            _diag("modem reset pulse")

        self.check_alive()
        _diag("modem AT ok")
        self.check_sim()
        _diag("SIM ready")
        self.wait_for_registration(seconds=registration_timeout_s)
        _diag("registered")

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

        _diag("NETOPEN ok")
        ip = self.at("AT+IPADDR", 5000)
        if "+IP ERROR" in ip or "ERROR" in ip or not ip.strip():
            raise CellularError(
                "AT+NETOPEN reported success but AT+IPADDR failed: %s" % one_line(ip)
            )

        print("Cellular data open. IP:", one_line(ip))
        _diag("data open ip=%s" % one_line(ip)[:80])
        self._data_open = True

    def close_data(self):
        # NOTE: this deliberately does NOT send AT+CFUN=0 anymore.
        # modem_cfun_test.py's standalone bench run (CFUN=0 -> confirm
        # still AT-responsive -> CFUN=1 -> re-register) passed cleanly, so
        # this was wired in here for real power savings between logging
        # cycles. On the very next real boot afterward, the boot-time OTA
        # check's very first AT+CPIN? got "+CME ERROR: SIM failure" --
        # not the transient "SIM busy" check_sim() already retries on,
        # but a harder failure -- and the SAME failure repeated identically
        # on the next auto-log cycle 300s later. check_alive() (AT/ATE0)
        # succeeded both times; only SIM detection failed, immediately
        # after self.reset()'s hardware reset pulse -- meaning reset()
        # alone did NOT reliably clear whatever state AT+CFUN=0 left the
        # SIM interface in, contradicting this method's own reasoning
        # above about reset() recovering from every prior state. The
        # timing (first cellular attempt after this exact change shipped)
        # is too suspicious to keep running unattended without further
        # investigation on real hardware -- reverted out of caution rather
        # than guessing at an unverified fix (e.g. adding AT+CFUN=1 to
        # ensure_data() without being able to test it directly).
        try:
            self.at("AT+HTTPTERM", 15000)
        except Exception:
            pass
        try:
            self.at("AT+NETCLOSE", 15000)
        except Exception:
            pass
        self._data_open = False
        try:
            self.power_off()
        except Exception as exc:
            # Teardown must not turn an otherwise successful Sheet/OTA
            # transaction into a reported failure. Leaving the modem on is
            # the safe fallback; the next session can reset it as before.
            print("WARNING: modem power-off failed:", exc)

    def read_http_head(self, timeout_ms=15000):
        """Read the response headers for the just-completed AT+HTTPACTION
        via AT+HTTPHEAD -- must be called BEFORE AT+HTTPTERM, which
        discards them. This is the only way to see a redirect's Location
        header: AT+HTTPREAD only returns the response BODY, and a
        redirect's <data_len> from AT+HTTPACTION is typically 0.

        Deliberately does NOT include "+HTTPHEAD:" as a read_until() stop
        token (unlike AT+HTTPACTION's use of "+HTTPACTION:") -- that
        marker appears at the very START of this response, so stopping on
        it would return before the header text and trailing OK have
        actually arrived. Waiting for the normal "\\r\\nOK\\r\\n"/
        "\\r\\nERROR\\r\\n" terminators (this method's default expect)
        gets the whole block.
        """
        resp = self.at("AT+HTTPHEAD", timeout_ms)
        if "+HTTPHEAD" not in resp:
            raise CellularError("AT+HTTPHEAD failed: %s" % one_line(resp))
        return resp

    def _resolve_redirect(self, url, redirect_count):
        """Read the Location header for the just-completed AT+HTTPACTION
        and close out this HTTP session. Must run before AT+HTTPTERM.
        """
        if redirect_count >= MAX_REDIRECTS:
            self.at("AT+HTTPTERM", 15000)
            raise CellularError("too many redirects starting from %s" % url)

        head = self.read_http_head(15000)
        location = extract_location(head)
        self.at("AT+HTTPTERM", 15000)
        if not location:
            raise CellularError("redirect with no Location header: %s" % one_line(head))
        print("Following redirect ->", location)
        return location

    def http_get(self, url):
        print("HTTP GET", url)
        redirect_count = 0
        while True:
            self.at("AT+HTTPTERM", 15000)
            self.at("AT+HTTPINIT", HTTP_CMD_TIMEOUT_MS)
            self.at('AT+HTTPPARA="CID",%d' % ota_config.OTA_CONTEXT_ID, 15000)

            if url.startswith("https://"):
                self.at("AT+HTTPSSL=1", 15000)
            else:
                self.at("AT+HTTPSSL=0", 15000)

            self.at('AT+HTTPPARA="URL","%s"' % url, 15000)
            action = self.at(
                "AT+HTTPACTION=0", HTTP_CMD_TIMEOUT_MS, expect=("+HTTPACTION:", "\r\nERROR\r\n")
            )
            status, length = parse_http_action(action)

            if status in REDIRECT_STATUSES:
                url = self._resolve_redirect(url, redirect_count)
                redirect_count += 1
                continue

            if status != 200:
                self.at("AT+HTTPTERM", 15000)
                raise CellularError("HTTP status %s for %s" % (status, url))

            if length > 0:
                raw = self.read_http_data(length, max(HTTP_CMD_TIMEOUT_MS, length * 4))
                self.at("AT+HTTPTERM", 15000)
                return parse_http_read(raw, expected_length=length)

            # Declared length 0 with a 200 status does NOT necessarily mean
            # an empty body -- confirmed on real hardware against
            # script.googleusercontent.com's Apps Script redirect target
            # (the same URL a Google Sheets logging POST's 302 redirect
            # leads to): AT+HTTPACTION reported "0,200,0" here, immediately
            # followed by an unsolicited "+HTTP_PEER_CLOSED" (SIMCom's
            # manual: the server closed the connection -- not that the
            # response was lost). That response is Transfer-Encoding:
            # chunked (no Content-Length header), which this modem/
            # firmware reports as declared length 0. Previously this
            # branch raised immediately without ever trying AT+HTTPREAD at
            # all. read_http_data(None, ...) now attempts the read anyway,
            # relying on the modem's own "+HTTPREAD: 0" terminator instead
            # of a byte count known in advance.
            raw = self.read_http_data(None, HTTP_CMD_TIMEOUT_MS)
            self.at("AT+HTTPTERM", 15000)
            return parse_http_read(raw, expected_length=None)

    def http_post_json(self, url, body_bytes, timeout_ms=HTTP_CMD_TIMEOUT_MS):
        self.at("AT+HTTPTERM", 15000)
        self.at("AT+HTTPINIT", HTTP_CMD_TIMEOUT_MS)
        self.at('AT+HTTPPARA="CID",%d' % ota_config.OTA_CONTEXT_ID, 15000)

        if url.startswith("https://"):
            self.at("AT+HTTPSSL=1", 15000)
        else:
            self.at("AT+HTTPSSL=0", 15000)

        self.at('AT+HTTPPARA="URL","%s"' % url, 15000)
        self.at('AT+HTTPPARA="CONTENT","application/json"', 15000)

        download_prompt = self.at(
            "AT+HTTPDATA=%d,10000" % len(body_bytes),
            15000,
            expect=("DOWNLOAD", "\r\nERROR\r\n"),
        )
        if "DOWNLOAD" not in download_prompt:
            self.at("AT+HTTPTERM", 15000)
            raise CellularError("modem did not prompt DOWNLOAD for HTTPDATA")

        print(">>> (writing %d bytes of JSON body)" % len(body_bytes))
        self.flush()
        self.uart.write(body_bytes)
        self.read_until(("\r\nOK\r\n", "\r\nERROR\r\n"), 15000)

        action = self.at("AT+HTTPACTION=1", timeout_ms, expect=("+HTTPACTION:", "\r\nERROR\r\n"))
        status, length = parse_http_action(action)

        if status in REDIRECT_STATUSES:
            # Per-spec a 307/308 should re-POST the same body, but Apps
            # Script (the only POST target this code has) only ever sends
            # 302 here, and its redirect target serves the already-computed
            # doPost() response on a plain GET -- the same convention
            # browsers and Python's urllib follow when downgrading a
            # redirected POST to GET. http_get() reuses this same
            # redirect-following loop for the (rare) case the redirect
            # target itself redirects again.
            redirect_url = self._resolve_redirect(url, 0)
            return self.http_get(redirect_url)

        if status != 200:
            self.at("AT+HTTPTERM", 15000)
            raise CellularError("HTTP status %s posting to %s" % (status, url))

        if length <= 0:
            self.at("AT+HTTPTERM", 15000)
            return ""

        raw = self.read_http_data(length, max(HTTP_CMD_TIMEOUT_MS, length * 4))
        self.at("AT+HTTPTERM", 15000)
        return parse_http_read(raw, expected_length=length)
