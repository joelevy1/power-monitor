"""Host tests for the reusable Power_Log acceptance contract."""

from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from product_acceptance import SHEET_TIME_ZONE, analyze_power_rows


def _rows():
    rows = []
    for minute in (0, 5, 10):
        rows.append(
            {
                "timestamp_utc": "Aug 29, 2026 7:%02d PM" % minute,
                "device": "boat-p2",
                "mode": "docked_off",
                "engine_v": "12.6",
                "engine_a": "-0.2",
                "house_v": "12.8",
                "house_a": "0.3",
                "v50_v": "5.1",
                "v50_a": "0.08",
                "fw": "1.1.174",
                "uplink": "DockNet",
            }
        )
    return rows


def test_healthy_rows_pass():
    result = analyze_power_rows(
        _rows(),
        expected_fw="1.1.174",
        now=datetime(2026, 8, 29, 19, 11, tzinfo=SHEET_TIME_ZONE),
    )
    assert result["ok"], result


def test_cellular_and_stale_rows_fail():
    rows = _rows()
    rows[-1]["uplink"] = "cellular"
    result = analyze_power_rows(
        rows,
        expected_fw="1.1.174",
        now=datetime(2026, 8, 29, 20, 0, tzinfo=SHEET_TIME_ZONE),
    )
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "wifi_uplink" in failed
    assert "freshness" in failed


def test_missing_sensor_value_fails():
    rows = _rows()
    rows[1]["house_a"] = ""
    result = analyze_power_rows(
        rows,
        now=datetime(2026, 8, 29, 19, 11, tzinfo=SHEET_TIME_ZONE),
    )
    failed = {item["name"] for item in result["checks"] if not item["ok"]}
    assert "house_a" in failed


def main():
    test_healthy_rows_pass()
    test_cellular_and_stale_rows_fail()
    test_missing_sensor_value_fails()
    print("product acceptance tests OK")


if __name__ == "__main__":
    main()
