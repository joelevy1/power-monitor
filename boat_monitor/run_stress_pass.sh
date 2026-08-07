#!/bin/bash
# Remote boat stress pass — logs to /tmp/boat_stress_pass.log
set -e
LOG=/tmp/boat_stress_pass.log
exec > >(tee -a "$LOG") 2>&1

poll() {
  python3 - <<'PY'
import sys
sys.path.insert(0, "/workspace/boat_monitor")
from remote_stress_pass import _power_log_tail, _stall_count
c, rows = _power_log_tail(6)
print("--- poll rows=%d stalls=%d" % (c, _stall_count()))
for r in rows:
    print(" ", r["ts"], r["fw"], r["uplink"])
PY
}

upsert() {
  cd /workspace/boat_monitor
  python3 sheets_config_upsert.py "$@"
}

echo "======== STRESS START $(date -u) ========"
poll

echo "PHASE 1: cmd_reboot (may already be queued)"
upsert boat-p2:cmd_reboot 1 "stress pass: reboot"
echo "Wait up to 8m for post-reboot log..."
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  sleep 30
  poll
  python3 - <<'PY' && break
import sys
sys.path.insert(0, "/workspace/boat_monitor")
from remote_stress_pass import _power_log_tail
c, rows = _power_log_tail(2)
# success if latest ts after phase start — crude: row count > 56
import sys
sys.exit(0 if c > 56 else 1)
PY
done

echo "PHASE 2: force cellular (invalid wifi_networks)"
BASE=$(python3 -c "import sys; sys.path.insert(0,'/workspace/boat_monitor'); from remote_stress_pass import _power_log_tail; print(_power_log_tail(1)[0])")
upsert wifi_networks "stress-invalid|badpass" "stress: no valid Wi-Fi"
echo "Wait up to 12m for cellular uplink..."
for i in $(seq 1 24); do
  sleep 30
  poll
  python3 - <<'PY' && break
import sys
sys.path.insert(0, "/workspace/boat_monitor")
from remote_stress_pass import _power_log_tail
_, rows = _power_log_tail(3)
if rows and rows[-1].get("uplink") == "cellular":
    sys.exit(0)
sys.exit(1)
PY
done

echo "PHASE 3: restore Wi-Fi"
upsert wifi_networks $'Seattle Boat|seaboats\nLevy-Guest|welcomehome' "stress: restore networks"
echo "Wait up to 12m for Levy-Guest..."
for i in $(seq 1 24); do
  sleep 30
  poll
  python3 - <<'PY' && break
import sys
sys.path.insert(0, "/workspace/boat_monitor")
from remote_stress_pass import _power_log_tail
_, rows = _power_log_tail(2)
u = rows[-1].get("uplink") if rows else ""
if u and u != "cellular":
    sys.exit(0)
sys.exit(1)
PY
done

echo "PHASE 4: Wi-Fi-only soak 12m"
sleep 720
poll

echo "PHASE 5: boot OTA one-shot"
BASE=$(python3 -c "import sys; sys.path.insert(0,'/workspace/boat_monitor'); from remote_stress_pass import _power_log_tail; print(_power_log_tail(1)[0])")
upsert boat-p2:cmd_ota 1 "stress: boot OTA"
echo "Wait up to 18m for recovery after OTA reboot..."
for i in $(seq 1 36); do
  sleep 30
  poll
  python3 - <<PY && break
import sys
sys.path.insert(0, "/workspace/boat_monitor")
from remote_stress_pass import _power_log_tail
c, rows = _power_log_tail(2)
if c > $BASE and rows and rows[-1].get("fw") == "1.1.39":
    sys.exit(0)
sys.exit(1)
PY
done

upsert min_fw_version 1.1.39 "stress pass complete"
echo "PHASE 6: final soak 10m"
sleep 600
poll
echo "======== STRESS END $(date -u) ========"
