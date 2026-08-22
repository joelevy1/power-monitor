"""Boat input and power status without loading the BLE stack."""

from machine import I2C, Pin

try:
    from machine import SoftI2C
except ImportError:
    SoftI2C = None

import config as cfg

try:
    import version
except ImportError:
    version = None


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

    def voltage_v(self):
        return self._read16(self.REG_VOLTAGE) * 1.25 / 1000

    def current_a(self):
        return self._read16(self.REG_CURRENT) * 1.25 / 1000

    def power_w(self):
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

    def _read_signed(self, reg):
        raw = self._read(reg)
        return raw - 65536 if raw > 32767 else raw

    def voltage_v(self):
        return (self._read(0x02) >> 3) * 0.004

    def current_a(self):
        return abs(self._read_signed(0x04) * 0.1) / 1000


def i2c_bus(sda, scl, bus_id):
    return I2C(bus_id, sda=Pin(sda), scl=Pin(scl), freq=100000)


def v50_i2c_bus(sda, scl):
    """Keep GP4/5 independent of the engine hardware I2C0 controller."""
    if SoftI2C is not None:
        return SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=100000)
    return i2c_bus(sda, scl, 0)


def read_ina260(sda, scl, bus_id, addr):
    try:
        sensor = INA260(i2c_bus(sda, scl, bus_id), addr)
        return {
            "v": round(sensor.voltage_v(), 3),
            "a": round(sensor.current_a(), 4),
            "w": round(sensor.power_w(), 3),
            "ok": True,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_v50():
    try:
        sensor = INA219(
            v50_i2c_bus(cfg.I2C_V50_SDA, cfg.I2C_V50_SCL),
            cfg.INA219_V50_ADDR,
        )
        raw_shunt = sensor._read_signed(0x01)
        raw_current = sensor._read_signed(0x04)
        raw_calibration = sensor._read(0x05)
        a = round(abs(raw_current * 0.1) / 1000, 4)
        v = round(sensor.voltage_v(), 3)
        result = {
            "v": v,
            "a": a,
            "ok": True,
            "raw_shunt": raw_shunt,
            "raw_current": raw_current,
            "raw_calibration": raw_calibration,
        }
        # With no USB bank on the harness, TPS IN1 can still show ~5 V at near-zero
        # amps (ghost on the unused leg). Treat as "not on bank" for logging/SOC.
        if abs(a) < 0.02:
            result["bank_idle"] = True
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def input_on(gpio):
    return Pin(gpio, Pin.IN, Pin.PULL_UP).value() == 0


def current_mode(inputs):
    if inputs["key"]:
        return "key_on"
    if inputs["switch"]:
        return "switch_on_key_off"
    if inputs["mid_float"] or inputs["aft_float"]:
        return "float_alert"
    if inputs["mid_bilge"] or inputs["aft_bilge"]:
        return "bilge_active"
    return "docked_off"


def read_status(command_result=None, sensors=True):
    inputs = {
        "switch": input_on(cfg.PIN_BATTERY_SWITCH),
        "key": input_on(cfg.PIN_KEY),
        "mid_bilge": input_on(cfg.PIN_BILGE_MID),
        "aft_bilge": input_on(cfg.PIN_BILGE_AFT),
        "mid_float": input_on(cfg.PIN_FLOAT_MID),
        "aft_float": input_on(cfg.PIN_FLOAT_AFT),
    }

    status = {
        "device": "boat-p2",
        "fw": getattr(version, "VERSION", "unknown") if version else "unknown",
        "mode": current_mode(inputs),
        "inputs": inputs,
        "note": "negative current means solar charging",
    }
    if sensors:
        status["engine"] = read_ina260(
            cfg.I2C_ENGINE_SDA, cfg.I2C_ENGINE_SCL, 0, cfg.INA260_ENGINE_ADDR
        )
        status["house"] = read_ina260(
            cfg.I2C_HOUSE_SDA, cfg.I2C_HOUSE_SCL, 1, cfg.INA260_HOUSE_ADDR
        )
        status["v50"] = read_v50()

    if command_result:
        status["command_result"] = command_result
        low = str(command_result).lower()
        if "fail" in low or "logged (power:" in low:
            try:
                import diag_log

                status["diag_tail"] = diag_log.recent_lines(8)
            except Exception:
                pass

    return status
