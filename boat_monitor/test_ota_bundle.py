#!/usr/bin/env python3
"""Round-trip test for ota_bundle.BMOTA format."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ota_bundle


def main():
    manifest = json.loads((ROOT / "ota_manifest.json").read_text(encoding="utf-8"))
    items = []
    for entry in manifest.get("files") or []:
        path = entry["path"]
        items.append((path, (ROOT / path).read_bytes()))

    blob = ota_bundle.build_bytes(items)
    seen = {}
    for path, data in ota_bundle.iter_records(blob):
        seen[path] = data.decode("utf-8")

    assert len(seen) == len(items)
    for path, raw in items:
        assert path in seen
        assert seen[path] == raw.decode("utf-8")
    print("OK: ota_bundle round-trip %d files (%d bytes)" % (len(seen), len(blob)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
