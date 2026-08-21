"""Host tests for ota_health manifest policy."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from ota_health import check_manifest_policy  # noqa: E402


def test_stress_one_file():
    ok, reason = check_manifest_policy({"files": [{}], "manifest_kind": "stress"}, used_wifi=False)
    assert ok and not reason


def test_bootstrap_two_cellular():
    ok, reason = check_manifest_policy(
        {"files": [{}, {}], "manifest_kind": "bootstrap"}, used_wifi=False
    )
    assert ok


def test_dock_fix_cellular_blocked():
    ok, reason = check_manifest_policy(
        {"files": [{}] * 5, "manifest_kind": "dock-fix"}, used_wifi=False
    )
    assert not ok and "wifi" in reason


def test_dock_fix_wifi_ok():
    ok, reason = check_manifest_policy(
        {"files": [{}] * 5, "manifest_kind": "dock-fix"}, used_wifi=True
    )
    assert ok


def test_wifi_feature_requires_wifi():
    manifest = {"files": [{}] * 6, "manifest_kind": "wifi-feature"}
    assert not check_manifest_policy(manifest, used_wifi=False)[0]
    assert check_manifest_policy(manifest, used_wifi=True)[0]


def main():
    test_stress_one_file()
    test_bootstrap_two_cellular()
    test_dock_fix_cellular_blocked()
    test_dock_fix_wifi_ok()
    test_wifi_feature_requires_wifi()
    print("ota_health manifest policy tests OK")


if __name__ == "__main__":
    main()
