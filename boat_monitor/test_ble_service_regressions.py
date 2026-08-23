#!/usr/bin/env python3
"""Static host guards for BLE behavior that depends on MicroPython hardware."""

from pathlib import Path


def main():
    source = (Path(__file__).resolve().parent / "ble_service.py").read_text(
        encoding="utf-8"
    )
    update = source.split("def update_status", 1)[1].split(
        "def handle_command", 1
    )[0]
    assert "for conn in tuple(self.connections)" in update
    assert "self.connections.discard(conn)" in update
    assert update.index("self.connections.discard(conn)") < update.index(
        "self.advertise()"
    )

    log_command = source.split('elif cmd in ("log", "log_now"):', 1)[1].split(
        'elif cmd in ("diag", "upload_diag"):', 1
    )[0]
    assert "resilience.set_service_hook(" in log_command
    assert "lambda: self.update_status(sensors=False)" in log_command
    assert "resilience.set_service_hook(None)" in log_command

    print("BLE service regression guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
