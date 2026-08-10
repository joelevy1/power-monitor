#!/usr/bin/env python3
"""Build ota_release.bmota from ota_manifest.json and attach bundle metadata."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "ota_manifest.json"
BUNDLE_NAME = "ota_release.bmota"
GITHUB_RAW_PREFIX = (
    "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/"
)


def main(argv=None):
    if not MANIFEST_PATH.is_file():
        print("build_ota_bundle: missing ota_manifest.json", file=sys.stderr)
        return 1

    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = data.get("files") or []
    if not files:
        print("build_ota_bundle: manifest has no files", file=sys.stderr)
        return 1

    try:
        import ota_bundle
    except ImportError:
        sys.path.insert(0, str(ROOT))
        import ota_bundle

    items = []
    for entry in files:
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        src = ROOT / path
        if not src.is_file():
            print("build_ota_bundle: missing %s" % path, file=sys.stderr)
            return 1
        items.append((path, src.read_bytes()))

    blob = ota_bundle.build_bytes(items)
    bundle_path = ROOT / BUNDLE_NAME
    bundle_path.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()

    data["bundle"] = {
        "path": BUNDLE_NAME,
        "url": GITHUB_RAW_PREFIX + BUNDLE_NAME,
        "size": len(blob),
        "sha256": digest,
    }
    MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(
        "OK: %s (%d bytes, sha256=%s…) %d files"
        % (BUNDLE_NAME, len(blob), digest[:12], len(items))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
