"""Host tests for exact boot OTA gate diagnostics."""

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import remote_boot_config  # noqa: E402


def _state(**values):
    remote_boot_config.save(values)


def _check(reason, should_run=False):
    actual = remote_boot_config.boot_ota_block_reason()
    assert actual == reason, (actual, reason)
    # Avoid invoking a skip-boot counter twice; all other gates must be exactly
    # the inverse used by should_run_boot_ota().
    if reason != "backoff_active":
        assert remote_boot_config.should_run_boot_ota() is should_run


def main():
    original_cwd = os.getcwd()
    original_path = remote_boot_config.PATH
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        remote_boot_config.PATH = str(Path(tmp) / "remote_boot_config.json")
        try:
            _state()
            assert (
                remote_boot_config.effective_cellular_control_sync_every_logs()
                == 3
            )

            _state(
                min_fw_version="999.0",
                auto_ota_on_boot=True,
                boot_ota_skip_remaining=2,
            )
            _check("backoff_active")

            _state(min_fw_version="999.0", auto_ota_on_boot=True, ota_degraded=True)
            _check("ota_degraded")

            _state(min_fw_version="0", auto_ota_on_boot=True)
            _check("current_meets_min_fw")

            _state(min_fw_version="999.0", auto_ota_on_boot=False)
            _check("auto_ota_disabled")

            _state(min_fw_version="999.0", auto_ota_on_boot=False, pending_ota=True)
            _check(None, should_run=True)
            remote_boot_config.set_pending_ota(True)
            state = remote_boot_config.load()
            assert state["pending_ota"] is True
            assert state["auto_ota_on_boot"] is False

            _state(
                min_fw_version="0",
                auto_ota_on_boot=False,
                pending_ota=True,
                cmd_ota_force=True,
                ota_degraded=True,
                boot_ota_skip_remaining=3,
            )
            _check(None, should_run=True)
            state = remote_boot_config.load()
            assert state.get("boot_ota_skip_remaining") == 3
            assert state.get("pending_ota") is True

            _state(
                min_fw_version="0",
                auto_ota_on_boot=True,
                pending_ota=True,
                cmd_ota_force=True,
                ota_degraded=True,
                boot_ota_fail_count=3,
            )
            remote_boot_config.apply_settings(
                {"clear_ota_degraded": "1", "clear_pending_ota": "1"}
            )
            state = remote_boot_config.load()
            assert "pending_ota" not in state
            assert "cmd_ota_force" not in state
            assert "ota_degraded" not in state
            assert state.get("boot_ota_fail_count") == 0
            _check("current_meets_min_fw")

            _state(
                min_fw_version="999.0",
                auto_ota_on_boot=True,
                pending_ota=True,
                cmd_ota_force=True,
                boot_ota_fail_count=1,
            )
            state = remote_boot_config.pause_after_ota_memory_failure(
                "[Errno 12] ENOMEM"
            )
            assert "pending_ota" not in state
            assert "cmd_ota_force" not in state
            assert state["auto_ota_on_boot"] is False
            assert state["ota_degraded"] is True
            assert state["boot_ota_fail_count"] >= 2
            assert state["last_boot_ota_outcome"] == "memory_pause"
            _check("ota_degraded")

            _state(
                min_fw_version="999.0",
                auto_ota_on_boot=True,
                pending_ota=True,
                cmd_ota_force=True,
                boot_ota_fail_count=1,
            )
            state = remote_boot_config.pause_after_terminal_ota_failure(
                "manifest_tier_max_2_files_cellular"
            )
            assert "pending_ota" not in state
            assert "cmd_ota_force" not in state
            assert state["auto_ota_on_boot"] is False
            assert state["last_boot_ota_outcome"] == "terminal_pause"

            previous_ble_policy = sys.modules.get("ble_policy")
            sys.modules["ble_policy"] = types.SimpleNamespace(
                ble_inputs_on=lambda: True
            )
            try:
                _state(
                    min_fw_version="999.0",
                    auto_ota_on_boot=False,
                    pending_ota=True,
                    cmd_ota_force=True,
                    boot_ota_fail_count=1,
                )
                _check(None, should_run=True)

                _state(
                    min_fw_version="999.0",
                    auto_ota_on_boot=True,
                    pending_ota=True,
                    boot_ota_fail_count=1,
                )
                _check("key_on_recovery")
                state = remote_boot_config.load()
                assert "pending_ota" not in state
                assert "cmd_ota_force" not in state
                assert state["auto_ota_on_boot"] is False
                assert state["last_boot_ota_outcome"] == "key_on_recovery"
            finally:
                if previous_ble_policy is None:
                    sys.modules.pop("ble_policy", None)
                else:
                    sys.modules["ble_policy"] = previous_ble_policy
        finally:
            remote_boot_config.PATH = original_path
            os.chdir(original_cwd)
    print("remote_boot_config tests OK")


if __name__ == "__main__":
    main()
