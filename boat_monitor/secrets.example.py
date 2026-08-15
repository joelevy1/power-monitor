# Copy this file to secrets.py in THIS folder (boat_monitor/secrets.py).
# It is NOT in git — .gitignore blocks secrets.py so keys never get committed.
# On the Pico: copy the same secrets.py to the Pico filesystem (Thonny → Save As).
# Template only: boat_monitor/secrets.example.py

# Google Sheets (service account, PC-only — see SHEETS_SETUP.md)
BOAT_MONITOR_SHEET_ID = ""
# Legacy name (still supported):
GOOGLE_SHEETS_ID = ""
GOOGLE_SERVICE_ACCOUNT_FILE = r""

# Google Sheets via Apps Script Web App (Pico + PC — see APPS_SCRIPT_SETUP.md)
GOOGLE_APPS_SCRIPT_URL = ""
SHEETS_POST_TOKEN = ""
