"""Shared helpers for post-log remote actions and OTA reboot."""

def maybe_reboot_for_ota(actions, source=""):
    """After a log session closed the modem: reboot for boot-time OTA if needed."""
    if not actions:
        return False
    if "ota" not in actions and "reboot" not in actions:
        return False
    try:
        import remote_boot_config

        if "ota" in actions:
            remote_boot_config.set_pending_ota(True)
    except Exception:
        pass
    try:
        import diag_log

        diag_log.log("maybe_reboot_for_ota actions=%s source=%s" % (actions, source))
    except Exception:
        pass
    try:
        import ota_lifecycle

        data = {}
        try:
            import remote_boot_config

            data = remote_boot_config.load()
        except Exception:
            pass
        ota_lifecycle.phase(
            "reboot_queued",
            inline=False,
            target_fw=data.get("min_fw_version"),
            source=source,
        )
    except Exception:
        pass
    try:
        from remote_control import run_actions

        run_actions(actions, prefer_wifi=False)
        return True
    except Exception as exc:
        print("maybe_reboot_for_ota:", exc)
        return False


def reboot_if_upgrade_pending(source=""):
    """When sheet min_fw is newer than version.py, queue OTA and reset immediately."""
    try:
        import remote_boot_config

        if not remote_boot_config.needs_firmware_upgrade():
            remote_boot_config.clear_pending_ota_if_current()
            return False
        remote_boot_config.set_pending_ota(True)
    except Exception:
        return False
    try:
        import diag_log

        diag_log.log("reboot_if_upgrade_pending source=%s" % source)
    except Exception:
        pass
    try:
        import ota_lifecycle

        data = {}
        try:
            import remote_boot_config

            data = remote_boot_config.load()
        except Exception:
            pass
        ota_lifecycle.phase(
            "reboot_queued",
            inline=False,
            target_fw=data.get("min_fw_version"),
            source=source,
        )
    except Exception:
        pass
    try:
        import ota_events_flush

        ota_events_flush.flush_ota_events_uplink(prefer_wifi=False, max_total_s=22)
    except Exception:
        pass
    import machine
    import time

    time.sleep(0.3)
    machine.reset()
    return True
