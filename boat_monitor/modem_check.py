import time
from machine import Pin, UART
import config as cfg


def ticks():
    return time.ticks_ms()


def elapsed_ms(start):
    return time.ticks_diff(time.ticks_ms(), start)


def one_line(text):
    text = text.replace("\r", "\n")
    parts = []
    for line in text.split("\n"):
        line = line.strip()
        if line and line != "OK":
            parts.append(line)
    return " | ".join(parts) if parts else "(none)"


class Modem:
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

    def send(self, cmd, timeout_ms=3000, quiet=False):
        if not quiet:
            print()
            print(">>>", cmd)

        self.flush()
        self.uart.write((cmd + "\r\n").encode())

        start = ticks()
        buf = b""
        while elapsed_ms(start) < timeout_ms:
            if self.uart.any():
                buf += self.uart.read()
                if b"\r\nOK\r\n" in buf or b"\r\nERROR\r\n" in buf:
                    break
            time.sleep(0.05)

        text = buf.decode("utf-8", "ignore").strip()
        if not quiet:
            print(text if text else "(no response)")
        return text

    def wait_for_registration(self, seconds=60):
        print()
        print("Waiting for network registration up to %d seconds..." % seconds)

        start = ticks()
        while elapsed_ms(start) < seconds * 1000:
            creg = self.send("AT+CREG?", timeout_ms=2000, quiet=True)
            cgreg = self.send("AT+CGREG?", timeout_ms=2000, quiet=True)
            cereg = self.send("AT+CEREG?", timeout_ms=2000, quiet=True)
            csq = self.send("AT+CSQ", timeout_ms=2000, quiet=True)

            print(
                "CREG:",
                one_line(creg),
                " CGREG:",
                one_line(cgreg),
                " CEREG:",
                one_line(cereg),
                " CSQ:",
                one_line(csq),
            )

            combined = creg + cgreg + cereg
            if ",1" in combined or ",5" in combined:
                print("Registered.")
                return True
            time.sleep(5)

        print("Not registered yet.")
        return False


def test_basic(modem):
    print()
    print("=== BASIC MODEM ===")
    modem.send("AT")
    modem.send("ATE0")
    modem.send("ATI")
    modem.send("AT+CPIN?")
    modem.send("AT+CSQ")
    modem.send("AT+COPS?")
    modem.send("AT+CREG?")
    modem.send("AT+CGREG?")
    modem.send("AT+CEREG?")


def test_data(modem):
    print()
    print("=== DATA / INTERNET ===")
    print("APN: iot.t-mobile.com")
    modem.send('AT+CGDCONT=1,"IPV6","iot.t-mobile.com"', timeout_ms=3000)
    modem.send("AT+CSOCKSETPN=1,6", timeout_ms=3000)
    modem.send("AT+CGACT?", timeout_ms=3000)
    modem.send("AT+NETCLOSE", timeout_ms=10000)
    modem.send("AT+NETOPEN", timeout_ms=30000)
    modem.send("AT+IPADDR", timeout_ms=5000)


def test_gps(modem):
    print()
    print("=== GPS ===")
    modem.send("AT+CGPS=1,1", timeout_ms=5000)
    time.sleep(2)

    for i in range(12):
        print()
        print("GPS poll %d/12" % (i + 1))
        text = modem.send("AT+CGPSINFO", timeout_ms=5000)
        if "+CGPSINFO:" in text and ",,,,,,,," not in text:
            print("GPS may have a fix.")
            break
        time.sleep(5)

    modem.send("AT+CGPS=0", timeout_ms=5000)


def main(reset_modem=True, do_gps=True):
    print("Boat Monitor P2 - SIM7600 modem check")
    print("Power modem from the path you are testing before running this.")
    print()

    modem = Modem()
    if reset_modem:
        modem.reset()

    test_basic(modem)
    modem.wait_for_registration(seconds=60)
    test_data(modem)

    if do_gps:
        test_gps(modem)

    print()
    print("Done.")


if __name__ == "__main__":
    main()
