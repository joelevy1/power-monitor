#!/usr/bin/env python3
"""Host-side tests for wifi_networks.parse_wifi_networks_text."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("wifi_networks", ROOT / "wifi_networks.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parse_pipe():
    text = "# comment\nSeattle Boat|secret1\nHome|pass two\n"
    assert mod.parse_wifi_networks_text(text) == [
        ("Seattle Boat", "secret1"),
        ("Home", "pass two"),
    ]


def test_parse_empty():
    assert mod.parse_wifi_networks_text("") == []
    assert mod.parse_wifi_networks_text("badline") == []


if __name__ == "__main__":
    test_parse_pipe()
    test_parse_empty()
    print("wifi_networks tests OK")
