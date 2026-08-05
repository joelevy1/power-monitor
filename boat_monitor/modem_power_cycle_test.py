"""
Boat Monitor P2 - bench test: does the modem survive AT+CPOF (power down)
and come back via the existing reset() sequence?

Why this matters: turning the modem fully off between logging cycles
(instead of leaving it powered and registered/searching the whole time,
which is what happens today) would save real power -- probably MORE than
the Pico's own continuous-awake draw, since cellular modems commonly pull
more current idle-registered than a microcontroller does. But a real
power-down is not a soft reset -- if the RST pin wired to this modem
(config.py's PIN_MODEM_RESET) is a true hardware RESET line rather than
the module's PWRKEY, the existing reset() sequence (a brief LOW pulse then
HIGH) may NOT be enough to bring it back from a powered-off state. Many
SIM7600 modules specifically require a PWRKEY toggle to power back on --
a reset line alone does not power on a module that is fully off.

NOTE on the command itself: an earlier version of this script used
AT+CPOWD=1, which is WRONG for this module -- that's a SIMCom SIM800/900
series command. Confirmed against this module's own official AT command
manual (SIM7500/SIM7600 series): the correct command is plain AT+CPOF
("This command is used to power off the module. Once the AT+CPOF command
is executed, the module will store user data and deactivate from network,
and then shutdown."). AT+CPOWD returning ERROR on real hardware is why
this got caught -- and it also means an earlier bench run of this exact
script reported a false PASS: since AT+CPOWD errored and the module never
actually powered off, of course it still responded to AT afterward -- that
proved nothing about waking from a real power-down. This version checks
that AT+CPOF itself returns OK before concluding anything about the wake
sequence, instead of assuming the power-down succeeded.

This is exactly the kind of thing to validate on the bench, with a PC
connected and ready to physically power-cycle everything if the modem
doesn't come back, BEFORE trusting it in the unattended automatic logging
flow (auto_log.py) where nobody would be around to notice or recover it.

CONFIRMED ON REAL HARDWARE: AT+CPOF returned OK (it genuinely powered the
module off), and afterward plain AT got "(no response)" even after the
normal reset() sequence -- FAIL. config.py's PIN_MODEM_RESET is a plain
RESET line on this board, not the module's PWRKEY, and cannot wake it
from a true power-off. Do NOT wire AT+CPOF-based power-down into
auto_log.py without either rewiring to the module's actual PWRKEY pin, or
accepting that a physical power cycle is needed every time. See
modem_cfun_test.py instead for a safer middle ground (AT+CFUN=0/1) that
stays UART-responsive the whole time -- no PWRKEY needed at all, though
it saves less power than a true power-off would.

Usage: run in Thonny. Watch for one of:
  "PASS: modem woke up after AT+CPOF"  -- safe to consider wiring this
      into the automatic logging flow for real power savings.
  "INCONCLUSIVE: AT+CPOF itself did not return OK" -- the module refused
      the power-down command entirely (e.g. still mid-registration, or a
      data/PDP session open) -- it never actually powered off, so this
      run proves nothing about the wake sequence either way. Try again
      right after a fresh boot, before anything else touches the modem.
  "FAIL: modem did not respond after AT+CPOF ..." -- do NOT wire this
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
    print("Step 2: sending AT+CPOF (graceful power down)...")
    resp = modem.at("AT+CPOF", 15000)
    powered_off = "OK" in resp and "ERROR" not in resp

    if not powered_off:
        print()
        print("INCONCLUSIVE: AT+CPOF did not return OK (got: %s)." % (resp.strip() or "(no response)"))
        print("The module refused the power-down command -- it never actually")
        print("powered off, so nothing below proves anything about waking it up.")
        print("Common reasons: a data/PDP session still open (this test doesn't")
        print("open one, so unlikely here), or the module still mid-registration.")
        print("Try again right after a fresh boot before anything else runs.")
        return

    print("Modem accepted AT+CPOF -- waiting 5s for it to fully power off...")
    time.sleep(5)

    print()
    print("Step 3: attempting to wake it via the normal reset() sequence...")
    modem.reset()

    print("Step 4: checking if it responds to AT now...")
    try:
        modem.check_alive()
        print()
        print("PASS: modem woke up after AT+CPOF via reset().")
        print("Safe to consider wiring AT+CPOF-based power-down into the")
        print("automatic logging flow (auto_log.py) for real power savings.")
    except Exception as exc:
        print()
        print("FAIL: modem did not respond after AT+CPOF within the reset timeout.")
        print("Reason:", exc)
        print()
        print("This likely means config.py's PIN_MODEM_RESET is wired to a plain")
        print("RESET line, not the module's PWRKEY -- reset() alone can't power")
        print("a module back ON once AT+CPOF has powered it fully off.")
        print("Do NOT wire AT+CPOF into auto_log.py without either:")
        print("  - confirming which physical pin actually IS PWRKEY on this module")
        print("    and wiring/controlling that separately, or")
        print("  - physically power-cycling the modem now to recover it.")


if __name__ == "__main__":
    main()
