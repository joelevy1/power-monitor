#!/usr/bin/env python3
"""Write slim ota_manifest.json for remote recovery or feature-pack OTA."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FULL = ROOT / "ota_manifest.full.json"
OUT = ROOT / "ota_manifest.json"
RAW = "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/"

RECOVERY_PATHS = (
    "version.py",
    "main.py",
    "ota.py",
    "ota_reboot.py",
    "remote_boot_config.py",
    "remote_control.py",
    "ota_events_flush.py",
    "ota_lifecycle.py",
    "ota_telemetry.py",
)

FEATURE_PACK_PATHS = RECOVERY_PATHS + (
    "ota_trace.py",
    "status_led.py",
    "ble_service.py",
    "sheets_log.py",
    "cellular.py",
    "diag_log.py",
    "ota_bundle.py",
)

RAM_FIX_PATHS = (
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
    "version.py",
)

VERSION_ONLY_PATHS = ("version.py",)

BOOTSTRAP_RULES_PATHS = (
    "version.py",
    "remote_boot_config.py",
)

DOCK_FIX_PATHS = (
    "version.py",
    "main.py",
    "standby_monitor.py",
    "ota_health.py",
    "remote_boot_config.py",
)


def _version():
    text = (ROOT / "version.py").read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("version.py missing VERSION")
    return m.group(1).strip()


def _write_manifest(paths, notes, include_bundle=True):
    full = json.loads(FULL.read_text(encoding="utf-8"))
    by_path = {e["path"]: e for e in full.get("files") or [] if e.get("path")}
    files = []
    for path in paths:
        if path not in by_path:
            if (ROOT / path).is_file():
                files.append({"path": path, "url": RAW + path})
            else:
                print("missing:", path, file=sys.stderr)
                return 1
        else:
            files.append(dict(by_path[path]))
    data = {
        "version": _version(),
        "notes": notes,
        "files": files,
    }
    if not include_bundle:
        data.pop("bundle", None)
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("OK: manifest %s with %d files" % (data["version"], len(files)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--recovery", action="store_true", help="9-file reboot-loop recovery")
    p.add_argument("--feature-pack", action="store_true", help="16-file pack: trace, LEDs, BLE (smaller than full)")
    p.add_argument(
        "--ram-fix",
        action="store_true",
        help="7-file per-file OTA (streaming cellular + bundle extract); no .bmota",
    )
    p.add_argument(
        "--version-only",
        action="store_true",
        help="1-file manifest (version.py only) for patch stress on cellular",
    )
    p.add_argument(
        "--bootstrap-rules",
        action="store_true",
        help="2-file manifest: version.py + remote_boot_config.py (once per stress campaign)",
    )
    p.add_argument(
        "--dock-fix",
        action="store_true",
        help="5-file dock OTA fix: version, main, standby, ota_health, remote_boot_config",
    )
    args = p.parse_args(argv)
    if args.dock_fix:
        return _write_manifest(
            DOCK_FIX_PATHS,
            "Dock OTA fix: Wi-Fi log / cellular boot OTA split + ENOMEM fallback.",
            include_bundle=False,
        )
    if args.bootstrap_rules:
        return _write_manifest(
            BOOTSTRAP_RULES_PATHS,
            "Bootstrap OTA: version.py + remote_boot_config.py (sheet backoff self-heal).",
            include_bundle=False,
        )
    if args.version_only:
        return _write_manifest(
            VERSION_ONLY_PATHS,
            "Patch OTA: version.py only (cellular heap safe).",
            include_bundle=False,
        )
    if args.ram_fix:
        return _write_manifest(
            RAM_FIX_PATHS,
            "RAM-safe OTA: stream bundle download/extract + reboot cooldown (per-file, no bundle).",
            include_bundle=False,
        )
    if args.feature_pack:
        return _write_manifest(
            FEATURE_PACK_PATHS,
            "Feature-pack OTA: trace, LEDs, loop fix (~175KB bundle, streamed).",
        )
    if args.recovery:
        return _write_manifest(
            RECOVERY_PATHS,
            "Slim remote recovery OTA (reboot-loop fix; stream bundle extract).",
        )
    print("Specify --recovery, --feature-pack, or --ram-fix", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
