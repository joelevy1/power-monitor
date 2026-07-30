"""
Boat Monitor P2 — bench bring-up tester (MicroPython / Pico W)

Copy config.py + bench_test.py to the Pico (Thonny → Save as → Pico).

SAFE START (your setup now):
  - Pico on USB to laptop only
  - No boat 12 V, V50, or modem 5 V yet
  - OK: I2C scan, LED test, GPIO idle read (opto pins should read 1 = HIGH)

SIMULATE boat signals (bench 12 V supply, current-limited if possible):
  - Minus → main ground bus (same as Pico GND)
  - Plus → ONE harness wire at a time (opto IN+ side only — never Pico pins)
  - Opto is active LOW: applying 12 V should pull the matching GPIO to 0

Run: bench_test.main()   or just F5 / Run in Thonny after import bench_test
"""

import time

from machine import I2C, Pin, UART

import config as cfg

# ---------------------------------------------------------------------------
# Sensor drivers (minimal — same math as remotebatterystatus)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Hardware setup
# ---------------------------------------------------------------------------

def setup():
    inputs = {}
    for _label, gpio, _harness in cfg.HARNESS_SIGNALS:
        # HY-M154 / PC817 outputs are open-collector style: idle=1, active=0.
        inputs[gpio] = Pin(gpio, Pin.IN, Pin.PULL_UP)

    tps_stat = Pin(cfg.PIN_TPS_STAT, Pin.IN)
    vsns = Pin(cfg.PIN_TPS_VSNS, Pin.OUT, value=0)

    leds = {
        "red": Pin(cfg.PIN_LED_RED, Pin.OUT, value=0),
        "green": Pin(cfg.PIN_LED_GREEN, Pin.OUT, value=0),
        "blue": Pin(cfg.PIN_LED_BLUE, Pin.OUT, value=0),
    }

    uart = UART(
        1,
        baudrate=cfg.MODEM_BAUD,
        tx=Pin(cfg.PIN_UART_TX),
        rx=Pin(cfg.PIN_UART_RX),
    )
    modem_rst = Pin(cfg.PIN_MODEM_RESET, Pin.OUT, value=1)

    return {
        "inputs": inputs,
        "tps_stat": tps_stat,
        "vsns": vsns,
        "leds": leds,
        "uart": uart,
        "modem_rst": modem_rst,
    }


def i2c_bus(sda, scl, bus_id):
    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=100_000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def print_help():
    print(
        """
=== SIMULATION CHEAT SHEET ===
Power stages (add when ready, in this order):
  1) USB only        → Pico, 3V3 sensors, opto outputs, GPIO tests
  2) V50 USB #1      → Pico via TPS path; INA219 should read ~5 V bus
  3) V50 USB #2      → Modem 5V (through diode) — for AT tests
  4) Bench 12V       → One harness wire at a time (see below)
  5) Full boat       → Batteries, solar, switch

Bench 12V rules:
  • (−) on main ground bus only
  • (+) on harness wire → opto IN+ (never a Pico GPIO)
  • Expected: GPIO goes 1→0 while 12V applied (active LOW)

Per-wire simulation:
  Mid bilge wire     → Ch1 IN+  → pin 31 / GP26
  Aft bilge wire     → Ch2 IN+  → pin 29 / GP22
  Mid water return   → Ch3 IN+  → pin 25 (float hot needs house +)
  Aft water return   → Ch4 IN+  → pin 24
  Switch wire        → Ch5 IN+  → pin 26 (+ PlusRoc IN+ when powered)
  Key wire           → Ch6 IN+  → pin 27

Float shortcut (no house + yet): 12V (+) to float return wire, (−) to ground.

TPS STAT (pin 9 / GP6): reads which input is selected when TPS has power.
Modem test needs 5V on SIM7600 + common GND; then menu option 8.

Menu:
  1  Scan all I2C buses
  2  Read INA260 + INA219
  3  Read all opto / GPIO inputs once
  4  Watch inputs (live, Ctrl+C to stop)
  5  LED test
  6  TPS STAT + VSNS
  7  Power summary (what should work with current wiring)
  8  Modem AT ping (needs modem 5V)
  9  Run automatic smoke test
  h  Help / simulation guide
  q  Quit
"""
    )


def scan_bus(name, sda, scl, bus_id):
    print(f"\n--- I2C {name} (SDA=GP{sda} SCL=GP{scl}) ---")
    try:
        i2c = i2c_bus(sda, scl, bus_id)
        addrs = i2c.scan()
        if not addrs:
            print("  (no devices — check 3V3 to sensor Vcc and SDA/SCL)")
        for a in addrs:
            print(f"  found 0x{a:02X}")
        return addrs
    except Exception as e:
        print(f"  ERROR: {e}")
        return []


def test_i2c_scan():
    print("\n=== TEST 1: I2C scan (three separate buses) ===")
    e = scan_bus("ENGINE INA260", cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0)
    h = scan_bus("HOUSE INA260", cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1)
    v = scan_bus("V50 INA219", cfg.I2C_V50_SDA, cfg.I2C_V50_SCL, 0)
    ok = bool(e) and bool(h) and bool(v)
    print("\nPASS" if ok else "PARTIAL/FAIL — expect 0x40 on each bus when powered")
    return ok


def test_sensors():
    print("\n=== TEST 2: INA260 / INA219 readings ===")
    try:
        ie = i2c_bus(cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0)
        eng = INA260(ie, cfg.INA260_ENGINE_ADDR)
        print(
            f"  Engine  V={eng.read_voltage_v():.3f} V  "
            f"I={eng.read_current_a()*1000:.1f} mA  P={eng.read_power_w():.3f} W"
        )
    except Exception as e:
        print(f"  Engine INA260 ERROR: {e}")

    try:
        ih = i2c_bus(cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1)
        house = INA260(ih, cfg.INA260_HOUSE_ADDR)
        print(
            f"  House   V={house.read_voltage_v():.3f} V  "
            f"I={house.read_current_a()*1000:.1f} mA  P={house.read_power_w():.3f} W"
        )
    except Exception as e:
        print(f"  House INA260 ERROR: {e}")

    try:
        iv = i2c_bus(cfg.I2C_V50_SDA, cfg.I2C_V50_SCL, 0)
        v50 = INA219(iv, cfg.INA219_V50_ADDR)
        print(
            f"  V50     bus={v50.read_bus_voltage_v():.3f} V  "
            f"I={v50.read_current_ma():.1f} mA"
        )
    except Exception as e:
        print(f"  INA219 ERROR: {e}")

    print("  (Bus V near 0 without 12V batteries / V50; that's normal on USB-only)")


def _gpio_label(gpio):
    for label, pin, harness in cfg.HARNESS_SIGNALS:
        if pin == gpio:
            return label, harness
    return "?", "?"


def read_inputs(hw):
    rows = []
    for label, gpio, harness in cfg.HARNESS_SIGNALS:
        v = hw["inputs"][gpio].value()
        active = v == 0
        rows.append((label, gpio, v, active, harness))
    return rows


def test_gpio_once(hw):
    print("\n=== TEST 3: Optocoupler GPIO (1=idle  0=signal ON) ===")
    for label, gpio, v, active, harness in read_inputs(hw):
        state = "ON " if active else "off"
        print(f"  {label:18} GP{gpio:2}  raw={v}  {state:4}  ← {harness}")
    print("  Apply 12V to a harness wire; re-run or use watch (4) to see 0.")


def watch_inputs(hw, interval=0.3):
    print("\n=== LIVE watch (Ctrl+C to stop) ===")
    print("Apply 12V to harness wires one at a time.\n")
    last = None
    try:
        while True:
            parts = []
            for label, gpio, v, active, _ in read_inputs(hw):
                parts.append(f"{label[:8]}:{'ON' if active else '--'}")
            line = "  ".join(parts)
            if line != last:
                print(line)
                last = line
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def test_leds(hw):
    print("\n=== TEST 5: LEDs ===")
    order = ("red", "green", "blue")
    for name in order:
        print(f"  {name} ON")
        for k, p in hw["leds"].items():
            p.value(1 if k == name else 0)
        time.sleep(0.5)
    for p in hw["leds"].values():
        p.value(0)
    print("  LEDs off — OK if you saw all three colors")


def test_tps(hw):
    print("\n=== TEST 6: TPS2113A ===")
    stat = hw["tps_stat"].value()
    print(f"  STAT (GP{cfg.PIN_TPS_STAT}) = {stat}")
    print("  (Meaningful only when TPS OUT has power from V50 or PlusRoc)")
    print("  VSNS (GP{}) held LOW = {}".format(cfg.PIN_TPS_VSNS, hw["vsns"].value()))


def test_modem(hw, timeout_ms=3000):
    print("\n=== TEST 8: Modem UART AT ===")
    print("  Needs SIM7600 5V + GND; PWR jumper = PWR-3V3 on HAT")
    uart = hw["uart"]
    rst = hw["modem_rst"]

    rst.value(0)
    time.sleep(0.3)
    rst.value(1)
    time.sleep(2)

    while uart.any():
        uart.read()

    uart.write(b"AT\r\n")
    t0 = time.ticks_ms()
    buf = b""
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        if uart.any():
            buf += uart.read()
            if b"OK" in buf or b"ERROR" in buf:
                break
        time.sleep(0.05)

    try:
        text = buf.decode("utf-8", "ignore").strip()
    except Exception:
        text = str(buf)
    print(f"  TX: AT")
    print(f"  RX: {text or '(nothing — check 5V, GND, pins 11/12)'}")
    return b"OK" in buf


def power_summary():
    print("\n=== TEST 7: What works with each power stage ===")
    print(
        """
  USB only (now):
    ✓ Pico, REPL, this script
    ✓ 3V3 sensor Vcc (if wired to pin 36)
    ✓ I2C scan, LED test, GPIO idle (all 1s)
    ✗ INA bus voltage ~0, modem, TPS STAT, PlusRoc

  + V50 USB #1:
    ✓ Pico via TPS/INA219 path
    ✓ INA219 ~5 V reading

  + V50 USB #2:
    ✓ Modem 5V (via diode)

  + Bench 12V to one harness wire (GND common):
    ✓ That opto channel → GPIO 0

  + House/engine bat + solar:
    ✓ INA260 voltage/current

  + Switch ON + PlusRoc:
    ✓ TPS IN2, modem from PlusRoc diode path
"""
    )


def smoke_test(hw):
    print("\n=== AUTOMATIC SMOKE TEST ===")
    test_i2c_scan()
    test_sensors()
    test_gpio_once(hw)
    test_tps(hw)
    test_leds(hw)
    power_summary()
    print("\nSmoke test done. Use menu 4 + bench 12V for opto wiring proof.")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def main():
    print("Boat Monitor P2 — bench_test.py")
    print("Type h for simulation guide.\n")
    hw = setup()

    while True:
        try:
            cmd = input("\nCommand [1-9,h,q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if cmd in ("q", "quit", "exit"):
            break
        elif cmd == "h":
            print_help()
        elif cmd == "1":
            test_i2c_scan()
        elif cmd == "2":
            test_sensors()
        elif cmd == "3":
            test_gpio_once(hw)
        elif cmd == "4":
            watch_inputs(hw)
        elif cmd == "5":
            test_leds(hw)
        elif cmd == "6":
            test_tps(hw)
        elif cmd == "7":
            power_summary()
        elif cmd == "8":
            test_modem(hw)
        elif cmd == "9":
            smoke_test(hw)
        else:
            print("Unknown. Try h for help.")

    for p in hw["leds"].values():
        p.value(0)


if __name__ == "__main__":
    main()
