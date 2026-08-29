"""Platform-independent linear calibration helpers for power sensors."""


def apply_linear(raw_value, scale=1.0, offset=0.0):
    """Apply reference = raw * scale + offset."""
    return float(raw_value) * float(scale) + float(offset)


def fit_two_point(raw_low, reference_low, raw_high, reference_high):
    """Return (scale, offset) from two raw/reference measurements."""
    raw_low = float(raw_low)
    raw_high = float(raw_high)
    if raw_high == raw_low:
        raise ValueError("raw calibration points must differ")
    reference_low = float(reference_low)
    reference_high = float(reference_high)
    scale = (reference_high - reference_low) / (raw_high - raw_low)
    offset = reference_low - raw_low * scale
    return scale, offset


def calibrated_reading(
    raw_voltage,
    raw_current,
    voltage_scale=1.0,
    voltage_offset=0.0,
    current_scale=1.0,
    current_offset=0.0,
):
    """Calibrate voltage/current while retaining auditable raw values."""
    return {
        "v": apply_linear(raw_voltage, voltage_scale, voltage_offset),
        "a": apply_linear(raw_current, current_scale, current_offset),
        "raw_v": float(raw_voltage),
        "raw_a": float(raw_current),
    }
