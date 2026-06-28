# Boat Monitor P2 — As-Built Wiring Notes

**Print:** [`WIRING_CHEAT_SHEET.docx`](WIRING_CHEAT_SHEET.docx)

---

## Optocoupler → Pico (locked)

| Opto | Signal | Pico pin | GPIO | RUN? |
|------|--------|----------|------|------|
| OUT1 | Mid bilge pump | **31** | GP26 | Yes |
| OUT2 | Aft bilge pump | **29** | GP22 | Yes |
| OUT3 | Mid water float | **25** | GP19 | Yes |
| OUT4 | Aft water float | **24** | GP18 | Yes |
| OUT5 | Battery Switch | **26** | GP20 | No |
| OUT6 | Key | **27** | GP21 | No |
| OUT7–8 | Spare | **21, 22** | GP16–17 | No |

**RUN:** OUT1–4 → shared node → 10kΩ → pin **30**.  
**GND:** all opto IN− and output GND → common ground bus.

---

## Modem

| Signal | Pin | GPIO |
|--------|-----|------|
| RXD | 11 | GP8 |
| TXD | 12 | GP9 |
| RST | 14 | GP10 |

---

## VSNS

Pin **15** (GP11) — `Pin(11, Pin.OUT)` + `value(0)`

---

## Sensors

| Label | Role | SDA/SCL pins | Address |
|-------|------|--------------|---------|
| Middle | House | 4 / 5 | 0x40 |
| Bottom | Engine | 1 / 2 | 0x40 |
| INA219 | V50 | 6 / 7 | 0x40 |

---

## Firmware (`config.py`)

```python
PIN_TPS_STAT = 6
PIN_TPS_VSNS = 11

PIN_UART_TX, PIN_UART_RX = 8, 9
PIN_MODEM_RESET = 10

PIN_BILGE_MID = 26      # pin 31
PIN_BILGE_AFT = 22      # pin 29
PIN_FLOAT_MID = 19      # pin 25
PIN_FLOAT_AFT = 18      # pin 24
PIN_BATTERY_SWITCH = 20 # pin 26
PIN_KEY = 21            # pin 27
```

---

## Change log

| Date | Note |
|------|------|
| 2026-06-18 | Opto pins: 31/29 bilge, 25/24 water, 26 switch, 27 key |
