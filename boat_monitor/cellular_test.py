"""
Boat Monitor P2 - bare cellular connectivity test. No Sheets/Apps Script
setup needed -- just answers "does cellular actually work" directly.
Run from Thonny with the SIM7600 modem wired, powered, and the cellular
antenna connected:

    import cellular_test
    cellular_test.main()

Confirms, in order: the modem responds to AT at all, the SIM is ready,
network registration succeeds (the step every previous "cellular data did
not open" failure skipped straight past -- AT+NETOPEN commonly fails if
the modem hasn't attached to the tower yet), then AT+NETOPEN/AT+IPADDR.
Finishes with one small real HTTP GET (the OTA manifest) as an end-to-end
smoke test, not just "data session opened."
"""

import ota_config
from cellular import CellularError, Sim7600Modem


def main():
    print("Boat Monitor P2 - bare cellular test")
    modem = Sim7600Modem()
    try:
        modem.ensure_data()
        print()
        print("Cellular data is up. Fetching the OTA manifest as an HTTP smoke test...")
        text = modem.http_get(ota_config.OTA_MANIFEST_URL)
        print("Got %d bytes. First 200 chars:" % len(text))
        print(text[:200])
        print()
        print("OK: cellular connectivity confirmed end-to-end.")
        return True
    except CellularError as exc:
        print()
        print("FAILED:", exc)
        return False
    finally:
        modem.close_data()


if __name__ == "__main__":
    main()
