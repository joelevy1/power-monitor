"""
Create boat-monitor sheet tabs and header rows (SHEETS_SETUP §3.3–3.4).

Uses GOOGLE_SERVICE_ACCOUNT_JSON (file path or JSON string) and GOOGLE_SHEETS_ID.
If GOOGLE_SHEETS_ID is missing, tries Drive API to find a spreadsheet named
"Boat Monitor" (SHEET_TITLE below) shared with the service account.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    # Read-only Drive access, used only by _find_sheet_id_via_drive()'s
    # fallback below when GOOGLE_SHEETS_ID isn't set.
    "https://www.googleapis.com/auth/drive.readonly",
)

SHEET_TITLE = "Boat Monitor"

TABS = {
    "Power_Log": [
        "timestamp_utc",
        "device",
        "mode",
        "engine_v",
        "engine_a",
        "house_v",
        "house_a",
        "v50_v",
        "note",
    ],
    "GPS_Log": ["timestamp_utc", "device", "lat", "lon", "maps_link", "status", "note"],
    "Bilge_Log": ["timestamp_utc", "device", "channel", "state", "note"],
    "Events": ["timestamp_utc", "device", "event", "detail"],
    "Config": ["key", "value", "updated_utc", "note"],
}


def _service_account_raw():
    for key in (
        "BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
    ):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    secrets = Path(__file__).resolve().parent / "secrets.py"
    if secrets.is_file():
        import importlib.util

        spec = importlib.util.spec_from_file_location("boat_secrets", secrets)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for attr in (
            "BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON",
            "GOOGLE_SERVICE_ACCOUNT_JSON",
            "GOOGLE_SERVICE_ACCOUNT_FILE",
        ):
            val = getattr(mod, attr, "") or ""
            if val:
                return val
    return ""


def _credentials_path():
    raw = _service_account_raw()
    if not raw:
        path = ""
    elif raw.startswith("{"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(raw)
        tmp.close()
        return tmp.name
    elif Path(raw).is_file():
        return raw
    else:
        path = ""

    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if creds and Path(creds).is_file():
        return creds

    raise SystemExit(
        "Missing BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SERVICE_ACCOUNT_JSON, "
        "or GOOGLE_APPLICATION_CREDENTIALS"
    )


def _find_sheet_id_via_drive(creds):
    """Fallback when GOOGLE_SHEETS_ID isn't set: search Drive for a
    spreadsheet named SHEET_TITLE ("Boat Monitor") shared with this
    service account. This module's docstring has promised this fallback
    from the start ("If GOOGLE_SHEETS_ID is missing, tries Drive API to
    find a spreadsheet named 'Boat Monitor Logs' shared with the service
    account") but _sheet_id() never actually implemented it -- it just
    raised SystemExit unconditionally if the env var was missing. (That
    quoted title has since been corrected to "Boat Monitor" -- the
    actual real-world spreadsheet's name, not "Boat Monitor Logs".)
    """
    from googleapiclient.discovery import build

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    query = (
        "name = '%s' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        % SHEET_TITLE
    )
    response = drive.files().list(q=query, fields="files(id, name)", pageSize=10).execute()
    files = response.get("files", [])

    if not files:
        raise SystemExit(
            "No spreadsheet named '%s' found shared with this service account via Drive API. "
            "Set environment or GitHub secret GOOGLE_SHEETS_ID to the spreadsheet ID (from the "
            "URL between /d/ and /edit), or share a spreadsheet named '%s' with this service "
            "account's email (the client_email field in its JSON key) so it can be found "
            "automatically." % (SHEET_TITLE, SHEET_TITLE)
        )
    if len(files) > 1:
        raise SystemExit(
            "Found %d spreadsheets named '%s' shared with this service account -- set "
            "GOOGLE_SHEETS_ID explicitly to disambiguate. IDs: %s"
            % (len(files), SHEET_TITLE, ", ".join(f["id"] for f in files))
        )

    print("Found spreadsheet '%s' via Drive API (no GOOGLE_SHEETS_ID set): %s" % (SHEET_TITLE, files[0]["id"]))
    return files[0]["id"]


def _sheet_id(creds=None):
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "").strip()
    if not sheet_id:
        sheet_id = os.environ.get("YOUR_SPREADSHEET_ID", "").strip()
    if sheet_id:
        return sheet_id

    if creds is not None:
        try:
            return _find_sheet_id_via_drive(creds)
        except SystemExit:
            raise
        except Exception as exc:
            print("Drive API lookup failed (falling back to the explicit-ID error below):", exc)

    raise SystemExit(
        "Set environment or GitHub secret GOOGLE_SHEETS_ID to the spreadsheet ID "
        "(from the URL between /d/ and /edit). Rename secret YOUR_SPREADSHEET_ID if needed."
    )


def main():
    creds_path = _credentials_path()

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    spreadsheet_id = _sheet_id(creds)
    print("Using spreadsheet:", spreadsheet_id)

    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    requests = []
    for title in TABS:
        if title not in existing:
            requests.append({"addSheet": {"properties": {"title": title}}})

    if requests:
        added = [t for t in TABS if t not in existing]
        sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        print("Added tabs:", ", ".join(added))
        meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    data = []
    for title, headers in TABS.items():
        data.append({"range": f"{title}!A1", "values": [headers]})

    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()

    print("OK: header rows written on:", ", ".join(TABS.keys()))
    print("Set GitHub secret GOOGLE_SHEETS_ID to:", spreadsheet_id)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
