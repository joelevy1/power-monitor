#!/usr/bin/env bash
set -euo pipefail
cd /workspace
export PYTHONUNBUFFERED=1

poll_fw() {
  python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _current_device_fw; print(_current_device_fw() or '?')"
}

echo "=== Dock recovery monitor ==="
for i in $(seq 1 180); do
  fw=$(poll_fw)
  echo "$(date -u +%H:%M:%SZ) fw=$fw"
  if python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _parse_ver_tuple; fw=sys.argv[1]; sys.exit(0 if _parse_ver_tuple(fw) >= _parse_ver_tuple(sys.argv[2]) else 1)" "$fw" "1.1.108" 2>/dev/null; then
    echo "Reached $fw >= 1.1.108 — shipping dock-fix 1.1.110"
    python3 -c "
import sys
sys.path.insert(0,'boat_monitor')
from sheets_config_upsert import upsert_config_keys
from sheets_bootstrap import SCOPES,_credentials_path,_sheet_id
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
c=Credentials.from_service_account_file(_credentials_path(),scopes=SCOPES)
s=build('sheets','v4',credentials=c,cache_discovery=False)
sid=_sheet_id(c)
upsert_config_keys(s, sid, [
    ('min_fw_version', '1.1.110', 'dock-fix after bootstrap'),
    ('cmd_ota_force', '1', ''),
    ('clear_ota_degraded', '1', ''),
    ('clear_boot_ota_backoff', '1', ''),
])
print('sheet min_fw=1.1.110')
"
    # restore version and dock-fix manifest on master
    echo 'VERSION = "1.1.110"' > boat_monitor/version.py
    python3 boat_monitor/apply_recovery_manifest.py --dock-fix
    git add boat_monitor/version.py boat_monitor/ota_manifest.json
    git commit -m "release: dock-fix 1.1.110 after bootstrap" || true
    git push origin master
    break
  fi
  sleep 60
done
