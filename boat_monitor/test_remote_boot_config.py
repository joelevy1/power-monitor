"""Host tests for exact boot OTA gate diagnostics."""

import os
import sys
import tempfile
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
        finally:
            remote_boot_config.PATH = original_path
            os.chdir(original_cwd)
    print("remote_boot_config tests OK")


if __name__ == "__main__":
    main()
