@echo off
REM Clear flash OTA backoff and set auto_ota_on_boot=true on Pico (COM7). Close Thonny first.
cd /d "%~dp0\.."
py -m pip install -q mpremote
set PORT=COM7
if not "%~1"=="" set PORT=%~1
set SCRIPT=%~dp0usb_recovery_patch_enable_ota.py
if not exist "%SCRIPT%" (
  echo Missing %SCRIPT% — run: git fetch origin && git merge origin/master
  exit /b 1
)
py -m mpremote connect %PORT% run "%SCRIPT%"
if errorlevel 1 exit /b 1
py -m mpremote connect %PORT% exec "import machine; machine.soft_reset()"
if errorlevel 1 exit /b 1
echo.
echo Done. Expect: remote_boot_config patched: auto_ota_on_boot=True pending_ota=True
echo Unplug USB, power cycle once, key ON.
