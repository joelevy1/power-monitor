# Google Sheets logging from the Pico over cellular (Phase 2 + 3)

`SHEETS_SETUP.md` covers the **service-account** path (PC / cloud agent only).
This doc covers the **Apps Script Web App** path, which is what actually lets
the **Pico** log rows over cellular — signing a Google service-account JWT
directly on MicroPython is possible but heavy, so the Pico instead POSTs
plain JSON over HTTPS to a small script that runs under your own Google
account and does the Sheets write for it.

Do this **after** `SHEETS_SETUP.md`'s steps 1–4 (spreadsheet created, tabs +
headers via `sheets_bootstrap.py`).

`sheets_log.py` prefers **Wi-Fi** over cellular when a known network is
configured (see `wifi_uplink.py`) — no cellular data usage, no modem needed.
Configure networks in `wifi_credentials.py` (copy from
`wifi_credentials.example.py`, gitignored, e.g. your marina's Wi-Fi and your
home Wi-Fi for bench testing) — same file/setup as OTA's Wi-Fi-first
behavior in `OTA_UPDATE.md`. **Only run `sheets_log_test.py`/`ota.py` when
BLE is NOT active** — Wi-Fi and BLE share one radio on the Pico W and cannot
run at the same time.

---

## 1. Deploy the Apps Script Web App

1. Open your **"Boat Monitor Logs"** spreadsheet.
2. **Extensions → Apps Script**.
3. Delete the default `Code.gs` contents and paste in
   [`boat_monitor/apps_script/Code.gs`](./apps_script/Code.gs) from this repo.
4. **Project Settings** (gear icon, left sidebar) → **Script properties** →
   **Add script property**:
   - Property: `SHEETS_POST_TOKEN`
   - Value: any random string (e.g. generate one with
     `python3 -c "import secrets; print(secrets.token_hex(16))"`)
5. **Deploy → New deployment**:
   - Type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone** (the token in step 4 is what actually
     protects it — anyone without the token gets `{"ok": false, "error": "bad token"}`)
6. Click **Deploy**, authorize when prompted, then copy the **Web app URL**
   (ends in `/exec`).

## 2. Store the URL + token

Add both to `boat_monitor/secrets.py` (gitignored — same file as the
service-account settings from `SHEETS_SETUP.md`):

```python
GOOGLE_APPS_SCRIPT_URL = "https://script.google.com/macros/s/XXXXXXXX/exec"
SHEETS_POST_TOKEN = "the-same-random-string-from-step-1.4"
```

Copy this **same `secrets.py`** to the Pico's filesystem too (Thonny → Save
As → Raspberry Pi Pico) — `gps.py`/`sheets_log.py` read it the same way the
BLE service already reads `config.py`.

## 3. Test the receiving end from your PC first (no cellular needed)

This validates the Apps Script deployment over your normal internet
connection before you ever touch the modem — much faster to debug:

```bash
cd power-monitor
python3 boat_monitor/apps_script_test.py
```

Expect:

```text
OK: appended to Power_Log (row N)
OK: appended to GPS_Log (row N)
```

Check the spreadsheet — two new test rows should be there. If you get
`bad token`, double check the Script property matches `secrets.py` exactly
(no extra whitespace).

## 3b. (Optional) Set up Wi-Fi-first for the Pico

Copy `wifi_credentials.example.py` as `wifi_credentials.py` (Pico
filesystem, gitignored) and fill in real networks, tried in order:

```python
WIFI_NETWORKS = [
    ("Seattle Boat", "the-marina-wifi-password"),
    ("YourHomeSSID", "your-home-wifi-password"),
]
```

With this in place, `sheets_log_test.py` and `ota.update()` will connect to
whichever of these is in range instead of using cellular at all.

## 4. Test one real cellular POST from the Pico (Phase 2.9)

If no Wi-Fi network is configured/in range, `sheets_log_test.py` falls back
to cellular automatically — this section is for testing that path
specifically.

With the SIM7600 modem wired and powered, in Thonny:

```python
import sheets_log_test
sheets_log_test.main()
```

Expect `AT+NETOPEN` to succeed, one `Power_Log` row posted, then
`AT+NETCLOSE`. This mirrors Phase 2's exit criteria in
`BOAT_MONITOR_P2_PLAN.md` — run it 3 times to confirm it's repeatable
before wiring it into the always-on boot flow.

## 5. GPS (Phase 3)

`gps.py`'s parser is unit-tested without any hardware:

```bash
python3 boat_monitor/test_gps_parser.py
```

On the Pico, once the modem has a clear sky view outdoors:

```python
from gps import Gps
g = Gps()
g.on()
fix = g.read(timeout_s=90)   # polls AT+CGPSINFO every 5s
print(fix)                   # {"ok": True, "lat": .., "lon": .., "raw": ".."}
g.off()
```

Combine with `sheets_log.py` to log a real fix:

```python
from gps import Gps
from sheets_log import SheetsLogger

g = Gps()
logger = SheetsLogger()
logger.ensure_data()
g.on()
fix = g.read(timeout_s=90)
if fix["ok"]:
    logger.log_gps("boat-p2", fix["lat"], fix["lon"])
g.off()
logger.close_data()
```

## What's intentionally *not* wired in yet

`gps.py` and `sheets_log.py` are **not** called from `main.py`'s boot flow
or from a BLE command yet — they're opt-in modules you run manually via
Thonny for bench testing, matching where Phase 2/3 sit in
`BOAT_MONITOR_P2_PLAN.md` (not yet checked off). Wiring periodic
GPS+cellular logging into the always-on flow is Phase 7B ("Underway GPS")
and depends on Phase 2/3's exit criteria passing first — outdoor GPS fixes
and repeatable cold-boot cellular POSTs, which need to happen on your bench
and boat, not from here.
