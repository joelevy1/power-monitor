"""Unit tests for remote_telemetry throttle (runs on PC)."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import remote_telemetry as rt  # noqa: E402


def run():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp) / "telemetry_throttle.json"
        rt.STATE_PATH = str(state)

        def check(name, cond):
            print("[%s] %s" % ("PASS" if cond else "FAIL", name))
            if not cond:
                failures.append(name)

        check("first upload allowed", rt.should_upload("auto_log_degraded", 600))
        rt.mark_uploaded("auto_log_degraded")
        check("second immediate blocked", not rt.should_upload("auto_log_degraded", 600))
        state.write_text(json.dumps({"auto_log_degraded": 0}))
        check("old timestamp allows", rt.should_upload("auto_log_degraded", 0))

    return failures


if __name__ == "__main__":
    fails = run()
    sys.exit(1 if fails else 0)
