#!/usr/bin/env python3
"""Static guard for acknowledged Apps Script command consumption."""

from pathlib import Path


def main():
    source = (
        Path(__file__).resolve().parent / "apps_script" / "Code.gs"
    ).read_text(encoding="utf-8")
    assert "var RECEIVER_VERSION = 7;" in source
    assert "return jsonOutput_(result);" in source
    json_output = source.split("function jsonOutput_(body)", 1)[1].split(
        "function handleDashboardGet_", 1
    )[0]
    assert "HtmlService.createHtmlOutput(text)" in json_output
    assert ".createTextOutput(" not in json_output
    assert ".replace(/&/g, '\\\\u0026')" in json_output
    assert ".replace(/</g, '\\\\u003c')" in json_output
    assert ".replace(/>/g, '\\\\u003e')" in json_output
    assert "body.consume_commands === true" in source
    assert "legacyResponseCapable" in source
    assert "uplink === 'cellular'" in source
    assert "uplink === 'cellular_control_sync'" in source
    assert "readConfigCommands_(deviceId, consumeCommands)" in source
    command_reader = source.split(
        "function readConfigCommands_(deviceId, consumeCommands)", 1
    )[1]
    assert "if (consumeCommands && truthy_(value))" in command_reader
    assert "if (consumeCommands) {" in command_reader
    print("Apps Script command acknowledgement guards OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
