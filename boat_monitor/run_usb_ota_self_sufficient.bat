@echo off
REM OTA self-sufficient USB kit — full dock-fix stack + flash policy for week-away OTA.
REM Close Thonny first. Default COM7.
cd /d "%~dp0\.."
git pull
py -m pip install -q mpremote
py boat_monitor\usb_recovery_push.py --ota-self-sufficient --enable-boot-ota %*
