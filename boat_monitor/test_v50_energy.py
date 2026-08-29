"""Host tests for v50_energy mAh integration."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v50_energy", ROOT / "v50_energy.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["v50_energy"] = mod
spec.loader.exec_module(mod)


class FakeClock:
    def __init__(self):
        self.ms = 0

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, a, b):
        return a - b

    def advance_s(self, s):
        self.ms += int(s * 1000)


def run():
    state_path = ROOT / "v50_energy.json"
    if state_path.exists():
        state_path.unlink()

    clock = FakeClock()
    mod._ticks_ms = clock.ticks_ms
    mod._ticks_diff = clock.ticks_diff

    mod.reset_full("2026-01-01T00:00:00Z")
    mod.set_capacity_mah(13400)

    v50 = {"ok": True, "v": 5.0, "a": 1.0}
    mod.tick(v50)
    clock.advance_s(3600)
    mod.tick(v50)
    snap = mod.snapshot()
    assert abs(snap["mah_used"] - 1000.0) < 1.0, snap
    assert snap["pct_remain"] is not None and snap["pct_remain"] < 100

    mod.mark_full_if_anchor("2026-02-01T00:00:00Z")
    snap2 = mod.snapshot()
    assert snap2["mah_used"] == 0.0

    mod.reset_full("2026-03-01T00:00:00Z")
    idle = {"ok": True, "v": 5.0, "a": 0.019, "bank_idle": True}
    mod.tick(idle)
    clock.advance_s(3600)
    mod.tick(idle)
    assert mod.snapshot()["mah_used"] == 0.0

    zero = {"ok": True, "v": 5.0, "a": 0.0}
    mod.tick(zero)
    clock.advance_s(3600)
    mod.tick(zero)
    assert mod.snapshot()["mah_used"] == 0.0

    if state_path.exists():
        state_path.unlink()
    print("v50_energy tests OK")


if __name__ == "__main__":
    run()
