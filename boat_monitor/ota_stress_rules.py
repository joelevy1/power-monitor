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
MAX_STRESS_BUNDLE_BYTES = 0  # no bundle during stress

# Round fails if device stays below min_fw with no boot_start (flash backoff trap).
BOOT_START_TIMEOUT_S = 1200

# After boot_ota outcome=success, Power_Log may lag reboot by several log cycles.
POST_OTA_POWER_LOG_GRACE_S = 900

# Dock / standby (switch+key off): ~5 min log interval + OTA reboot time.
DOCK_ROUND_TIMEOUT_S = 3600

# Sheet keys that must be empty before stress / after ship (one-shot storms).
STALE_SHEET_KEYS = (
    "force_ota",
    "cmd_ota",
    "boat-p2:cmd_ota",
    "cmd_clear_pending_ota",
    "ota_action",
)

# Keys applied before each stress pass to clear device-side traps.
STRESS_RECOVERY_KEYS = (
    ("clear_ota_degraded", "1", "ota_stress_rules: allow boot OTA"),
    ("clear_boot_ota_backoff", "1", "ota_stress_rules: clear flash backoff"),
    ("auto_ota_on_boot", "1", "ota_stress_rules: boot OTA enabled"),
)

# Dock / standby profile (switch+key off): Wi-Fi-first logging and boot OTA.
DOCK_STRESS_KEYS = (
    ("boot_ota_prefer_wifi", "1", "ota_stress_rules: dock Wi-Fi-first OTA"),
    ("boat-p2:boot_ota_prefer_wifi", "1", "ota_stress_rules: dock Wi-Fi-first OTA"),
    ("dock_mode", "home", "ota_stress_rules: dock standby profile"),
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
