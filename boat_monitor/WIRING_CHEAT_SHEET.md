# Boat Monitor P2 — Wiring Guide (minimal changes)

**middle = HOUSE · bottom = ENGINE · three I2C buses · no A0/A1 changes**

**Print:** `WIRING_CHEAT_SHEET.docx` (regenerate: `python3 boat_monitor/build_cheat_sheet_docx.py`) or export PDF from Word.

---

## Policy: no more moving existing wires

Everything in **Section 1** stays where it is. What’s left is **new** connections only — loose pigtails, modem, opto, PlusRoc, boat harness. **No hard requirement to move anything else.**

The VSNS move to **pin 15** you already did is **fine** (works the same as pin 16). Leave it there.

---

# SECTION 1 — ALREADY DONE (do not change)

| Pico pin | GPIO | Connected to |
|----------|------|--------------|
| **39** | VSYS | TPS2113A **OUT** |
| **38** | GND | GND rail |
| **36** | 3V3 | + rail → sensor **Vcc** |
| **1** | GP0 | Engine INA260 **SDA** |
| **2** | GP1 | Engine INA260 **SCL** |
| **4** | GP2 | House INA260 **SDA** |
| **5** | GP3 | House INA260 **SCL** |
| **6** | GP4 | INA219 **SDA** |
| **7** | GP5 | INA219 **SCL** |
| **9** | GP6 | TPS **STAT** |
| **15** | GP11 | TPS **VSNS** *(you moved here — keep)* |
| **17** | GP13 | Red LED |
| **19** | GP14 | Blue LED |
| **20** | GP15 | Green LED |

**Power (done):** `V50 USB+ → INA219 → TPS IN1 → pin 39`

**Also done:** INA260 A0/A1 untouched · I2C on pins 1–7 untouched

**INA260 power terminals** (Adafruit silkscreen — no “OUT” pin):

| Terminal | High-side wiring (this project) |
|----------|----------------------------------|
| **VIN+** | **House +**, **Engine +**, solar **+** — also tee both water float **12 V** wires here |
| **VIN−** | Load / distribution side (solar return leg, other loads) |

Current flows **VIN+ → VIN−** when the bank is discharging. VIN+ and VIN− are both ~12 V when the switch is on; only a few mV differ across the internal shunt.

**Firmware for VSNS:** use **`Pin(11, Pin.OUT)`** + `value(0)` — matches **pin 15**.

---

# SECTION 2 — STILL TO DO (new connections only)

Nothing below requires unsoldering an existing wire.

## SIM7600X

**HAT jumpers:** UART = **B** · PWR = **PWR–3V3** · VCCIO = **3.3V** · Flight = **NC**

| Modem | Connect to |
|-------|------------|
| **5V** | 5V rail — **not** pin 36 |
| **GND** | GND rail |
| **RXD** | Pico pin **11** *(pigtail)* |
| **TXD** | Pico pin **12** *(pigtail)* |
| **RST** | Pico pin **14** *(same side as 11, 12)* |
| Antennas | MAIN U.FL / GNSS SMA |

**Modem cluster (one side):** pins **11, 12, 14** + 5V/GND from diode bus.

---

## Optocoupler

### INPUT side (boat 12 V)

| Opto IN | Boat wire |
|---------|-----------|
| Ch1 IN+ | Mid bildge |
| Ch2 IN+ | Aft bilgde |
| Ch3 IN+ | Mid water (return) |
| Ch4 IN+ | Aft water (return) |
| Ch5 IN+ | **Switch** *(also → PlusRoc IN+)* |
| Ch6 IN+ | **Key** |
| All IN− | Ground bus |

### OUTPUT side (Pico 3.3 V)

| Opto OUT | Pico pin | Signal | → RUN? |
|----------|----------|--------|--------|
| VCC | 3.3V rail | | |
| GND | GND rail (same as IN− bus) | | |
| **OUT1** | **31** | Mid bilge pump | Yes |
| **OUT2** | **29** | Aft bilge pump | Yes |
| **OUT3** | **25** | Mid water float | Yes |
| **OUT4** | **24** | Aft water float | Yes |
| **OUT5** | **26** | Battery **Switch** | No |
| **OUT6** | **27** | **Key** | No |
| OUT7–8 | **21, 22** | Spare | No |

Jumpers = **pull-up**. **RUN wake:** OUT1–4 (pins 31, 29, 25, 24) → shared node → **10kΩ** → pin **30**.

**Water floats (2 wires each):** One wire of each float → **House +** (same node as middle INA260 **VIN+**). Other wire → Opto Ch3/4 **IN+** → Pico pins **25** / **24** when float closes.

---

## PlusRoc 12 V → 5 V

| PlusRoc | Connect to |
|---------|------------|
| IN+ | Boat **Switch** |
| GND | Ground bus |
| OUT+ 5V | TPS **IN2** + **V50 USB-C charge in** + modem 5V *(via diodes)* |

### V50 power bank — three ports

| V50 port | Direction | Connect to |
|----------|-----------|------------|
| **USB-A #1** | OUT → Pico path | INA219 Vin+ → TPS IN1 → VSYS *(done)* |
| **USB-A #2** | OUT → modem | **+** through diode → modem 5V bus; **−** → ground |
| **USB-C** | **IN** (recharge bank) | **+** ← PlusRoc **OUT+** direct *(no diode)*; **−** → ground |

Use a **USB-C break-in cable** or pigtail — only **5V + GND** needed; data pins NC.

**When does USB-C charge?** PlusRoc runs when the **master Switch** is ON (12 V on PlusRoc IN+). In normal boating you’ll have switch + key on together; the **Key** wire only **senses** ignition on pin 27 — it does **not** feed PlusRoc today. If you need charge **only** when key is on (switch off), that would need a different 12 V feed or a relay — say so and we can sketch it.

**Do not** tie USB-C into the USB-A #1 Pico path or modem diode bus backwards.

---

## Switch vs Key

| Wire | Meaning |
|------|---------|
| **Switch** | Master battery ON — powers PlusRoc |
| **Key** | Ignition ON even if engine not charging |

---

## Checklist

| ☐ | New connection only |
|---|---------------------|
| ☐ | Modem → 5V, GND, pins **11, 12, 14** |
| ☐ | Opto → pins **21, 22, 24–27, 29, 31** + RUN 10kΩ |
| ☐ | PlusRoc |
| ☐ | 16 boat wires |

---

# SECTION 3 — Final pin map

| Pin | Status | Goes to |
|-----|--------|---------|
| 1–7, 9, 15, 17, 19–20, 39 | **DONE** | I2C, STAT, VSNS, LEDs, VSYS |
| 11–12, 14 | TODO | Modem UART + RST |
| **24** | TODO | Opto OUT4 aft water |
| **25** | TODO | Opto OUT3 mid water |
| **26** | TODO | Opto OUT5 Switch |
| **27** | TODO | Opto OUT6 Key |
| **29** | TODO | Opto OUT2 aft bilge |
| **31** | TODO | Opto OUT1 mid bilge |
| **21–22** | spare | Opto Ch7–8 |
| 30 | TODO | RUN 10kΩ (from OUT1–4) |

---

# SECTION 4 — 16 boat wires

| # | Label | Connect to |
|---|-------|------------|
| 1 | Engine + | Bottom INA260 **VIN+** |
| 2 | Engine − | Bottom GND + ground bus |
| 3 | House + | Middle INA260 **VIN+** *(tee both float 12 V wires here too)* |
| 4 | House − | Middle GND + ground bus |
| 5 | Mid bildge | Opto Ch1 IN+ |
| 6 | Aft bilgde | Opto Ch2 IN+ |
| 7 | Key | Opto Ch6 IN+ |
| 8 | Switch | PlusRoc IN+ + Opto Ch5 IN+ |
| 9 | Mid water | **House +** *(same node as wire 3 / VIN+)* |
| 10 | Mid water | Opto Ch3 IN+ |
| 11–12 | Solar engin | Bottom INA260 **VIN+** / **VIN−** |
| 13–14 | Solar hous | Middle INA260 **VIN+** / **VIN−** |
| 15–16 | Aft water | **House +** (wire 15) + Opto Ch4 IN+ (wire 16) |

---

*Detail: `AS_BUILT_WIRING.md`*
