#!/usr/bin/env python3
"""Generate WIRING_CHEAT_SHEET.docx — minimal-change wiring plan."""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from docx.oxml.ns import qn

OUT = Path(__file__).parent / "WIRING_CHEAT_SHEET.docx"


def margins(doc):
    for s in doc.sections:
        s.top_margin = Inches(0.4)
        s.bottom_margin = Inches(0.4)
        s.left_margin = Inches(0.45)
        s.right_margin = Inches(0.45)


def h(doc, text, level=2):
    doc.add_heading(text, level=level)


def p(doc, text, bold=False, size=8.5):
    par = doc.add_paragraph()
    r = par.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)


def tbl(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = hd
        for r in c.paragraphs[0].runs:
            r.bold = True
            r.font.size = Pt(8)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            c = t.rows[ri + 1].cells[ci]
            c.text = str(val)
            for r in c.paragraphs[0].runs:
                r.font.size = Pt(8)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph()


def main():
    doc = Document()
    margins(doc)

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Boat Monitor P2 — Wiring (Minimal Changes)")
    r.bold = True
    r.font.size = Pt(13)
    s = doc.add_paragraph()
    s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s.add_run("VSNS on pin 15 (done) · No more wire moves · New connections only").font.size = Pt(9)

    h(doc, "SECTION 1 — ALREADY DONE (do not change)", 1)
    tbl(doc, ["Pin", "Goes to"], [
        ("1, 2", "Engine INA260 SDA, SCL"),
        ("4, 5", "House INA260 SDA, SCL"),
        ("6, 7", "INA219 SDA, SCL"),
        ("9", "TPS STAT"),
        ("15", "TPS VSNS (you moved here — keep)"),
        ("17, 19, 20", "Red, Blue, Green LED"),
        ("39", "TPS OUT → VSYS"),
    ])
    p(doc, "Firmware: Pin(11) for VSNS. Do NOT change I2C or A0/A1. No more unsoldering.", bold=True, size=8)
    p(doc, "INA260 terminals: VIN+ = battery/source side. VIN− = load side (not “OUT”).", size=8)

    h(doc, "SECTION 2 — STILL TO DO", 1)

    h(doc, "SIM7600 (jumpers: UART=B, PWR=PWR-3V3, VCCIO=3.3V)")
    tbl(doc, ["Modem", "Connect to"], [
        ("5V", "5V rail"),
        ("GND", "GND rail"),
        ("RXD", "Pico pin 11"),
        ("TXD", "Pico pin 12"),
        ("RST", "Pico pin 14 (same side as UART)"),
    ])

    h(doc, "Optocoupler — INPUT side (12V boat)")
    tbl(doc, ["Opto IN", "Boat wire"], [
        ("Ch1 IN+", "Mid bildge"),
        ("Ch2 IN+", "Aft bilgde"),
        ("Ch3 IN+", "Mid water return"),
        ("Ch4 IN+", "Aft water return"),
        ("Ch5 IN+", "Switch (also → PlusRoc IN+)"),
        ("Ch6 IN+", "Key"),
        ("All IN−", "Ground bus"),
    ])

    h(doc, "Optocoupler — OUTPUT side (3.3V Pico)")
    tbl(doc, ["Opto OUT", "Pico pin", "Signal", "RUN?"], [
        ("OUT1", "31", "Mid bilge pump", "Yes"),
        ("OUT2", "29", "Aft bilge pump", "Yes"),
        ("OUT3", "25", "Mid water float", "Yes"),
        ("OUT4", "24", "Aft water float", "Yes"),
        ("OUT5", "26", "Switch", "No"),
        ("OUT6", "27", "Key", "No"),
        ("OUT7-8", "21, 22", "Spare", "No"),
    ])
    p(doc, "GND: common bus. RUN: OUT1-4 → 10kΩ → pin 30.", size=8)

    h(doc, "PlusRoc + V50 USB-C charge")
    tbl(doc, ["PlusRoc / V50", "Connect to"], [
        ("IN+", "Switch boat wire"),
        ("OUT+ 5V", "TPS IN2 + V50 USB-C charge IN (+)"),
        ("Modem 5V", "PlusRoc OUT+ and V50 USB-A #2 (+) each via diode"),
        ("GND", "Ground bus (all V50 −, PlusRoc IN−/OUT−)"),
    ])
    p(doc, "V50 USB-C = charge IN only (separate from USB-A #1 Pico and #2 modem).", size=8)

    h(doc, "Switch vs Key")
    p(doc, "Switch = master battery ON (powers boat). Key = ignition ON even if engine not charging.", size=8.5)

    h(doc, "Checklist")
    tbl(doc, ["☐", "Task"], [
        ("☐", "Modem 5V GND pins 11 12 14"),
        ("☐", "Opto + RUN 10kΩ"),
        ("☐", "PlusRoc"),
        ("☐", "16 boat wires (page 2)"),
    ], [0.25, 6.0])

    doc.add_page_break()

    h(doc, "SECTION 3 — Final pin map", 1)
    tbl(doc, ["Pin", "Status", "Goes to"], [
        ("1-7, 9, 15, 17-20, 39", "DONE", "I2C, STAT, VSNS, LEDs, VSYS"),
        ("11-12, 14", "TODO", "Modem"),
        ("21-22", "spare", "Opto Ch7-8"),
        ("24-27, 29, 31", "TODO", "Opto OUT1-6"),
        ("30", "TODO", "RUN 10k from OUT1-4"),
    ])

    h(doc, "SECTION 4 — 16 boat wires", 1)
    tbl(doc, ["#", "Label", "Connect to"], [
        ("1", "Engine +", "Bottom INA260 VIN+"),
        ("2", "Engine −", "Bottom GND + ground bus"),
        ("3", "House +", "Middle INA260 VIN+ + both float 12V wires"),
        ("4", "House −", "Middle GND + ground bus"),
        ("5", "Mid bildge", "Opto Ch1 IN+"),
        ("6", "Aft bilgde", "Opto Ch2 IN+"),
        ("7", "Key", "Opto Ch6 IN+"),
        ("8", "Switch", "PlusRoc IN+ + Opto Ch5 IN+"),
        ("9", "Mid water", "House + (same as wire 3)"),
        ("10", "Mid water", "Opto Ch3 IN+"),
        ("11", "Solar engin", "Bottom INA260 VIN+"),
        ("12", "Solar engin", "Bottom INA260 VIN−"),
        ("13", "Solar hous", "Middle INA260 VIN+"),
        ("14", "Solar hous", "Middle INA260 VIN−"),
        ("15", "Aft water", "House + (same as wire 3)"),
        ("16", "Aft water", "Opto Ch4 IN+"),
    ], [0.3, 1.0, 4.9])

    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
