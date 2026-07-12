"""
Boat Monitor P2 - quick INA sensor checker (MicroPython / Pico W)

Copy config.py and this file to the Pico, then run:

    import check_inas
    check_inas.main()

USB-only is enough to prove each I2C board responds. Add V50 / bench 12 V only
when you are ready to verify the voltage and current readings.
"""

import time

from machine import I2C, Pin

import config as cfg


class INA260:
    REG_CURRENT = 0x01
    REG_VOLTAGE = 0x02
    REG_POWER = 0x03

    def __init__(self, i2c, address=0x40):
        self.i2c = i2c
        self.addr = address

    def _read16_signed(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        raw = (data[0] << 8) | data[1]
        if raw > 32767:
            raw -= 65536
        return raw

    def _read16_unsigned(self, reg):
        data = self.i2c.readfrom_mem(self.addr, reg, 2)
        return (data[0] << 8) | data[1]

    def read_current_a(self):
        return self._read16_signed(self.REG_CURRENT) * 1.25 / 1000

    def read_voltage_v(self):
        return self._read16_signed(self.REG_VOLTAGE) * 1.25 / 1000

    def read_power_w(self):
        return self._read16_unsigned(self.REG_POWER) * 10 / 1000


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
        return raw * 0.1


def i2c_bus(bus_id, sda_gpio, scl_gpio):
    return I2C(bus_id, sda=Pin(sda_gpio), scl=Pin(scl_gpio), freq=100_000)


def fmt_addrs(addrs):
    if not addrs:
        return "(none)"
    return ", ".join("0x%02X" % addr for addr in addrs)


def scan_expected(label, bus_id, sda_gpio, scl_gpio, expected_addr):
    print("\n%s" % label)
    print("  I2C%d SDA=GP%d SCL=GP%d expected=0x%02X" % (
        bus_id,
        sda_gpio,
        scl_gpio,
        expected_addr,
    ))

    i2c = i2c_bus(bus_id, sda_gpio, scl_gpio)
    addrs = i2c.scan()
    print("  scan: %s" % fmt_addrs(addrs))

    if expected_addr not in addrs:
        print("  FAIL: expected address not found")
        return None

    print("  PASS: board found")
    return i2c


def check_ina260(label, bus_id, sda_gpio, scl_gpio, address):
    i2c = scan_expected(label, bus_id, sda_gpio, scl_gpio, address)
    if i2c is None:
        return False

    try:
        sensor = INA260(i2c, address)
        print("  voltage: %.3f V" % sensor.read_voltage_v())
        print("  current: %.3f A" % sensor.read_current_a())
        print("  power:   %.3f W" % sensor.read_power_w())
        return True
    except Exception as exc:
        print("  READ FAIL: %s" % exc)
        return False


def check_ina219(label, bus_id, sda_gpio, scl_gpio, address):
    i2c = scan_expected(label, bus_id, sda_gpio, scl_gpio, address)
    if i2c is None:
        return False

    try:
        sensor = INA219(i2c, address)
        print("  bus voltage: %.3f V" % sensor.read_bus_voltage_v())
        print("  current:     %.1f mA" % sensor.read_current_ma())
        return True
    except Exception as exc:
        print("  READ FAIL: %s" % exc)
        return False


def run_once():
    print("\n=== Boat Monitor P2 INA check ===")
    print("USB-only: scans should pass; voltage may be near zero.")

    results = (
        check_ina260(
            "Engine INA260",
            0,
            cfg.I2C_ENGINE_SDA,
            cfg.I2C_ENGINE_SCL,
            cfg.INA260_ENGINE_ADDR,
        ),
        check_ina260(
            "House INA260",
            1,
            cfg.I2C_HOUSE_SDA,
            cfg.I2C_HOUSE_SCL,
            cfg.INA260_HOUSE_ADDR,
        ),
        check_ina219(
            "V50 INA219",
            0,
            cfg.I2C_V50_SDA,
            cfg.I2C_V50_SCL,
            cfg.INA219_V50_ADDR,
        ),
    )

    passed = sum(1 for ok in results if ok)
    print("\nSummary: %d/3 sensors found and readable" % passed)
    return passed == 3


def main(samples=1, delay_s=1):
    ok = False
    for sample in range(samples):
        if samples > 1:
            print("\nSample %d of %d" % (sample + 1, samples))
        ok = run_once()
        if sample + 1 < samples:
            time.sleep(delay_s)
    return ok


if __name__ == "__main__":
    main()
