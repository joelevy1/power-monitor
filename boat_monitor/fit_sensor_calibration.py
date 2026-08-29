#!/usr/bin/env python3
"""Calculate linear sensor calibration constants from two reference points."""

import argparse

from sensor_calibration import apply_linear, fit_two_point


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fit corrected = raw * scale + offset from two measurements"
    )
    parser.add_argument("--raw-low", required=True, type=float)
    parser.add_argument("--reference-low", required=True, type=float)
    parser.add_argument("--raw-high", required=True, type=float)
    parser.add_argument("--reference-high", required=True, type=float)
    parser.add_argument("--label", default="SENSOR")
    args = parser.parse_args(argv)

    scale, offset = fit_two_point(
        args.raw_low,
        args.reference_low,
        args.raw_high,
        args.reference_high,
    )
    label = args.label.strip().upper().replace("-", "_").replace(" ", "_")
    print("%s_SCALE = %.9g" % (label, scale))
    print("%s_OFFSET = %.9g" % (label, offset))
    print(
        "check: %.9g -> %.9g; %.9g -> %.9g"
        % (
            args.raw_low,
            apply_linear(args.raw_low, scale, offset),
            args.raw_high,
            apply_linear(args.raw_high, scale, offset),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
