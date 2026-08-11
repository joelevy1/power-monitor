#!/usr/bin/env python3
"""Gate firmware releases: local consistency and optional GitHub master check.

Exit 0 only when it is safe to set min_fw_version on the sheet.

  python3 validate_release.py
  python3 validate_release.py --check-github
  python3 validate_release.py --min-fw 1.1.44   # fail if > shipped manifest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "ota_manifest.json"
VERSION_PATH = ROOT / "version.py"
MANIFEST_URL = (
    "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json"
)
MANIFEST_API_URL = (
    "https://api.github.com/repos/joelevy1/power-monitor/contents/"
    "boat_monitor/ota_manifest.json?ref=master"
)


def _read_local_version():
    text = VERSION_PATH.read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        raise SystemExit("validate_release: could not parse VERSION from version.py")
    return m.group(1).strip()


def _read_manifest_version(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data.get("version", "")).strip()


def _parse_version(text):
    parts = []
    for piece in str(text or "").strip().split("."):
        try:
            parts.append(int(piece))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _version_lt(a, b):
    return _parse_version(a) < _parse_version(b)


MANIFEST_BLOCKLIST = (
    "bench_",
    "test_",
    "pico_import_check",
    "ota_stress_harness",
    "ota_stress_analyze",
    "remote_stress",
    "apps_script_test",
    "sheet_tail_report",
    "validate_release",
    "apply_ship_config",
    "sheets_config_",
    "sheets_bootstrap",
)


def _manifest_file_errors(data):
    errs = []
    files = data.get("files") or []
    paths = []
    for entry in files:
        path = str(entry.get("path") or "").strip()
        if not path:
            errs.append("manifest entry missing path")
            continue
        paths.append(path)
        for bad in MANIFEST_BLOCKLIST:
            if bad in path:
                errs.append("manifest must not ship %s (matches %s)" % (path, bad))
    if len(paths) != len(set(paths)):
        errs.append("duplicate paths in manifest")
    return errs, files


def _manifest_has_version_py(data):
    for entry in data.get("files") or []:
        if entry.get("path") == "version.py":
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate OTA release before sheet min_fw bump")
    parser.add_argument(
        "--check-github",
        action="store_true",
        help="Require GitHub master ota_manifest.json version to match local",
    )
    parser.add_argument(
        "--min-fw",
        metavar="X.Y.Z",
        help="Fail if this min_fw_version is newer than local manifest (sheet safety)",
    )
    args = parser.parse_args(argv)

    errors = []

    if not MANIFEST_PATH.is_file():
        errors.append("missing ota_manifest.json")
    if not VERSION_PATH.is_file():
        errors.append("missing version.py")

    if errors:
        for e in errors:
            print("FAIL:", e, file=sys.stderr)
        return 1

    local_ver = _read_local_version()
    manifest_ver = _read_manifest_version(MANIFEST_PATH)

    if local_ver != manifest_ver:
        print(
            "FAIL: version.py VERSION=%s != ota_manifest.json version=%s"
            % (local_ver, manifest_ver),
            file=sys.stderr,
        )
        return 1

    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not _manifest_has_version_py(data):
        print("FAIL: ota_manifest.json does not include version.py", file=sys.stderr)
        return 1

    m_errs, files = _manifest_file_errors(data)
    for e in m_errs:
        print("FAIL:", e, file=sys.stderr)
    if m_errs:
        return 1

    total_bytes = 0
    for entry in files:
        p = ROOT / entry.get("path", "")
        if p.is_file():
            total_bytes += p.stat().st_size
    print("OK: manifest %d runtime files (~%d KB source)" % (len(files), total_bytes // 1024))

    bundle = data.get("bundle")
    if bundle:
        bpath = ROOT / str(bundle.get("path") or "ota_release.bmota")
        if not bpath.is_file():
            print(
                "FAIL: manifest bundle.path missing on disk: %s (run build_ota_bundle.py)"
                % bpath.name,
                file=sys.stderr,
            )
            return 1
        size = bpath.stat().st_size
        want = int(bundle.get("size") or 0)
        if want and size != want:
            print("FAIL: bundle size on disk %d != manifest %d" % (size, want), file=sys.stderr)
            return 1
        print("OK: bundle %s (%d bytes)" % (bpath.name, size))

    if args.min_fw and _version_lt(manifest_ver, args.min_fw):
        print(
            "FAIL: min_fw_version %s > shipped manifest %s (merge to master first)"
            % (args.min_fw, manifest_ver),
            file=sys.stderr,
        )
        return 1

    if args.check_github:
        remote_ver = ""
        try:
            req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "validate_release"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                remote = json.loads(resp.read().decode("utf-8"))
            remote_ver = str(remote.get("version", "")).strip()
        except Exception as exc:
            print("WARN: raw manifest fetch failed:", exc, file=sys.stderr)
        if remote_ver != manifest_ver:
            api_ver = ""
            try:
                req = urllib.request.Request(
                    MANIFEST_API_URL,
                    headers={
                        "User-Agent": "validate_release",
                        "Accept": "application/vnd.github.raw",
                    },
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    remote = json.loads(resp.read().decode("utf-8"))
                api_ver = str(remote.get("version", "")).strip()
            except Exception as exc:
                print("WARN: GitHub API manifest fetch failed:", exc, file=sys.stderr)
            if api_ver == manifest_ver and remote_ver != manifest_ver:
                print(
                    "FAIL: raw CDN manifest=%s but GitHub API=%s (Pico uses raw; wait for CDN)"
                    % (remote_ver or "?", api_ver),
                    file=sys.stderr,
                )
            else:
                print(
                    "FAIL: GitHub master manifest version=%s != local %s (push/merge master first)"
                    % (remote_ver or api_ver or "?", manifest_ver),
                    file=sys.stderr,
                )
            return 1

    print("OK: release %s (manifest + version.py)" % local_ver)
    if args.check_github:
        print("OK: GitHub raw master manifest matches")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
