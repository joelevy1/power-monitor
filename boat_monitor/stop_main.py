"""
Disable main.py auto-run so Thonny REPL stays up on the bench.

Run once in Thonny (F5) as soon as you connect — before the next reboot:

    import stop_main
    stop_main.run()

Then press Ctrl+D (soft reboot). You should get an idle REPL with no
standby_monitor / ble_service / boot OTA loop.

To restore field behavior:

    import stop_main
    stop_main.restore()
    # then Ctrl+D
"""

import os

BACKUP_NAME = "main.py.autorun"
STUB = """# Bench: main auto-run disabled (stop_main.py)
# Restore with: import stop_main; stop_main.restore()
import time
while True:
    time.sleep(3600)
"""


def run():
    try:
        st = os.stat("main.py")
        # Already our stub?
        with open("main.py", "r") as f:
            if "stop_main.py" in f.read():
                print("main.py already bench-disabled")
                return True
    except OSError:
        print("No main.py on filesystem")
        return False

    try:
        os.rename("main.py", BACKUP_NAME)
        print("OK: renamed main.py ->", BACKUP_NAME)
    except OSError as exc:
        print("Rename failed:", exc)
        print("Trying overwrite stub...")
    try:
        with open("main.py", "w") as f:
            f.write(STUB)
        print("OK: main.py is now a sleep stub")
    except Exception as exc:
        print("FAILED:", exc)
        return False
    print("Press Ctrl+D (soft reboot) — REPL should stay idle.")
    return True


def restore():
    try:
        os.remove("main.py")
    except OSError:
        pass
    try:
        os.rename(BACKUP_NAME, "main.py")
        print("OK: restored", BACKUP_NAME, "-> main.py")
        print("Press Ctrl+D to boot normally.")
        return True
    except OSError as exc:
        print("Restore failed:", exc, "- is", BACKUP_NAME, "present?")
        return False


if __name__ == "__main__":
    run()
