"""Host tests for ota_state manifest ordering and verify helpers."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ota_state  # noqa: E402


class TestSortManifestFiles(unittest.TestCase):
    def test_main_and_version_last(self):
        files = [
            {"path": "main.py"},
            {"path": "gpio_probe.py"},
            {"path": "version.py"},
            {"path": "ota.py"},
        ]
        ordered = ota_state.sort_manifest_files(files)
        paths = [e["path"] for e in ordered]
        self.assertEqual(paths[-2:], ["version.py", "main.py"])
        self.assertEqual(paths[:2], ["gpio_probe.py", "ota.py"])


class TestVerifyManifest(unittest.TestCase):
    def test_missing_file_fails(self):
        manifest = {
            "version": "9.9.9",
            "files": [{"path": "only.py", "min_size": 1}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with open("version.py", "w") as f:
                    f.write('VERSION = "9.9.9"\n')
                self.assertFalse(ota_state.verify_manifest(manifest))
            finally:
                os.chdir(cwd)

    def test_complete_manifest_passes(self):
        manifest = {
            "version": "9.9.9",
            "files": [{"path": "only.py", "min_size": 1}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with open("version.py", "w") as f:
                    f.write('VERSION = "9.9.9"\n')
                with open("only.py", "w") as f:
                    f.write("x")
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "version", os.path.join(tmp, "version.py")
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                with mock.patch.dict(sys.modules, {"version": mod}):
                    self.assertTrue(ota_state.verify_manifest(manifest))
            finally:
                os.chdir(cwd)


class TestPending(unittest.TestCase):
    def test_begin_and_verify_pending_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "ota_pending.json"
            with mock.patch.object(ota_state, "PENDING_PATH", str(pending)):
                ota_state.begin("1.0.0", ["a.py", "b.py"])
                ota_state.mark_done("a.py")
                ok, detail = ota_state.verify_pending()
                self.assertFalse(ok)
                self.assertIn("b.py", detail)


if __name__ == "__main__":
    unittest.main()
