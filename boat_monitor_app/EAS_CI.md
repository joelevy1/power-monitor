# Boat Monitor iOS — test before EAS credits

You cannot run the iPhone app from a Windows PC without **EAS** or a Mac. This repo adds **free GitHub checks** plus EAS builds that **auto-submit to TestFlight** when the build finishes.

## Automatic TestFlight submit (no manual `eas submit`)

The **GitHub Actions** workflow and all **store** EAS profiles use **`eas build --auto-submit`**. When EAS finishes building, it **queues submission to App Store Connect** (TestFlight — not public App Store review).

**Requirements (one-time on Expo):** App Store Connect API key (or other non-interactive Apple auth) on the Expo project so `eas submit` runs unattended. Same setup as your working Ballast app.

Each build profile has a matching **`submit`** entry in `eas.json` with `ascAppId` **6797728128**.

## What runs automatically (free)

On every push to `master` that touches `boat_monitor_app/`:

| Check | Runner | What it proves |
|--------|--------|----------------|
| **validate-js** | Linux | `expo-doctor`, JS bundles for **full** and **smoke** variants |
| **ios-native-compile** | macOS | `pod install` + **Release simulator compile** for committed **full** `ios/` and a fresh **smoke** prebuild |

## EAS profiles (manual workflow — all auto-submit to TestFlight)

**Actions → EAS iOS build (Boat Monitor) → Run workflow**

1. **`smoke`** — **Boat Monitor Smoke**, no BLE native, `EXPO_PUBLIC_APP_VARIANT=smoke`.  
   - Workflow **removes committed `ios/`** before upload so EAS prebuilds without BLE.  
   - **Store** distribution + **auto-submit** → TestFlight.

2. **`preview`** — Full app + BLE, **store** + **auto-submit** → TestFlight (full BLE before you rely on `production`).

3. **`production`** / **`production_xcode26`** — Full app, TestFlight auto-submit.  
   - Default image **Xcode 16.4**; use `production_xcode26` for the Xcode 26 image.

Approve the **`eas-build`** GitHub environment when prompted (optional credit gate).

## Local (PC)

From `boat_monitor_app/`:

```bash
npm ci
npm run validate
```

## If TestFlight still crashes immediately

1. Run **`smoke`** first on TestFlight (look for **Boat Monitor Smoke** / smoke screen).  
2. Paste crash excerpt (exception + first stack frames) from Settings → Analytics Data.

## Secrets

- GitHub **`EXPO_TOKEN`** — required for EAS workflow.  
- Optional **`eas-build`** environment with required reviewers before the job runs.
