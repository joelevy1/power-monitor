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
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    # Read-only Drive access, used only by _find_sheet_id_via_drive()'s
    # fallback below when GOOGLE_SHEETS_ID isn't set.
    "https://www.googleapis.com/auth/drive.readonly",
)

SHEET_TITLE = "Boat Monitor"
SHEET_TIME_ZONE = "America/Los_Angeles"
TIMESTAMP_NUMBER_FORMAT = "mmm d, yyyy h:mm AM/PM"
GOOGLE_SHEETS_EPOCH = datetime(1899, 12, 30)

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
        "v50_a",
        "v50_mah_used",
        "v50_pct_remain",
        "fw",
        "uplink",
        "note",
    ],
    "GPS_Log": ["timestamp_utc", "device", "lat", "lon", "maps_link", "status", "note"],
    "Bilge_Log": ["timestamp_utc", "device", "channel", "state", "note"],
    "Events": ["timestamp_utc", "device", "event", "detail"],
    "V50_Bank": [
        "timestamp_utc",
        "device",
        "v50_v",
        "v50_a",
        "mah_used",
        "mah_capacity",
        "pct_remain",
        "note",
    ],
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


def _format_timestamp_columns(sheets, spreadsheet_id, existing):
    requests = [
        {
            "updateSpreadsheetProperties": {
                "properties": {"timeZone": SHEET_TIME_ZONE},
                "fields": "timeZone",
            }
        }
    ]

    for title, headers in TABS.items():
        if "timestamp_utc" not in headers:
            continue
        sheet_id = existing.get(title)
        if sheet_id is None:
            continue
        col = headers.index("timestamp_utc")
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "DATE_TIME",
                                "pattern": TIMESTAMP_NUMBER_FORMAT,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat",
                }
            }
        )

    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
    print("OK: spreadsheet timezone set to %s and timestamp columns formatted" % SHEET_TIME_ZONE)


def _parse_iso_timestamp(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _sheets_serial_for_pacific(dt_utc):
    local = dt_utc.astimezone(ZoneInfo(SHEET_TIME_ZONE)).replace(tzinfo=None)
    return (local - GOOGLE_SHEETS_EPOCH).total_seconds() / 86400


def _maps_link(lat, lon):
    try:
        return "https://www.google.com/maps?q=%.7f,%.7f" % (float(lat), float(lon))
    except Exception:
        return ""


def _convert_existing_timestamps_and_repair_gps(sheets, spreadsheet_id, existing):
    """One-time cleanup for rows written before timestamp/maps_link fixes.

    - Converts ISO timestamp text into date/time values formatted in Pacific
      time, so number formatting applies to old rows too.
    - Repairs legacy GPS_Log rows from before the maps_link column existed
      (old E=status, F=note, G=blank -> new E=maps_link, F=status, G=note).
    """
    requests = []
    converted_timestamps = {}

    for title, headers in TABS.items():
        if "timestamp_utc" not in headers or title not in existing:
            continue
        col = headers.index("timestamp_utc")
        col_letter = chr(ord("A") + col)
        values = (
            sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range="%s!%s2:%s" % (title, col_letter, col_letter),
                valueRenderOption="UNFORMATTED_VALUE",
            )
            .execute()
            .get("values", [])
        )

        count = 0
        for offset, row in enumerate(values):
            if not row:
                continue
            dt = _parse_iso_timestamp(row[0])
            if not dt:
                continue
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": existing[title],
                            "startRowIndex": offset + 1,
                            "endRowIndex": offset + 2,
                            "startColumnIndex": col,
                            "endColumnIndex": col + 1,
                        },
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {"numberValue": _sheets_serial_for_pacific(dt)},
                                        "userEnteredFormat": {
                                            "numberFormat": {
                                                "type": "DATE_TIME",
                                                "pattern": TIMESTAMP_NUMBER_FORMAT,
                                            }
                                        },
                                    }
                                ]
                            }
                        ],
                        "fields": "userEnteredValue,userEnteredFormat.numberFormat",
                    }
                }
            )
            count += 1
        converted_timestamps[title] = count

    repaired_gps = 0
    if "GPS_Log" in existing:
        rows = (
            sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range="GPS_Log!A2:G",
                valueRenderOption="UNFORMATTED_VALUE",
            )
            .execute()
            .get("values", [])
        )
        for offset, row in enumerate(rows):
            padded = list(row) + [""] * (7 - len(row))
            # Legacy layout before maps_link existed: E=status, F=note, G=blank.
            if str(padded[4]).strip() in ("fix", "no_fix") and str(padded[6]).strip() == "":
                status = str(padded[4]).strip()
                note = str(padded[5])
                link = _maps_link(padded[2], padded[3]) if status == "fix" else ""
                requests.append(
                    {
                        "updateCells": {
                            "range": {
                                "sheetId": existing["GPS_Log"],
                                "startRowIndex": offset + 1,
                                "endRowIndex": offset + 2,
                                "startColumnIndex": 4,
                                "endColumnIndex": 7,
                            },
                            "rows": [
                                {
                                    "values": [
                                        {"userEnteredValue": {"stringValue": link}},
                                        {"userEnteredValue": {"stringValue": status}},
                                        {"userEnteredValue": {"stringValue": note}},
                                    ]
                                }
                            ],
                            "fields": "userEnteredValue",
                        }
                    }
                )
                repaired_gps += 1

    for start in range(0, len(requests), 100):
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests[start : start + 100]},
        ).execute()

    print(
        "OK: converted existing timestamp text cells:",
        ", ".join("%s=%d" % item for item in sorted(converted_timestamps.items())),
    )
    print("OK: repaired legacy GPS_Log rows:", repaired_gps)


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
    _format_timestamp_columns(sheets, spreadsheet_id, existing)
    _convert_existing_timestamps_and_repair_gps(sheets, spreadsheet_id, existing)
    print("Set GitHub secret GOOGLE_SHEETS_ID to:", spreadsheet_id)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
