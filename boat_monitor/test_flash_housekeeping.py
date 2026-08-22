#!/usr/bin/env python3
"""Host checks for bounded diagnostics and OTA artifact cleanup."""

import os
import tempfile
from pathlib import Path

import diag_log
import ota_health


def main():
    original_cwd = os.getcwd()
    original_path = diag_log.LOG_PATH
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        diag_log.LOG_PATH = "boat_diag.log"
        try:
            Path("boat_diag.log").write_bytes(b"x" * (diag_log.MAX_BYTES + 5000))
            removed_size = diag_log.trim_if_oversize()
            assert removed_size > diag_log.MAX_BYTES
            assert Path("boat_diag.log").stat().st_size < 200

            Path("module.py.bak").write_text("old")
            Path("module.py.new").write_text("partial")
            Path("ota_release.bmota").write_text("bundle")
            removed = ota_health.reclaim_stale_ota_flash()
            assert "module.py.bak" in removed
            assert "module.py.new" in removed
            assert "ota_release.bmota" in removed
            assert not Path("module.py.bak").exists()
            assert not Path("module.py.new").exists()
        finally:
            diag_log.LOG_PATH = original_path
            os.chdir(original_cwd)
    print("flash housekeeping tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
