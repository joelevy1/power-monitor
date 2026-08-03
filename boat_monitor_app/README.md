# Boat Monitor (iOS)

Expo / React Native app that connects to the Pico W over BLE. Your phone can stay on cellular data while you read status and send service commands (refresh, Wi‑Fi service mode, OTA, reboot).

**TestFlight from a PC (no Mac):** follow **[EAS_CI.md](./EAS_CI.md)** — same GitHub Actions + `EXPO_TOKEN` pattern as [ballast-app](https://github.com/joelevy1/ballast-app).

## Prerequisites

- Node 18–24
- Apple Developer account (for TestFlight)
- [EAS CLI](https://docs.expo.dev/build/setup/): `npm install -g eas-cli` (optional if you only use GitHub Actions)

## Local development

```bash
cd boat_monitor_app
npm install
npx expo start
```

BLE requires a physical iPhone build; the iOS Simulator cannot talk to the boat monitor radio.

## TestFlight via GitHub Actions (recommended)

1. Complete the one-time steps in **EAS_CI.md** (`eas init`, `EXPO_TOKEN`, Apple credentials on Expo).
2. Merge to **`master`** (workflow triggers on pushes that change `boat_monitor_app/`).
3. Open **TestFlight** on your iPhone after App Store Connect finishes processing the build.

Manual run: **Actions → EAS iOS build (Boat Monitor) → Run workflow**.

## Pico pairing

1. Flash or OTA to firmware **0.3.0+** so `ble_service.py` is on the device.
2. On boot, the Pico advertises as **BoatMonitor**.
3. Open the app, tap **Connect BLE**, then use **Refresh** / **Start Wi‑Fi** / **OTA** as needed.

Service UUID: `7e400001-b5a3-f393-e0a9-e50e24dcca9e` (Nordic UART–style layout for status notify + command write).
