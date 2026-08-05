"""
Test the Apps Script Web App receiver (boat_monitor/apps_script/Code.gs)
directly from a PC over plain internet -- no cellular modem or Pico needed.
This is the fast way to validate Phase 2's "receiving end" before ever
touching AT commands (Phase 2.2's PC POST check, done via HTTPS instead of
the Google Sheets API client).

Requires: pip install requests (or anything with urllib -- see fallback below)

Environment:
  GOOGLE_APPS_SCRIPT_URL   the deployed /exec URL (see APPS_SCRIPT_SETUP.md)
  SHEETS_POST_TOKEN        the same token set as a Script property in Code.gs

Or boat_monitor/secrets.py with the same two names.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _load_config():
    url = os.environ.get("GOOGLE_APPS_SCRIPT_URL", "").strip()
    token = os.environ.get("SHEETS_POST_TOKEN", "").strip()

    secrets = Path(__file__).resolve().parent / "secrets.py"
    if secrets.is_file():
        import importlib.util

        spec = importlib.util.spec_from_file_location("boat_secrets", secrets)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        url = url or getattr(mod, "GOOGLE_APPS_SCRIPT_URL", "")
        token = token or getattr(mod, "SHEETS_POST_TOKEN", "")

    if not url:
        raise SystemExit(
            "Missing GOOGLE_APPS_SCRIPT_URL (env or secrets.py) -- deploy "
            "boat_monitor/apps_script/Code.gs first, see APPS_SCRIPT_SETUP.md"
        )
    return url, token


def post_json(url, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main():
    url, token = _load_config()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    tests = [
        (
            "Power_Log",
            {
                "timestamp_utc": now,
                "device": "pc-test",
                "mode": "apps_script_test",
                "engine_v": 12.6,
                "engine_a": 0.1,
                "house_v": 12.8,
                "house_a": -0.05,
                "v50_v": 5.0,
                "note": "apps_script_test.py",
            },
        ),
        (
            "GPS_Log",
            {
                "timestamp_utc": now,
                "device": "pc-test",
                "lat": 31.222388,
                "lon": 121.354,
                "status": "fix",
                "note": "apps_script_test.py",
            },
        ),
    ]

    ok = True
    for tab, data in tests:
        body = {"tab": tab, "token": token, "data": data}
        try:
            result = post_json(url, body)
        except Exception as exc:
            print("FAIL: %s -> request error: %s" % (tab, exc))
            ok = False
            continue

        if result.get("ok"):
            print("OK: appended to %s (row %s)" % (tab, result.get("row")))
        else:
            print("FAIL: %s -> %s" % (tab, result.get("error")))
            ok = False

    if not ok:
        return 1

    print()
    print("All rows posted -- check the spreadsheet to confirm they landed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
