# OTA stress rules (boat-p2)

Policy for cellular OTA stress campaigns and releases that must not repeat the
1.1.88–1.1.93 incident (ENOMEM loops, flash backoff trap, `force_ota` storms).

## Manifest rules

1. **Bootstrap once per campaign** — ship `version.py` + `remote_boot_config.py`
   (`--bootstrap-rules`, ~12 KB) so sheet `clear_boot_ota_backoff` works on-device.
   **Cellular bootstrap often ENOMEM** on `remote_boot_config.py` (~12 KB heap alloc).
   Use USB instead: `run_usb_bootstrap_rules.bat` (one file + patch-only).
   Version-only bumps **do not** update `remote_boot_config.py`; without bootstrap,
   backoff traps return after ~2 rounds.
2. **Stress rounds ship version-only** — `ota_manifest.json` must contain only
   `version.py` (~19 bytes). No `bundle`, no multi-file manifests on cellular
   boot OTA.
2. **`validate_release.py --max-files 1`** must pass before any stress ship or
   `apply_ship_config.py`.
3. **`apply_recovery_manifest.py --version-only`** runs in the harness before
   every git push.
4. Full / ram-fix / feature-pack manifests are for **USB push** or **Wi‑Fi bench**
   only, not automated cellular stress.

## Sheet rules

1. Before stress: `ota_stress_rules.preflight_sheet()` (or harness startup) sets
   `clear_ota_degraded=1`, `clear_boot_ota_backoff=1`, `auto_ota_on_boot=1` and
   clears `force_ota`, `cmd_ota`, `boat-p2:cmd_ota`, `cmd_clear_pending_ota`.
2. After every ship: `apply_ship_config.py` clears the same one-shots.
3. **Never** leave `force_ota=1` on Config while `current >= min_fw` — device
   will `reboot_queued` every log cycle without upgrading.

## Device rules (firmware)

1. **`remote_control`**: `force_ota` / `cmd_ota` ignored when `VERSION >= min_fw`.
2. **`ota_health`**: preflight failures (`low_mem`, `low_flash`) do **not** set
   `ota_degraded` (transient heap/flash, not bad OTA).
3. **`main.py`**: on preflight fail while `needs_firmware_upgrade()`, keep
   `pending_ota` so recovery can retry boot OTA after sheet/USB clears backoff.
4. **Backoff trap**: `clear_boot_ota_backoff` on sheet clears flash
   `boot_ota_backoff_until` / `boot_ota_skip_remaining` (1.1.91+).

## USB recovery rules

1. **Patch-only** for stress recovery: use `--enable-boot-ota` so flash is not
   left with `auto_ota_on_boot=false` while `min_fw > VERSION`.
2. Default patch-only (non-stress) still sets `auto_ota_on_boot=false` to stop
   boot loops during manual recovery.
3. After USB patch: unplug USB, power cycle, sheet `auto_ota_on_boot=1` if you
   used default patch-only.

## Watch / harness rules

1. Watch clears backoff keys during OTA-pending recovery; **never** sets
   `force_ota=1` during stress.
2. Harness aborts a round if no `boot_start` within 20 minutes while device
   remains below `min_fw` (likely flash backoff — USB patch-only).
3. Harness bootstrap uses sheet preflight, not bare `cmd_ota=1`.
4. Harness accepts `boot_ota outcome=success` as round pass if Power_Log lags
   reboot (grace `POST_OTA_POWER_LOG_GRACE_S`, default 15 min).
5. Sheet preflight runs before **each** round ship (not only at startup).
6. `ota_stress_monitor.py` polls sheet + harness log every 5 min during runs.

## Dock / standby profile (switch+key off, V50 power)

1. Use harness `--profile dock` — sets `dock_mode=home` (Wi‑Fi standby logs),
   `boot_ota_prefer_wifi=0` (cellular boot OTA — rare updates, safer heap).
2. Round timeout default **3600s** (5 min log interval + OTA).
3. `--reset-v50` sets `boat-p2:v50_full_at_utc` for mAh / % tracking.
4. Expect Power_Log `mode=docked_off`, `uplink=wifi` when home AP reachable.
5. **Boot OTA Wi-Fi ENOMEM**: firmware retries cellular on same boot (`main.py`);
   standby skips auto_log while `min_fw` is ahead (`standby_monitor.py`).
6. **Dock split policy**: `dock_mode=home` → Wi‑Fi logs; boot OTA defaults cellular
   unless `boot_ota_prefer_wifi=1` explicitly set.

## Quick recovery

| Symptom | Action |
|---------|--------|
| `reboot_queued` loop, no `boot_start` | USB `run_usb_recovery.bat --patch-only --enable-boot-ota`, power cycle |
| ENOMEM on boot OTA | Ship version-only manifest; never bump min_fw with multi-file master |
| Stuck after USB | Sheet `auto_ota_on_boot=1`, power cycle |
| At min_fw but still rebooting | Clear `force_ota` / `cmd_ota` on Config |
