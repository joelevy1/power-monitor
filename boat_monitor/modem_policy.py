"""
When to leave the SIM7600 powered between log cycles (skip AT+CPOF).

Underway (switch/key on): keeping the modem warm makes the next cellular log
much faster and avoids PWRKEY wake failures. Standby / power-bank: always
power off after each session.

Override from Config: keep_modem_awake_underway = 1|0 (via remote_boot_config).
"""

try:
    import ujson as json
except ImportError:
    import json

from remote_telemetry import BOAT_ACTIVE_MODES

PATH = "remote_boot_config.json"


def _load():
    try:
        with open(PATH, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def keep_modem_awake_for_mode(mode):
    if mode not in BOAT_ACTIVE_MODES:
        return False
    data = _load()
    if "keep_modem_awake_underway" in data:
        return bool(data["keep_modem_awake_underway"])
    # Default on for boat power — user has 12V; wake latency hurts more than idle mA.
    return True
