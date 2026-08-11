"""Unit tests for ota_stress_rules.py enforcement helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ota_stress_rules import (  # noqa: E402
    count_reboot_queued,
    detect_reboot_trap,
    master_manifest_policy_errors,
    saw_boot_start,
)


def _ev(phase, detail=""):
    return ["Jan 1, 2026 12:00 PM", "boat-p2", "ota_lifecycle", "phase=%s;%s" % (phase, detail)]


def test_count_reboot_queued():
    events = [_ev("reboot_queued"), _ev("aware"), _ev("reboot_queued"), _ev("reboot_queued")]
    assert count_reboot_queued(events) == 3
    tail = [_ev("aware"), _ev("reboot_queued")]
    assert count_reboot_queued(tail, window=2) == 1


def test_saw_boot_start():
    events = [_ev("reboot_queued"), ["Jan 1, 2026 12:01 PM", "boat-p2", "boot_ota", "phase=boot_start"]]
    assert saw_boot_start(events)
    assert not saw_boot_start([_ev("reboot_queued")] * 5)


def test_detect_reboot_trap():
    events = [_ev("reboot_queued")] * 4
    trap = detect_reboot_trap(events, "1.1.107", "1.1.110")
    assert trap and "reboot_trap" in trap
    assert detect_reboot_trap(events, "1.1.110", "1.1.110") is None
    events2 = events + [["Jan 1, 2026 12:01 PM", "boat-p2", "boot_ota", "phase=boot_start"]]
    assert detect_reboot_trap(events2, "1.1.107", "1.1.110") is None


def test_master_policy_stress():
    data = {"files": [{"path": "version.py"}], "manifest_kind": "stress"}
    assert master_manifest_policy_errors(data) == []


def test_master_policy_bootstrap():
    data = {
        "manifest_kind": "bootstrap",
        "files": [{"path": "version.py"}, {"path": "remote_boot_config.py"}],
    }
    assert master_manifest_policy_errors(data) == []


def test_master_policy_blocks_recovery():
    data = {
        "manifest_kind": "dock-fix",
        "files": [{"path": "version.py"}, {"path": "main.py"}, {"path": "ota.py"}],
    }
    errs = master_manifest_policy_errors(data)
    assert errs and "3 files" in errs[0]


def test_master_policy_bootstrap_wrong_kind():
    data = {"files": [{"path": "version.py"}, {"path": "remote_boot_config.py"}]}
    errs = master_manifest_policy_errors(data)
    assert errs and "manifest_kind" in errs[0]


def test_assert_version_only_manifest():
    from ota_stress_rules import assert_version_only_manifest

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "ota_manifest.json"
        path.write_text(
            json.dumps({"version": "1.0.0", "manifest_kind": "stress", "files": [{"path": "version.py"}]}),
            encoding="utf-8",
        )
        assert_version_only_manifest(path)


def main():
    test_count_reboot_queued()
    test_saw_boot_start()
    test_detect_reboot_trap()
    test_master_policy_stress()
    test_master_policy_bootstrap()
    test_master_policy_blocks_recovery()
    test_master_policy_bootstrap_wrong_kind()
    test_assert_version_only_manifest()
    print("ota_stress_rules tests OK")


if __name__ == "__main__":
    main()
