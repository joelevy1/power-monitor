"""
Boat Monitor P2 - one real cellular POST to Google Sheets (Phase 2.9 in
BOAT_MONITOR_P2_PLAN.md). Run this from Thonny with the SIM7600 modem wired
and powered, AFTER apps_script_test.py has already passed from a PC (that
confirms the receiving end works before you spend a cellular data session
debugging it).

    import sheets_log_test
    sheets_log_test.main()

Requires boat_monitor/secrets.py with GOOGLE_APPS_SCRIPT_URL and
SHEETS_POST_TOKEN (see APPS_SCRIPT_SETUP.md).
"""

from sheets_log import SheetsLogger


def main():
    print("Boat Monitor P2 - Sheets logging over cellular (bench test)")
    logger = SheetsLogger()

    try:
        print("Opening cellular data (AT+NETOPEN)...")
        logger.ensure_data()

        print("Posting one Power_Log row...")
        result = logger.log_power(
            device="boat-p2",
            mode="bench_test",
            engine={"v": 12.6, "a": 0.1},
            house={"v": 12.8, "a": -0.05},
            v50={"v": 5.0},
            note="sheets_log_test.py",
        )
        print("Response:", result)

        if not result.get("ok"):
            print("FAILED:", result.get("error", "unknown error"))
            return False

        print("OK: row", result.get("row"), "in Power_Log")
        return True
    finally:
        print("Closing cellular data (AT+NETCLOSE)...")
        logger.close_data()


if __name__ == "__main__":
    main()
