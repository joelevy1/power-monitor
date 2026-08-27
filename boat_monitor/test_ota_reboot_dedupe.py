"""Host regression for deduplicating blocked OTA telemetry call sites."""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ota_reboot  # noqa: E402


def main():
    module_names = (
        "remote_boot_config",
        "ota_lifecycle",
        "ota_telemetry",
        "diag_log",
    )
    originals = {name: sys.modules.get(name) for name in module_names}
    original_path = ota_reboot.SKIP_TELEMETRY_STATE_PATH
    lifecycle = []
    telemetry = []
    try:
        state = {
            "min_fw_version": "1.1.164",
            "last_boot_ota_outcome": "memory_pause",
        }
        remote = types.ModuleType("remote_boot_config")
        remote.load = lambda: dict(state)
        life = types.ModuleType("ota_lifecycle")
        life.phase = lambda *args, **kwargs: lifecycle.append((args, kwargs))
        telem = types.ModuleType("ota_telemetry")
        telem.report_boot_ota = lambda *args, **kwargs: telemetry.append(
            (args, kwargs)
        )
        diag = types.ModuleType("diag_log")
        diag.log = lambda *_args, **_kwargs: None
        sys.modules["remote_boot_config"] = remote
        sys.modules["ota_lifecycle"] = life
        sys.modules["ota_telemetry"] = telem
        sys.modules["diag_log"] = diag

        with tempfile.TemporaryDirectory() as tmp:
            ota_reboot.SKIP_TELEMETRY_STATE_PATH = str(
                Path(tmp) / "ota_skip_event_state.json"
            )
            for source in (
                "sheets_log.close_data",
                "log_power_and_gps",
                "ble_auto_log",
            ):
                ota_reboot._skip_boot_ota_telemetry(
                    "ota_reboot_blocked", source=source
                )
            assert len(lifecycle) == 1
            assert len(telemetry) == 1

            ota_reboot._skip_boot_ota_telemetry(
                "auto_ota_disabled", source="next_log"
            )
            assert len(lifecycle) == 2
            assert len(telemetry) == 2
    finally:
        ota_reboot.SKIP_TELEMETRY_STATE_PATH = original_path
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    print("OTA skipped telemetry dedupe tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
