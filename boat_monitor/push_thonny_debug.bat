# Copy Thonny debug scripts to the Pico (close Thonny first, then reopen after).

@echo off
cd /d "%~dp0\.."
set PORT=COM7
py -m pip install -q mpremote
py -m mpremote connect %PORT% cp boat_monitor\thonny_usb_debug.py :thonny_usb_debug.py
echo.
echo Copied thonny_usb_debug.py to Pico. Open Thonny on %PORT% and Run thonny_usb_debug.py
