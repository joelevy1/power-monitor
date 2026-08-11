#!/usr/bin/env python3
"""
Hard preflight before OTA stress or sheet min_fw bump.

Exits non-zero on any policy violation (manifest, watch, reboot trap, sheet keys).

  python3 ota_stress_preflight.py
  python3 ota_stress_preflight.py --profile dock --no-watch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _sheets():
    from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False), _sheet_id(creds)


def _device_fw():
    from ota_stress_harness import _current_device_fw, _fetch_events, _read_local_version

    return _current_device_fw() or "", _read_local_version(), _fetch_events()


def main(argv=None):
    p = argparse.ArgumentParser(description="OTA stress preflight gate")
    p.add_argument("--profile", choices=("underway", "dock"), default="underway")
    p.add_argument("--no-watch", action="store_true", help="skip boat_p2_watch running check")
    args = p.parse_args(argv)

    from ota_stress_rules import preflight_stress_campaign

    device_fw, repo_ver, events = _device_fw()
    sheets, sid = _sheets()
    preflight_stress_campaign(
        sheets,
        sid,
        profile=args.profile,
        device_fw=device_fw,
        repo_ver=repo_ver,
        require_watch=not args.no_watch,
        events=events,
    )
    print("OK: ota_stress_preflight passed (profile=%s device=%s repo=%s)" % (args.profile, device_fw, repo_ver))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
