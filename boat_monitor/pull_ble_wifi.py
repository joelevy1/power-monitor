"""
Pull main + BLE-related modules from GitHub over Wi-Fi (Thonny REPL).

  import pull_ble_wifi
  pull_ble_wifi.run()

Defaults to master (same as pull_master.py). Prefer pull_master.run() for clarity.
"""

from pull_master import BRANCH, FILES, run  # noqa: F401

__all__ = ("BRANCH", "FILES", "run")

if __name__ == "__main__":
    run()
