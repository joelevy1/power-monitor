# Copy to wifi_credentials.py (same folder, on the Pico). Do not commit
# wifi_credentials.py -- it's gitignored.
#
# Tried in this order by wifi_uplink.connect() -- first network that
# actually connects wins, others are skipped. Add as many as you want
# (e.g. the marina's Wi-Fi and your home Wi-Fi for bench testing).

WIFI_NETWORKS = [
    ("Seattle Boat", "marina-wifi-password-here"),
    ("YourHomeNetworkSSID", "your-home-wifi-password-here"),
]
