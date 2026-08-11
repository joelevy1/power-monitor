@echo off
REM Push remote_boot_config.py + version.py (bootstrap rules) + clear flash backoff.
REM Close Thonny first. Default COM7. Pass --port COM5 if needed.
cd /d "%~dp0\.."
py -m pip install -q mpremote
py -m mpremote connect COM7 cp boat_monitor\remote_boot_config.py :remote_boot_config.py
py -m mpremote connect COM7 cp boat_monitor\version.py :version.py
py boat_monitor\usb_recovery_push.py --patch-only --enable-boot-ota %*
echo.
echo Unplug USB, power cycle once, key ON. Then tell the agent "done".
