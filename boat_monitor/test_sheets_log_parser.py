"""
Pure-Python unit test for sheets_log.py's maps_link_url() helper -- no
MicroPython/hardware dependency (sheets_log.py only imports machine/gps/
cellular lazily inside method bodies, specifically so this stays
importable here). Run directly with:

    python3 boat_monitor/test_sheets_log_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheets_log import maps_link_url  # noqa: E402


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # A real fix -- both lat/lon present -- should produce a usable,
    # clickable Google Maps URL (7 decimal places, same precision
    # field_console.py's existing "Open in Google Maps" link already uses).
    check(
        "maps_link_url builds a Google Maps URL",
        maps_link_url(31.222388, 121.354)
        == "https://www.google.com/maps?q=31.2223880,121.3540000",
    )

    # Negative lat/lon (Southern/Western hemisphere) shouldn't break the
    # URL format.
    check(
        "maps_link_url handles negative lat/lon",
        maps_link_url(-33.865143, -151.209900) == "https://www.google.com/maps?q=-33.8651430,-151.2099000",
    )

    # No fix yet -- lat and/or lon is None. A blank cell reads far better
    # in the sheet than a broken link with the literal text "None" in it.
    check("maps_link_url blank when lat is None", maps_link_url(None, 121.354) == "")
    check("maps_link_url blank when lon is None", maps_link_url(31.222388, None) == "")
    check("maps_link_url blank when both are None", maps_link_url(None, None) == "")

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
