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

1. Open your **"Boat Monitor"** spreadsheet.
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

### Important: publishing updates later

If you pull newer `Code.gs` from this repo (for example Pacific-time
timestamps instead of raw `2026-08-06T01:30:36Z` text), **saving the
file in the Apps Script editor is not enough**. The Pico still hits the
**last deployed Web App version**.

1. **Extensions → Apps Script** → paste the updated `Code.gs`.
2. **Deploy → Manage deployments**.
3. Click the **pencil** on the active Web app deployment.
4. **Version:** choose **New version** (not "Head").
5. **Deploy**.

Verify from a PC:

```bash
curl -sL "$GOOGLE_APPS_SCRIPT_URL" | python3 -m json.tool
```

You want `"receiver_version": 3` (or higher) for remote Config commands on each log POST (see `REMOTE_CONTROL.md`). Version `2` logs rows only. **Version `4`+** adds `GET ?action=dashboard&token=...` for the iOS app’s away-from-boat view. If that field is missing,
the live deployment is still old and new log rows will keep ISO text
timestamps until you redeploy.

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

## 3c. Test cellular connectivity by itself first (no Sheets setup needed)

Before involving Sheets/Apps Script at all, confirm the modem + SIM +
antenna + registration sequence works on its own:

```python
import cellular_test
cellular_test.main()
```

This runs `cellular.py`'s hardened sequence (modem-alive check, SIM check,
network registration wait with signal logged throughout, `NETOPEN`, one
retry if it errors) and finishes with a real HTTP GET of the OTA manifest.
If this fails, it'll tell you specifically **why** (not responding / no
SIM / not registered / NETOPEN failed) instead of the generic "cellular
data did not open" every earlier attempt produced — that generic message
came from skipping the registration wait entirely, which is very likely
why every previous attempt failed the same way regardless of antenna.

## 4. Test one real cellular POST from the Pico (Phase 2.9)

`sheets_log_test.py` forces cellular (skips Wi-Fi even if configured) —
it exists specifically to test this path. Run `cellular_test.py` above
first; if that passes, this should too.

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

## Three different ways this gets tested/used (don't confuse them)

| | Trigger | Transport | When to use |
|---|---|---|---|
| **Bench test** | `sheets_log_test.py` via Thonny/USB | Wi-Fi first, cellular fallback | At your desk, laptop plugged in |
| **BLE "Log Now"** | Tap **Log Now** in the app (BLE command `log`) | **Cellular only** (`prefer_wifi=False`) | Once it's mounted on the boat — no laptop there, but your phone over BLE always works. Forces cellular specifically because Wi-Fi and BLE share one radio; trying Wi-Fi while BLE is connected would drop the very connection you're using to trigger it. |
| **Automatic periodic logging** | *(not built yet)* | — | Phase 6 (winter storage, hourly RTC wake) / Phase 7B (underway GPS every 30s) in `BOAT_MONITOR_P2_PLAN.md`. This is what would eventually log without you doing anything — it doesn't exist yet. |

**Log Now** only posts `Power_Log` (current voltage/current/mode) — no GPS, kept
intentionally fast (GPS fixes can take up to 90s, which would leave the BLE
connection quiet for way too long). Result shows up in the app's `Raw BLE`
panel as `"command_result": "logged"` or `"log_failed: ..."` once the
cellular POST finishes (typically 10–60s depending on modem/network).

The same `prefer_wifi=False` fix was needed for the existing **OTA** BLE
command too — it was about to inherit the same Wi-Fi-vs-BLE conflict once
Wi-Fi-first landed in `ota.py`. Both are fixed now.

## What's intentionally *not* wired in yet

`gps.py` and `sheets_log.py` are **not** called from `main.py`'s boot flow
or from a BLE command yet — they're opt-in modules you run manually via
Thonny for bench testing, matching where Phase 2/3 sit in
`BOAT_MONITOR_P2_PLAN.md` (not yet checked off). Wiring periodic
GPS+cellular logging into the always-on flow is Phase 7B ("Underway GPS")
and depends on Phase 2/3's exit criteria passing first — outdoor GPS fixes
and repeatable cold-boot cellular POSTs, which need to happen on your bench
and boat, not from here.
