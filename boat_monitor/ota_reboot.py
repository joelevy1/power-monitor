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
            return False
        remote_boot_config.set_pending_ota(True)
    except Exception:
        return False
    try:
        import diag_log

        diag_log.log("reboot_if_upgrade_pending source=%s" % source)
    except Exception:
        pass
    import machine
    import time

    time.sleep(0.3)
    machine.reset()
    return True
