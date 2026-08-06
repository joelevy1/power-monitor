# =============================================================================
# BOAT MONITOR — Wi-Fi networks (edit this file in GitHub)
# =============================================================================
#
# Easiest workflow: tell Cursor/your agent something like:
#   "Add Wi-Fi network Seattle Boat with password xyz to wifi_known_networks.py"
#
# Networks ship to the Pico on the next OTA (Config min_fw / cmd_ota) or boot
# OTA. For a change without waiting for OTA, use the Google Sheet **Config**
# tab instead — key `wifi_networks`, one line per network:
#       MySSID|my-password
#
# Order on the Pico: wifi_credentials.py (local) → Sheet cache → this file.
# =============================================================================

WIFI_NETWORKS = [
    # ("Seattle Boat", "marina-wifi-password"),
    # ("HomeNetwork", "home-wifi-password"),
]
