#!/usr/bin/env python3
"""Push standard field Config: 1 min engine-on logs, 5 min docked, OTA floor 1.1.42."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_config_upsert import upsert_config_keys  # noqa: E402
from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402

ROWS = [
    ("interval_engine_on_s", "60", "1 min while key_on (engine charging)"),
    ("interval_engine_off_s", "300", "5 min docked / standby battery test"),
    ("min_fw_version", "1.1.43", "OTA: BLE underway logging + prior ship fixes"),
]


def main():
    creds_path = _credentials_path()
    if not creds_path:
        print("Missing service account credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)
    upsert_config_keys(sheets, sid, ROWS)
    for key, val, _ in ROWS:
        print("OK:", key, "=", val)
    print("Pico applies intervals on next successful log; OTA when version < min_fw_version.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
