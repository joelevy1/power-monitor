# Firmware release process (mandatory)

**Rule:** The boat only installs firmware that appears in **`master`** on GitHub
(`ota_manifest.json` → raw URLs). Config `min_fw_version` and sheet scripts
**cannot** deploy code that is not merged to `master`.

## Never do this

1. Set **`min_fw_version`** (or run `apply_ship_config.py`) to a version **newer
   than** `ota_manifest.json` on **`master`**.
2. Tell the owner to OTA while fixes exist **only on a PR branch**.
3. Bump `min_fw_version` on the sheet **before** `version.py`, `ota_manifest.json`,
   and all manifest files are **merged to `master`**.

That produces: reboot-for-OTA → boot OTA → “Already at target version” → **stuck
forever** on old `fw` while Events show `min_fw_version=X current=Y`.

## Ship order (every release)

Do these **in order**. Do not skip steps.

| Step | Action |
|------|--------|
| 1 | Implement fix on a branch; bump **`version.py`** `VERSION` and **`ota_manifest.json`** `version` to the **same** string. |
| 2 | Add every changed `.py` (and required peers) to **`ota_manifest.json`** `files[]` with `master` raw URLs. |
| 3 | Run **`python3 boat_monitor/validate_release.py`** (and **`--check-github`** after push to `master`). |
| 4 | **Merge to `master`** and confirm raw manifest in browser shows the new version. |
| 5 | **Only then** update sheet Config: `min_fw_version` = that version (or `apply_ship_config.py`). |
| 6 | Optional: `cmd_ota=1` one-shot for a field unit; otherwise wait for next log + boot OTA. |
| 7 | Confirm **Power_Log `fw`** column matches on the boat. |

## For Cloud Agents / Cursor

Before any `sheets_config_upsert`, `apply_ship_config`, or advising
`min_fw_version`:

```bash
python3 boat_monitor/validate_release.py --check-github
```

If `--check-github` fails, **merge to `master` first** — do not touch Config.

After merging firmware, **push `master`**, re-run `--check-github`, then update
the sheet.

## Quick checks

```bash
# Local: version.py matches manifest; manifest lists version.py
python3 boat_monitor/validate_release.py

# Remote: GitHub master manifest matches this repo (after push)
python3 boat_monitor/validate_release.py --check-github

# Push standard intervals + min_fw (= shipped VERSION only)
python3 boat_monitor/apply_ship_config.py
```

## What remote OTA actually does

- Each successful log may queue **`ota`** when `current < min_fw_version`.
- **`run_actions(ota)`** → **reboot** → **`main.py`** boot OTA downloads from
  **GitHub `master` manifest only**.
- Logging/Wi‑Fi/cellular working does **not** imply OTA will upgrade if `master`
  manifest is still old.

See also `OTA_UPDATE.md` and `REMOTE_CONTROL.md`.
