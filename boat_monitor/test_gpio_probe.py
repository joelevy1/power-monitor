"""Unit test gpio_probe note suffix (PC, no machine)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gpio_probe  # noqa: E402


def run():
    status = {"mode": "docked_off", "inputs": {"switch": False, "key": False}}
    note = gpio_probe.enrich_note("auto_log", status)
    assert "sw=0" in note and "key=0" in note
    assert "gpio" in note
    status2 = {"mode": "key_on", "inputs": {"switch": True, "key": True}}
    note2 = gpio_probe.enrich_note("auto_log", status2)
    assert "sw=1" in note2 and "key=1" in note2
    print("OK gpio_probe enrich_note")


if __name__ == "__main__":
    run()
