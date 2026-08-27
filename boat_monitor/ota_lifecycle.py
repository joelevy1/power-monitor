"""
Structured OTA lifecycle telemetry on the Google Sheet Events tab.

Phases (in order):
  aware          — sheet min_fw > device fw (or cmd_ota)
  reboot_queued  — about to reset for boot OTA
  boot_start     — main.py starting ota.update()
  boot_end       — boot OTA finished (success / no_upgrade / failed)
  confirmed      — first Power_Log posted on new fw after target met

Detail lines are key=value; use run_id to correlate one upgrade attempt.
"""

try:
    import utime as time
except ImportError:
    import time

try:
    import ujson as json
except ImportError:
    import json

STATE_PATH = "ota_lifecycle.json"
PENDING_PATH = "ota_lifecycle_pending.json"
EVENT_NAME = "ota_lifecycle"


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _ticks_diff(new, old):
    try:
        return time.ticks_diff(new, old)
    except AttributeError:
        return new - old


def _fw():
    try:
        import version

        return getattr(version, "VERSION", "?")
    except Exception:
        return "?"


def _load():
    try:
        with open(STATE_PATH, "r") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(data):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(data, f)
    except Exception as exc:
        print("ota_lifecycle save:", exc)


def _load_pending():
    try:
        with open(PENDING_PATH, "r") as f:
            d = json.load(f)
            return d if isinstance(d, list) else []
    except Exception:
        return []


def _save_pending(items):
    try:
        with open(PENDING_PATH, "w") as f:
            json.dump(items[-20:], f)
    except Exception:
        pass


def _append_pending(detail, device):
    items = _load_pending()
    items.append({"device": device or "boat-p2", "detail": detail})
    _save_pending(items)


def _format_detail(phase, run_id, extra=None):
    parts = ["phase=%s" % phase, "run_id=%s" % run_id, "fw=%s" % _fw(), "t_ms=%s" % _ticks_ms()]
    if extra:
        for k, v in extra.items():
            if v is not None and str(v) != "":
                parts.append("%s=%s" % (k, v))
    return "; ".join(parts)


def current_run_id():
    return _load().get("run_id")


def begin_run(target_fw, source=""):
    data = _load()
    run_id = int(data.get("run_id") or 0) + 1
    data["run_id"] = run_id
    data["target_fw"] = str(target_fw or "")
    data["started_ms"] = _ticks_ms()
    data["source"] = str(source or "")
    _save(data)
    return run_id


def phase(phase_name, logger=None, device=None, target_fw=None, inline=True, **extra):
    data = _load()
    run_id = data.get("run_id")
    if phase_name == "aware":
        if not run_id or data.get("target_fw") != str(target_fw or ""):
            run_id = begin_run(target_fw, source=extra.pop("source", ""))
    if not run_id:
        run_id = data.get("run_id") or begin_run(target_fw or data.get("target_fw"), source="implicit")
    if target_fw:
        data["target_fw"] = str(target_fw)
        _save(data)
    detail = _format_detail(phase_name, run_id, extra)
    try:
        import diag_log

        diag_log.log("ota_lifecycle %s" % detail[:200])
    except Exception:
        pass
    device = device or "boat-p2"
    if inline and logger is not None and getattr(logger, "_data_open", False):
        try:
            logger.log_event(device, EVENT_NAME, detail[:1500])
            return run_id
        except Exception as exc:
            print("ota_lifecycle inline:", exc)
    _append_pending(detail, device)
    return run_id


def flush_pending(logger, device=None, max_rows=2):
    if not getattr(logger, "_data_open", False):
        return 0
    device = device or "boat-p2"
    items = _load_pending()
    if not items:
        return 0
    posted = 0
    keep = []
    for index, item in enumerate(items):
        if posted >= max(1, int(max_rows)):
            keep.extend(items[index:])
            break
        try:
            logger.log_event(device, EVENT_NAME, item.get("detail", "")[:1500])
            posted += 1
        except Exception:
            keep.append(item)
    _save_pending(keep)
    if posted:
        try:
            import diag_log

            diag_log.log("ota_lifecycle flushed %s Events rows" % posted)
        except Exception:
            pass
    return posted


def upload_pending_uplink(
    device=None, prefer_wifi=False, max_total_s=35, max_rows=2
):
    """POST pending lifecycle rows via a short cellular/Wi-Fi session."""
    items = _load_pending()
    if not items:
        return 0
    device = device or "boat-p2"
    try:
        import diag_log
    except Exception:
        return 0
    posted = 0
    keep = []
    budget = max_total_s
    started_ms = _ticks_ms()
    for index, item in enumerate(items):
        if posted >= max(1, int(max_rows)):
            keep.extend(items[index:])
            break
        elapsed_s = max(0, _ticks_diff(_ticks_ms(), started_ms)) / 1000
        remaining_s = max(0, float(budget) - elapsed_s)
        if remaining_s < 2:
            keep.extend(items[index:])
            break
        detail = (item.get("detail") or "")[:1500]
        if not detail:
            continue
        try:
            ok = diag_log.upload_event_bounded(
                device,
                EVENT_NAME,
                detail,
                diag_tail_lines=0,
                max_total_s=min(20, remaining_s),
                prefer_wifi=prefer_wifi,
            )
            if ok:
                posted += 1
            else:
                keep.append(item)
        except Exception:
            keep.append(item)
    _save_pending(keep)
    return posted


def maybe_confirm_after_log(logger, device, fw_reported):
    """Call after Power_Log POST when fw column matches persisted target."""
    data = _load()
    target = str(data.get("target_fw") or "").strip()
    if not target:
        return False
    if _parse_ver(fw_reported) < _parse_ver(target):
        return False
    if data.get("confirmed_run_id") == data.get("run_id"):
        return False
    data["confirmed_run_id"] = data.get("run_id")
    started = int(data.get("started_ms") or 0)
    elapsed_s = None
    if started:
        elapsed_s = int((_ticks_ms() - started) / 1000)
    phase(
        "confirmed",
        logger=logger,
        device=device,
        target_fw=target,
        elapsed_total_s=elapsed_s,
        fw_reported=fw_reported,
    )
    data["target_fw"] = ""
    _save(data)
    return True


def _parse_ver(text):
    parts = []
    for p in str(text or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            parts.append(0)
    return tuple(parts)
