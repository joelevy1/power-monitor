"""Host tests for the V50 INA219 SoftI2C path and raw measurements."""

import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class FakePin:
    IN = 0
    PULL_UP = 1

    def __init__(self, number, *_args, **_kwargs):
        self.number = number

    def value(self):
        return 1


class FakeBus:
    def __init__(self, kind, calls, bus_id=None, **kwargs):
        self.kind = kind
        self.calls = calls
        self.bus_id = bus_id
        self.kwargs = kwargs
        self.registers = {
            0x01: 3500,       # signed shunt register count
            0x02: 1250 << 3,  # 5.000 V
            0x04: 320,        # 32.0 mA at 0.1 mA/bit
        }
        calls.append(self)

    def writeto_mem(self, _addr, reg, data):
        self.registers[reg] = int.from_bytes(data, "big")

    def readfrom_mem(self, _addr, reg, _length):
        return self.registers[reg].to_bytes(2, "big")


def load_boat_status(with_soft_i2c):
    calls = []

    class FakeI2C(FakeBus):
        def __init__(self, bus_id, **kwargs):
            super().__init__("hardware", calls, bus_id=bus_id, **kwargs)

    machine_attrs = {"I2C": FakeI2C, "Pin": FakePin}
    if with_soft_i2c:
        class FakeSoftI2C(FakeBus):
            def __init__(self, **kwargs):
                super().__init__("soft", calls, **kwargs)

        machine_attrs["SoftI2C"] = FakeSoftI2C

    original_machine = sys.modules.get("machine")
    sys.modules["machine"] = types.SimpleNamespace(**machine_attrs)
    try:
        name = "boat_status_v50_test_%s" % ("soft" if with_soft_i2c else "fallback")
        spec = importlib.util.spec_from_file_location(name, ROOT / "boat_status.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, calls
    finally:
        if original_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = original_machine


def run():
    soft_module, soft_calls = load_boat_status(with_soft_i2c=True)
    result = soft_module.read_v50()

    assert result["ok"] is True, result
    assert result["v"] == 5.0, result
    assert result["a"] == 0.032, result
    assert "bank_idle" not in result, result
    assert result["raw_shunt"] == 3500, result
    assert result["raw_current"] == 320, result
    assert result["raw_calibration"] == 4096, result
    assert result["raw_v"] == 5.0, result
    assert result["raw_a"] == 0.032, result
    assert result["raw_a_signed"] == 0.032, result
    assert [bus.kind for bus in soft_calls] == ["soft"], soft_calls
    assert soft_calls[0].kwargs["sda"].number == 4
    assert soft_calls[0].kwargs["scl"].number == 5

    class Ina260Bus:
        registers = {
            0x01: (65536 - 800),  # -1.000 A
            0x02: 10000,          # 12.500 V
            0x03: 123,            # 1.230 W
        }

        def readfrom_mem(self, _addr, reg, _length):
            return self.registers[reg].to_bytes(2, "big")

    ina260 = soft_module.INA260(Ina260Bus())
    assert ina260.voltage_v() == 12.5
    assert ina260.current_a() == -1.0
    assert ina260.power_w() == 1.23

    fallback_module, fallback_calls = load_boat_status(with_soft_i2c=False)
    fallback = fallback_module.read_v50()
    assert fallback["ok"] is True, fallback
    assert [bus.kind for bus in fallback_calls] == ["hardware"], fallback_calls
    assert fallback_calls[0].bus_id == 0

    sensor_reads = []

    def fake_ina(*args):
        sensor_reads.append(args)
        return {"ok": True, "v": 12.4, "a": 0.2}

    soft_module.read_ina260 = fake_ina
    soft_module.read_v50 = lambda *_args: {"ok": True, "v": 5.1, "a": 0.03}
    old_remote = sys.modules.get("remote_boot_config")
    sys.modules["remote_boot_config"] = types.SimpleNamespace(
        load=lambda: {"engine_voltage_scale": 1.01}
    )
    try:
        populated = soft_module.read_status(sensors=True)
    finally:
        if old_remote is None:
            sys.modules.pop("remote_boot_config", None)
        else:
            sys.modules["remote_boot_config"] = old_remote
    assert populated["engine"]["v"] == 12.4
    assert populated["house"]["v"] == 12.4
    assert populated["v50"]["v"] == 5.1
    assert len(sensor_reads) == 2
    assert sensor_reads[0][4] == 1.01
    assert {
        "device",
        "fw",
        "mode",
        "inputs",
        "note",
        "engine",
        "house",
        "v50",
    }.issubset(populated)
    assert set(populated["inputs"]) == {
        "switch",
        "key",
        "mid_bilge",
        "aft_bilge",
        "mid_float",
        "aft_float",
    }

    sensor_reads.clear()
    cached = soft_module.read_status(sensors=False)
    assert cached["engine"] == populated["engine"]
    assert cached["house"] == populated["house"]
    assert cached["v50"] == populated["v50"]
    assert sensor_reads == []

    print("boat_status V50 tests OK")


if __name__ == "__main__":
    run()
