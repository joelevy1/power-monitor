"""Shared helpers for post-log remote actions and OTA reboot."""


def _skip_boot_ota_telemetry(reason, source=""):
    try:
        import diag_log

        diag_log.log("boot_ota skipped %s source=%s" % (reason, source))
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
            "boot_ota_skipped",
            inline=False,
            target_fw=data.get("min_fw_version"),
            error=reason,
            source=source,
        )
    except Exception:
        pass
    try:
        import ota_telemetry

        ota_telemetry.report_boot_ota(
            "skipped",
            error=reason,
            source=source or "ota_reboot",
        )
    except Exception:
        pass


def _boot_ota_will_run():
    """True only when main.py boot OTA path should run on next reset."""
    try:
        import remote_boot_config

        return bool(remote_boot_config.should_run_boot_ota())
    except Exception:
        return False


def maybe_reboot_for_ota(actions, source="", prefer_wifi=False):
    """After a log session closed the modem: reboot for boot-time OTA if needed."""
    if not actions:
        return False
    if "ota" not in actions and "reboot" not in actions:
        return False
    if "ota" in actions and not _boot_ota_will_run():
        reason = "will_not_run_boot_ota"
        try:
            import remote_boot_config

            if remote_boot_config.boot_ota_backoff_active():
                reason = "backoff_active"
            elif remote_boot_config.needs_firmware_upgrade():
                try:
                    import ota_health

                    if ota_health.ota_degraded():
                        reason = "ota_degraded"
                except Exception:
                    reason = "ota_degraded"
        except Exception:
            pass
        _skip_boot_ota_telemetry(reason, source=source)
        return False
    try:
        import remote_boot_config

        if "ota" in actions:
            remote_boot_config.set_pending_ota(True)
    except Exception:
        pass
    try:
        import diag_log

        diag_log.log(
            "maybe_reboot_for_ota actions=%s source=%s prefer_wifi=%s"
            % (actions, source, prefer_wifi)
        )
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

        run_actions(actions, prefer_wifi=prefer_wifi)
        return True
    except Exception as exc:
        print("maybe_reboot_for_ota:", exc)
        return False


def reboot_if_upgrade_pending(source=""):
    """When sheet min_fw is newer than version.py, queue OTA and reset if boot OTA will run."""
    try:
        import ota_health

        if ota_health.ota_reboot_blocked():
            _skip_boot_ota_telemetry("ota_reboot_blocked", source=source)
            return False
    except ImportError:
        pass
    except Exception:
        pass
    try:
        import remote_boot_config

        if not remote_boot_config.needs_firmware_upgrade():
            remote_boot_config.clear_pending_ota_if_current()
            return False
        if remote_boot_config.ota_reboot_cooldown_active():
            try:
                import diag_log

                diag_log.log("reboot_if_upgrade_pending skipped cooldown source=%s" % source)
            except Exception:
                pass
            return False
        if not remote_boot_config.should_run_boot_ota():
            reason = "boot_ota_not_scheduled"
            if remote_boot_config.boot_ota_backoff_active():
                reason = "backoff_active"
            else:
                try:
                    import ota_health

                    if ota_health.ota_degraded():
                        reason = "ota_degraded"
                except Exception:
                    pass
            _skip_boot_ota_telemetry(reason, source=source)
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
    remote_boot_config.note_ota_reboot_reset()
    machine.reset()
    return True
