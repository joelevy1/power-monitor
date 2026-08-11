@echo off
REM Push remote_boot_config.py only (bootstrap rules) + clear flash backoff.
REM Close Thonny first. Default COM7.
cd /d "%~dp0\.."
py -m pip install -q mpremote
py -m mpremote connect COM7 cp boat_monitor\remote_boot_config.py :remote_boot_config.py
py boat_monitor\usb_recovery_push.py --patch-only --enable-boot-ota --port COM7
echo Unplug USB, power cycle once, key ON.
