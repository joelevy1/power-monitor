"""
Pure-Python unit test for gps.py's parser (Phase 3.10 in BOAT_MONITOR_P2_PLAN.md:
"Parser: 3 sample +CGPSINFO strings"). No MicroPython/hardware dependency --
run directly with:

    python3 boat_monitor/test_gps_parser.py

gps.py defers its `machine`/`config` imports into Gps.__init__ specifically so
gps_to_decimal()/parse_cgpsinfo() can be imported and tested here without a
Pico or a SIM7600 modem attached.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gps import gps_to_decimal, parse_cgpsinfo  # noqa: E402


def approx(a, b, tol=1e-4):
    return a is not None and b is not None and abs(a - b) < tol


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # 1. Real fix, both hemispheres positive (N/E) -- from SIMCom's documented
    #    +CGPSINFO format: <lat>,<N/S>,<lon>,<E/W>,<date>,<UTC>,<alt>,<speed>,<course>
    text1 = "+CGPSINFO: 3113.343286,N,12121.234064,E,250311,072809.0,44.1,0.0,0"
    lat1, lon1, raw1 = parse_cgpsinfo(text1)
    check("fix N/E parses to a value", lat1 is not None and lon1 is not None)
    check("fix N/E lat ~31.222 deg", approx(lat1, 31.222388, tol=1e-3))
    check("fix N/E lon ~121.354 deg", approx(lon1, 121.354, tol=1e-3))
    check("fix N/E raw line captured", raw1.startswith("+CGPSINFO:"))

    # 2. Fix with S/W hemispheres -- both should come back negative.
    text2 = "+CGPSINFO: 3355.123456,S,07012.654321,W,010124,235959.0,10.5,2.3,180"
    lat2, lon2, raw2 = parse_cgpsinfo(text2)
    check("fix S/W parses to a value", lat2 is not None and lon2 is not None)
    check("fix S/W lat is negative", lat2 is not None and lat2 < 0)
    check("fix S/W lon is negative", lon2 is not None and lon2 < 0)

    # 3. No fix yet -- SIM7600 returns all-empty fields; must not crash and
    #    must report "no fix" (None, None), matching field_console.py's
    #    existing behavior this was refactored from.
    text3 = "+CGPSINFO: ,,,,,,,,"
    lat3, lon3, raw3 = parse_cgpsinfo(text3)
    check("no-fix returns lat=None", lat3 is None)
    check("no-fix returns lon=None", lon3 is None)
    check("no-fix still returns the raw line", raw3.startswith("+CGPSINFO:"))

    # 4. Garbage / no +CGPSINFO in the response at all (e.g. modem echoed
    #    something else, or a timeout with empty buffer) -- must not crash.
    lat4, lon4, raw4 = parse_cgpsinfo("ERROR\r\n")
    check("non-CGPSINFO text returns lat=None", lat4 is None)
    check("non-CGPSINFO text returns lon=None", lon4 is None)
    check("non-CGPSINFO text returns empty raw", raw4 == "")

    # 5. gps_to_decimal() directly, including hemisphere sign flips.
    check("gps_to_decimal empty value -> None", gps_to_decimal("", "N") is None)
    check("gps_to_decimal no dot -> None", gps_to_decimal("12345", "N") is None)
    check("gps_to_decimal N stays positive", approx(gps_to_decimal("3113.343286", "N"), 31.222388, tol=1e-3))
    check("gps_to_decimal S flips negative", approx(gps_to_decimal("3113.343286", "S"), -31.222388, tol=1e-3))

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
