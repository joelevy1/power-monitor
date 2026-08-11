@echo off
REM Clear flash OTA backoff and set auto_ota_on_boot=true on Pico (COM7). Close Thonny first.
cd /d "%~dp0\.."
py -m pip install -q mpremote
set PORT=COM7
if not "%~1"=="" set PORT=%~1
py -m mpremote connect %PORT% cp boat_monitor\usb_recovery_patch_enable_ota.py :usb_recovery_patch_enable_ota.py
py -m mpremote connect %PORT% run :usb_recovery_patch_enable_ota.py
py -m mpremote connect %PORT% exec "import machine; machine.soft_reset()"
echo.
echo Done. Unplug USB, power cycle once, key ON.
