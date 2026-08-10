#!/usr/bin/env python3
"""Write slim ota_manifest.json for remote recovery (small bundle, loop-fix files)."""

from __future__ import annotations

import json
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


def main():
    full = json.loads(FULL.read_text(encoding="utf-8"))
    by_path = {e["path"]: e for e in full.get("files") or [] if e.get("path")}
    files = []
    for path in RECOVERY_PATHS:
        if path not in by_path:
            print("missing in full manifest:", path, file=sys.stderr)
            return 1
        files.append(dict(by_path[path]))
    ver = (ROOT / "version.py").read_text(encoding="utf-8")
    import re

    m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', ver)
    version = m.group(1) if m else full.get("version")
    data = {
        "version": version,
        "notes": "Slim remote recovery OTA (reboot-loop fix; stream bundle extract).",
        "files": files,
    }
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("OK: recovery manifest %s with %d files" % (version, len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
