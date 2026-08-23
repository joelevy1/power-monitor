"""
OTA stress campaign rules — shared constants and preflight helpers.

These guardrails prevent the recurring failure modes from the boat-p2 cellular
stress runs: ENOMEM from multi-file manifests, flash backoff traps, force_ota
reboot storms, and USB recovery leaving auto_ota_on_boot disabled.

See OTA_STRESS_RULES.md for the human-readable policy.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Cellular boot OTA on Pico W: version-only manifest (~19 bytes) is the stress default.
MAX_STRESS_MANIFEST_FILES = 1
MAX_BOOTSTRAP_MANIFEST_FILES = 2
MAX_WIFI_FEATURE_MANIFEST_FILES = 8
MAX_STRESS_BUNDLE_BYTES = 0  # no bundle during stress

# Round fails if device stays below min_fw with no boot_start (flash backoff trap).
BOOT_START_TIMEOUT_S = 1200
# Winter dock logging is hourly. The device cannot learn about a Sheet target
# until its next scheduled POST, so allow one full interval plus 15m grace.
DOCK_BOOT_START_TIMEOUT_S = 4500

# After boot_ota outcome=success, Power_Log may lag reboot by several log cycles.
POST_OTA_POWER_LOG_GRACE_S = 900

# Dock / standby (switch+key off): ~5 min log interval + OTA reboot time.
DOCK_ROUND_TIMEOUT_S = 3600

# Reboot trap: many reboot_queued with no boot_start while min_fw is ahead of device.
REBOOT_TRAP_MIN_REBOOT_QUEUED = 3
WATCH_STATE_MAX_AGE_S = 120

# manifest_kind values allowed on GitHub master (Pico raw CDN).
MASTER_MANIFEST_KIND_STRESS = "stress"
MASTER_MANIFEST_KIND_BOOTSTRAP = "bootstrap"
MASTER_MANIFEST_KIND_WIFI_FEATURE = "wifi-feature"
MASTER_ALLOWED_MANIFEST_KINDS = (
    MASTER_MANIFEST_KIND_STRESS,
    MASTER_MANIFEST_KIND_BOOTSTRAP,
    MASTER_MANIFEST_KIND_WIFI_FEATURE,
)

# Sheet keys that must be empty before stress / after ship (one-shot storms).
STALE_SHEET_KEYS = (
    "force_ota",
    "cmd_ota",
    "cmd_ota_force",
    "boat-p2:cmd_ota",
    "boat-p2:cmd_ota_force",
    "cmd_clear_pending_ota",
    "ota_action",
)

# Keys applied before each stress pass to clear device-side traps.
STRESS_RECOVERY_KEYS = (
    ("clear_ota_degraded", "1", "ota_stress_rules: allow boot OTA"),
    ("clear_boot_ota_backoff", "1", "ota_stress_rules: clear flash backoff"),
    ("auto_ota_on_boot", "1", "ota_stress_rules: boot OTA enabled"),
)

# Dock / standby: Wi-Fi routine logs; cellular boot OTA (rare, heap-safe).
DOCK_STRESS_KEYS = (
    ("boot_ota_prefer_wifi", "0", "ota_stress_rules: dock cellular boot OTA"),
    ("boat-p2:boot_ota_prefer_wifi", "0", "ota_stress_rules: dock cellular boot OTA"),
    ("dock_mode", "home", "ota_stress_rules: dock Wi-Fi standby logs"),
    ("standby_prefer_wifi", "1", "ota_stress_rules: require dock Wi-Fi standby logs"),
    ("boat-p2:standby_prefer_wifi", "1", "ota_stress_rules: require dock Wi-Fi standby logs"),
)


def _truthy(value):
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")


def _parse_ver_tuple(text):
    parts = []
    for p in str(text or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    return tuple(parts)


def assert_version_only_manifest(manifest_path: Path | None = None) -> None:
    """Abort if manifest is not safe for cellular boot OTA stress."""
    path = manifest_path or (ROOT / "ota_manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files") or []
    if data.get("bundle"):
        raise SystemExit(
            "ota_stress_rules: manifest has bundle — use apply_recovery_manifest --version-only"
        )
    if len(files) > MAX_STRESS_MANIFEST_FILES:
        raise SystemExit(
            "ota_stress_rules: manifest has %d files (max %d for stress)"
            % (len(files), MAX_STRESS_MANIFEST_FILES)
        )
    paths = [str(e.get("path") or "") for e in files]
    if paths != ["version.py"]:
        raise SystemExit(
            "ota_stress_rules: stress manifest must be version.py only, got %s" % paths
        )


def read_config_map(sheets, spreadsheet_id):
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range="Config!A2:C")
        .execute()
        .get("values", [])
    )
    out = {}
    for row in rows:
        if row and row[0]:
            out[str(row[0]).strip()] = str(row[1]).strip() if len(row) > 1 else ""
    return out


def preflight_sheet(sheets, spreadsheet_id, note_prefix="ota_stress_rules", profile="underway"):
    """
    Normalize Config for a stress pass. Returns list of stale keys that were set.
    profile: 'underway' (cellular-first key on) or 'dock' (Wi-Fi-first standby).
    """
    from sheets_config_upsert import upsert_config_keys

    cfg = read_config_map(sheets, spreadsheet_id)
    stale = [k for k in STALE_SHEET_KEYS if _truthy(cfg.get(k))]
    rows = list(STRESS_RECOVERY_KEYS)
    if profile == "dock":
        rows.extend(DOCK_STRESS_KEYS)
    for key in STALE_SHEET_KEYS:
        rows.append((key, "", "%s: clear stale one-shot" % note_prefix))
    upsert_config_keys(sheets, spreadsheet_id, rows)
    return stale


def reset_v50_full(sheets, spreadsheet_id, note="ota_stress_rules: bank full baseline"):
    """Mark V50 bank 100% for mAh tracking (Pico applies on next successful log)."""
    from datetime import datetime, timezone
    from sheets_config_upsert import upsert_config_keys

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    upsert_config_keys(
        sheets,
        spreadsheet_id,
        [
            ("boat-p2:v50_full_at_utc", ts, note),
            ("boat-p2:v50_capacity_mah", "13400", "V50 rated capacity"),
        ],
    )
    print("OK: boat-p2:v50_full_at_utc =", ts)
    return ts


def preflight_sheet_or_exit(sheets, spreadsheet_id, profile="underway"):
    stale = preflight_sheet(sheets, spreadsheet_id, profile=profile)
    if stale:
        print(
            "WARN: cleared stale Config keys before stress:",
            ", ".join(stale),
            file=sys.stderr,
        )
    print("OK: sheet preflight (recovery keys + cleared one-shots)")


def device_ahead_of_repo(device_fw: str, repo_ver: str) -> bool:
    if not device_fw or not repo_ver:
        return False
    return _parse_ver_tuple(device_fw) > _parse_ver_tuple(repo_ver)


def _event_detail(row):
    return str(row[3]) if len(row) > 3 else ""


def count_reboot_queued(events, window=20):
    """Count ota_lifecycle reboot_queued rows in the tail of Events."""
    recent = list(events or [])[-window:]
    return sum(
        1
        for r in recent
        if len(r) > 2 and r[2] == "ota_lifecycle" and "reboot_queued" in _event_detail(r)
    )


def saw_boot_start(events, window=40):
    """True if any recent boot_start phase appears in Events."""
    recent = list(events or [])[-window:]
    for r in recent:
        if len(r) < 4:
            continue
        detail = _event_detail(r)
        if r[2] == "boot_ota" and "phase=boot_start" in detail:
            return True
        if r[2] == "ota_lifecycle" and "phase=boot_start" in detail:
            return True
    return False


def detect_reboot_trap(events, device_fw: str, target_fw: str, min_reboot_queued=None):
    """
    Return a human-readable trap reason when min_fw is ahead but device is not
    progressing (reboot_queued storm, no boot_start). Otherwise return None.
    """
    min_rq = REBOOT_TRAP_MIN_REBOOT_QUEUED if min_reboot_queued is None else min_reboot_queued
    if not device_fw or not target_fw:
        return None
    if _parse_ver_tuple(device_fw) >= _parse_ver_tuple(target_fw):
        return None
    rq = count_reboot_queued(events)
    if rq < min_rq:
        return None
    if saw_boot_start(events):
        return None
    return (
        "reboot_trap: reboot_queued x%d, no boot_start, device fw=%s < target=%s "
        "(flash backoff / multi-file ahead of device — USB patch-only)"
        % (rq, device_fw, target_fw)
    )


def manifest_kind(data) -> str:
    return str((data or {}).get("manifest_kind") or "").strip().lower()


def master_manifest_policy_errors(data, file_count: int | None = None) -> list[str]:
    """
    CI / pre-ship gate: master CDN manifest must be stress (1 file), bootstrap
    (2), or an explicitly Wi-Fi-only feature release (up to 8, version last).
    """
    files = (data or {}).get("files") or []
    n = file_count if file_count is not None else len(files)
    kind = manifest_kind(data)
    paths = [str(e.get("path") or "") for e in files]
    bundle = data.get("bundle")
    if bundle:
        if kind != MASTER_MANIFEST_KIND_WIFI_FEATURE:
            return ["bundle allowed only for explicit wifi-feature manifests"]
        if n < 2 or n > MAX_WIFI_FEATURE_MANIFEST_FILES:
            return [
                "bundled wifi-feature has %d files (expected 2..%d)"
                % (n, MAX_WIFI_FEATURE_MANIFEST_FILES)
            ]
        if not paths or paths[-1] != "version.py":
            return ["bundled wifi-feature must install version.py last"]
        if not bundle.get("url") or not bundle.get("size") or not bundle.get("sha256"):
            return ["bundled wifi-feature requires url, size, and sha256"]
        return []
    if kind == MASTER_MANIFEST_KIND_WIFI_FEATURE:
        if n < 2 or n > MAX_WIFI_FEATURE_MANIFEST_FILES:
            return [
                "wifi-feature manifest has %d files (expected 2..%d)"
                % (n, MAX_WIFI_FEATURE_MANIFEST_FILES)
            ]
        if not paths or paths[-1] != "version.py":
            return ["wifi-feature manifest must install version.py last, got %s" % paths]
        if len(set(paths)) != len(paths):
            return ["wifi-feature manifest contains duplicate paths"]
        return []
    if n <= 1:
        if kind and kind not in (MASTER_MANIFEST_KIND_STRESS, "version-only", ""):
            return [
                "manifest has 1 file but manifest_kind=%r (expected %r)"
                % (kind, MASTER_MANIFEST_KIND_STRESS)
            ]
        return []
    if n == 2:
        if kind != MASTER_MANIFEST_KIND_BOOTSTRAP:
            return [
                "manifest has 2 files but manifest_kind=%r (expected %r for master)"
                % (kind, MASTER_MANIFEST_KIND_BOOTSTRAP)
            ]
        sorted_paths = sorted(paths)
        want = ["remote_boot_config.py", "version.py"]
        if sorted_paths != want:
            return [
                "bootstrap manifest must be version.py + remote_boot_config.py, got %s"
                % sorted_paths
            ]
        return []
    return [
        "manifest has %d files with kind=%r — multi-file master releases must "
        "be explicit wifi-feature manifests (version.py last); otherwise use USB."
        % (n, kind)
    ]


def assert_master_manifest_policy(manifest_path: Path | None = None) -> None:
    path = manifest_path or (ROOT / "ota_manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    errs = master_manifest_policy_errors(data)
    if errs:
        raise SystemExit("ota_stress_rules: " + errs[0])


def pause_min_fw_to_device(sheets, spreadsheet_id, device_fw: str, reason: str):
    """Emergency brake: set min_fw to device fw so reboot storms stop."""
    from sheets_config_upsert import upsert_config_keys

    if not device_fw:
        print("WARN: pause_min_fw skipped — no device fw", file=sys.stderr)
        return False
    rows = [
        ("min_fw_version", device_fw, "ota_stress_rules: PAUSE %s" % reason[:80]),
    ]
    for key in STALE_SHEET_KEYS:
        rows.append((key, "", "ota_stress_rules: clear one-shot on pause"))
    rows.extend(STRESS_RECOVERY_KEYS)
    upsert_config_keys(sheets, spreadsheet_id, rows)
    print("PAUSE: min_fw_version=%s (%s)" % (device_fw, reason))
    return True


def assert_watch_running(state_path: Path | None = None, max_age_s: int | None = None) -> None:
    """Stress harness requires boat_p2_watch polling the sheet."""
    import time

    repo = ROOT.parent
    path = state_path or (repo / "boat_p2_watch_state.json")
    age_limit = WATCH_STATE_MAX_AGE_S if max_age_s is None else max_age_s
    if not path.is_file():
        raise SystemExit(
            "ota_stress_rules: boat_p2_watch not running (missing %s). "
            "Start: python3 boat_monitor/boat_p2_watch.py"
            % path.name
        )
    age = time.time() - path.stat().st_mtime
    if age > age_limit:
        raise SystemExit(
            "ota_stress_rules: boat_p2_watch stale (last poll %.0fs ago, max %ds)"
            % (age, age_limit)
        )


def preflight_stress_campaign(
    sheets,
    spreadsheet_id,
    *,
    profile="underway",
    device_fw: str = "",
    repo_ver: str = "",
    require_watch: bool = True,
    events=None,
):
    """
    Full preflight before stress ship or min_fw bump. Raises SystemExit on violation.
    Returns list of stale keys cleared from sheet.
    """
    assert_version_only_manifest()
    assert_master_manifest_policy()
    if require_watch:
        assert_watch_running()
    if device_fw and repo_ver and device_ahead_of_repo(device_fw, repo_ver):
        raise SystemExit(
            "ota_stress_rules: device fw %s ahead of repo %s — sync repo or USB recovery first"
            % (device_fw, repo_ver)
        )
    if events and device_fw and repo_ver:
        trap = detect_reboot_trap(events, device_fw, repo_ver)
        if trap:
            pause_min_fw_to_device(sheets, spreadsheet_id, device_fw, trap)
            raise SystemExit("ota_stress_rules: " + trap)
    return preflight_sheet(sheets, spreadsheet_id, profile=profile)
