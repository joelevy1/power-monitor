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
    """Parse Apps Script `commands` object.

    Returns (actions, applied_detail) where actions is a list like ['ota']
    and applied_detail is a short human-readable summary for Events / debugging.
    """
    if not payload or not isinstance(payload, dict):
        return [], ""

    settings = payload.get("settings") or {}
    one_shots = payload.get("one_shots") or []
    applied = []

    try:
        import auto_log

        on_s = settings.get("interval_engine_on_s")
        off_s = settings.get("interval_engine_off_s")
        if on_s is not None and str(on_s).strip() != "":
            auto_log.set_interval_overrides(engine_on_s=int(on_s))
            applied.append("interval_engine_on_s=%s" % int(on_s))
        if off_s is not None and str(off_s).strip() != "":
            auto_log.set_interval_overrides(engine_off_s=int(off_s))
            applied.append("interval_engine_off_s=%s" % int(off_s))
    except Exception as exc:
        print("remote_control: interval override failed:", exc)

    wifi_text = settings.get("wifi_networks")
    if wifi_text is not None and str(wifi_text).strip() != "":
        try:
            import wifi_networks

            nets = wifi_networks.parse_wifi_networks_text(wifi_text)
            if wifi_networks.save_sheet_networks(nets):
                applied.append("wifi_networks=%d" % len(nets))
        except Exception as exc:
            print("remote_control: wifi_networks failed:", exc)

    actions = []
    for name in one_shots:
        key = str(name or "").strip().lower()
        if key in ("ota", "update", "firmware"):
            actions.append("ota")
            applied.append("one_shot=ota")
        elif key in ("reboot", "reset"):
            actions.append("reboot")
            applied.append("one_shot=reboot")

    min_fw = settings.get("min_fw_version") or settings.get("target_fw_version")
    if min_fw:
        try:
            import version

            current = getattr(version, "VERSION", "0")
            applied.append("min_fw_version=%s current=%s" % (min_fw, current))
            if _version_lt(current, min_fw):
                actions.append("ota")
        except Exception as exc:
            print("remote_control: min_fw_version check failed:", exc)

    if _truthy(settings.get("cmd_ota")) or _truthy(settings.get("force_ota")):
        actions.append("ota")
        applied.append("cmd_ota=1")
    if _truthy(settings.get("cmd_reboot")) or _truthy(settings.get("force_reboot")):
        actions.append("reboot")
        applied.append("cmd_reboot=1")

    hold = settings.get("ble_gpio_off_hold_s")
    if hold is not None and str(hold).strip() != "":
        try:
            import ble_policy

            ble_policy.set_gpio_off_hold_s(int(hold))
            applied.append("ble_gpio_off_hold_s=%s" % int(hold))
        except Exception as exc:
            print("remote_control: ble_gpio_off_hold_s failed:", exc)

    if _truthy(settings.get("cmd_ble_latch")) or _truthy(settings.get("ble_latch")):
        try:
            import ble_policy

            ble_policy.set_ble_latch(True)
            applied.append("ble_latch=1")
        except Exception as exc:
            print("remote_control: ble_latch failed:", exc)

    try:
        import v50_energy

        v50_energy.apply_config_settings(settings)
    except Exception as exc:
        print("remote_control: v50_energy:", exc)

    try:
        import remote_boot_config

        boot_applied = remote_boot_config.apply_settings(settings)
        applied.extend(boot_applied)
    except Exception as exc:
        print("remote_control: remote_boot_config:", exc)

    out = []
    if "ota" in actions:
        out.append("ota")
    if "reboot" in actions and "ota" not in out:
        out.append("reboot")
    return out, "; ".join(applied)


def apply_from_log_response(response, device_id=""):
    commands = {}
    if response and isinstance(response, dict):
        commands = response.get("commands") or {}
    return apply_commands_payload(commands, device_id=device_id)


def run_actions(actions, prefer_wifi=False):
    """Execute remote actions after a log session closed the modem."""
    if not actions:
        return

    try:
        import diag_log

        diag_log.log("run_actions %s prefer_wifi=%s" % (actions, prefer_wifi))
    except Exception:
        pass

    for action in actions:
        if action == "ota":
            try:
                import remote_boot_config

                remote_boot_config.set_pending_ota(True)
            except Exception as exc:
                print("remote_control: set_pending_ota:", exc)

            # Post-log heap is usually highest; try cellular OTA before reboot-only.
            try:
                import ota
                import remote_boot_config

                max_s = remote_boot_config.effective_boot_ota_max_seconds()
                try:
                    import diag_log

                    diag_log.log("run_actions inline OTA start max_s=%s" % max_s)
                except Exception:
                    pass
                changed = ota.update(reboot=True, prefer_wifi=False, max_total_s=max_s)
                if changed:
                    return
            except Exception as exc:
                print("remote_control: inline OTA failed:", exc)
                try:
                    import diag_log

                    diag_log.log("run_actions inline OTA failed %s -> reboot" % exc)
                except Exception:
                    pass

            print("remote_control: reboot for boot-time OTA (pending_ota set)")
            try:
                import diag_log

                diag_log.log("run_actions -> reboot for boot OTA")
            except Exception:
                pass
            import machine
            import time

            time.sleep(0.5)
            machine.reset()
            return
        if action == "reboot":
            print("remote_control: reboot from sheet command")
            try:
                import diag_log

                diag_log.log("run_actions -> reboot from sheet")
            except Exception:
                pass
            import machine
            import time

            time.sleep(0.5)
            machine.reset()
