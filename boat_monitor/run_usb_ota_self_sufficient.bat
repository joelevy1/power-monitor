@echo off
REM Week-away USB kit — ENOMEM lean logging + OTA self-sufficient policy (fw 1.1.113+).
REM Close Thonny first. Default COM7.
cd /d "%~dp0\.."
git pull
py -m pip install -q mpremote
py boat_monitor\usb_recovery_push.py --ota-self-sufficient --enable-boot-ota %*
