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


def get_json(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def verify_timestamp_cell(sheet_id, tab, row_num):
    """Return True if the timestamp cell is a real Sheets date, not ISO text."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("(skip timestamp cell check -- pip install -r boat_monitor/requirements-sheets.txt)")
        return True

    raw = (
        os.environ.get("BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    )
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw and not creds_path:
        secrets = Path(__file__).resolve().parent / "secrets.py"
        if secrets.is_file():
            import importlib.util

            spec = importlib.util.spec_from_file_location("boat_secrets", secrets)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            creds_path = getattr(mod, "GOOGLE_SERVICE_ACCOUNT_FILE", "") or creds_path

    import tempfile

    if raw.startswith("{"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(raw)
        tmp.close()
        creds_path = tmp.name
    elif not creds_path or not Path(creds_path).is_file():
        print("(skip timestamp cell check -- no service account for Sheets API)")
        return True

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=("https://www.googleapis.com/auth/spreadsheets",)
    )
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    cell = (
        svc.spreadsheets()
        .values()
        .get(
            spreadsheetId=sheet_id,
            range="%s!A%d" % (tab, row_num),
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
        .get("values", [[None]])[0][0]
    )
    if isinstance(cell, str) and ("T" in cell or cell.endswith("Z")):
        return False
    if isinstance(cell, (int, float)):
        return True
    return not isinstance(cell, str)


def main():
    url, token = _load_config()

    try:
        info = get_json(url)
        version = info.get("receiver_version")
        if version is None:
            print(
                "WARNING: Live Apps Script deployment looks OLD (no receiver_version in GET). "
                "Redeploy Code.gs: Deploy -> Manage deployments -> New version. "
                "See APPS_SCRIPT_SETUP.md"
            )
        elif version < 2:
            print("WARNING: receiver_version=%s; need >= 2 for Pacific date/time cells." % version)
        else:
            print("Apps Script receiver_version:", version)
    except Exception as exc:
        print("Could not GET Apps Script URL (continuing POST test):", exc)

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
                "maps_link": "https://www.google.com/maps?q=31.2223880,121.3540000",
                "status": "fix",
                "note": "apps_script_test.py",
            },
        ),
    ]

    ok = True
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "").strip()
    for tab, data in tests:
        body = {"tab": tab, "token": token, "data": data}
        try:
            result = post_json(url, body)
        except Exception as exc:
            print("FAIL: %s -> request error: %s" % (tab, exc))
            ok = False
            continue

        if result.get("ok"):
            row = result.get("row")
            print("OK: appended to %s (row %s)" % (tab, row))
            if sheet_id and row:
                if verify_timestamp_cell(sheet_id, tab, int(row)):
                    print("  timestamp cell: OK (date value, not ISO text)")
                else:
                    print(
                        "  timestamp cell: FAIL (still ISO text) -- redeploy Apps Script "
                        "(Deploy -> Manage deployments -> New version). See APPS_SCRIPT_SETUP.md"
                    )
                    ok = False
        else:
            print("FAIL: %s -> %s" % (tab, result.get("error")))
            ok = False

    if not ok:
        return 1

    print()
    print("All rows posted -- timestamps should show like 'Aug 5, 2026 8:26 PM' in the sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
