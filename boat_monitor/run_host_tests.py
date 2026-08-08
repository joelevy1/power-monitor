#!/usr/bin/env python3
"""Run all host-side boat_monitor unit tests + validate_release."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TESTS = sorted(ROOT.glob("test_*.py"))


def main():
    failed = []
    for path in TESTS:
        print("\n---", path.name, "---")
        r = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
        if r.returncode != 0:
            failed.append(path.name)

    print("\n--- validate_release.py ---")
    r = subprocess.run([sys.executable, str(ROOT / "validate_release.py")], cwd=str(ROOT))
    if r.returncode != 0:
        failed.append("validate_release.py")

    if failed:
        print("\nFAILED:", ", ".join(failed))
        return 1
    print("\nAll host tests OK")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
