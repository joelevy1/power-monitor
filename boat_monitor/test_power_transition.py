"""Host tests for portable bank-to-house power transition policy."""

import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class FakeTime:
    def __init__(self):
        self.ms = 0

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, current, previous):
        return current - previous

    def sleep(self, _seconds):
        pass


def _status(v50_v, house_v):
    return {"v50": {"v": v50_v}, "house": {"v": house_v}}


def test_transition_and_cooldown():
    clock = FakeTime()
    resets = []
    old_time = sys.modules.get("time")
    old_machine = sys.modules.get("machine")
    old_diag = sys.modules.get("diag_log")
    sys.modules["time"] = clock
    sys.modules["machine"] = types.SimpleNamespace(reset=lambda: resets.append(clock.ms))
    sys.modules["diag_log"] = types.SimpleNamespace(log=lambda _message: None)
    try:
        import power_transition

        power_transition = importlib.reload(power_transition)
        assert not power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 0.0), "docked_off"
        )
        clock.ms = 1000
        assert power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 12.6), "docked_off"
        )
        assert resets == [1000]

        clock.ms = 2000
        assert not power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 0.0), "docked_off"
        )
        clock.ms = 3000
        assert not power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 12.6), "docked_off"
        )

        clock.ms = power_transition.MIN_GAP_MS + 2000
        assert not power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 0.0), "docked_off"
        )
        clock.ms += 1000
        assert power_transition.maybe_reboot_on_power_transition(
            _status(5.0, 12.6), "docked_off"
        )
        assert len(resets) == 2
    finally:
        for name, old in (
            ("time", old_time),
            ("machine", old_machine),
            ("diag_log", old_diag),
        ):
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_non_dock_mode_never_reboots():
    import power_transition

    power_transition._last_sig = None
    assert not power_transition.maybe_reboot_on_power_transition(
        _status(5.0, 12.8), "key_on"
    )


def main():
    test_transition_and_cooldown()
    test_non_dock_mode_never_reboots()
    print("power transition tests OK")


if __name__ == "__main__":
    main()
