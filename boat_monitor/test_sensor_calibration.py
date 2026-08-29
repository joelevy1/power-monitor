"""Host tests for portable sensor calibration math."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sensor_calibration


def test_apply_linear():
    assert abs(sensor_calibration.apply_linear(10, 1.02, -0.1) - 10.1) < 1e-12


def test_fit_two_point():
    scale, offset = sensor_calibration.fit_two_point(0.2, 0.0, 9.8, 10.0)
    assert abs(sensor_calibration.apply_linear(0.2, scale, offset)) < 1e-12
    assert abs(sensor_calibration.apply_linear(9.8, scale, offset) - 10.0) < 1e-12


def test_fit_rejects_identical_raw_points():
    try:
        sensor_calibration.fit_two_point(1, 2, 1, 3)
    except ValueError:
        return
    raise AssertionError("identical raw points must fail")


def test_calibrated_reading_retains_raw_values():
    result = sensor_calibration.calibrated_reading(
        12.0,
        -1.0,
        voltage_scale=1.01,
        voltage_offset=0.1,
        current_scale=0.98,
        current_offset=-0.02,
    )
    assert abs(result["v"] - 12.22) < 1e-12
    assert result["a"] == -1.0
    assert result["raw_v"] == 12.0
    assert result["raw_a"] == -1.0


def main():
    test_apply_linear()
    test_fit_two_point()
    test_fit_rejects_identical_raw_points()
    test_calibrated_reading_retains_raw_values()
    print("sensor calibration tests OK")


if __name__ == "__main__":
    main()
