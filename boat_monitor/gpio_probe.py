"""GPIO probe helpers — append switch/key state to Power_Log notes for remote diagnosis."""

try:
    import config as cfg
except ImportError:
    cfg = None


def _raw_pin(gpio):
    from machine import Pin

    return Pin(gpio, Pin.IN, Pin.PULL_UP).value()


def format_gpio_suffix(status):
    """Compact string for Power_Log note (sw/key logic + raw GP levels)."""
    inputs = (status or {}).get("inputs") or {}
    sw_on = 1 if inputs.get("switch") else 0
    key_on = 1 if inputs.get("key") else 0
    if cfg is None:
        return " gpio sw=%d key=%d cfg=missing" % (sw_on, key_on)
    try:
        r_sw = _raw_pin(cfg.PIN_BATTERY_SWITCH)
        r_key = _raw_pin(cfg.PIN_KEY)
        return (
            " gpio sw=%d key=%d gp%d=%d gp%d=%d"
            % (sw_on, key_on, cfg.PIN_BATTERY_SWITCH, r_sw, cfg.PIN_KEY, r_key)
        )
    except Exception as exc:
        return " gpio sw=%d key=%d read_err=%s" % (sw_on, key_on, exc)


def enrich_note(note, status):
    base = (note or "").strip()
    suffix = format_gpio_suffix(status)
    out = (base + suffix).strip()
    return out[:160]


def event_detail(status):
    """Longer text for Events tab gpio_probe row."""
    inputs = (status or {}).get("inputs") or {}
    lines = [
        "mode=%s" % (status or {}).get("mode"),
        "inputs=%s" % inputs,
        format_gpio_suffix(status).strip(),
    ]
    if cfg is not None:
        lines.append(
            "pins GP%d=switch GP%d=key (0=LOW/on with pull-up)" % (cfg.PIN_BATTERY_SWITCH, cfg.PIN_KEY)
        )
    return " ".join(lines)[:800]
