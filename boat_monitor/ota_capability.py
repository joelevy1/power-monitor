"""
Post OTA-relevant device capability on Events after each successful log.

Helps remote monitoring confirm USB recovery stuck and that OTA policy is active
before bumping min_fw during a week-away campaign.
"""

try:
    import ujson as json
except ImportError:
    import json


def _fw():
    try:
        import version

        return str(getattr(version, "VERSION", "?"))
    except Exception:
        return "?"


def report_after_log(device="boat-p2", prefer_wifi=False, logger=None):
    """Emit ota_capability row: heap, flash policy, boot OTA readiness."""
    parts = ["fw=%s" % _fw()]
    try:
        import diag_log

        parts.append("heap_kb=%s" % diag_log.mem_kb())
    except Exception:
        pass
    try:
        import remote_boot_config as rbc

        data = rbc.load()
        parts.append("min_fw=%s" % (data.get("min_fw_version") or "?"))
        parts.append("auto_ota_on_boot=%s" % int(bool(data.get("auto_ota_on_boot"))))
        parts.append("boot_ota_prefer_wifi=%s" % int(rbc.effective_boot_ota_prefer_wifi()))
        parts.append("dock_mode=%s" % (data.get("dock_mode") or ""))
        parts.append("ota_manifest_profile=%s" % (data.get("ota_manifest_profile") or ""))
        parts.append("ota_self_sufficient=%s" % int(bool(data.get("ota_self_sufficient"))))
        parts.append("pending_ota=%s" % int(bool(data.get("pending_ota"))))
        parts.append("ota_degraded=%s" % int(bool(data.get("ota_degraded"))))
        parts.append("boot_ota_backoff=%s" % int(rbc.boot_ota_backoff_active()))
        parts.append("will_boot_ota=%s" % int(rbc.should_run_boot_ota()))
        parts.append("needs_upgrade=%s" % int(rbc.needs_firmware_upgrade()))
    except Exception as exc:
        parts.append("rbc_err=%s" % str(exc)[:40])
    try:
        import ota_health

        parts.append("manifest_profile=%s" % ota_health.effective_manifest_profile())
    except Exception:
        pass
    parts.append("uplink=%s" % ("wifi" if prefer_wifi else "cellular"))
    detail = "; ".join(parts)
    try:
        import diag_log

        diag_log.log("ota_capability %s" % detail[:220])
    except Exception:
        pass
    if logger is not None:
        try:
            logger.log_event(device, "ota_capability", detail)
            return True
        except Exception:
            pass
    try:
        import ota_events_flush

        ota_events_flush.flush_ota_events_uplink(
            device=device, prefer_wifi=prefer_wifi, max_total_s=25
        )
    except Exception:
        pass
    return False
