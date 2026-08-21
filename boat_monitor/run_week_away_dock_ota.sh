#!/usr/bin/env bash
# Week-away dock OTA: 6 version-only rounds, 1h log interval, watch + trap pause.
set -euo pipefail
cd /workspace
export PYTHONUNBUFFERED=1

EXPECT_FW="${EXPECT_FW:-$(python3 -c 'import sys; sys.path.insert(0, "boat_monitor"); import version; print(version.VERSION)')}"
ROUNDS="${ROUNDS:-6}"
LOG_INTERVAL="${LOG_INTERVAL:-3600}"
ALLOW_MASTER_PUSH="${ALLOW_MASTER_PUSH:-0}"

if [[ "$ALLOW_MASTER_PUSH" != "1" ]]; then
  echo "FAIL: set ALLOW_MASTER_PUSH=1 only after explicit approval for six master releases" >&2
  exit 2
fi

echo "=== Week-away dock OTA ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ==="
echo "expect base fw=$EXPECT_FW rounds=$ROUNDS log_interval=${LOG_INTERVAL}s"

python3 << PY
import sys
sys.path.insert(0, "boat_monitor")
from sheets_config_upsert import upsert_config_keys
from sheets_bootstrap import SCOPES, _credentials_path, _sheet_id
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
c = Credentials.from_service_account_file(_credentials_path(), scopes=SCOPES)
s = build("sheets", "v4", credentials=c, cache_discovery=False)
sid = _sheet_id(c)
rows = [
    ("min_fw_version", "$EXPECT_FW", "week-away: match USB-loaded fw"),
    ("auto_ota_on_boot", "1", "week-away OTA enabled"),
    ("interval_engine_off_s", "$LOG_INTERVAL", "week-away 1h dock logs"),
    ("interval_engine_on_s", "600", "week-away 10m key-on"),
    ("dock_mode", "home", "week-away dock Wi-Fi logs"),
    ("standby_prefer_wifi", "1", "week-away require Wi-Fi-first standby logs"),
    ("boot_ota_prefer_wifi", "0", "week-away cellular boot OTA"),
    ("boot_ota_max_seconds", "420", "week-away boot OTA budget"),
    ("force_ota", "", "clear"),
    ("cmd_ota", "", "clear"),
    ("cmd_ota_force", "", "clear"),
]
upsert_config_keys(s, sid, rows)
print("OK: week-away sheet profile applied")
PY

python3 boat_monitor/ota_stress_preflight.py --profile dock

SESSION="week-away-watch"
tmux -f /exec-daemon/tmux.portal.conf has-session -t "=$SESSION" 2>/dev/null \
  || tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION" -c "/workspace" -- "${SHELL:-zsh}" -l
tmux -f /exec-daemon/tmux.portal.conf send-keys -t "$SESSION:0.0" \
  'python3 boat_monitor/boat_p2_watch.py --interval 120' C-m

SESSION2="week-away-ota"
tmux -f /exec-daemon/tmux.portal.conf has-session -t "=$SESSION2" 2>/dev/null \
  && tmux -f /exec-daemon/tmux.portal.conf kill-session -t "$SESSION2" 2>/dev/null || true
tmux -f /exec-daemon/tmux.portal.conf new-session -d -s "$SESSION2" -c "/workspace" -- "${SHELL:-zsh}" -l
tmux -f /exec-daemon/tmux.portal.conf send-keys -t "$SESSION2:0.0" \
  "python3 boat_monitor/ota_stress_harness.py --profile dock --rounds $ROUNDS --no-bootstrap --round-timeout 7200 --allow-master-push 2>&1 | tee boat_monitor/week_away_ota.log" C-m

echo "Started boat_p2_watch (tmux $SESSION) and stress harness (tmux $SESSION2)"
echo "Log: boat_monitor/week_away_ota.log"
