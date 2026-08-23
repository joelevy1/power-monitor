#!/usr/bin/env python3
"""Regression guards for escaping boot OTA memory failures into normal service."""

from pathlib import Path


def main():
    source = (Path(__file__).resolve().parent / "main.py").read_text(
        encoding="utf-8"
    )
    assert "pause_after_ota_memory_failure" in source
    assert "boot OTA Wi-Fi ENOMEM" not in source
    assert "if not ota_memory_failure:" in source
    flush = source.split("if not ota_memory_failure:", 1)[1].split(
        "except Exception as exc:", 1
    )[0]
    assert "flush_ota_events_uplink" in flush
    print("OTA fail-open recovery guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
