# Power sensor calibration

The INA260 and INA219 conversion formulas come from their datasheets. Do not
replace them with guessed correction values. Boat-specific calibration is a
separate linear correction:

```text
corrected = raw × scale + offset
```

Defaults are `scale=1` and `offset=0`, so installing this firmware does not
change existing readings. Raw and corrected values are both included in the
BLE status payload for audit and fitting.

## Equipment

- Calibrated digital multimeter for voltage
- DC clamp meter or purpose-built USB load meter for current
- A stable, known load

Do not put a handheld multimeter in current mode across a battery. For the
12 V circuits, use a DC clamp meter around one conductor or a properly fused,
current-rated series meter. Keep each load within the sensor and wiring rating.

## Voltage

For each channel, record two simultaneous raw/reference pairs separated by
several volts. Suitable points are resting battery voltage and charging
voltage. Fit them with:

```bash
python3 boat_monitor/fit_sensor_calibration.py \
  --label ENGINE_VOLTAGE \
  --raw-low 12.10 --reference-low 12.08 \
  --raw-high 14.20 --reference-high 14.18
```

Repeat with `HOUSE_VOLTAGE` and `V50_VOLTAGE`. The numbers above only
demonstrate the command; never copy them as calibration values.

## Current

1. Turn charging sources and switched loads off and record the zero point.
2. Apply a stable known load and record the sensor and reference currents at
   the same time.
3. Fit `ENGINE_CURRENT`, `HOUSE_CURRENT`, or `V50_CURRENT` with the same tool.
4. Confirm a third load not used for fitting.

INA260 current is signed. Preserve the sign: the installed orientation uses
negative current for charging and positive current for discharge. V50 tracks
discharge magnitude, while `raw_a_signed` remains available to verify wiring
orientation.

## Applying values remotely

The following Config keys are accepted, range-checked, persisted, and reported
in the next `remote_config` event:

- `engine_voltage_scale`, `engine_voltage_offset`
- `engine_current_scale`, `engine_current_offset`
- `house_voltage_scale`, `house_voltage_offset`
- `house_current_scale`, `house_current_offset`
- `v50_voltage_scale`, `v50_voltage_offset`
- `v50_current_scale`, `v50_current_offset`

Change one channel at a time. After each change, compare at zero, the fitted
load, and an independent load before accepting it. Record the meter model,
measurement points, load, raw values, references, and resulting constants.

These names and the calibration formula are platform-independent and should be
kept when the sensor code moves to Particle Device OS.
