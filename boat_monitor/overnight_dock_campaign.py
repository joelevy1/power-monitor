#!/usr/bin/env python3
"""Wait for a clean dock/Wi-Fi baseline, then run guarded OTA regression."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from ota_stress_harness import (  # noqa: E402
    _fetch_power_tail,
    _parse_ver_tuple,
    _read_local_version,
)


def wait_for_baseline(version, timeout_s, poll_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        _count, rows = _fetch_power_tail()
        last = rows[-1] if rows else {}
        fw = str(last.get("fw") or "")
        mode = str(last.get("mode") or "")
        uplink = str(last.get("uplink") or "")
        good = (
            _parse_ver_tuple(fw) >= _parse_ver_tuple(version)
            and mode == "docked_off"
            and bool(uplink)
            and uplink != "cellular"
        )
        print(
            "BASELINE fw=%s need=%s mode=%s uplink=%s good=%s"
            % (fw or "?", version, mode or "?", uplink or "?", good),
            flush=True,
        )
        if good:
            return True
        time.sleep(poll_s)
    return False


def restore_production():
    version = _read_local_version()
    command = [
        sys.executable,
        str(ROOT / "sheets_config_upsert.py"),
        "interval_engine_on_s",
        "600",
        "overnight campaign complete: production key-on cadence",
        "interval_engine_off_s",
        "3600",
        "overnight campaign complete: production dock cadence",
        "min_fw_version",
        version,
        "overnight campaign final firmware",
        "auto_ota_on_boot",
        "0",
        "overnight campaign complete",
        "cmd_ota",
        "",
        "overnight campaign complete",
        "cmd_ota_force",
        "",
        "overnight campaign complete",
        "clear_pending_ota",
        "",
        "overnight campaign complete",
        "clear_ota_degraded",
        "",
        "overnight campaign complete",
    ]
    return subprocess.run(command, cwd=str(REPO), check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--baseline-timeout", type=int, default=21600)
    args = parser.parse_args(argv)

    baseline = _read_local_version()
    print("Waiting for clean dock Wi-Fi baseline at", baseline, flush=True)
    if not wait_for_baseline(baseline, args.baseline_timeout):
        print("FAIL: no clean dock Wi-Fi baseline; OTA rounds not started", flush=True)
        restore_production()
        return 2

    command = [
        sys.executable,
        "-u",
        str(ROOT / "ota_stress_harness.py"),
        "--rounds",
        str(args.rounds),
        "--profile",
        "dock-stress",
        "--no-bootstrap",
        "--round-timeout",
        "2400",
        "--allow-master-push",
    ]
    try:
        result = subprocess.run(command, cwd=str(REPO), check=False)
        return result.returncode
    finally:
        restore_production()


if __name__ == "__main__":
    raise SystemExit(main())
