#!/usr/bin/env python3
"""Validate Config tab — one row per critical key; optional auto-dedupe."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id  # noqa: E402
from sheets_config_policy import (  # noqa: E402
    dedupe_config_keys,
    find_duplicate_keys,
    read_config_rows,
    validate_config_or_exit,
)


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate Config tab has no duplicate singleton keys")
    p.add_argument("--fix", action="store_true", help="Remove duplicate rows (canonical merge)")
    p.add_argument("--dry-run", action="store_true", help="With --fix, print only")
    args = p.parse_args(argv)

    creds_path = _credentials_path()
    if not creds_path:
        print("Missing credentials", file=sys.stderr)
        return 1

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sid = _sheet_id(creds)

    if args.fix:
        dupes, deleted = dedupe_config_keys(sheets, sid, dry_run=args.dry_run)
        if not dupes:
            print("OK: no duplicate Config keys")
            return 0
        print(
            "FIX: %d duplicate key(s)%s, %d row(s) %s"
            % (
                len(dupes),
                ": " + ", ".join(sorted(dupes.keys())),
                deleted,
                "would be removed" if args.dry_run else "removed",
            )
        )
        return 0

    rows = read_config_rows(sheets, sid)
    dupes = find_duplicate_keys(rows)
    if dupes:
        print("FAIL: duplicate Config keys:")
        for k, nums in sorted(dupes.items()):
            print(" ", k, "rows", nums)
        print("Run: python3 sheets_config_validate.py --fix", file=sys.stderr)
        return 1
    print("OK: Config keys unique (%d rows)" % len(rows))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except SystemExit as exc:
        if exc.code:
            print(exc, file=sys.stderr)
        sys.exit(exc.code if exc.code else 1)
