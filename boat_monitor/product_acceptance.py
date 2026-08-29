#!/usr/bin/env python3
"""Read-only acceptance checks for the platform-independent Power_Log contract."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
SHEET_TIME_ZONE = ZoneInfo("America/Los_Angeles")
SHEET_TIMESTAMP_FORMAT = "%b %d, %Y %I:%M %p"


def _number(row, key):
    value = row.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError("%s is blank" % key)
    return float(value)


def analyze_power_rows(
    rows,
    expected_fw="",
    expected_interval_s=300,
    expected_mode="docked_off",
    require_wifi=True,
    now=None,
    max_age_s=900,
):
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    check("sample_count", len(rows) >= 3, "%d rows (need at least 3)" % len(rows))
    if not rows:
        return {"ok": False, "checks": checks}

    latest = rows[-1]
    if expected_fw:
        versions = [str(row.get("fw") or "") for row in rows]
        check(
            "firmware",
            all(version == expected_fw for version in versions),
            "expected %s, observed %s" % (expected_fw, sorted(set(versions))),
        )

    modes = [str(row.get("mode") or "") for row in rows]
    check(
        "mode",
        all(mode == expected_mode for mode in modes),
        "expected %s, observed %s" % (expected_mode, sorted(set(modes))),
    )

    uplinks = [str(row.get("uplink") or "").strip() for row in rows]
    wifi_ok = all(uplink and uplink.lower() != "cellular" for uplink in uplinks)
    check(
        "wifi_uplink",
        wifi_ok if require_wifi else all(uplinks),
        "observed %s" % sorted(set(uplinks)),
    )

    timestamps = []
    for row in rows:
        try:
            timestamps.append(
                datetime.strptime(
                    str(row.get("timestamp_utc") or row.get("ts") or "").strip(),
                    SHEET_TIMESTAMP_FORMAT,
                ).replace(tzinfo=SHEET_TIME_ZONE)
            )
        except ValueError:
            pass
    check(
        "timestamps",
        len(timestamps) == len(rows),
        "parsed %d/%d" % (len(timestamps), len(rows)),
    )
    if len(timestamps) >= 2:
        deltas = [
            int((timestamps[index] - timestamps[index - 1]).total_seconds())
            for index in range(1, len(timestamps))
        ]
        lower = max(60, int(expected_interval_s * 0.75))
        upper = int(expected_interval_s * 1.5)
        check(
            "cadence",
            all(lower <= delta <= upper for delta in deltas),
            "expected %d-%ds, observed %s" % (lower, upper, deltas),
        )

    if timestamps:
        now = now or datetime.now(SHEET_TIME_ZONE)
        age_s = int((now - timestamps[-1]).total_seconds())
        check("freshness", 0 <= age_s <= max_age_s, "latest age %ds" % age_s)

    ranges = {
        "engine_v": (0.0, 20.0),
        "house_v": (0.0, 20.0),
        "v50_v": (0.0, 6.0),
        "engine_a": (-20.0, 20.0),
        "house_a": (-20.0, 20.0),
        "v50_a": (0.0, 5.0),
    }
    for key, limits in ranges.items():
        try:
            values = [_number(row, key) for row in rows]
            ok = all(limits[0] <= value <= limits[1] for value in values)
            detail = "range %.3f..%.3f" % (min(values), max(values))
        except (TypeError, ValueError) as exc:
            ok = False
            detail = str(exc)
        check(key, ok, detail)

    return {
        "ok": all(item["ok"] for item in checks),
        "latest": latest,
        "checks": checks,
    }


def fetch_power_rows(device, count):
    sys.path.insert(0, str(ROOT))
    from ota_stress_harness import _sheets

    sheets, spreadsheet_id = _sheets()
    header = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Power_Log!1:1")
        .execute()
        .get("values", [[]])[0]
    )
    values = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Power_Log!A2:Z")
        .execute()
        .get("values", [])
    )
    rows = []
    for values_row in values:
        row = {
            key: values_row[index] if index < len(values_row) else ""
            for index, key in enumerate(header)
        }
        if str(row.get("device") or "") == device:
            rows.append(row)
    return rows[-count:]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="boat-p2")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--expected-fw", default="")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--mode", default="docked_off")
    parser.add_argument("--allow-cellular", action="store_true")
    parser.add_argument("--max-age", type=int, default=900)
    args = parser.parse_args(argv)

    result = analyze_power_rows(
        fetch_power_rows(args.device, max(3, args.rows)),
        expected_fw=args.expected_fw,
        expected_interval_s=args.interval,
        expected_mode=args.mode,
        require_wifi=not args.allow_cellular,
        max_age_s=args.max_age,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
