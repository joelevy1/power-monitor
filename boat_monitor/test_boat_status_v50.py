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
    assert [bus.kind for bus in soft_calls] == ["soft"], soft_calls
    assert soft_calls[0].kwargs["sda"].number == 4
    assert soft_calls[0].kwargs["scl"].number == 5

    fallback_module, fallback_calls = load_boat_status(with_soft_i2c=False)
    fallback = fallback_module.read_v50()
    assert fallback["ok"] is True, fallback
    assert [bus.kind for bus in fallback_calls] == ["hardware"], fallback_calls
    assert fallback_calls[0].bus_id == 0

    print("boat_status V50 tests OK")


if __name__ == "__main__":
    run()
