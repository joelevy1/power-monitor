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
        cap = [r for r in ev if len(r) > 2 and r[2] == "ota_capability"]
        last_cap = str(cap[-1][3])[:200] if cap else ""
        ok_fw = fw != "?" and _ge(fw, args.expect_fw)
        ok_trap = not trap
        print(
            "%s fw=%s trap=%s capability=%s"
            % (datetime.now(timezone.utc).strftime("%H:%M:%SZ"), fw, trap, "yes" if last_cap else "no")
        )
        if last_cap:
            print("  ", last_cap)
        if ok_fw and ok_trap and last_cap and "will_boot_ota=" in last_cap:
            print("\nOK: USB recovery verified fw=%s" % fw)
            return 0
        time.sleep(max(15, args.poll))
    print("\nFAIL: verification timeout — check Power_Log, Events ota_capability, USB push", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
