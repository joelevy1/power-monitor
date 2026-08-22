# Google Sheets (service account — Option A)

Use this for **PC tests** and **cloud-agent** append/read. The spreadsheet is owned by you; the service account is a robot user that only accesses sheets you **share** with it.

You already enabled **Google Sheets API** on your GCP project. Finish the steps below, then run the PC test script.

---

## 1. Create the service account

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select your **boat monitor** project.
2. **IAM & Admin** → **Service accounts** → **+ Create service account**
3. **Service account name:** `boat-monitor-sheets` (or any name)
4. **Service account ID:** auto-filled (note it) → **Create and continue**
5. **Grant access (optional):** **skip** — you do **not** need a project IAM role for Sheets if you share the spreadsheet with the SA email in step 4. → **Done**

---

## 2. Create a JSON key

1. On the service accounts list, click **`boat-monitor-sheets@….iam.gserviceaccount.com`**
2. **Keys** tab → **Add key** → **Create new key** → **JSON** → **Create**
3. A file downloads (e.g. `boat-monitor-abc123.json`). Store it somewhere **outside** git, e.g.  
   `C:\dev\secrets\boat-monitor-sheets.json`

**Important:** Treat this file like a password. Never commit it or paste it in public chat.

From the JSON file, copy:

| Field | Used for |
|--------|-----------|
| `client_email` | Share the Google Sheet with this address |
| `private_key` | Stays inside the JSON file only |

Example `client_email`:

```text
boat-monitor-sheets@your-project-id.iam.gserviceaccount.com
```

---

## 3. Create the spreadsheet and tabs

1. [Google Sheets](https://sheets.google.com) → **Blank spreadsheet**
2. Name it **Boat Monitor**.
3. Add tabs (rename the default sheet and add others):

   | Tab name | Purpose |
   |----------|---------|
   | `Power_Log` | Voltage/current snapshots |
   | `GPS_Log` | Lat/lon fixes |
   | `Bilge_Log` | Bilge/float events |
   | `Events` | Alerts, mode changes |
   | `Config` | Thresholds / device settings (key-value) |

4. On **`Power_Log`**, row 1 headers (example):

   ```text
   timestamp_utc	device	mode	engine_v	engine_a	house_v	house_a	v50_v	note
   ```

5. **Share** the spreadsheet:
   - **Share** → paste **`client_email`** from the JSON → role **Editor** → uncheck “notify people” if offered → **Share**

The service account does **not** use your `@gmail.com` login; it only sees spreadsheets shared to `client_email`.

6. Copy the **Spreadsheet ID** from the URL:

   ```text
   https://docs.google.com/spreadsheets/d/THIS_PART_IS_THE_ID/edit
   ```

---

## 4. (Optional) Enable Google Drive API

Only needed if code will **create** spreadsheets via API. For a sheet you created manually, **Sheets API alone is enough**.

---

## 5. Store the service-account credential

### On your PC (local tests)

```powershell
# Example — adjust paths
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\dev\secrets\boat-monitor-sheets.json"
```

Or in `boat_monitor/secrets.py` (gitignored):

```python
GOOGLE_SERVICE_ACCOUNT_FILE = r"C:\dev\secrets\boat-monitor-sheets.json"
```

The production spreadsheet ID is committed in `sheets_bootstrap.py`; it is not
a secret. `BOAT_MONITOR_SHEET_ID` remains available as an optional override
when deliberately targeting another spreadsheet.

### For GitHub Actions / cloud agent

Repo → **Settings** → **Secrets and variables** → **Actions**:

| Secret name | Value |
|-------------|--------|
| `BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON` | Full boat service-account `.json` |

#### JSON in the GitHub web UI

The **Value** field accepts multiline JSON. Paste the **entire** key file. Do not put JSON in the **Name** field.

#### Easier: GitHub CLI from your PC (recommended)

```powershell
gh auth login
Get-Content C:\dev\secrets\boat-monitor-sheets.json -Raw | gh secret set BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON --repo joelevy1/power-monitor
```

#### Cursor cloud agent only

- **`BOAT_MONITOR_GOOGLE_SERVICE_ACCOUNT_JSON`** — **boat-monitor-sheets** JSON (power-monitor only).

---

## 5b. Automate tabs + headers (§3.3–3.4)

After the blank sheet exists and is **shared with the service account**:

- **GitHub:** Actions → **Bootstrap Google Sheets** → Run workflow  
- **Or PC/agent:** `python boat_monitor/sheets_bootstrap.py`

Creates: `Power_Log`, `GPS_Log`, `Bilge_Log`, `Events`, `Config` and writes header row 1 on each.

---

## 6. Verify with the PC test script

From repo root (Python 3.10+ on your PC):

```powershell
cd C:\dev\power-monitor
python -m venv .venv
.\.venv\Scripts\activate
pip install -r boat_monitor/requirements-sheets.txt
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\dev\secrets\boat-monitor-sheets.json"
python boat_monitor/sheets_test_append.py
```

You should see `OK: appended row to Power_Log` and a new row in the sheet.

---

## Pico / LTE note

Posting from the **Pico over cellular** with a service-account JWT is possible but heavy on MicroPython. This repo uses an **Apps Script Web App** for that instead — see **`APPS_SCRIPT_SETUP.md`** for the receiver (`apps_script/Code.gs`), the Pico-side modules (`gps.py`, `sheets_log.py`), and how to test both the receiving end (PC, `apps_script_test.py`) and one real cellular POST (Pico, `sheets_log_test.py`) — covers Phase 2 + 3 in `BOAT_MONITOR_P2_PLAN.md`.

---

## Checklist

- [ ] Service account created
- [ ] JSON key downloaded and stored safely
- [ ] Sheet created with tabs
- [ ] Sheet shared with `client_email` as **Editor**
- [ ] `sheets_test_append.py` succeeds

When the test passes, you can paste **only** the spreadsheet ID here (not the JSON key) if you want help wiring Pico logging next.
