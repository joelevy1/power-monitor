"""Force one Power_Log+GPS cycle from USB (standby path). Run: mpremote connect COM7 run usb_bench_log.py"""

try:
    from ble_service import log_power_and_gps

    summary = log_power_and_gps(
        note="usb_bench_log",
        prefer_wifi=True,
        ble_monitor=None,
        gps_timeout_s=8,
    )
    print("RESULT:", summary)
except Exception as exc:
    print("FAILED:", exc)
