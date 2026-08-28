"""Host regression for transient Windows COM-port retries."""

import subprocess
from pathlib import Path

import usb_recovery_push


def main():
    calls = []
    sleeps = []
    original_call = subprocess.check_call
    original_sleep = usb_recovery_push.time.sleep

    def flaky_call(cmd):
        calls.append(cmd)
        if len(calls) < 3:
            raise subprocess.CalledProcessError(1, cmd)

    subprocess.check_call = flaky_call
    usb_recovery_push.time.sleep = sleeps.append
    try:
        usb_recovery_push._run(
            ["python", "-m", "mpremote"],
            ["connect", "COM7", "cp", "main.py", ":main.py"],
            "copy main.py",
        )
    finally:
        subprocess.check_call = original_call
        usb_recovery_push.time.sleep = original_sleep

    assert len(calls) == 3
    assert sleeps == [2, 4]
    source = Path(usb_recovery_push.__file__).read_text(encoding="utf-8")
    assert '_mp_args(port, "reset")' in source
    assert 'exec", "import machine; machine.soft_reset()' not in source
    print("USB recovery transient retry tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
