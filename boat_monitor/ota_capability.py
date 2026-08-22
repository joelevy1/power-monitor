"""
Post OTA-relevant device capability on Events after each successful log.

Helps remote monitoring confirm USB recovery stuck and that OTA policy is active
before bumping min_fw during a week-away campaign.
"""

STATE_PATH = "ota_capability_event_state.json"
MAX_DETAIL_CHARS = 1500


def _fw():
    try:
        import version

        return str(getattr(version, "VERSION", "?"))
    except Exception:
        return "?"


def _build_report(prefer_wifi=False):
    """Return local diagnostic detail and a stable OTA-policy fingerprint."""
    firmware = _fw()
    stable = ["fw=%s" % firmware]
    parts = list(stable)
    try:
        import diag_log

        parts.append("heap_kb=%s" % diag_log.mem_kb())
    except Exception:
        pass
    try:
        import remote_boot_config as rbc

        data = rbc.load()
        policy = [
            "min_fw=%s" % (data.get("min_fw_version") or "?"),
            "auto_ota_on_boot=%s" % int(bool(data.get("auto_ota_on_boot"))),
            "boot_ota_prefer_wifi=%s" % int(rbc.effective_boot_ota_prefer_wifi()),
            "dock_mode=%s" % (data.get("dock_mode") or ""),
            "ota_manifest_profile=%s" % (data.get("ota_manifest_profile") or ""),
            "ota_self_sufficient=%s" % int(bool(data.get("ota_self_sufficient"))),
            "pending_ota=%s" % int(bool(data.get("pending_ota"))),
            "ota_degraded=%s" % int(bool(data.get("ota_degraded"))),
            "boot_ota_backoff=%s" % int(rbc.boot_ota_backoff_active()),
            "will_boot_ota=%s" % int(rbc.should_run_boot_ota()),
            "needs_upgrade=%s" % int(rbc.needs_firmware_upgrade()),
        ]
        stable.extend(policy)
        parts.extend(policy)
    except Exception as exc:
        error = "rbc_err=%s" % str(exc)[:40]
        stable.append(error)
        parts.append(error)
    try:
        import ota_health

        profile = "manifest_profile=%s" % ota_health.effective_manifest_profile()
        stable.append(profile)
        parts.append(profile)
    except Exception:
        pass
    parts.append("uplink=%s" % ("wifi" if prefer_wifi else "cellular"))
    return "; ".join(parts)[:MAX_DETAIL_CHARS], "; ".join(stable)


def _post_succeeded(result):
    if result is False:
        return False
    if isinstance(result, dict) and result.get("ok") is False:
        return False
    return True


def _bounded_fingerprint(value):
    """Keep state bounded even if a remotely supplied profile is very long."""
    value = str(value)
    if len(value) <= 1400:
        return value
    checksum = 2166136261
    for char in value:
        checksum = ((checksum ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return "%d:%08x:%s:%s" % (
        len(value),
        checksum,
        value[:600],
        value[-600:],
    )


def report_after_log(device="boat-p2", prefer_wifi=False, logger=None):
    """Emit ota_capability row: heap, flash policy, boot OTA readiness."""
    detail, fingerprint = _build_report(prefer_wifi=prefer_wifi)
    fingerprint = _bounded_fingerprint(fingerprint)
    try:
        import diag_log

        diag_log.log("ota_capability %s" % detail[:220])
    except Exception:
        pass
    try:
        import telemetry_dedupe

        if not telemetry_dedupe.should_post(STATE_PATH, fingerprint):
            return False
    except Exception:
        telemetry_dedupe = None
    if logger is not None:
        try:
            result = logger.log_event(device, "ota_capability", detail)
            if _post_succeeded(result):
                if telemetry_dedupe is not None:
                    telemetry_dedupe.mark_posted(STATE_PATH, fingerprint)
                return True
        except Exception:
            pass
        return False
    try:
        import diag_log

        posted = diag_log.upload_event_bounded(
            device,
            "ota_capability",
            detail,
            diag_tail_lines=0,
            max_total_s=25,
            prefer_wifi=prefer_wifi,
        )
        if posted:
            if telemetry_dedupe is not None:
                telemetry_dedupe.mark_posted(STATE_PATH, fingerprint)
            return True
    except Exception:
        pass
    return False
