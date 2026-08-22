"""Host tests for persistent optional Events telemetry deduplication."""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ota_capability  # noqa: E402
import sheets_log  # noqa: E402


class EventLogger:
    def __init__(self, failures=0):
        self.events = []
        self.failures = failures

    def log_event(self, device, event, detail):
        self.events.append((device, event, detail))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("simulated POST failure")
        return {"ok": True}


def run():
    failures = []

    def check(name, condition):
        print("[%s] %s" % ("PASS" if condition else "FAIL", name))
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as tmp:
        original_remote_path = sheets_log.REMOTE_CONFIG_STATE_PATH
        original_capability_path = ota_capability.STATE_PATH
        module_names = (
            "remote_control",
            "version",
            "diag_log",
            "remote_boot_config",
            "ota_health",
        )
        originals = {name: sys.modules.get(name) for name in module_names}
        try:
            sheets_log.REMOTE_CONFIG_STATE_PATH = str(
                Path(tmp) / "remote_config_state.json"
            )
            applied = []
            fake_remote = types.ModuleType("remote_control")

            def apply_response(response, device_id=""):
                applied.append((response, device_id))
                return response.get("actions", []), response.get("detail", "")

            fake_remote.apply_from_log_response = apply_response
            sys.modules["remote_control"] = fake_remote

            remote_logger = EventLogger()
            remote = sheets_log.SheetsLogger.__new__(sheets_log.SheetsLogger)
            remote.log_event = remote_logger.log_event
            remote._emit_ota_lifecycle_from_detail = lambda *args, **kwargs: None
            base = {"detail": "target=1; setting=on", "actions": []}
            remote._apply_remote_from_response(base, "boat-test")
            remote._apply_remote_from_response(
                {"detail": " target=1 ;  setting=on ", "actions": []},
                "boat-test",
            )
            check("remote_config unchanged detail skips POST", len(remote_logger.events) == 1)
            check("remote settings still apply when event skips", len(applied) == 2)
            remote._apply_remote_from_response(
                {"detail": "target=2; setting=on", "actions": ["ota"]},
                "boat-test",
            )
            check("remote_config changed detail posts immediately", len(remote_logger.events) == 2)

            reloaded_logger = EventLogger()
            reloaded = sheets_log.SheetsLogger.__new__(sheets_log.SheetsLogger)
            reloaded.log_event = reloaded_logger.log_event
            reloaded._emit_ota_lifecycle_from_detail = lambda *args, **kwargs: None
            reloaded._apply_remote_from_response(
                {"detail": "target=2; setting=on", "actions": []}, "boat-test"
            )
            check("remote_config state persists across logger reload", not reloaded_logger.events)

            retry_logger = EventLogger(failures=1)
            retry = sheets_log.SheetsLogger.__new__(sheets_log.SheetsLogger)
            retry.log_event = retry_logger.log_event
            retry._emit_ota_lifecycle_from_detail = lambda *args, **kwargs: None
            changed = {"detail": "target=3; setting=off", "actions": []}
            retry._apply_remote_from_response(changed, "boat-test")
            retry._apply_remote_from_response(changed, "boat-test")
            check("failed remote_config POST retries", len(retry_logger.events) == 2)

            heap = [80]
            policy = {
                "min_fw_version": "1.2.3",
                "auto_ota_on_boot": True,
                "dock_mode": "winter",
                "ota_manifest_profile": "stable",
                "ota_self_sufficient": True,
                "pending_ota": False,
                "ota_degraded": False,
            }
            fake_version = types.ModuleType("version")
            fake_version.VERSION = "1.2.0"
            fake_diag = types.ModuleType("diag_log")
            fake_diag.mem_kb = lambda: heap[0]
            fake_diag.log = lambda message: None
            fake_rbc = types.ModuleType("remote_boot_config")
            fake_rbc.load = lambda: dict(policy)
            fake_rbc.effective_boot_ota_prefer_wifi = lambda: True
            fake_rbc.boot_ota_backoff_active = lambda: False
            fake_rbc.should_run_boot_ota = lambda: True
            fake_rbc.needs_firmware_upgrade = lambda: True
            fake_health = types.ModuleType("ota_health")
            fake_health.effective_manifest_profile = lambda: "stable"
            sys.modules["version"] = fake_version
            sys.modules["diag_log"] = fake_diag
            sys.modules["remote_boot_config"] = fake_rbc
            sys.modules["ota_health"] = fake_health

            ota_capability.STATE_PATH = str(Path(tmp) / "capability_state.json")
            cap_logger = EventLogger()
            check(
                "first capability report posts",
                ota_capability.report_after_log(
                    device="boat-test", prefer_wifi=True, logger=cap_logger
                ),
            )
            heap[0] = 2
            ota_capability.report_after_log(
                device="boat-test", prefer_wifi=False, logger=cap_logger
            )
            check(
                "heap and uplink do not change capability fingerprint",
                len(cap_logger.events) == 1,
            )
            policy["pending_ota"] = True
            ota_capability.report_after_log(
                device="boat-test", prefer_wifi=False, logger=cap_logger
            )
            check("capability policy change posts immediately", len(cap_logger.events) == 2)

            persisted_logger = EventLogger()
            ota_capability.report_after_log(
                device="boat-test", prefer_wifi=True, logger=persisted_logger
            )
            check("capability state persists across logger reload", not persisted_logger.events)

            policy["ota_degraded"] = True
            failed_logger = EventLogger(failures=1)
            ota_capability.report_after_log(logger=failed_logger)
            ota_capability.report_after_log(logger=failed_logger)
            check("failed capability POST retries", len(failed_logger.events) == 2)
        finally:
            sheets_log.REMOTE_CONFIG_STATE_PATH = original_remote_path
            ota_capability.STATE_PATH = original_capability_path
            for name, original in originals.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

    return failures


if __name__ == "__main__":
    failed = run()
    sys.exit(1 if failed else 0)
