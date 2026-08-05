"""
Boat Monitor P2 - bench test: does the modem survive AT+CPOWD (power down)
and come back via the existing reset() sequence?

Why this matters: turning the modem fully off between logging cycles
(instead of leaving it powered and registered/searching the whole time,
which is what happens today) would save real power -- probably MORE than
the Pico's own continuous-awake draw, since cellular modems commonly pull
more current idle-registered than a microcontroller does. But AT+CPOWD is
a real power-down, not a soft reset -- if the RST pin wired to this modem
(config.py's PIN_MODEM_RESET) is a true hardware RESET line rather than
the module's PWRKEY, the existing reset() sequence (a brief LOW pulse then
HIGH) may NOT be enough to bring it back from AT+CPOWD's power-off state.
Many SIM7600 modules specifically require a PWRKEY toggle to power back
on -- a reset line alone does not power on a module that is fully off.

This is exactly the kind of thing to validate on the bench, with a PC
connected and ready to physically power-cycle everything if the modem
doesn't come back, BEFORE trusting it in the unattended automatic logging
flow (auto_log.py) where nobody would be around to notice or recover it.

Usage: run in Thonny. Watch for either:
  "PASS: modem woke up after AT+CPOWD"  -- safe to consider wiring this
      into the automatic logging flow for real power savings.
  "FAIL: modem did not respond after AT+CPOWD ..." -- do NOT wire this
      into auto_log.py as-is; the pin is likely a plain RESET, not
      PWRKEY, and powering the modem off this way would need a physical
      power cycle (or a wiring change) to recover.

If it fails, you will likely need to physically power-cycle the modem
(unplug/replug its 5V, or toggle whatever supplies it) to get AT
responses again -- have that access ready before running this.
"""

import time

from cellular import Sim7600Modem


def main():
    print("Boat Monitor - modem power-down/wake test")
    modem = Sim7600Modem()

    print("Step 1: confirm the modem responds normally first...")
    modem.check_alive()
    print("OK -- modem responds to AT.")

    print()
    print("Step 2: sending AT+CPOWD=1 (graceful power down)...")
    try:
        resp = modem.at("AT+CPOWD=1", 15000)
        print("Response:", resp.strip() or "(no response)")
    except Exception as exc:
        print("AT+CPOWD=1 itself failed to send/respond:", exc)

    print("Waiting 5s for the module to fully power off...")
    time.sleep(5)

    print()
    print("Step 3: attempting to wake it via the normal reset() sequence...")
    modem.reset()

    print("Step 4: checking if it responds to AT now...")
    try:
        modem.check_alive()
        print()
        print("PASS: modem woke up after AT+CPOWD via reset().")
        print("Safe to consider wiring AT+CPOWD-based power-down into the")
        print("automatic logging flow (auto_log.py) for real power savings.")
    except Exception as exc:
        print()
        print("FAIL: modem did not respond after AT+CPOWD within the reset timeout.")
        print("Reason:", exc)
        print()
        print("This likely means config.py's PIN_MODEM_RESET is wired to a plain")
        print("RESET line, not the module's PWRKEY -- reset() alone can't power")
        print("a module back ON once AT+CPOWD has powered it fully off.")
        print("Do NOT wire AT+CPOWD into auto_log.py without either:")
        print("  - confirming which physical pin actually IS PWRKEY on this module")
        print("    and wiring/controlling that separately, or")
        print("  - physically power-cycling the modem now to recover it.")


if __name__ == "__main__":
    main()
