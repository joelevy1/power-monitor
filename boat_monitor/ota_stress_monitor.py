#!/usr/bin/env python3
"""
Poll sheet + harness log on a fixed interval (default 5 min, 6 updates).

  python3 boat_monitor/ota_stress_monitor.py
  python3 boat_monitor/ota_stress_monitor.py --interval 300 --count 6 --log boat_monitor/ota_stress_monitor.log
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _poll_once(update_n: int, count: int, harness_log: Path | None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = ["", "=" * 60, "MONITOR update %d/%d @ %s" % (update_n, count, now), "=" * 60]

    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "sheet_tail_report.py")],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        tail = (r.stdout or "") + (r.stderr or "")
        for line in tail.splitlines()[:22]:
            lines.append(line)
    except Exception as exc:
        lines.append("sheet_tail_report error: %s" % exc)

    if harness_log and harness_log.is_file():
        try:
            text = harness_log.read_text(encoding="utf-8", errors="replace")
            htail = text.splitlines()[-12:]
            lines.append("--- harness log tail ---")
            lines.extend(htail)
        except Exception as exc:
            lines.append("harness log read error: %s" % exc)

    try:
        r2 = subprocess.run(
            ["pgrep", "-af", "ota_stress_harness"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines.append("--- harness process ---")
        lines.append((r2.stdout or "not running").strip())
    except Exception:
        pass

    block = "\n".join(lines)
    print(block, flush=True)
    return block


def main():
    p = argparse.ArgumentParser(description="Periodic OTA stress monitor")
    p.add_argument("--interval", type=int, default=300, help="seconds between polls (default 300)")
    p.add_argument("--count", type=int, default=6, help="number of updates (default 6)")
    p.add_argument(
        "--log",
        default=str(ROOT / "ota_stress_monitor.log"),
        help="append monitor output to this file",
    )
    p.add_argument(
        "--harness-log",
        default=str(ROOT / "ota_stress_run2.log"),
        help="harness log to tail",
    )
    args = p.parse_args()
    log_path = Path(args.log)
    harness_log = Path(args.harness_log)

    for i in range(1, args.count + 1):
        block = _poll_once(i, args.count, harness_log)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(block + "\n")
        if i < args.count:
            time.sleep(args.interval)

    print("Monitor done (%d updates)." % args.count)


if __name__ == "__main__":
    main()
