"""
Boat Monitor P2 - GPS bench test (run directly in Thonny).

Turns the modem's GPS on, polls for a fix with live "still searching..."
progress every few seconds (instead of gps.py's Gps.read() staying silent
for its whole timeout), and reports either a lat/lon fix with a clickable
Google Maps link, or a clear "no fix" with likely reasons.

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
POLL_INTERVAL_S = 5  # how often to send AT+CGPSINFO
PROGRESS_EVERY_S = 5  # how often to print "still searching..."


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

    last_progress = [0]  # mutable cell so the nested function can update it

    def on_progress(elapsed_s, raw):
        if elapsed_s - last_progress[0] < PROGRESS_EVERY_S:
            return
        last_progress[0] = elapsed_s
        print("  still searching... (%.0fs elapsed) raw: %s" % (elapsed_s, raw.strip() or "(no response)"))

    try:
        fix = gps.read(timeout_s=TOTAL_TIMEOUT_S, poll_interval_s=POLL_INTERVAL_S, on_progress=on_progress)
        print()
        if fix["ok"]:
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
