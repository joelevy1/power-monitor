"""Golden contract between firmware payloads and Google Sheet headers."""

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sheets_log
from sheets_bootstrap import TABS


def _assert_payload_matches(tab, payload):
    expected = set(TABS[tab]) - {"timestamp_utc"}
    assert set(payload) == expected, (tab, sorted(set(payload) - expected), sorted(expected - set(payload)))


def test_all_logging_payloads_match_sheet_schema():
    calls = []
    logger = sheets_log.SheetsLogger(url="https://example.test", token="token")
    logger.log_row = lambda tab, payload: calls.append((tab, payload)) or {"ok": True}

    old_modules = {
        name: sys.modules.get(name)
        for name in ("v50_energy", "mem_guard", "ota_lifecycle")
    }
    sys.modules["v50_energy"] = types.SimpleNamespace(
        tick=lambda _reading: None,
        snapshot=lambda: {
            "mah_used": 10.0,
            "mah_capacity": 1000,
            "pct_remain": 99.0,
            "full_anchor_utc": "",
        },
    )
    sys.modules["mem_guard"] = types.SimpleNamespace(
        free_bytes=lambda: 0,
        low_heap_threshold=lambda: 1,
    )
    sys.modules["ota_lifecycle"] = types.SimpleNamespace(
        maybe_confirm_after_log=lambda *_args: None
    )
    try:
        logger.log_power(
            "boat-p2",
            "docked_off",
            {"v": 12.6, "a": -0.2},
            {"v": 12.8, "a": 0.1},
            {"v": 5.0, "a": 0.08},
            note="contract",
            fw="1.1.175",
            uplink="DockNet",
        )
        logger.log_v50_bank(
            "boat-p2",
            {"v": 5.0, "a": 0.08},
            {"mah_used": 10.0, "mah_capacity": 1000, "pct_remain": 99.0},
            note="contract",
        )
        logger.log_gps("boat-p2", 47.6, -122.3, note="contract")
        logger.log_event("boat-p2", "contract", "schema")
    finally:
        for name, old in old_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    assert [tab for tab, _payload in calls] == [
        "Power_Log",
        "V50_Bank",
        "GPS_Log",
        "Events",
    ]
    for tab, payload in calls:
        _assert_payload_matches(tab, payload)


def main():
    test_all_logging_payloads_match_sheet_schema()
    print("logging schema contract tests OK")


if __name__ == "__main__":
    main()
