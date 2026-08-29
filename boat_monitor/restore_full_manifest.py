#!/usr/bin/env python3
"""Restore full ota_manifest.json from ota_manifest.full.json + current version.py."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FULL = ROOT / "ota_manifest.full.json"
OUT = ROOT / "ota_manifest.json"
RAW = "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/"

# Added after ota_manifest.full.json snapshot — ensure present in full releases.
EXTRA_PATHS = (
    "ota_trace.py",
    "status_led.py",
    "sensor_calibration.py",
)


def _version():
    text = (ROOT / "version.py").read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("version.py missing VERSION")
    return m.group(1).strip()


def _entry(path):
    return {
        "path": path,
        "url": RAW + path,
    }


def main():
    if not FULL.is_file():
        print("missing ota_manifest.full.json", file=sys.stderr)
        return 1
    data = json.loads(FULL.read_text(encoding="utf-8"))
    files = list(data.get("files") or [])
    paths = {e.get("path") for e in files}
    for path in EXTRA_PATHS:
        if path not in paths and (ROOT / path).is_file():
            files.append(_entry(path))
            paths.add(path)
    data["files"] = files
    data["version"] = _version()
    data["notes"] = "Full OTA + ota_trace timing on Events; boot_ota elapsed_s/http_sessions."
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("OK: full manifest %s (%d files)" % (data["version"], len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
