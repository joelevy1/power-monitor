"""PC-side tests for remote_control.py (no Pico hardware)."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("remote_control", ROOT / "remote_control.py")
remote_control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote_control)

spec2 = importlib.util.spec_from_file_location("auto_log", ROOT / "auto_log.py")
auto_log = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(auto_log)


def test_interval_override():
    auto_log.set_interval_overrides(engine_off_s=999)
    assert auto_log.interval_for_mode("docked_off") == 999
    auto_log.set_interval_overrides(engine_on_s=120)
    assert auto_log.interval_for_mode("key_on") == 120


def test_one_shot_ota():
    actions = remote_control.apply_commands_payload(
        {"settings": {}, "one_shots": ["ota"]},
        device_id="boat-p2",
    )
    assert actions == ["ota"]


def test_min_fw_version():
    actions = remote_control.apply_commands_payload(
        {"settings": {"min_fw_version": "9.9.9"}, "one_shots": []},
        device_id="boat-p2",
    )
    assert actions == ["ota"]


def main():
    test_interval_override()
    test_one_shot_ota()
    test_min_fw_version()
    print("remote_control tests OK")


if __name__ == "__main__":
    main()
