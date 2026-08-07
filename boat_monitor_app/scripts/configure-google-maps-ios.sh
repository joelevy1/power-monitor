#!/usr/bin/env bash
# EAS Build: inject Google Maps API key into Info.plist (never commit the key).
# Run from boat_monitor_app/ (where eas.json lives).
# Invoked via eas.json prebuildCommand and package.json eas-build-post-install (after pod install).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$ROOT/ios/BoatMonitor/Info.plist"
KEY="${GOOGLE_MAPS_API_KEY:-${EXPO_PUBLIC_GOOGLE_MAPS_API_KEY:-}}"
echo "configure-google-maps-ios: pwd=$(pwd) app_root=$ROOT"
if [ -z "$KEY" ]; then
  echo "configure-google-maps-ios: no GOOGLE_MAPS_API_KEY — skipping"
  exit 0
fi
if [ ! -f "$PLIST" ]; then
  echo "configure-google-maps-ios: Info.plist not found at $PLIST"
  exit 1
fi
/usr/libexec/PlistBuddy -c "Delete :GMSApiKey" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :GMSApiKey string $KEY" "$PLIST"
echo "configure-google-maps-ios: GMSApiKey set in Info.plist"
