#!/usr/bin/env python3
"""Write slim ota_manifest.json for remote recovery or feature-pack OTA."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FULL = ROOT / "ota_manifest.full.json"
OUT = ROOT / "ota_manifest.json"
RAW = "https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/"

RECOVERY_PATHS = (
    "version.py",
    "main.py",
    "ota.py",
    "ota_reboot.py",
    "remote_boot_config.py",
    "remote_control.py",
    "ota_events_flush.py",
    "ota_lifecycle.py",
    "ota_telemetry.py",
)

FEATURE_PACK_PATHS = RECOVERY_PATHS + (
    "ota_trace.py",
    "status_led.py",
    "ble_service.py",
    "sheets_log.py",
    "cellular.py",
    "diag_log.py",
    "ota_bundle.py",
)

RAM_FIX_PATHS = (
    "ota_bundle.py",
    "ota_diag.py",
    "remote_boot_config.py",
    "ota_reboot.py",
    "ota_events_flush.py",
    "ota_lifecycle.py",
    "ota_telemetry.py",
    "ota_trace.py",
    "ota.py",
    "main.py",
    "cellular.py",
    "version.py",
)

VERSION_ONLY_PATHS = ("version.py",)

BOOTSTRAP_RULES_PATHS = (
    "version.py",
    "remote_boot_config.py",
)

DOCK_FIX_PATHS = (
    "version.py",
    "main.py",
    "standby_monitor.py",
    "ota_health.py",
    "remote_boot_config.py",
)

V50_TRACK_PATHS = (
    "version.py",
    "v50_energy.py",
    "ble_service.py",
)

WINTER_HARDENING_PATHS = (
    "resilience.py",
    "cellular.py",
    "gps.py",
    "wifi_uplink.py",
    "remote_boot_config.py",
    "version.py",
)

STANDBY_WIFI_FIX_PATHS = (
    "boat_status.py",
    "log_session.py",
    "wifi_uplink.py",
    "ble_service.py",
    "standby_monitor.py",
    "main.py",
    "version.py",
)

OTA_STREAM_FIX_PATHS = (
    "ota.py",
    "version.py",
)

WIFI_RESPONSE_FIX_PATHS = (
    "wifi_uplink.py",
    "version.py",
)

WIFI_SCAN_TELEMETRY_PATHS = (
    "wifi_uplink.py",
    "sheets_log.py",
    "version.py",
)

OPTIONAL_TELEMETRY_DEDUPE_PATHS = (
    "telemetry_dedupe.py",
    "sheets_log.py",
    "ota_capability.py",
    "version.py",
)

WIFI_AUTH_OTA_GATE_PATHS = (
    "telemetry_dedupe.py",
    "sheets_log.py",
    "ota_capability.py",
    "wifi_uplink.py",
    "remote_boot_config.py",
    "ota_reboot.py",
    "remote_control.py",
    "version.py",
)

PERSISTENT_DOCK_WIFI_PATHS = (
    "wifi_uplink.py",
    "sheets_log.py",
    "log_session.py",
    "remote_boot_config.py",
    "version.py",
)

BLE_TRANSITION_FIX_PATHS = (
    "standby_monitor.py",
    "version.py",
)

FLASH_HOUSEKEEPING_PATHS = (
    "diag_log.py",
    "ota_health.py",
    "version.py",
)

WINTER_FINAL_FIX_PATHS = (
    "wifi_uplink.py",
    "boat_status.py",
    "version.py",
)

ONE_TLS_WIFI_PATHS = (
    "wifi_uplink.py",
    "sheets_log.py",
    "log_session.py",
    "remote_boot_config.py",
    "standby_monitor.py",
    "version.py",
)

BLE_COMMAND_TRANSITION_PATHS = (
    "ble_service.py",
    "version.py",
)

WIFI_TRANSPORT_BOOTSTRAP_PATHS = (
    "wifi_uplink.py",
    "version.py",
)

BLE_LOG_HANDOFF_PATHS = (
    "main.py",
    "ble_service.py",
    "version.py",
)

BLE_SENSOR_CACHE_PATHS = (
    "boat_status.py",
    "version.py",
)

CLEAN_STANDBY_BOOT_PATHS = (
    "main.py",
    "version.py",
)

WIFI_TELEMETRY_PATHS = (
    "wifi_uplink.py",
    "sheets_log.py",
    "version.py",
)

HEADLESS_DOCK_LOG_PATHS = (
    "main.py",
    "standby_monitor.py",
    "version.py",
)

COMMAND_ACK_PATHS = (
    "sheets_log.py",
    "remote_boot_config.py",
    "version.py",
)

CUMULATIVE_DOCK_PATHS = (
    "main.py",
    "standby_monitor.py",
    "wifi_uplink.py",
    "sheets_log.py",
    "remote_boot_config.py",
    "version.py",
)

OTA_FAIL_OPEN_PATHS = (
    "main.py",
    "ota_health.py",
    "ota_reboot.py",
    "remote_boot_config.py",
    "remote_control.py",
    "version.py",
)

DOCK_CONTROL_SYNC_PATHS = (
    "main.py",
    "version.py",
)

BLOCKED_OTA_CADENCE_PATHS = (
    "auto_log.py",
    "main.py",
    "version.py",
)

WIFI_OTA_HARDENING_PATHS = (
    "main.py",
    "ota.py",
    "ota_capability.py",
    "ota_events_flush.py",
    "ota_lifecycle.py",
    "wifi_uplink.py",
    "version.py",
)

RADIO_TEARDOWN_PATHS = (
    "ble_service.py",
    "main.py",
    "remote_boot_config.py",
    "wifi_uplink.py",
    "version.py",
)


def _version():
    text = (ROOT / "version.py").read_text(encoding="utf-8")
    m = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise SystemExit("version.py missing VERSION")
    return m.group(1).strip()


def version_last(paths):
    return tuple(path for path in paths if path != "version.py") + (
        ("version.py",) if "version.py" in paths else ()
    )


def _write_manifest(paths, notes, include_bundle=True, manifest_kind=""):
    paths = version_last(paths)
    full = json.loads(FULL.read_text(encoding="utf-8"))
    by_path = {e["path"]: e for e in full.get("files") or [] if e.get("path")}
    files = []
    for path in paths:
        if path not in by_path:
            if (ROOT / path).is_file():
                files.append({"path": path, "url": RAW + path})
            else:
                print("missing:", path, file=sys.stderr)
                return 1
        else:
            files.append(dict(by_path[path]))
    data = {
        "version": _version(),
        "notes": notes,
        "files": files,
    }
    if manifest_kind:
        data["manifest_kind"] = manifest_kind
    if not include_bundle:
        data.pop("bundle", None)
    OUT.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("OK: manifest %s with %d files" % (data["version"], len(files)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--recovery", action="store_true", help="9-file reboot-loop recovery")
    p.add_argument("--feature-pack", action="store_true", help="16-file pack: trace, LEDs, BLE (smaller than full)")
    p.add_argument(
        "--ram-fix",
        action="store_true",
        help="7-file per-file OTA (streaming cellular + bundle extract); no .bmota",
    )
    p.add_argument(
        "--version-only",
        action="store_true",
        help="1-file manifest (version.py only) for patch stress on cellular",
    )
    p.add_argument(
        "--bootstrap-rules",
        action="store_true",
        help="2-file manifest: version.py + remote_boot_config.py (once per stress campaign)",
    )
    p.add_argument(
        "--dock-fix",
        action="store_true",
        help="5-file dock OTA fix: version, main, standby, ota_health, remote_boot_config",
    )
    p.add_argument(
        "--v50-track",
        action="store_true",
        help="3-file fix: version.py + v50_energy.py + ble_service read_v50",
    )
    p.add_argument(
        "--winter-hardening",
        action="store_true",
        help="6-file Wi-Fi-only WDT/network hardening release",
    )
    p.add_argument(
        "--standby-wifi-fix",
        action="store_true",
        help="8-file standby Wi-Fi memory refactor (no bundle)",
    )
    p.add_argument(
        "--ota-stream-fix",
        action="store_true",
        help="2-file streamed per-file OTA bootstrap",
    )
    p.add_argument(
        "--wifi-response-fix",
        action="store_true",
        help="2-file Wi-Fi response polling fix",
    )
    p.add_argument(
        "--wifi-scan-telemetry",
        action="store_true",
        help="3-file configured-SSID scan telemetry release",
    )
    p.add_argument(
        "--optional-telemetry-dedupe",
        action="store_true",
        help="4-file optional Event deduplication release",
    )
    p.add_argument(
        "--wifi-auth-ota-gate",
        action="store_true",
        help="5-file Wi-Fi auth retry and OTA gate diagnostics release",
    )
    p.add_argument(
        "--persistent-dock-wifi",
        action="store_true",
        help="5-file persistent dock Wi-Fi association release",
    )
    p.add_argument(
        "--ble-transition-fix",
        action="store_true",
        help="2-file dock-to-BLE Wi-Fi teardown release",
    )
    p.add_argument(
        "--flash-housekeeping",
        action="store_true",
        help="3-file bounded diagnostic/OTA cleanup release",
    )
    p.add_argument(
        "--winter-final-fixes",
        action="store_true",
        help="3-file Wi-Fi redirect and V50 SoftI2C release",
    )
    p.add_argument(
        "--one-tls-wifi",
        action="store_true",
        help="6-file one-TLS dock logging/control-sync release",
    )
    p.add_argument(
        "--ble-command-transition",
        action="store_true",
        help="2-file BLE command completion/key-off release",
    )
    p.add_argument(
        "--wifi-transport-bootstrap",
        action="store_true",
        help="2-file Wi-Fi OTA transport bootstrap",
    )
    p.add_argument(
        "--ble-log-handoff",
        action="store_true",
        help="3-file bounded BLE-to-cellular Log Now handoff",
    )
    p.add_argument(
        "--ble-sensor-cache",
        action="store_true",
        help="2-file cached BLE sensor status release",
    )
    p.add_argument(
        "--disable-wifi-console",
        action="store_true",
        help="3-file removal of normal Wi-Fi console runtime paths",
    )
    p.add_argument(
        "--clean-standby-boot",
        action="store_true",
        help="2-file clean-heap dock standby launcher",
    )
    p.add_argument(
        "--wifi-telemetry",
        action="store_true",
        help="3-file detailed Wi-Fi association telemetry release",
    )
    p.add_argument(
        "--headless-dock-log",
        action="store_true",
        help="3-file fresh-heap dock logging handoff",
    )
    p.add_argument(
        "--command-ack",
        action="store_true",
        help="3-file acknowledged remote command delivery",
    )
    p.add_argument(
        "--cumulative-dock",
        action="store_true",
        help="6-file cumulative fresh-heap dock and command-sync release",
    )
    p.add_argument(
        "--ota-fail-open",
        action="store_true",
        help="6-file failure, key-on rescue, dedupe, and split-dispatch release",
    )
    p.add_argument(
        "--dock-control-sync",
        action="store_true",
        help="2-file fresh-heap dock cellular command-sync release",
    )
    p.add_argument(
        "--blocked-ota-cadence",
        action="store_true",
        help="3-file dock cadence and cellular command-sync release",
    )
    p.add_argument(
        "--wifi-ota-hardening",
        action="store_true",
        help="7-file MicroPython 1.29 Wi-Fi association/TLS hardening release",
    )
    p.add_argument(
        "--radio-teardown",
        action="store_true",
        help="5-file non-destructive Wi-Fi/BLE handoff release",
    )
    args = p.parse_args(argv)
    if args.radio_teardown:
        return _write_manifest(
            RADIO_TEARDOWN_PATHS,
            "Avoid CYW43 deinit during Wi-Fi/BLE handoff; honor explicit OTA.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_ota_hardening:
        return _write_manifest(
            WIFI_OTA_HARDENING_PATHS,
            "MicroPython 1.29 Wi-Fi OTA TLS and dock association hardening.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.blocked_ota_cadence:
        return _write_manifest(
            BLOCKED_OTA_CADENCE_PATHS,
            "Keep blocked OTA targets from accelerating dock logs; restore control sync.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.dock_control_sync:
        return _write_manifest(
            DOCK_CONTROL_SYNC_PATHS,
            "Restore periodic cellular command sync in fresh-heap dock logging.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ota_fail_open:
        return _write_manifest(
            OTA_FAIL_OPEN_PATHS,
            "Fail open after terminal/repeated OTA failures with key-on BLE rescue.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.cumulative_dock:
        return _write_manifest(
            CUMULATIVE_DOCK_PATHS,
            "Cumulative fresh-heap dock logging, Wi-Fi teardown, and command acknowledgement.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.command_ack:
        return _write_manifest(
            COMMAND_ACK_PATHS,
            "Preserve Wi-Fi one-shots until a response-capable transport consumes them.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.headless_dock_log:
        return _write_manifest(
            HEADLESS_DOCK_LOG_PATHS,
            "Run each dock upload in a bounded fresh-heap boot.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_telemetry:
        return _write_manifest(
            WIFI_TELEMETRY_PATHS,
            "Capture complete per-SSID association failures before fallback.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.clean_standby_boot:
        return _write_manifest(
            CLEAN_STANDBY_BOOT_PATHS,
            "Launch dock standby before importing heavy OTA/telemetry modules.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.disable_wifi_console:
        return _write_manifest(
            BLE_LOG_HANDOFF_PATHS,
            "Disable Wi-Fi console commands, boot routing, and runtime fallback.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ble_sensor_cache:
        return _write_manifest(
            BLE_SENSOR_CACHE_PATHS,
            "Keep refreshed sensor readings across lightweight BLE heartbeats.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ble_log_handoff:
        return _write_manifest(
            BLE_LOG_HANDOFF_PATHS,
            "Bounded headless cellular handoff for BLE Log Now.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_transport_bootstrap:
        return _write_manifest(
            WIFI_TRANSPORT_BOOTSTRAP_PATHS,
            "Bootstrap TLS heap reclamation for subsequent Wi-Fi feature OTA.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ble_command_transition:
        return _write_manifest(
            BLE_COMMAND_TRANSITION_PATHS,
            "BLE repeated-command completion and key-off transition fix.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.one_tls_wifi:
        return _write_manifest(
            ONE_TLS_WIFI_PATHS,
            "One-TLS dock logging with periodic cellular control sync.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.winter_final_fixes:
        return _write_manifest(
            WINTER_FINAL_FIX_PATHS,
            "Iterative Wi-Fi redirects and V50 SoftI2C measurement.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.flash_housekeeping:
        return _write_manifest(
            FLASH_HOUSEKEEPING_PATHS,
            "Bound diagnostics and reclaim stale OTA artifacts before preflight.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ble_transition_fix:
        return _write_manifest(
            BLE_TRANSITION_FIX_PATHS,
            "Deinitialize shared Wi-Fi radio before dock-to-BLE reboot.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.persistent_dock_wifi:
        return _write_manifest(
            PERSISTENT_DOCK_WIFI_PATHS,
            "Keep healthy dock Wi-Fi association between logs.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_auth_ota_gate:
        return _write_manifest(
            WIFI_AUTH_OTA_GATE_PATHS,
            "Retry Wi-Fi auth once and report exact OTA gate reasons.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.optional_telemetry_dedupe:
        return _write_manifest(
            OPTIONAL_TELEMETRY_DEDUPE_PATHS,
            "Reduce TLS pressure by deduplicating unchanged optional Events.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_scan_telemetry:
        return _write_manifest(
            WIFI_SCAN_TELEMETRY_PATHS,
            "Wi-Fi fallback: report configured SSID visibility and RSSI.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.wifi_response_fix:
        return _write_manifest(
            WIFI_RESPONSE_FIX_PATHS,
            "Wi-Fi logging: tolerate cold-start response timeout slices.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.ota_stream_fix:
        return _write_manifest(
            OTA_STREAM_FIX_PATHS,
            "OTA bootstrap: stream each source file directly to flash.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.standby_wifi_fix:
        return _write_manifest(
            STANDBY_WIFI_FIX_PATHS,
            "Standby Wi-Fi memory refactor: logging and status without BLE imports.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.winter_hardening:
        return _write_manifest(
            WINTER_HARDENING_PATHS,
            "Winter hardening: bounded WDT feeds + Wi-Fi policy control.",
            include_bundle=False,
            manifest_kind="wifi-feature",
        )
    if args.v50_track:
        return _write_manifest(
            V50_TRACK_PATHS,
            "V50 sheet tracking: v50_energy mAh integrator + INA219 read_v50 fix.",
            include_bundle=False,
            manifest_kind="stress",
        )
    if args.dock_fix:
        return _write_manifest(
            DOCK_FIX_PATHS,
            "Dock OTA fix: Wi-Fi log / cellular boot OTA split + ENOMEM fallback.",
            include_bundle=False,
        )
    if args.bootstrap_rules:
        return _write_manifest(
            BOOTSTRAP_RULES_PATHS,
            "Bootstrap OTA: version.py + remote_boot_config.py (sheet backoff self-heal).",
            include_bundle=False,
            manifest_kind="bootstrap",
        )
    if args.version_only:
        return _write_manifest(
            VERSION_ONLY_PATHS,
            "Patch OTA: version.py only (cellular heap safe).",
            include_bundle=False,
            manifest_kind="stress",
        )
    if args.ram_fix:
        return _write_manifest(
            RAM_FIX_PATHS,
            "RAM-safe OTA: stream bundle download/extract + reboot cooldown (per-file, no bundle).",
            include_bundle=False,
        )
    if args.feature_pack:
        return _write_manifest(
            FEATURE_PACK_PATHS,
            "Feature-pack OTA: trace, LEDs, loop fix (~175KB bundle, streamed).",
        )
    if args.recovery:
        return _write_manifest(
            RECOVERY_PATHS,
            "Slim remote recovery OTA (reboot-loop fix; stream bundle extract).",
        )
    print(
        "Specify --recovery, --feature-pack, --ram-fix, --winter-hardening, "
        "--standby-wifi-fix, --ota-stream-fix, --wifi-response-fix, "
        "--wifi-scan-telemetry, or --optional-telemetry-dedupe",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
