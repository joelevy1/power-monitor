#!/usr/bin/env python3
"""Push standard field Config after a validated release.

NEVER run before validate_release.py --check-github passes on master.
min_fw_version is always set to VERSION in version.py (not a future PR version).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_config_upsert import upsert_config_keys  # noqa: E402
from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402


def _shipped_version():
    import version

    return getattr(version, "VERSION", "").strip()


def main():
    v = _shipped_version()
    if not v:
        print("Missing VERSION in version.py", file=sys.stderr)
        return 1

    script = Path(__file__).resolve().parent / "validate_release.py"
    for extra in ([], ["--check-github"]):
        cmd = [sys.executable, str(script)] + extra
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0:
            print(
                "apply_ship_config: validate_release failed — fix release before sheet min_fw",
                file=sys.stderr,
            )
            return r.returncode

    rows = [
        ("interval_engine_on_s", "60", "1 min while key_on (engine charging)"),
        ("interval_engine_off_s", "300", "5 min docked / standby battery test"),
        ("boot_ota_max_seconds", "420", "cellular full manifest needs 3–7 min"),
        ("min_fw_version", v, "OTA floor (= GitHub master manifest %s)" % v),
    ]

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing service account credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)
    upsert_config_keys(sheets, sid, rows)

    from ota_stress_rules import STALE_SHEET_KEYS

    clear_rows = [(k, "", "apply_ship_config: clear one-shot") for k in STALE_SHEET_KEYS]
    upsert_config_keys(sheets, sid, clear_rows)

    for key, val, _ in rows:
        print("OK:", key, "=", val)
    print("Sheet updated. Pico OTA when current < min_fw after master manifest ships.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
