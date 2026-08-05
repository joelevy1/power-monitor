"""
Pure-Python unit test for auto_log.py's schedule decision logic -- no
MicroPython/hardware dependency (auto_log.py makes no hardware/network
calls at all). Run directly with:

    python3 boat_monitor/test_auto_log_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auto_log import (  # noqa: E402
    ENGINE_ON_MODE,
    INTERVAL_ENGINE_OFF_S,
    INTERVAL_ENGINE_ON_S,
    interval_for_mode,
    should_log_now,
)


def run():
    failures = []

    def check(name, condition):
        status = "PASS" if condition else "FAIL"
        print("[%s] %s" % (status, name))
        if not condition:
            failures.append(name)

    # interval_for_mode(): engine-on gets the short interval, everything
    # else gets the long one.
    check("interval_for_mode key_on is the short interval", interval_for_mode("key_on") == INTERVAL_ENGINE_ON_S)
    for other_mode in ("docked_off", "switch_on_key_off", "bilge_active", "float_alert", "unknown"):
        check(
            "interval_for_mode %s is the long interval" % other_mode,
            interval_for_mode(other_mode) == INTERVAL_ENGINE_OFF_S,
        )
    # <=, not <: INTERVAL_ENGINE_OFF_S is temporarily set equal to
    # INTERVAL_ENGINE_ON_S for a multi-day standalone battery-life test
    # (see auto_log.py) -- this only asserts engine-on is never LONGER,
    # which stays true whether they're temporarily equal or (normally)
    # engine-off is the longer one.
    check("engine-on interval is never longer than engine-off", INTERVAL_ENGINE_ON_S <= INTERVAL_ENGINE_OFF_S)

    # should_log_now(): the ordinary "enough time has passed" case, for
    # both engine-on and engine-off intervals.
    check(
        "key_on: not due before the short interval elapses",
        should_log_now("key_on", INTERVAL_ENGINE_ON_S - 1, last_mode="key_on") is False,
    )
    check(
        "key_on: due once the short interval elapses",
        should_log_now("key_on", INTERVAL_ENGINE_ON_S, last_mode="key_on") is True,
    )
    check(
        "docked_off: not due before the long interval elapses",
        should_log_now("docked_off", INTERVAL_ENGINE_OFF_S - 1, last_mode="docked_off") is False,
    )
    check(
        "docked_off: due once the long interval elapses",
        should_log_now("docked_off", INTERVAL_ENGINE_OFF_S, last_mode="docked_off") is True,
    )

    # The "log immediately on engine start" behavior -- the whole point of
    # "very frequent when engine is on, much less frequent when off": a
    # transition INTO key_on shouldn't have to wait out whatever's left of
    # the previous (longer) docked interval.
    check(
        "engine just started: logs immediately even with 1s elapsed",
        should_log_now("key_on", 1, last_mode="docked_off") is True,
    )
    check(
        "engine just started from switch_on_key_off: logs immediately",
        should_log_now("key_on", 0, last_mode="switch_on_key_off") is True,
    )

    # No forced log on the REVERSE transition (engine just stopped) --
    # that's intentionally not time-sensitive; it picks up on its own next
    # scheduled (now-longer) interval instead.
    check(
        "engine just stopped: not forced, follows the normal long interval",
        should_log_now("docked_off", 1, last_mode="key_on") is False,
    )
    check(
        "engine just stopped: still fires once the long interval actually elapses",
        should_log_now("docked_off", INTERVAL_ENGINE_OFF_S, last_mode="key_on") is True,
    )

    # First tick since boot -- no prior mode recorded (last_mode=None).
    # Should NOT force an immediate log just because there's no history,
    # even if already in key_on mode -- avoids an auto-log firing on
    # every single reboot regardless of how the engine got to that state.
    check(
        "first tick since boot in key_on: not forced without prior mode",
        should_log_now("key_on", 1, last_mode=None) is False,
    )
    check(
        "first tick since boot: still follows the normal interval",
        should_log_now("key_on", INTERVAL_ENGINE_ON_S, last_mode=None) is True,
    )

    # Staying in the same mode across ticks should never force a log
    # early -- only an actual transition into key_on does.
    check(
        "staying in key_on across ticks doesn't force an early log",
        should_log_now("key_on", 1, last_mode="key_on") is False,
    )

    print()
    if failures:
        print("FAILED: %d check(s): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
