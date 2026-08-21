#!/usr/bin/env python3
"""
Post-USB verification gate — do not leave the dock until green.

  python3 usb_recovery_verify.py --expect-fw 1.1.111
  python3 usb_recovery_verify.py --expect-fw 1.1.111 --timeout 1800
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone


def _parse_ver(text):
    parts = []
    for p in str(text or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _ge(a, b):
    return _parse_ver(a) >= _parse_ver(b)


def recovery_gate(fw, expect_fw, trap, events):
    capabilities = [r for r in events if len(r) > 3 and r[2] == "ota_capability"]
    full_capability = str(capabilities[-1][3]) if capabilities else ""
    ok = (
        fw != "?"
        and _ge(fw, expect_fw)
        and not trap
        and "will_boot_ota=" in full_capability
    )
    return ok, full_capability


def main(argv=None):
    p = argparse.ArgumentParser(description="Verify USB recovery succeeded on the sheet")
    p.add_argument("--expect-fw", required=True, metavar="X.Y.Z")
    p.add_argument("--timeout", type=int, default=1800, help="seconds to wait (default 30 min)")
    p.add_argument("--poll", type=int, default=45, help="seconds between polls")
    args = p.parse_args(argv)

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from ota_stress_harness import _current_device_fw, _fetch_events, _parse_ver_tuple
    from ota_stress_rules import count_reboot_queued, saw_boot_start

    start = time.time()
    print("USB verify: expect fw>=%s (timeout %ds)" % (args.expect_fw, args.timeout))
    while time.time() - start < args.timeout:
        fw = _current_device_fw() or "?"
        ev = _fetch_events()
        trap = count_reboot_queued(ev) >= 3 and not saw_boot_start(ev)
        recovery_ok, full_capability = recovery_gate(fw, args.expect_fw, trap, ev)
        capability_preview = full_capability[:200]
        print(
            "%s fw=%s trap=%s capability=%s"
            % (
                datetime.now(timezone.utc).strftime("%H:%M:%SZ"),
                fw,
                trap,
                "yes" if full_capability else "no",
            )
        )
        if capability_preview:
            print("  ", capability_preview)
        if recovery_ok:
            print("\nOK: USB recovery verified fw=%s" % fw)
            return 0
        time.sleep(max(15, args.poll))
    print("\nFAIL: verification timeout — check Power_Log, Events ota_capability, USB push", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
