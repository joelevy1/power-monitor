"""Power and GPS logging orchestration without loading the BLE stack."""

from boat_status import read_status


def _wifi_uplink_configured():
    try:
        import wifi_uplink

        return bool(wifi_uplink.load_networks())
    except Exception:
        return False


def log_power_and_gps(
    note,
    on_progress=None,
    gps_timeout_s=20,
    prefer_wifi=True,
    ble_monitor=None,
    wifi_handoff=None,
    periodic_cellular_sync=False,
):
    """Log Power_Log + GPS_Log, optionally handing Wi-Fi radio control to BLE."""
    import sheets_log

    if ble_monitor is not None and getattr(ble_monitor, "_cellular_busy", False):
        msg = "power: failed: cellular session busy, gps: skipped"
        print("log_power_and_gps:", msg)
        try:
            import diag_log

            diag_log.log(msg)
        except Exception:
            pass
        return msg

    if ble_monitor is not None:
        ble_monitor._cellular_busy = True
    try:
        try:
            import diag_log

            diag_log.log(
                "log_power_and_gps entry note=%s prefer_wifi=%s ble=%s"
                % (note, prefer_wifi, ble_monitor is not None)
            )
        except Exception:
            pass

        status = read_status()
        sync_eligible = (
            periodic_cellular_sync
            and prefer_wifi
            and ble_monitor is None
            and status.get("mode") in ("docked_off", "bilge_active", "float_alert")
        )
        force_cellular_sync = False
        if sync_eligible:
            try:
                import remote_boot_config

                force_cellular_sync = (
                    remote_boot_config.cellular_control_sync_due()
                )
            except Exception:
                force_cellular_sync = False

        def _run(prefer):
            logger_kwargs = {
                "prefer_wifi": prefer,
                # BLE handoffs always return the CYW43439 to BLE, regardless
                # of dock persistence policy.
                "keep_wifi_connected": False if ble_monitor is not None else None,
            }
            if force_cellular_sync:
                logger_kwargs["cellular_control_sync"] = True
            logger = sheets_log.SheetsLogger(**logger_kwargs)
            actions = []
            log_mode = status.get("mode")
            try:
                import version

                fw = getattr(version, "VERSION", "")
                session_note = note
                if force_cellular_sync:
                    session_note = (
                        (str(note) + "; ") if note else ""
                    ) + "cellular_control_sync"
                    session_note = session_note[:160]
                try:
                    import gpio_probe

                    log_note = gpio_probe.enrich_note(session_note, status)
                except Exception:
                    log_note = session_note
                summary = logger.log_power_and_gps(
                    device=status["device"],
                    mode=status["mode"],
                    engine=status["engine"],
                    house=status["house"],
                    v50=status["v50"],
                    note=log_note,
                    fw=fw,
                    gps_timeout_s=gps_timeout_s,
                    on_progress=on_progress,
                )
                if sync_eligible and getattr(logger, "_last_power_success", False):
                    try:
                        import remote_boot_config

                        remote_boot_config.note_cellular_control_sync_power_success(
                            bool(getattr(logger, "_used_cellular", False))
                        )
                    except Exception as exc:
                        try:
                            import diag_log

                            diag_log.log("cellular control sync counter: %s" % exc)
                        except Exception:
                            pass
                actions = getattr(logger, "_last_remote_actions", []) or []
                return summary, actions
            finally:
                logger.close_data(mode=log_mode)

        if prefer_wifi and not _wifi_uplink_configured():
            msg = "power: failed: no Wi-Fi networks on Pico, gps: skipped"
            print("log_power_and_gps:", msg)
            try:
                import diag_log

                diag_log.log(msg)
            except Exception:
                pass
            return msg

        use_wifi = (
            prefer_wifi
            and not force_cellular_sync
            and _wifi_uplink_configured()
        )
        if use_wifi and ble_monitor is not None and ble_monitor.connections:
            use_wifi = False

        if use_wifi and ble_monitor is not None:
            if wifi_handoff is None:
                raise RuntimeError("BLE Wi-Fi handoff callback required")
            summary, actions = wifi_handoff(lambda: _run(True))
        else:
            session_prefer_wifi = (
                prefer_wifi and not force_cellular_sync
                if ble_monitor is None
                else use_wifi
            )
            summary, actions = _run(session_prefer_wifi)

        try:
            import ota_reboot

            ota_reboot.reboot_if_upgrade_pending(source="log_power_and_gps")
        except Exception:
            pass
        return summary
    finally:
        if ble_monitor is not None:
            ble_monitor._cellular_busy = False
