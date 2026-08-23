#!/usr/bin/env python3
"""Regression guards for escaping boot OTA memory failures into normal service."""

from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    source = (root / "main.py").read_text(
        encoding="utf-8"
    )
    assert "pause_after_ota_memory_failure" in source
    assert "boot OTA Wi-Fi ENOMEM" not in source
    assert "if not ota_memory_failure:" in source
    flush = source.split("if not ota_memory_failure:", 1)[1].split(
        "except Exception as exc:", 1
    )[0]
    assert "flush_ota_events_uplink" in flush
    ota_source = (root / "ota.py").read_text(encoding="utf-8")
    reboot_success = ota_source.split("if reboot:", 1)[1].split(
        "return True", 1
    )[0]
    assert "record_boot_ota_result(" in reboot_success
    assert 'emit=False' in reboot_success
    assert reboot_success.index("clear_pending_ota()") < reboot_success.index(
        "machine.reset()"
    )
    print("OTA fail-open recovery guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
