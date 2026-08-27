"""
OTA failure tracking, preflight checks, manifest tier selection, reboot gating.

Events: ota_health (detail key=value).
"""

try:
    import ujson as json
except ImportError:
    import json

FAIL_LIMIT_REBOOT_BLOCK = 2
FAIL_LIMIT_MICRO_MANIFEST = 2
MIN_MEM_FREE_BOOT_OTA = 45000
MIN_FS_FREE_BOOT_OTA = 120000
# Cellular boot OTA: at most bootstrap (2 files) unless cmd_ota_force on flash.
MAX_CELLULAR_MANIFEST_FILES = 2
MAX_WIFI_MANIFEST_FILES = 8
RECOVERY_MANIFEST_KINDS = ("recovery", "dock-fix", "feature-pack", "ram-fix")


def enomem_error(exc):
    """True when an exception looks like MicroPython heap exhaustion."""
    if exc is None:
        return False
    text = str(exc).lower()
    return (
        "enomem" in text
        or "errno 12" in text
        or "memory allocation" in text
        or text.strip() in ("12", "28", "[errno 28]")
    )


def terminal_ota_error(exc):
    """True for deterministic release-policy errors that a reboot cannot fix."""
    if exc is None:
        return False
    text = str(exc).strip().lower()
    return text.startswith(
        (
            "manifest_tier_",
            "manifest_kind_",
            "manifest has no files",
            "bundle missing ",
            "bundle sha256 mismatch",
        )
    )


def boot_retry_allowed(error=None):
    """Bound transient boot retries; policy refusals never retry automatically."""
    if terminal_ota_error(error):
        return False
    return fail_count() < FAIL_LIMIT_REBOOT_BLOCK


def reclaim_stale_ota_flash():
    """Remove safe transient artifacts before refusing an OTA for low flash."""
    removed = []
    try:
        import diag_log

        if diag_log.trim_if_oversize():
            removed.append("boat_diag.log:trimmed")
    except Exception:
        pass
    try:
        import os

        for name in os.listdir():
            if (
                name.endswith(".bak")
                or name.endswith(".new")
                or name in ("ota_release.bmota", "ota_release.bmota.new")
            ):
                try:
                    os.remove(name)
                    removed.append(name)
                except OSError:
                    pass
    except Exception:
        pass
    return removed


def _snapshot():
    try:
        import ota_diag

        return ota_diag.snapshot()
    except Exception:
        return {}


def fail_count():
    try:
        import remote_boot_config

        return int(remote_boot_config.load().get("boot_ota_fail_count") or 0)
    except Exception:
        return 0


def record_boot_ota_result(success, error=None, outcome=None, emit=True):
    try:
        import remote_boot_config

        data = remote_boot_config.load()
        if success:
            data["boot_ota_fail_count"] = 0
            data["last_boot_ota_outcome"] = "success"
            data.pop("ota_degraded", None)
            data.pop("cmd_ota_force", None)
        else:
            n = int(data.get("boot_ota_fail_count") or 0) + 1
            outcome_s = str(outcome or "failed")
            # Transient heap/flash preflight skips are not "bad OTA" — don't trap degraded.
            preflight_only = outcome_s == "preflight" or (
                error and str(error).startswith(("low_mem", "low_flash"))
            )
            if not preflight_only:
                data["boot_ota_fail_count"] = n
            data["last_boot_ota_outcome"] = outcome_s[:40]
            if error:
                data["last_boot_ota_error"] = str(error)[:200]
            if not preflight_only and n >= FAIL_LIMIT_REBOOT_BLOCK:
                data["ota_degraded"] = True
        remote_boot_config.save(data)
        if emit:
            _emit(
                "boot_ota_recorded",
                success=1 if success else 0,
                fail_count=data.get("boot_ota_fail_count"),
                outcome=outcome or "",
                error=str(error)[:120] if error else "",
            )
    except Exception:
        pass


def ota_degraded():
    try:
        import remote_boot_config

        return bool(remote_boot_config.load().get("ota_degraded"))
    except Exception:
        return False


def ota_reboot_blocked():
    """Block post-log reboot storm; explicit cmd_ota still allowed via set_pending."""
    if not ota_degraded() and fail_count() < FAIL_LIMIT_REBOOT_BLOCK:
        return False
    try:
        import remote_boot_config

        if remote_boot_config.load().get("cmd_ota_force"):
            return False
    except Exception:
        pass
    return True


def clear_degraded():
    try:
        import remote_boot_config

        data = remote_boot_config.load()
        data.pop("ota_degraded", None)
        data["boot_ota_fail_count"] = 0
        data.pop("cmd_ota_force", None)
        remote_boot_config.save(data)
    except Exception:
        pass


def manifest_kind(data):
    return str((data or {}).get("manifest_kind") or "").strip().lower()


def check_manifest_policy(manifest, used_wifi=False):
    """
    Refuse unsafe CDN manifests before download (device-side tier gate).
    Returns (ok, reason).
    """
    files = (manifest or {}).get("files") or []
    n = len(files)
    if n <= 1:
        return True, ""
    kind = manifest_kind(manifest)
    # A force command may bypass scheduling/degraded gates, never transport
    # safety. Rebooting cannot make a cellular feature bundle safe for heap.
    if kind in RECOVERY_MANIFEST_KINDS and not used_wifi:
        return False, "manifest_tier_recovery_requires_wifi"
    limit = MAX_WIFI_MANIFEST_FILES if used_wifi else MAX_CELLULAR_MANIFEST_FILES
    if n > limit:
        return False, "manifest_tier_max_%d_files_%s" % (limit, "wifi" if used_wifi else "cellular")
    if not used_wifi and n > 1 and kind not in ("bootstrap", "stress", ""):
        return False, "manifest_kind_%s_cellular_blocked" % (kind or "?")
    return True, ""


def effective_manifest_profile():
    try:
        import remote_boot_config

        data = remote_boot_config.load()
        prof = str(data.get("ota_manifest_profile") or "").strip().lower()
        if prof in ("micro", "ram-fix", "ram_fix", "feature", "feature-pack", "default"):
            if prof in ("ram_fix",):
                return "ram-fix"
            if prof in ("feature", "feature-pack"):
                return "feature-pack"
            return prof if prof != "default" else "ram-fix"
        if int(data.get("boot_ota_fail_count") or 0) >= FAIL_LIMIT_MICRO_MANIFEST:
            return "micro"
    except Exception:
        pass
    return "ram-fix"


def effective_manifest_url():
    try:
        import ota_config

        profile = effective_manifest_profile()
        if profile == "micro":
            return getattr(ota_config, "OTA_MANIFEST_MICRO_URL", ota_config.OTA_MANIFEST_URL)
        if profile == "feature-pack":
            return getattr(
                ota_config, "OTA_MANIFEST_FEATURE_URL", ota_config.OTA_MANIFEST_URL
            )
        return getattr(ota_config, "OTA_MANIFEST_RAM_URL", ota_config.OTA_MANIFEST_URL)
    except Exception:
        try:
            import ota_config

            return ota_config.OTA_MANIFEST_URL
        except Exception:
            return ""


def preflight_boot_ota():
    """Return (ok, reason). Posts device_stats on failure."""
    snap = _snapshot()
    mem = snap.get("mem_free")
    fs = snap.get("fs_free_b")
    if mem is not None and int(mem) < MIN_MEM_FREE_BOOT_OTA:
        _emit("preflight_fail", reason="low_mem", mem_free=mem)
        return False, "low_mem_%s" % mem
    if fs is not None and int(fs) < MIN_FS_FREE_BOOT_OTA:
        removed = reclaim_stale_ota_flash()
        if removed:
            snap = _snapshot()
            fs = snap.get("fs_free_b")
            _emit(
                "preflight_cleanup",
                removed=len(removed),
                fs_free_b=fs,
            )
        if fs is not None and int(fs) >= MIN_FS_FREE_BOOT_OTA:
            _emit(
                "preflight_ok_after_cleanup",
                mem_free=mem,
                fs_free_b=fs,
                profile=effective_manifest_profile(),
            )
            return True, ""
        _emit("preflight_fail", reason="low_flash", fs_free_b=fs)
        return False, "low_flash_%s" % fs
    _emit(
        "preflight_ok",
        mem_free=mem,
        fs_free_b=fs,
        profile=effective_manifest_profile(),
    )
    return True, ""


def _emit(phase, **extra):
    parts = ["phase=%s" % phase]
    for k, v in extra.items():
        if v is not None and str(v) != "":
            parts.append("%s=%s" % (k, v))
    detail = "; ".join(parts)
    try:
        import diag_log

        diag_log.log("ota_health %s" % detail[:200])
    except Exception:
        pass
    try:
        import ota_diag

        ota_diag.upload_bounded(phase="ota_health_%s" % phase, max_total_s=20, **extra)
    except Exception:
        pass
    return detail
