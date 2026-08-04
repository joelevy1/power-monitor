# Boat Monitor iOS — test before EAS credits

You cannot run the iPhone app from a Windows PC without **EAS** or a Mac. This repo adds **free GitHub checks** plus a **cheap diagnostic build** so you are not guessing on TestFlight.

## What runs automatically (free)

On every push to `master` that touches `boat_monitor_app/`:

| Check | Runner | What it proves |
|--------|--------|----------------|
| **validate-js** | Linux | `expo-doctor`, JS bundles for **full** and **smoke** variants |
| **ios-native-compile** | macOS | `pod install` + **Release simulator compile** for committed **full** `ios/` and a fresh **smoke** prebuild |

If **ios-native-compile** is green, the native shell and CocoaPods graph are sane. It still does **not** run on your physical iPhone.

## Recommended EAS order (manual — saves credits)

**Actions → EAS iOS build (Boat Monitor) → Run workflow**

1. **`smoke`** — Internal distribution, **no BLE native module**, same bundle id as production (`com.joelevy.boatmonitor`) so Expo credentials reuse. App name shows **Boat Monitor Smoke**.  
   - The GitHub workflow **removes committed `ios/`** before upload so EAS runs a fresh prebuild for smoke.  
   - Install from the Expo build page (QR / link).  
   - **If this crashes on open:** signing, Expo shell, or device/OS issue — not BLE JS.  
   - **If this opens:** the iOS shell is fine; continue.

2. **`preview`** — Full app + BLE, **internal** only (no TestFlight submit).  
   - Confirms BLE links and you can tap **Connect BLE** before store submit.

3. **`production`** — TestFlight auto-submit (`ascAppId` in `eas.json`).  
   - Uses **Xcode 16.4** image (same as smoke/preview) for stability.  
   - Use **`production_xcode26`** only when you intentionally want the Xcode 26 image (Ballast-style).

Production builds **do not** run on every push; only **Validate iOS app** does.

## Local (PC)

From `boat_monitor_app/`:

```bash
npm ci
npm run validate
```

## If TestFlight still crashes immediately

1. Run **smoke** first (above).  
2. In App Store Connect → **Analytics → Crashes** or Xcode **Organizer**, copy the top frames (e.g. `ExceptionsManager`, `UIFont`, `BlePlx`).  
3. Paste that excerpt in an issue — native vs JS is obvious from the stack.

## Secrets

- GitHub **`EXPO_TOKEN`** — required for EAS workflow only.  
- Optional **`eas-build`** environment with required reviewers so a build waits for your approval before it queues.
