#!/usr/bin/env python3
"""Regression checks for the post-USB telemetry gate."""

from __future__ import annotations

from usb_recovery_verify import recovery_gate


def main():
    detail = (
        "fw=1.1.116; heap_kb=60; min_fw=1.1.116; auto_ota_on_boot=0; "
        "boot_ota_prefer_wifi=0; dock_mode=away; ota_manifest_profile=micro; "
        "ota_self_sufficient=1; pending_ota=0; ota_degraded=0; "
        "boot_ota_backoff=0; will_boot_ota=0; needs_upgrade=0; "
        "manifest_profile=micro; uplink=cellular"
    )
    assert len(detail) > 200
    assert "will_boot_ota=" not in detail[:200]
    events = [["Aug 20, 2026 9:30 PM", "boat-p2", "ota_capability", detail]]

    ok, full_detail = recovery_gate("1.1.116", "1.1.116", False, events)
    assert ok
    assert full_detail == detail

    assert not recovery_gate("1.1.115", "1.1.116", False, events)[0]
    assert not recovery_gate("1.1.116", "1.1.116", True, events)[0]
    assert not recovery_gate("1.1.116", "1.1.116", False, [])[0]
    print("USB recovery verifier tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
