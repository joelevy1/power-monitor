# Firmware release process (mandatory)

**Rule:** The boat only installs firmware that appears in **`master`** on GitHub
(`ota_manifest.json` → raw URLs). Config `min_fw_version` and sheet scripts
**cannot** deploy code that is not merged to `master`.

## Owner mandate (non‑negotiable)

The field unit must **always** receive **one** current release — never a staircase
of versions.

1. **Batch before merge:** If more than one firmware fix or feature is in flight
   for the boat, put it all in **one** `VERSION` bump and **one** merge to
   **`master`**. Do **not** merge `1.1.44` today and `1.1.45` tomorrow when both
   could have shipped together.
2. **One target on the sheet:** After merge, set **`min_fw_version`** exactly once
   to that **`master`** version (`apply_ship_config.py`). Never tell the owner to
   “get X first, then Y” unless X and Y are literally the same release.
3. **OTA is a single jump:** Boot OTA installs the full manifest on **`master`** in
   one pass (`1.1.39` → `1.1.45` is normal). Multi-step advice is only a sign that
   **`master`** or the sheet was updated at the wrong time — fix the process, not
   the boat visit.
4. **No sheet bump ahead of `master`:** Never raise **`min_fw_version`** until
   `validate_release.py --check-github` passes for the version you are shipping.

Violating this wastes field time and breaks trust. Treat repeat violations as a
process failure.

### Controlled qualification exception

The owner may explicitly authorize a sequential OTA resilience campaign whose
purpose is to prove repeated unattended upgrades. That exception is governed by
`WINTER_READINESS_CAMPAIGN.md` and `OTA_STRESS_RULES.md`:

- every round is version-only;
- every target is published and remotely validated before the Sheet changes;
- each round must pass independently before the next release;
- any ship, transport, telemetry, flash, or reboot failure pauses the target and
  stops the campaign;
- `--allow-master-push` / `ALLOW_MASTER_PUSH=1` records explicit authorization.

This exception is for controlled testing only. Normal feature work still ships
as one batched release.

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
