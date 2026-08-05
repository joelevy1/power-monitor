"""
Boat Monitor P2 - bench test: does AT+CFUN=0 (minimum functionality) stay
UART-responsive, and does AT+CFUN=1 reliably bring it back to full
functionality (registered, ready for NETOPEN)?

Why this instead of AT+CPOF: modem_power_cycle_test.py already confirmed
on real hardware that AT+CPOF (true power-off) can NOT be woken back up
with this board's current wiring -- config.py's PIN_MODEM_RESET is a
plain RESET line, not the module's PWRKEY, so a true power-down strands
the modem until someone physically power-cycles it. Confirmed on real
hardware: AT+CPOF returned OK (it genuinely powered off), and afterward
plain AT got "(no response)" even after the normal reset() sequence.

AT+CFUN is different: it's a SOFTWARE functionality level, not a
power-off. Per this module's own AT command manual: "0 - minimum
functionality... 1 - full functionality, online mode" -- the module
stays attached to the UART/AT command interface the whole time at
CFUN=0, so there's no PWRKEY/hardware-pin uncertainty at all. It won't
save as much power as a true power-off would (the baseband processor
and UART interface stay powered; only the RF/network circuits shut
down), but it's the safe middle ground: cuts the biggest power draw
(active RF, searching/registered on the network) between logging
cycles, with none of the "how do we wake it back up" risk AT+CPOF has
on this board.

Usage: run in Thonny.
"""

import time

from cellular import Sim7600Modem


def main():
    print("Boat Monitor - modem AT+CFUN low-power test")
    modem = Sim7600Modem()

    print("Step 1: confirm the modem responds normally first...")
    modem.check_alive()
    print("OK -- modem responds to AT.")

    print()
    print("Step 2: sending AT+CFUN=0 (minimum functionality)...")
    resp = modem.at("AT+CFUN=0", 15000)
    if "OK" not in resp or "ERROR" in resp:
        print("INCONCLUSIVE: AT+CFUN=0 did not return OK (got: %s)." % (resp.strip() or "(no response)"))
        return
    print("Accepted. Module should now be in minimum-functionality (RF off) mode.")

    print()
    print("Step 3: confirming the modem STILL responds to plain AT while in this mode...")
    try:
        modem.check_alive()
        print("OK -- modem stays responsive over UART even at CFUN=0, as expected --")
        print("this is a software mode, not a power-off.")
    except Exception as exc:
        print("UNEXPECTED: modem stopped responding even at CFUN=0:", exc)
        print("This contradicts the AT manual's description of CFUN=0 -- do not rely")
        print("on this without investigating further.")
        return

    print()
    print("Waiting 3s (simulating an idle 'engine off' gap)...")
    time.sleep(3)

    print()
    print("Step 4: sending AT+CFUN=1 (restore full functionality)...")
    resp = modem.at("AT+CFUN=1", 15000)
    if "OK" not in resp or "ERROR" in resp:
        print("FAIL: AT+CFUN=1 did not return OK (got: %s)." % (resp.strip() or "(no response)"))
        return
    print("Accepted.")

    print()
    print("Step 5: confirming the modem can register on the network again...")
    try:
        modem.check_sim()
        modem.wait_for_registration(seconds=60)
        print()
        print("PASS: AT+CFUN=0 -> AT+CFUN=1 round-trip works -- modem re-registered")
        print("successfully. Safe to consider wiring this into the automatic logging")
        print("flow (auto_log.py) as a real power-saving step between cycles.")
    except Exception as exc:
        print()
        print("FAIL: modem did not re-register after AT+CFUN=1:", exc)
        print("The CFUN toggle itself worked, but re-registration failed -- may just")
        print("need a longer wait, or investigate further before automating this.")


if __name__ == "__main__":
    main()
