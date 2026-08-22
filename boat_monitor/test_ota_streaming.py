#!/usr/bin/env python3
"""Host checks for heap-safe per-file OTA downloads."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ota import download_file_streaming


class StreamingClient:
    def __init__(self, payload, fail_once=False):
        self.payload = payload
        self.fail_once = fail_once
        self.calls = 0

    def download_to_file(self, url, path, timeout_s=120):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            Path(path + ".new").write_bytes(b"partial")
            raise OSError("temporary network failure")
        old = Path(path)
        if old.exists():
            old.rename(path + ".bak")
        Path(path).write_bytes(self.payload)
        return len(self.payload)


class BufferedClient:
    def __init__(self, payload):
        self.payload = payload

    def http_get(self, url, timeout_s=30):
        return self.payload.decode()


def main():
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            Path("module.py").write_text("old", encoding="utf-8")
            client = StreamingClient(b"new module", fail_once=True)
            nbytes = download_file_streaming(
                client,
                "https://example.invalid/module.py",
                "module.py",
                min_size=4,
            )
            assert nbytes == len(b"new module")
            assert Path("module.py").read_bytes() == b"new module"
            assert not Path("module.py.new").exists()
            assert not Path("module.py.bak").exists()
            assert client.calls == 2

            buffered = BufferedClient(b"fallback")
            nbytes = download_file_streaming(
                buffered,
                "https://example.invalid/fallback.py",
                "fallback.py",
            )
            assert nbytes == len(b"fallback")
            assert Path("fallback.py").read_text(encoding="utf-8") == "fallback"
        finally:
            os.chdir(original_cwd)

    print("OTA streaming tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
