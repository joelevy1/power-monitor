#!/usr/bin/env bash
# One-liner wrapper from repo root.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/.."
python3 -m pip install -q mpremote
exec python3 boat_monitor/usb_recovery_push.py "$@"
