# Boat Monitor P2 — Phased Build Plan

Companion to `Boat_Monitor_P2_Design_v7.docx`. Work **one phase at a time**; do not start the next phase until exit criteria are all checked.

---

## How to see and use checkboxes

1. Open this file in the **editor** tab (not Preview only) — click the filename so you see raw markdown.
2. Check tasks by changing `[ ]` to `[x]`, or click the box in the gutter if Cursor shows one.
3. Preview (`Ctrl+Shift+V`) shows ☐ / ☑ but editing is easier in the source tab.
4. Use **Outline** or `Ctrl+F` → `## Phase 0` to jump.

**Tip:** Collapse completed phases in the editor (fold headings) and only expand your current phase.

---

## Progress dashboard (phases)

- [ ] **Phase 0** — Foundations
- [x] **Phase 1** — Cellular bench (done on desk)
- [ ] **Phase 2** — Cellular → Google Sheets
- [ ] **Phase 3** — GPS
- [ ] **Phase 4** — INA sensors
- [ ] **Phase 5** — Bilge inputs
- [ ] **Phase 6** — Winter storage mode
- [ ] **Phase 7** — Mode detection + boating
- [ ] **Phase 8** — iOS app
- [ ] **Phase 9** — Field install
- [ ] **Phase 10** — SMS status (optional)

**Current focus:** Phase 0 → Phase 2.

---

**Bench references:** `remotebatterystatus/main.py` (P1 only). Cellular bench notes are in design doc / Phase 1 (done).

**Pin map (v7 §2.4):** GP0/1 debug · GP2–3 bilge pumps · GP4/5 UART1 modem · GP6/7 floats · GP8/9 I2C · GP10 switch · GP14 modem reset

**APN default:** `iot.t-mobile.com` + IPv6 + `AT+CSOCKSETPN=1,6`

---

## Optional: SMS wake / status (Phase 10)

Text boat SIM → status reply. Validate T-Mobile IoT allows inbound SMS first.

**Phase 10 steps (later):**

- [ ] 10.1 Confirm SMS to SIM works (`AT+CMGF=1`, `AT+CMGL`)
- [ ] 10.2 `sms_poll()` on hourly wake (lowest power)
- [ ] 10.3 Keyword + PIN parser (`STATUS 1234`)
- [ ] 10.4 `sms_reply()` ≤160 chars (volts, mode, bilge)
- [ ] 10.5 Field test; measure extra mAh/week

Hook: commented `check_inbound_sms()` after `NETOPEN` in `modem.py` when you build Phase 2.

---

## Phase 0 — Foundations (no boat wiring)

**Goal:** Pin map, config schema, Google endpoint v2, modem recipe on PC.

### Steps

- [ ] **0.1** Copy pin table to `boat_monitor/PIN_MAP.md` _(Repo)_
- [ ] **0.2** Fix v7 doc: §2.1 UART → GP4/5; §7.4 I2C → GP8/9 _(Doc)_
- [ ] **0.3** Create `boat_monitor/` + `main.py` prints version/pins _(Pico)_
- [ ] **0.4** `config.py`: WiFi, Pushover, APN, GPIO, I2C `0x40`/`0x41`/`0x44` _(Pico)_
- [ ] **0.5** `modem_pc_test.py` AT sequence in `boat_monitor/` _(PC, when modem wired)_
- [ ] **0.6** Sheet tabs: `Power_Log`, `GPS_Log`, `Bilge_Log`, `Events`, `Config` _(Sheets)_
- [ ] **0.7** Apps Script POST JSON `{ tab, data }` → `{ ok: true }` _(Apps Script)_
- [ ] **0.8** Apps Script read Config thresholds _(Apps Script)_
- [x] **0.9** Production Apps Script URL committed; env override remains available _(Repo)_
- [ ] **0.10** `internet_acceptance_test.py --sheets "<url>"` passes _(PC)_

### Tests

- [ ] Postman/curl POST → row in `Power_Log`
- [ ] `internet_acceptance_test.py` all core checks green
- [ ] `boat_monitor` imports on Pico (no hardware)

### Exit criteria

- [ ] Pin map frozen; no GP4/5 I2C conflict
- [ ] Cellular POST to your script returns 200 from PC
- [ ] P1 `remotebatterystatus` unchanged

---

## Phase 1 — Cellular bench ✓

**Goal:** SIM7600 + T-Mobile + HTTPS + GPS on desk — **done**.

### Optional cleanup

- [ ] **1.1** Document production APN in `DEPLOY_NOTES.md`
- [ ] **1.2** Archive `deploy_battery_results.txt` with date

### Exit criteria

- [x] Bench acceptance met (`deploy_battery_results.txt`)

---

## Phase 2 — Cellular → Google Sheets

**Goal:** JSON row to `Power_Log` via LTE; repeatable cold boot.

### Steps

- [ ] **2.1** Define POST body `{ "tab": "Power_Log", "data": { "event": "phase2_test" } }`
- [ ] **2.2** PC POST via `internet_acceptance_test.py --sheets`
- [ ] **2.3** If HTTP* fails, try `ssl_https_post` (`AT+CCH*`); record winner
- [ ] **2.4** Teardown every time: `HTTPTERM` → `NETCLOSE` (document in `modem.py`)
- [ ] **2.5** PC cold boot ×3: power cycle → register → NETOPEN → POST
- [ ] **2.6** Extract `modem.py`: `netopen()`, `https_post()`, `modem_shutdown()`
- [ ] **2.7** Pico UART GP4/5: `modem_at_test.py` → `AT` OK
- [ ] **2.8** Pico `NETOPEN` only; log seconds
- [ ] **2.9** Pico one HTTPS POST (URL in `config.py`)
- [ ] **2.10** `upload_cell()` with 120 s timeout; no hang on fail
- [ ] **2.11** Always call `modem_shutdown()` / `CPWROFF` after upload

### Tests

- [ ] PC POST → `Power_Log` row + script ok
- [ ] 3× PC cold boot POST → 3/3 success
- [ ] Pico POST once → row appears
- [ ] Pico POST after `CPWROFF` + power cycle → success
- [ ] Wrong URL → Pico recovers &lt; 120 s

### Exit criteria

- [ ] 5 consecutive PC cold-boot POSTs succeed
- [ ] 3 consecutive Pico POSTs succeed
- [ ] Teardown used every run

**Do not start Phase 3+ until Phase 2 exit criteria are checked.**

---

## Phase 3 — GPS

**Goal:** Parse `AT+CGPSINFO`; one `GPS_Log` row via cellular.

### Steps

- [ ] **3.1** PC: `AT+CGPS=1,1`, poll `AT+CGPSINFO` up to 90 s
- [ ] **3.2** `parse_cgpsinfo()` → lat, lon, speed, heading, fix_ok
- [ ] **3.3** Outdoor: 10 fixes; log cold vs warm time
- [ ] **3.4** PC POST one row to `GPS_Log`
- [ ] **3.5** `gps.py`: `gps_on()`, `gps_read()`, `gps_off()`
- [ ] **3.6** Pico: GPS after `NETOPEN`
- [ ] **3.7** Pico: POST GPS fields; `gps_off()` before `CPWROFF`
- [ ] **3.8** On `NETOPEN` fail: log `fix_quality=0`, skip GPS

### Tests

- [ ] Outdoor fix: valid lat/lon (not 0,0)
- [ ] Parser: 3 sample `+CGPSINFO` strings
- [ ] `GPS_Log` row has speed/heading
- [ ] Indoor warm fix &lt; 15 s (after outdoor session)

### Exit criteria

- [ ] 9/10 outdoor fixes parse OK
- [ ] 3/3 Pico cycles upload GPS when sky view OK

---

## Phase 4 — INA sensors (bench)

**Goal:** I2C GP8/9; addresses `0x40`, `0x41`, `0x44`.

### Steps

- [ ] **4.1** Strap INA260 #1→`0x40`, #2→`0x41`, INA219→`0x44`
- [ ] **4.2** Wire SDA/SCL GP8/GP9 + GND
- [ ] **4.3** Port INA classes from P1; correct addresses
- [ ] **4.4** `i2c_scan()` → exactly three devices
- [ ] **4.5** House V vs multimeter (±0.1 V)
- [ ] **4.6** Engine V; simulate &gt; 13.5 V “alternator”
- [ ] **4.7** Solar current sign documented
- [ ] **4.8** INA219 reads V50/USB bank
- [ ] **4.9** 10 min @ 1 Hz — no crashes
- [ ] **4.10** _(Optional)_ POST via WiFi to `Power_Log`

### Tests

- [ ] Scan: 3 devices only
- [ ] Voltage within ±0.1 V
- [ ] V &gt; 13.5 sets “engine running” flag in test
- [ ] 10 min soak pass

### Exit criteria

- [ ] All three sensors reliable on one bus
- [ ] I2C only on GP8/9

---

## Phase 5 — Bilge inputs

**Goal:** Opto → GPIO + RUN; IRQ + deep-sleep wake.

### Steps

- [ ] **5.1** Opto Ch1–4 → GP2, GP3, GP6, GP7 (active-LOW)
- [ ] **5.2** Shared node → 10kΩ → RUN (open-collector verified)
- [ ] **5.3** `bilge.py`: `read_pins()`, debounce if needed
- [ ] **5.4** Always-on: IRQ on pump edges
- [ ] **5.5** Log pump start/stop + duration on serial
- [ ] **5.6** `boot_reason.txt`: write `rtc` before scheduled sleep
- [ ] **5.7** Deep sleep: RUN pulse → boot → `boot_reason=bilge`
- [ ] **5.8** Float LOW → Pushover (PC script first)
- [ ] **5.9** Pump &gt; 60 s → alert on stop
- [ ] **5.10** POST bilge event to `Bilge_Log`

### Tests

- [ ] Simulated pump LOW → IRQ + duration OK
- [ ] RUN wake from deep sleep → bilge boot reason
- [ ] Float → Pushover received
- [ ] RUN pulse while awake → no bad reset (note if it happens)

### Exit criteria

- [ ] Bilge wake identifiable on boot
- [ ] 1 h IRQ soak pass (in-season stub)

---

## Phase 6 — Winter storage mode

**Goal:** Hourly RTC; day upload / night bilge-only; WiFi → cell fallback.

### Steps

- [ ] **6.1** `modes.py`: `MODE_WINTER` only
- [ ] **6.2** RTC alarm every 60 min
- [ ] **6.3** Read Config day window (e.g. 6:00–21:00)
- [ ] **6.4** Night wake: bilge only, then sleep
- [ ] **6.5** Day wake: INAs → WiFi → POST `Power_Log`
- [ ] **6.6** WiFi fail → cellular POST → `CPWROFF`
- [ ] **6.7** Bilge handling on day wake before upload
- [ ] **6.8** Write `boot_reason` before each `deepsleep`
- [ ] **6.9** LED fail-count pattern (like P1)
- [ ] **6.10** 24 h desk soak log

### Tests

- [ ] RTC wake within ±2 min
- [ ] Night: no WiFi/cell activity
- [ ] Day + WiFi: hourly sheet row
- [ ] Day + WiFi blocked: cell fallback row
- [ ] Night bilge: RUN → Pushover → sleep
- [ ] 24 h average current measured (~2–3 mA target)

### Exit criteria

- [ ] 24 h soak without manual reset
- [ ] Day uploads working (12 in 24 h or scaled test)
- [ ] Bilge wake tested once

**Optional stop:** deploy “winter beta” here before Phase 7.

---

## Phase 7 — Mode detection + boating

### 7A — Detection only

- [ ] **7A.1** GP10 switch (active-LOW = ON)
- [ ] **7A.2** Underway: engine V &gt; 13.5 V × 3 samples
- [ ] **7A.3** Exit underway: V &lt; 13.5 V × 3 samples
- [ ] **7A.4** Anchor: switch ON + 12.0–13.5 V
- [ ] **7A.5** End-of-day: switch ON + stationary 30 min
- [ ] **7A.6** Mode changes → `Events` tab
- [ ] **7A.7** Hardware watchdog enabled

### 7B — Underway GPS

- [ ] **7B.1** `MODE_UNDERWAY`: GPS every 30 s
- [ ] **7B.2** POST `GPS_Log` without NETOPEN every 30 s (keep session or batch)
- [ ] **7B.3** Battery V every 5 min → `Power_Log`
- [ ] **7B.4** Field: short drive/dock test

### 7C — Anchor watch

- [ ] **7C.1** On anchor entry: save lat/lon
- [ ] **7C.2** Haversine each GPS tick
- [ ] **7C.3** Drift &gt; 50 m → Pushover
- [ ] **7C.4** `anchor_radius_m` from Config tab

### 7D — End-of-day

- [ ] **7D.1** Pushover: switch may be left on
- [ ] **7D.2** Log every 5 min until switch OFF
- [ ] **7D.3** Switch OFF → `CPWROFF`, toward winter behavior

### Tests

- [ ] Mode FSM script → correct modes
- [ ] 13.48 V hold → no mode flapping
- [ ] Walk 60 m from anchor → drift alert
- [ ] 30 min EOD timer fires once

### Exit criteria

- [ ] 7A–7D each tested alone, then combined
- [ ] One full day on water

---

## Phase 8 — iOS app

### Steps

- [ ] **8.1** Apps Script read API (latest + 24 h series)
- [ ] **8.2** Screen: Boat Status
- [ ] **8.3** Screen: Power Dashboard
- [ ] **8.4** Screen: Location / Map
- [ ] **8.5** Screen: Bilge Status
- [ ] **8.6** Screen: Settings (view-only thresholds)
- [ ] **8.7** _(Optional)_ BLE config update

### Exit criteria

- [ ] App shows live sheet data from boat
- [ ] Threshold tweaks via sheet only (no app release)

---

## Phase 9 — Field install

### Steps

- [ ] **9.1** Label harness (v7 §7)
- [ ] **9.2** INA260 in solar + leads (not battery −)
- [ ] **9.3** TPS2113A: switch ON charges V50 + feeds Pico
- [ ] **9.4** LTE + GPS antennas routed
- [ ] **9.5** Winter mode 48 h monitor
- [ ] **9.6** In-season modes one at a time
- [ ] **9.7** Tune Config thresholds
- [ ] **9.8** As-built photos + pin map in repo

### Exit criteria

- [ ] Sign-off: winter + one boating weekend

---

## Log template (copy per test run)

```text
Phase: __
Date: __
Hardware: Pico / modem / sensors
APN: iot.t-mobile.com
NETOPEN: __ s
POST: OK / FAIL
Notes:
```
