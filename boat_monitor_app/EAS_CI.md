# EAS build automation (PC-friendly)

Same approach as **[ballast-app](https://github.com/joelevy1/ballast-app)**: **GitHub Actions on Linux** runs `eas build` and **`--auto-submit`** to TestFlight. You do **not** need a Mac for day-to-day releases.

## One-time checklist

Do these once (about 15–30 minutes). After that, pushes to `master` that touch `boat_monitor_app/` can ship to TestFlight automatically.

### 1. Link this folder to an Expo project

On any PC (PowerShell or WSL), from the repo root:

```bash
cd boat_monitor_app
npm install
npx eas-cli login
npx eas-cli init
```

- Choose **create a new project** (name e.g. `boat-monitor`).
- Commit the updated `app.json` (`expo.extra.eas.projectId`).

### 2. GitHub secret `EXPO_TOKEN`

1. Expo: **Account settings → Access tokens** → create token (Build scope is enough).
2. GitHub repo **power-monitor**: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `EXPO_TOKEN`
   - Value: paste the token.

(You can reuse the same token you already use for **ballast-app** if it is under the same Expo account.)

### 3. GitHub environment `eas-build` (optional approval gate)

**Settings → Environments → New environment** → name: `eas-build`  
Add **Required reviewers** if you want to approve each build before EAS spends a credit. If the environment does not exist, create it before the first workflow run.

### 4. Apple credentials on Expo (required for auto-submit)

Expo must be able to run **`eas submit` non-interactively**:

- In [expo.dev](https://expo.dev) → your **boat-monitor** project → **Credentials** / **App Store Connect API key**, **or**
- One **interactive** build (no `--non-interactive`) from PC/WSL:

```bash
cd boat_monitor_app
npx eas-cli build --platform ios --profile production
```

Sign in to Apple when prompted and let EAS create provisioning for **`com.joelevy.boatmonitor`**. After one successful build, GitHub Actions can use `--non-interactive`.

### 5. App Store Connect app record

1. [App Store Connect](https://appstoreconnect.apple.com) → **Apps → +** → new app, bundle ID **`com.joelevy.boatmonitor`**.
2. Optional but recommended: copy the numeric **Apple ID** from the app’s **App Information** page (URL looks like `.../apps/1234567890/...`) into `eas.json`:

```json
"submit": {
  "production": {
    "ios": { "ascAppId": "1234567890" }
  }
}
```

(Same as ballast’s `ascAppId` in `ballast-app/eas.json`.)

### 6. TestFlight testers

App Store Connect → your app → **TestFlight** → add **internal** testers (your Apple ID). Assign the build to your group when processing finishes (often 15–30 minutes).

---

## How CI works

| Trigger | Behavior |
|--------|----------|
| Push to **`master`** changing `boat_monitor_app/**` | **`production`** iOS build + **`--auto-submit`** → TestFlight |
| **Actions → EAS iOS build (Boat Monitor) → Run workflow** | Pick `production`, `production_xcode26`, or `preview` |
| Commit message contains **`[skip-eas]`** | Skips the workflow on push |

**`preview`** = internal distribution only (no auto-submit).  
**`production`** / **`production_xcode26`** = store/TestFlight path (same Xcode image as ballast).

Workflow file: `.github/workflows/eas-ios.yml` (runs with `working-directory: boat_monitor_app`).

## Windows notes

Local `eas build` on Windows often fails during upload (`EPERM` on `%TEMP%`). Prefer **GitHub Actions** or **WSL** — same as ballast’s `EAS_CI.md`.

## Troubleshooting

- **`app.json is missing expo.extra.eas.projectId`** → run `npx eas-cli init` and commit.
- **`EXPO_TOKEN` / `eas whoami` failed** → regenerate token and update the GitHub secret.
- **Credentials not set up in non-interactive mode** → complete step 4 once interactively.
- **Auto-submit failed** → Expo dashboard → **Submissions** tab for the error; fix Apple API key / `ascAppId`, then re-run the workflow.

## Pico firmware

The iOS app is independent of CI. Flash **`ble_service.py`** + **`main.py`** (or OTA 0.3.0+) on the Pico before testing BLE.
