"""PC-side tests for remote_control.py (no Pico hardware)."""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("remote_control", ROOT / "remote_control.py")
remote_control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remote_control)

spec2 = importlib.util.spec_from_file_location("auto_log", ROOT / "auto_log.py")
auto_log = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(auto_log)

import remote_boot_config  # noqa: E402


def test_interval_override():
    auto_log.set_interval_overrides(engine_off_s=999)
    assert auto_log.interval_for_mode("docked_off") == 999
    auto_log.set_interval_overrides(engine_on_s=120)
    assert auto_log.interval_for_mode("key_on") == 120


def test_one_shot_ota():
    actions, detail = remote_control.apply_commands_payload(
        {"settings": {}, "one_shots": ["ota"]},
        device_id="boat-p2",
    )
    assert actions == ["ota"]
    assert "one_shot=ota" in detail


def test_one_shot_ota_force_and_unknown():
    remote_boot_config.save({})
    actions, detail = remote_control.apply_commands_payload(
        {"settings": {}, "one_shots": ["ota_force", "future-command"]},
        device_id="boat-p2",
    )
    assert actions == ["ota"]
    assert "one_shot=ota_force" in detail
    assert "one_shot_unknown=future-command" in detail
    state = remote_boot_config.load()
    assert state.get("pending_ota") is True
    assert state.get("cmd_ota_force") is True

    remote_boot_config.save({})
    actions, detail = remote_control.apply_commands_payload(
        {"settings": {}, "one_shots": ["force"]},
        device_id="boat-p2",
    )
    assert actions == ["ota"]
    assert remote_boot_config.load().get("cmd_ota_force") is True


def test_min_fw_version():
    actions, detail = remote_control.apply_commands_payload(
        {"settings": {"min_fw_version": "9.9.9"}, "one_shots": []},
        device_id="boat-p2",
    )
    assert actions == ["ota"]
    assert "min_fw_version=9.9.9" in detail


def test_transport_change_defers_ota_until_later_payload():
    remote_boot_config.save({"boot_ota_prefer_wifi": False})
    payload = {
        "settings": {
            "boot_ota_prefer_wifi": "1",
            "auto_ota_on_boot": "1",
            "min_fw_version": "9.9.9",
        },
        "one_shots": ["ota_force"],
    }
    actions, detail = remote_control.apply_commands_payload(
        payload, device_id="boat-p2"
    )
    assert actions == []
    assert "ota_deferred_transport=1" in detail
    state = remote_boot_config.load()
    assert state["boot_ota_prefer_wifi"] is True
    assert "pending_ota" not in state
    assert "cmd_ota_force" not in state
    assert "auto_ota_on_boot" not in state
    assert "min_fw_version" not in state

    actions, detail = remote_control.apply_commands_payload(
        payload, device_id="boat-p2"
    )
    assert actions == ["ota"]
    assert "ota_deferred_transport=1" not in detail
    state = remote_boot_config.load()
    assert state["pending_ota"] is True
    assert state["cmd_ota_force"] is True
    assert state["auto_ota_on_boot"] is True
    assert state["min_fw_version"] == "9.9.9"


def main():
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            test_interval_override()
            test_one_shot_ota()
            test_one_shot_ota_force_and_unknown()
            test_min_fw_version()
            test_transport_change_defers_ota_until_later_payload()
        finally:
            os.chdir(original_cwd)
    print("remote_control tests OK")


if __name__ == "__main__":
    main()
