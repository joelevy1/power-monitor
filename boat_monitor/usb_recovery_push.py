#!/usr/bin/env python3
"""
One-shot USB recovery for a stuck Pico (reboot loop on old fw).

Copies the current ram-fix file set from this repo onto the device via mpremote,
merges USB recovery boot policy into remote_boot_config.json (keeps min_fw, etc.),
then soft-resets so main.py runs.

From the repo root (Pico on USB; close Thonny serial first if mpremote cannot connect):

    python3 -m pip install -q mpremote && python3 boat_monitor/usb_recovery_push.py

Windows (boat Pico on COM7; close Thonny first):

    py -m pip install -q mpremote
    py boat_monitor\\usb_recovery_push.py --patch-only

Or:

    ./boat_monitor/run_usb_recovery.sh
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_PORT = "COM7"

ROOT = Path(__file__).resolve().parent

RECOVERY_FILES = (
    "mem_guard.py",
    "diag_log.py",
    "resilience.py",
    "remote_telemetry.py",
    "auto_log.py",
    "ble_policy.py",
    "modem_policy.py",
    "wifi_uplink.py",
    "ble_service.py",
    "ota_health.py",
    "ota_bundle.py",
    "ota_diag.py",
    "remote_boot_config.py",
    "ota_reboot.py",
    "ota_events_flush.py",
    "ota_lifecycle.py",
    "ota_telemetry.py",
    "ota_trace.py",
    "ota.py",
    "main.py",
    "cellular.py",
    "standby_monitor.py",
    "sheets_log.py",
    "remote_control.py",
    "ota_capability.py",
    "v50_energy.py",
    "version.py",
)


def _ensure_mpremote():
    try:
        subprocess.run(
            [sys.executable, "-m", "mpremote", "--help"],
            capture_output=True,
            check=True,
            timeout=30,
        )
        return [sys.executable, "-m", "mpremote"]
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "mpremote"])
        return [sys.executable, "-m", "mpremote"]


def _run(mpremote_base, args, description):
    cmd = mpremote_base + list(args)
    print("+", " ".join(cmd), "(%s)" % description)
    subprocess.check_call(cmd)


def _mp_args(port, *parts):
    """mpremote CLI: without port use `mpremote cp ...`; with port use `mpremote connect COM3 cp ...`.

    `mpremote connect cp ...` is wrong — mpremote treats `cp` as the device name.
    """
    if port:
        return ["connect", port] + list(parts)
    return list(parts)


def main(argv=None):
    p = argparse.ArgumentParser(description="USB-push ram-fix firmware and reset OTA state")
    p.add_argument(
        "--port",
        default=DEFAULT_PORT,
        help="Serial device (default: %(default)s). Use empty string to auto-detect.",
    )
    p.add_argument(
        "--patch-only",
        action="store_true",
        help="Only patch remote_boot_config.json and reset (no firmware file copy).",
    )
    p.add_argument(
        "--no-prefer-wifi",
        action="store_true",
        help="Do not set boot_ota_prefer_wifi in remote_boot_config.json",
    )
    p.add_argument(
        "--enable-boot-ota",
        action="store_true",
        help="OTA stress recovery: keep auto_ota_on_boot=true and pending_ota on device",
    )
    p.add_argument(
        "--ota-self-sufficient",
        action="store_true",
        help="Persist dock policy + manifest tier cap on flash (recommended week-away kit)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only",
    )
    args = p.parse_args(argv)

    missing = [f for f in RECOVERY_FILES if not (ROOT / f).is_file()]
    if missing and not args.patch_only:
        print("Missing local files:", ", ".join(missing), file=sys.stderr)
        return 1

    mp = _ensure_mpremote()
    port = (args.port or "").strip()

    patch_src = ROOT / "usb_recovery_patch.py"
    patch_text = patch_src.read_text(encoding="utf-8")
    prefer = "True" if not args.no_prefer_wifi else "False"
    patch_text = re.sub(r"PREFER_WIFI = \w+", "PREFER_WIFI = %s" % prefer, patch_text, count=1)
    auto_ota = "True" if args.enable_boot_ota or args.ota_self_sufficient else "False"
    patch_text = re.sub(
        r"AUTO_OTA_ON_BOOT = \w+", "AUTO_OTA_ON_BOOT = %s" % auto_ota, patch_text, count=1
    )
    if args.ota_self_sufficient or args.enable_boot_ota:
        patch_text = re.sub(r"OTA_SELF_SUFFICIENT = \w+", "OTA_SELF_SUFFICIENT = True", patch_text, count=1)
        patch_text = re.sub(r"DOCK_MODE = \"[^\"]*\"", "DOCK_MODE = \"away\"", patch_text, count=1)
        patch_text = re.sub(
            r"STANDBY_PREFER_WIFI = \w+",
            "STANDBY_PREFER_WIFI = False",
            patch_text,
            count=1,
        )
    else:
        patch_text = re.sub(r"OTA_SELF_SUFFICIENT = \w+", "OTA_SELF_SUFFICIENT = False", patch_text, count=1)
    patch_local = ROOT / ".usb_recovery_patch_run.py"
    patch_local.write_text(patch_text, encoding="utf-8")

    free_script = ROOT / "usb_recovery_free.py"
    if not free_script.is_file():
        print(
            "Missing %s — restore from git pull or: copy boat_monitor\\usb_recovery_free.py.bak boat_monitor\\usb_recovery_free.py"
            % free_script,
            file=sys.stderr,
        )
        return 1
    steps = []
    if not args.patch_only:
        steps.append(
            (_mp_args(port, "run", str(free_script)), "free flash (.bak/.new/bundles/logs)"),
        )
        for name in RECOVERY_FILES:
            steps.append(
                (
                    _mp_args(port, "cp", str(ROOT / name), ":%s" % name),
                    "copy %s" % name,
                )
            )
    steps.append(
        (
            _mp_args(port, "cp", str(patch_local), ":usb_recovery_patch.py"),
            "copy patch script",
        ),
    )
    steps.append(
        (_mp_args(port, "run", str(patch_local)), "patch remote_boot_config")
    )
    steps.append(
        (
            _mp_args(port, "exec", "import machine; machine.soft_reset()"),
            "soft reset",
        ),
    )

    if args.dry_run:
        for cmd, desc in steps:
            print("[dry-run]", " ".join(mp + cmd), "-", desc)
        return 0

    try:
        for cmd, desc in steps:
            _run(mp, cmd, desc)
    except subprocess.CalledProcessError:
        print(
            "\nmpremote failed. Close Thonny and any serial monitor, unplug/replug USB, then retry.\n"
            "On Windows, list ports:  python -m mpremote connect list\n"
            "Then pass the COM port:  python boat_monitor\\usb_recovery_push.py --port COM7\n"
            "If you see 'No space left on device', pull latest script (runs cleanup first) or run:\n"
            "  python -m mpremote cp boat_monitor/usb_recovery_free.py :usb_recovery_free.py\n"
            "  python -m mpremote run usb_recovery_free.py",
            file=sys.stderr,
        )
        return 1
    finally:
        try:
            patch_local.unlink(missing_ok=True)
        except Exception:
            pass

    print(
        "\nDone. Pico should reboot into main.py with fw from this folder "
        "(see version.py). On home Wi-Fi it should run boot OTA to GitHub min_fw."
    )
    if args.ota_self_sufficient or args.enable_boot_ota:
        version_text = (ROOT / "version.py").read_text(encoding="utf-8")
        match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', version_text)
        expected_fw = match.group(1) if match else "<version.py>"
        print(
            "\nNext: unplug USB, power-cycle, run:\n"
            "  python3 boat_monitor/usb_recovery_verify.py --expect-fw %s\n"
            "Sheet: min_fw_version=%s, interval_engine_off_s=3600, clear force_ota/cmd_ota.\n"
            "Then start week-away OTA (optional):\n"
            "  ./boat_monitor/run_week_away_dock_ota.sh"
            % (expected_fw, expected_fw)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
