"""Config tab canonical rules — one row per key, safe merge when duplicates exist."""

from __future__ import annotations

from datetime import datetime, timezone

CONFIG_TAB = "Config"
DEVICE = "boat-p2"

# Keys that must not appear twice (global or device-scoped).
SINGLETON_KEYS = frozenset(
    {
        "dock_mode",
        "standby_prefer_wifi",
        "min_fw_version",
        "interval_engine_off_s",
        "interval_engine_on_s",
        "auto_ota_on_boot",
        "boot_ota_prefer_wifi",
        "ota_manifest_profile",
        "wifi_networks",
    }
)

# When duplicate rows exist, pick the value that wins for logging safety.
def pick_canonical_value(key: str, values: list[str], settings_context: dict | None = None) -> str:
    """Choose one value when the sheet has duplicate keys."""
    if not values:
        return ""
    cleaned = [str(v).strip() for v in values]
    if key == "dock_mode":
        lows = [v.lower() for v in cleaned]
        if "away" in lows:
            return "away"
        if settings_context and not _truthy(settings_context.get("standby_prefer_wifi")):
            if "home" in lows or "dock" in lows or "wifi" in lows:
                return "away"
        return cleaned[-1]
    if key in ("standby_prefer_wifi", "boot_ota_prefer_wifi", "auto_ota_on_boot"):
        if any(v.lower() in ("0", "false", "no", "off") for v in cleaned):
            return "0"
        return cleaned[-1]
    return cleaned[-1]


def _truthy(value):
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")


def _parse_updated(text: str) -> datetime | None:
    text = str(text or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except Exception:
        return None


def read_config_rows(sheets, spreadsheet_id):
    """Return list of (row_num_1based, key, value, updated_utc, note)."""
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Config!A2:D2000")
        .execute()
        .get("values", [])
    )
    out = []
    for idx, row in enumerate(rows):
        if not row or not str(row[0]).strip():
            continue
        key = str(row[0]).strip()
        val = row[1] if len(row) > 1 else ""
        updated = row[2] if len(row) > 2 else ""
        note = row[3] if len(row) > 3 else ""
        out.append((idx + 2, key, val, updated, note))
    return out


def find_duplicate_keys(rows):
    """Return {key: [row_num, ...]} for keys with more than one row."""
    by_key: dict[str, list[int]] = {}
    for row_num, key, _val, _upd, _note in rows:
        by_key.setdefault(key, []).append(row_num)
    return {k: v for k, v in by_key.items() if len(v) > 1}


def _config_sheet_id(sheets, spreadsheet_id):
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("title") == CONFIG_TAB:
            return sheet["properties"]["sheetId"]
    return None


def delete_config_rows(sheets, spreadsheet_id, row_nums_1based):
    """Delete Config rows (1-based sheet row numbers)."""
    sheet_id = _config_sheet_id(sheets, spreadsheet_id)
    if sheet_id is None or not row_nums_1based:
        return 0
    reqs = []
    for row_num in sorted(row_nums_1based, reverse=True):
        idx = int(row_num) - 1
        reqs.append(
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    }
                }
            }
        )
    sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": reqs}).execute()
    return len(row_nums_1based)


def dedupe_config_keys(sheets, spreadsheet_id, dry_run=False):
    """
    Collapse duplicate Config keys to a single row per key.
    Returns (duplicate_keys, rows_deleted).
    """
    rows = read_config_rows(sheets, spreadsheet_id)
    dupes = find_duplicate_keys(rows)
    if not dupes:
        return {}, 0

    settings_ctx = {}
    for _rn, key, val, _u, _n in rows:
        if key in SINGLETON_KEYS or key.endswith(":standby_prefer_wifi"):
            settings_ctx[key.split(":", 1)[-1]] = val

    to_delete = []
    for key, row_nums in dupes.items():
        entries = [(rn, val, upd) for rn, k, val, upd, _ in rows if k == key]
        values = [e[1] for e in entries]
        winner_val = pick_canonical_value(
            key.split(":", 1)[-1] if ":" in key else key,
            values,
            settings_ctx,
        )
        # Prefer row with latest updated_utc among those matching winner, else last row
        best_row = entries[-1][0]
        best_ts = None
        for rn, val, upd in entries:
            if str(val).strip() == str(winner_val).strip():
                ts = _parse_updated(upd)
                if ts and (best_ts is None or ts > best_ts):
                    best_ts = ts
                    best_row = rn
        for rn, val, upd in entries:
            if rn != best_row:
                to_delete.append(rn)
        if not dry_run:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range="Config!B%d:D%d" % (best_row, best_row),
                valueInputOption="USER_ENTERED",
                body={"values": [[winner_val, now, "config dedupe canonical"]]},
            ).execute()

    deleted = 0
    if not dry_run and to_delete:
        deleted = delete_config_rows(sheets, spreadsheet_id, to_delete)
    return dupes, deleted if not dry_run else len(to_delete)


def validate_config_or_exit(sheets, spreadsheet_id, auto_fix=True):
    """Raise SystemExit if duplicate singleton keys remain after optional dedupe."""
    dupes = find_duplicate_keys(read_config_rows(sheets, spreadsheet_id))
    if dupes and auto_fix:
        fixed, deleted = dedupe_config_keys(sheets, spreadsheet_id)
        if fixed:
            print(
                "OK: config dedupe removed %d duplicate row(s): %s"
                % (deleted, ", ".join(sorted(fixed.keys())))
            )
        dupes = find_duplicate_keys(read_config_rows(sheets, spreadsheet_id))
    critical = [
        k
        for k in dupes
        if k in SINGLETON_KEYS or (":" in k and k.split(":", 1)[1] in SINGLETON_KEYS)
    ]
    if critical:
        lines = ["Config duplicate keys (unsafe): %s" % ", ".join(sorted(critical))]
        for k in sorted(critical):
            lines.append("  %s rows %s" % (k, dupes[k]))
        lines.append("Run: python3 sheets_config_validate.py --fix")
        raise SystemExit("\n".join(lines))
    if dupes:
        print("WARN: non-singleton duplicate keys:", ", ".join(sorted(dupes.keys())))
    return dupes
