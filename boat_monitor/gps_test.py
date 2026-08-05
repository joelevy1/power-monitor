"""
Boat Monitor P2 - GPS bench test (run directly in Thonny).

Turns the modem's GPS on, polls for a fix with live "still searching..."
progress every few seconds, and reports either a lat/lon fix with a
clickable Google Maps link, or a clear "no fix" with likely reasons.

Deliberately self-contained: calls Gps.read(timeout_s, poll_interval_s)
repeatedly in short CHUNK_TIMEOUT_S-long chunks instead of depending on
any newer gps.py feature, so this script works standalone even if it's
copy-pasted directly into Thonny ahead of an OTA update -- confirmed on
real hardware that running this against an OLDER gps.py already on the
device (from before Gps.read() gained an on_progress parameter) raised
"TypeError: unexpected keyword argument 'on_progress'" when this script
first tried to pass it. Gps.on()/off()/read(timeout_s, poll_interval_s)
has existed since gps.py was first created, so this sticks to only that.

Does NOT touch cellular data (no AT+NETOPEN/AT+HTTP*) -- GPS uses the
modem's own separate AT+CGPS/AT+CGPSINFO commands, so this is safe to run
on its own without opening (or disturbing) a cellular data session.

Usage: open this file in Thonny (or paste it in) and press Run. Ctrl-C
(or Thonny's Stop button) cancels early -- GPS is turned off in a
finally block either way, so it never gets left running.

Bench notes:
- Needs a clear view of the sky. Will NOT get a fix indoors, under a hard
  top/cabin roof, or with only a cellular antenna connected -- the SIM7600
  needs its own GPS antenna, separate from the cellular one.
- First fix ("cold start") commonly takes anywhere from ~30 seconds to a
  few minutes; this defaults to a 3-minute window before giving up.
"""

import time

from gps import Gps

TOTAL_TIMEOUT_S = 180  # give up after this long with no fix
CHUNK_TIMEOUT_S = 5  # each Gps.read() call tries for this long before returning
POLL_INTERVAL_S = 1  # how often Gps.read() sends AT+CGPSINFO within one chunk


def maps_link(lat, lon):
    return "https://www.google.com/maps?q=%.7f,%.7f" % (lat, lon)


def main():
    print("Boat Monitor - GPS test")
    print("Turning GPS on (AT+CGPS=1,1)...")

    gps = Gps()
    if not gps.on():
        print("FAILED: GPS did not start (AT+CGPS=1,1 did not return OK)")
        print("Check modem power/wiring -- see cellular_test.py to confirm the modem itself responds.")
        return

    print("GPS on. Waiting for a fix (up to %ds) -- Ctrl-C to stop early." % TOTAL_TIMEOUT_S)
    print("Needs a clear view of the sky -- will not work indoors or under a hard top/cabin roof.")
    print("First fix can take ~30 seconds to a few minutes.")
    print()

    start = time.ticks_ms()
    fix = None

    try:
        while time.ticks_diff(time.ticks_ms(), start) < TOTAL_TIMEOUT_S * 1000:
            result = gps.read(timeout_s=CHUNK_TIMEOUT_S, poll_interval_s=POLL_INTERVAL_S)
            if result["ok"]:
                fix = result
                break

            elapsed = time.ticks_diff(time.ticks_ms(), start) / 1000
            print(
                "  still searching... (%.0fs elapsed) raw: %s"
                % (elapsed, (result.get("raw") or "").strip() or "(no response)")
            )

        print()
        if fix:
            print("FIX ACQUIRED")
            print("  Lat:  %.7f" % fix["lat"])
            print("  Lon:  %.7f" % fix["lon"])
            print("  Raw:  %s" % fix["raw"])
            print("  Maps: %s" % maps_link(fix["lat"], fix["lon"]))
        else:
            print("NO FIX within %ds." % TOTAL_TIMEOUT_S)
            print("Likely reasons, most common first:")
            print("  - No dedicated GPS antenna connected (a cellular-only antenna will")
            print("    NOT receive GPS -- SIM7600 needs a separate GPS antenna).")
            print("  - No clear view of the sky (indoors, under a hard top/cabin roof, etc).")
            print("  - Cold start still in progress -- try again, or increase TOTAL_TIMEOUT_S")
            print("    at the top of this file for a longer window.")
    except KeyboardInterrupt:
        print()
        print("Stopped by user.")
    finally:
        print("Turning GPS off (AT+CGPS=0)...")
        gps.off()
        print("Done.")


if __name__ == "__main__":
    main()
