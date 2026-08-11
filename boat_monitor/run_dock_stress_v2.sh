#!/usr/bin/env bash
set -euo pipefail
cd /workspace
export PYTHONUNBUFFERED=1

python3 boat_monitor/ota_stress_preflight.py --profile dock || {
  echo "Preflight failed — fix manifest/sheet/watch before stress"
  exit 1
}

python3 boat_monitor/boat_p2_watch.py --interval 60 &
WATCH_PID=$!
trap 'kill $WATCH_PID 2>/dev/null || true' EXIT

echo "Waiting for device fw >= 1.1.110 (dock-fix deploy)..."
for i in $(seq 1 120); do
  fw=$(python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _current_device_fw, _parse_ver_tuple; print(_current_device_fw() or '?')")
  echo "$(date -u +%H:%M:%SZ) poll $i fw=$fw min=1.1.110"
  if python3 -c "import sys; sys.path.insert(0,'boat_monitor'); from ota_stress_harness import _current_device_fw, _parse_ver_tuple; fw=_current_device_fw() or '0'; sys.exit(0 if _parse_ver_tuple(fw) >= _parse_ver_tuple('1.1.110') else 1)"; then
    echo "Device at $fw — continuing"
    break
  fi
  sleep 60
done

python3 boat_monitor/apply_recovery_manifest.py --version-only
git add boat_monitor/ota_manifest.json
git commit -m "release: version-only manifest after dock-fix 1.1.110" || true
git push origin master

echo "Starting 4-round dock stress from 1.1.110..."
python3 boat_monitor/ota_stress_harness.py --profile dock --rounds 4 --no-bootstrap 2>&1 | tee boat_monitor/ota_stress_dock_v2.log
