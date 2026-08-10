@echo off
REM USB recovery for boat-p2 Pico (default COM7). Close Thonny first.
cd /d "%~dp0\.."
py -m pip install -q mpremote
py boat_monitor\usb_recovery_push.py %*
