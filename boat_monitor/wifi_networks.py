"""
Load Wi-Fi networks from every source the boat monitor uses.

  - If wifi_sheet.json exists (from Config tab `wifi_networks`), use it only.
  - Else: wifi_credentials.py, then wifi_known_networks.py (GitHub / OTA).
"""

try:
    import ujson as json
except ImportError:
    import json

SHEET_CACHE_FILE = "wifi_sheet.json"


def parse_wifi_networks_text(text):
    """One network per line: SSID|password  (or tab-separated). # comments OK."""
    networks = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            ssid, password = line.split("|", 1)
        elif "\t" in line:
            ssid, password = line.split("\t", 1)
        else:
            continue
        ssid = ssid.strip()
        password = password.strip()
        if ssid and password:
            networks.append((ssid, password))
    return networks


def save_sheet_networks(networks):
    """Persist Config-tab networks on the Pico."""
    try:
        with open(SHEET_CACHE_FILE, "w") as f:
            json.dump([list(p) for p in networks], f)
        return True
    except Exception as exc:
        print("wifi_networks: save_sheet failed:", exc)
        return False


def load_sheet_networks():
    try:
        with open(SHEET_CACHE_FILE, "r") as f:
            data = json.load(f)
        out = []
        for item in data or []:
            if item and len(item) >= 2:
                out.append((str(item[0]).strip(), str(item[1])))
        return out
    except Exception:
        return []


def load_networks():
    """Ordered list of (ssid, password) for wifi_uplink.connect().

    When the Config tab has pushed a non-empty list (wifi_sheet.json), that list
    is authoritative — it replaces GitHub wifi_known_networks for this device.
    Otherwise: wifi_credentials.py → wifi_known_networks.py.
    """
    sheet = load_sheet_networks()
    if sheet:
        return sheet

    result = []
    seen = set()

    def add(entries):
        for ssid, password in entries or []:
            if not ssid or not password or ssid in seen:
                continue
            seen.add(ssid)
            result.append((ssid, password))

    try:
        import wifi_credentials

        add(getattr(wifi_credentials, "WIFI_NETWORKS", []))
    except ImportError:
        pass

    try:
        import wifi_known_networks

        add(getattr(wifi_known_networks, "WIFI_NETWORKS", []))
    except ImportError:
        pass

    return result
