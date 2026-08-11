#!/usr/bin/env bash
# Staged remote dock upgrade: 1.1.107 -> bootstrap 1.1.108 -> dock-fix 1.1.110
# Pauses min_fw on reboot trap. Requires dock Wi-Fi reachability.
set -euo pipefail
cd /workspace
export PYTHONUNBUFFERED=1
LOG=boat_monitor/remote_dock_upgrade.log
exec > >(tee -a "$LOG") 2>&1

poll_fw() {
  python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _current_device_fw; print(_current_device_fw() or '?')"
}

fw_ge() {
  python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _parse_ver_tuple; sys.exit(0 if _parse_ver_tuple(sys.argv[1]) >= _parse_ver_tuple(sys.argv[2]) else 1)" "$1" "$2"
}

sheet_apply() {
  python3 -c "
import sys
sys.path.insert(0,'boat_monitor')
from sheets_config_upsert import upsert_config_keys
from sheets_bootstrap import SCOPES,_credentials_path,_sheet_id
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
c=Credentials.from_service_account_file(_credentials_path(),scopes=SCOPES)
s=build('sheets','v4',credentials=c,cache_discovery=False)
sid=_sheet_id(c)
rows = []
for line in sys.stdin:
    line=line.strip()
    if not line or line.startswith('#'): continue
    key,val,note=line.split('|',2)
    rows.append((key,val,note))
upsert_config_keys(s,sid,rows)
for k,v,_ in rows: print('  ',k,'=',v or '(cleared)')
"
}

check_trap() {
  python3 -c "
import sys
sys.path.insert(0,'boat_monitor')
from ota_stress_harness import _current_device_fw,_fetch_events,_sheets
from ota_stress_rules import detect_reboot_trap,pause_min_fw_to_device
dev=_current_device_fw() or ''
target=sys.argv[1]
ev=_fetch_events()
trap=detect_reboot_trap(ev, dev, target)
if trap:
    sheets,sid=_sheets()
    pause_min_fw_to_device(sheets,sid,dev,trap)
    print('TRAP:', trap)
    sys.exit(2)
sys.exit(0)
" "$1" || return $?
}

echo "=== Remote dock upgrade monitor $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# --- Stage 1: bootstrap 1.1.108 (2-file manifest already on GitHub master) ---
echo "--- Stage 1: bootstrap 1.1.108 ---"
if ! fw_ge "$(poll_fw)" "1.1.108"; then
  cat <<'EOF' | sheet_apply
min_fw_version|1.1.108|remote upgrade stage1 bootstrap
auto_ota_on_boot|1|remote upgrade
interval_engine_off_s|300|remote upgrade: 5 min logs during OTA
interval_engine_on_s|300|remote upgrade
dock_mode|home|dock Wi-Fi logs
boot_ota_prefer_wifi|1|remote upgrade: Wi-Fi boot OTA for 2-file bootstrap
boot_ota_max_seconds|420|remote upgrade
clear_ota_degraded|1|remote upgrade stage1
clear_boot_ota_backoff|1|remote upgrade stage1
force_ota||remote upgrade clear
cmd_ota||remote upgrade clear
cmd_ota_force||remote upgrade clear
cmd_clear_pending_ota||remote upgrade clear
EOF
  echo "Waiting for device fw >= 1.1.108 (timeout ~90 min)..."
  for i in $(seq 1 90); do
    fw=$(poll_fw)
    echo "$(date -u +%H:%M:%SZ) stage1 poll $i fw=$fw"
    check_trap "1.1.108" && true || { echo "ABORT stage1 trap"; exit 1; }
    if fw_ge "$fw" "1.1.108"; then
      echo "Stage 1 OK: fw=$fw"
      break
    fi
    sleep 60
  done
  fw=$(poll_fw)
  if ! fw_ge "$fw" "1.1.108"; then
    echo "FAIL stage1: device still $fw after 90 min"
    exit 1
  fi
else
  echo "Stage 1 skip: already fw=$(poll_fw) >= 1.1.108"
fi

# --- Stage 2: dock-fix 1.1.110 (5-file — Wi-Fi boot OTA at dock) ---
echo "--- Stage 2: dock-fix 1.1.110 ---"
git fetch origin master
git checkout master
git pull origin master
echo 'VERSION = "1.1.110"' > boat_monitor/version.py
python3 boat_monitor/apply_recovery_manifest.py --dock-fix --offline-recovery
git add boat_monitor/version.py boat_monitor/ota_manifest.json
git commit -m "release: dock-fix 1.1.110 remote staged upgrade" || true
git push origin master

echo "Waiting for GitHub CDN manifest..."
for _ in $(seq 1 24); do
  if python3 boat_monitor/validate_release.py --check-github 2>/dev/null; then break; fi
  sleep 15
done

cat <<'EOF' | sheet_apply
min_fw_version|1.1.110|remote upgrade stage2 dock-fix
auto_ota_on_boot|1|remote upgrade
boot_ota_prefer_wifi|1|remote upgrade: Wi-Fi for 5-file dock-fix
clear_ota_degraded|1|remote upgrade stage2
clear_boot_ota_backoff|1|remote upgrade stage2
cmd_ota_force|1|remote upgrade: allow boot OTA if degraded
force_ota||remote upgrade clear
cmd_ota||remote upgrade clear
EOF

echo "Waiting for device fw >= 1.1.110 (timeout ~120 min)..."
for i in $(seq 1 120); do
  fw=$(poll_fw)
  echo "$(date -u +%H:%M:%SZ) stage2 poll $i fw=$fw"
  check_trap "1.1.110" && true || { echo "ABORT stage2 trap"; exit 1; }
  if fw_ge "$fw" "1.1.110"; then
    echo "Stage 2 OK: fw=$fw"
    break
  fi
  sleep 60
done

fw=$(poll_fw)
if ! fw_ge "$fw" "1.1.110"; then
  echo "FAIL stage2: device still $fw — pausing min_fw"
  python3 -c "
import sys; sys.path.insert(0,'boat_monitor')
from ota_stress_harness import _current_device_fw,_sheets
from ota_stress_rules import pause_min_fw_to_device
fw=_current_device_fw() or '1.1.108'
pause_min_fw_to_device(*_sheets(), fw, 'stage2 timeout')
"
  exit 1
fi

# --- Stage 3: restore version-only manifest for future stress ---
echo "--- Stage 3: restore version-only manifest ---"
git checkout master
git pull origin master
python3 boat_monitor/apply_recovery_manifest.py --version-only
git add boat_monitor/ota_manifest.json
git commit -m "release: version-only manifest after dock-fix 1.1.110" || true
git push origin master

cat <<'EOF' | sheet_apply
min_fw_version|1.1.110|remote upgrade complete
auto_ota_on_boot|1|post upgrade
boot_ota_prefer_wifi|0|dock cellular boot OTA policy
interval_engine_off_s|1800|restore 30 min dock interval
cmd_ota_force||post upgrade clear
clear_ota_degraded||post upgrade clear
clear_boot_ota_backoff||post upgrade clear
EOF

echo "=== Remote dock upgrade COMPLETE fw=$(poll_fw) ==="
