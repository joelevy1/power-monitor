"""
Apply remote settings/commands returned by the Apps Script receiver on each
successful Sheets POST (see apps_script/Code.gs and REMOTE_CONTROL.md).

The Pico already opens cellular (or Wi-Fi) for every log cycle, so piggybacking
commands on the POST response avoids a separate poll and works from the boat
without BLE or Wi-Fi console.
"""

try:
    import ujson as json
except ImportError:
    import json


def _truthy(value):
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "on")


def _parse_version(text):
    parts = []
    for piece in str(text or "").strip().split("."):
        try:
            parts.append(int(piece))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _version_lt(current, minimum):
    return _parse_version(current) < _parse_version(minimum)


def apply_commands_payload(payload, device_id=""):
    """Parse Apps Script `commands` object. Returns a list of actions:
    'ota', 'reboot' (deduped, ota before reboot).
    """
    if not payload or not isinstance(payload, dict):
        return []

    settings = payload.get("settings") or {}
    one_shots = payload.get("one_shots") or []

    try:
        import auto_log

        on_s = settings.get("interval_engine_on_s")
        off_s = settings.get("interval_engine_off_s")
        if on_s is not None and str(on_s).strip() != "":
            auto_log.set_interval_overrides(engine_on_s=int(on_s))
        if off_s is not None and str(off_s).strip() != "":
            auto_log.set_interval_overrides(engine_off_s=int(off_s))
    except Exception as exc:
        print("remote_control: interval override failed:", exc)

    actions = []
    for name in one_shots:
        key = str(name or "").strip().lower()
        if key in ("ota", "update", "firmware"):
            actions.append("ota")
        elif key in ("reboot", "reset"):
            actions.append("reboot")

    min_fw = settings.get("min_fw_version") or settings.get("target_fw_version")
    if min_fw:
        try:
            import version

            current = getattr(version, "VERSION", "0")
            if _version_lt(current, min_fw):
                actions.append("ota")
        except Exception as exc:
            print("remote_control: min_fw_version check failed:", exc)

    if _truthy(settings.get("cmd_ota")) or _truthy(settings.get("force_ota")):
        actions.append("ota")
    if _truthy(settings.get("cmd_reboot")) or _truthy(settings.get("force_reboot")):
        actions.append("reboot")

    # Stable order: OTA (may reboot) before plain reboot.
    out = []
    if "ota" in actions:
        out.append("ota")
    if "reboot" in actions and "ota" not in out:
        out.append("reboot")
    return out


def apply_from_log_response(response, device_id=""):
    commands = {}
    if response and isinstance(response, dict):
        commands = response.get("commands") or {}
    return apply_commands_payload(commands, device_id=device_id)


def run_actions(actions, prefer_wifi=False):
    """Execute remote actions after a log session closed the modem."""
    if not actions:
        return

    for action in actions:
        if action == "ota":
            print("remote_control: running OTA from sheet command")
            import ota

            ota.update(reboot=True, prefer_wifi=prefer_wifi)
            return
        if action == "reboot":
            print("remote_control: reboot from sheet command")
            import machine
            import time

            time.sleep(0.5)
            machine.reset()
