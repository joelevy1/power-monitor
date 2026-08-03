# Boat Monitor (iOS)

Expo / React Native app that connects to the Pico W over BLE. Your phone can stay on cellular data while you read status and send service commands (refresh, Wi‑Fi service mode, OTA, reboot).

## Prerequisites

- Node 18–24
- Apple Developer account (for TestFlight / device builds)
- [EAS CLI](https://docs.expo.dev/build/setup/): `npm install -g eas-cli`

## Local development

```bash
cd boat_monitor_app
npm install
npx expo start
```

BLE requires a physical iPhone build; the iOS Simulator cannot talk to the boat monitor radio.

## TestFlight (internal preview)

```bash
cd boat_monitor_app
npm install
eas login
eas build --platform ios --profile preview
```

Install the build from the EAS link or add testers in App Store Connect. Bundle ID: `com.joelevy.boatmonitor`.

## Pico pairing

1. Flash or OTA to firmware **0.3.0+** so `ble_service.py` is on the device.
2. On boot, the Pico advertises as **BoatMonitor**.
3. Open the app, tap **Connect BLE**, then use **Refresh** / **Start Wi‑Fi** / **OTA** as needed.

Service UUID: `7e400001-b5a3-f393-e0a9-e50e24dcca9e` (Nordic UART–style layout for status notify + command write).
