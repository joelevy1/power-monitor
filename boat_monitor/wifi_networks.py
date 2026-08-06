"""
Load Wi-Fi networks from every source the boat monitor uses.

Try order (first match wins per SSID):
  1. wifi_credentials.py on the Pico (gitignored, local bench overrides)
  2. wifi_sheet.json (written from Google Sheet Config key wifi_networks)
  3. wifi_known_networks.py (GitHub — edit in repo, ship via OTA)
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
    """Ordered list of (ssid, password) for wifi_uplink.connect()."""
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

    add(load_sheet_networks())

    try:
        import wifi_known_networks

        add(getattr(wifi_known_networks, "WIFI_NETWORKS", []))
    except ImportError:
        pass

    return result
