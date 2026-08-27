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
3. **`validate_release.py --max-files 1`** must pass before any stress ship or
   `apply_ship_config.py`.
4. **`apply_recovery_manifest.py --version-only`** runs in the harness before
   every git push.
5. Multi-file master releases are allowed only as explicit `wifi-feature`
   manifests: no bundle, at most eight files, and `version.py` last. Device
   policy refuses them over cellular.
6. `apply_ship_config.py` stages `boot_ota_prefer_wifi=1` without a firmware
   target, then waits for both a device `remote_config` acknowledgement and a
   successful Wi-Fi Power_Log. Only a later invocation may publish `min_fw`.

## Sheet rules

1. Before stress: `ota_stress_rules.preflight_sheet()` (or harness startup) sets
   `clear_ota_degraded=1`, `clear_boot_ota_backoff=1`, `auto_ota_on_boot=1` and
   clears `force_ota`, `cmd_ota`, `cmd_ota_force`, device-scoped equivalents,
   `cmd_clear_pending_ota`, and `ota_action`.
2. After every ship: `apply_ship_config.py` clears the same one-shots.
3. **Never** leave `force_ota=1` on Config while `current >= min_fw` — device
   will `reboot_queued` every log cycle without upgrading.
4. Transport prerequisites and a multi-file OTA target must never be written in
   the same phase.
5. Firmware defensively applies a changed transport setting but defers any OTA
   action and target from the same response until a later acknowledged payload.

## Device rules (firmware)

1. **`remote_control`**: `force_ota` / `cmd_ota` ignored when `VERSION >= min_fw`.
2. **`ota_health`**: preflight failures (`low_mem`, `low_flash`) do **not** set
   `ota_degraded` (transient heap/flash, not bad OTA).
3. **`main.py`**: on preflight fail while `needs_firmware_upgrade()`, keep
   `pending_ota` so recovery can retry boot OTA after sheet/USB clears backoff.
4. **Backoff trap**: `clear_boot_ota_backoff` on sheet clears flash
   `boot_ota_backoff_until` / `boot_ota_skip_remaining` (1.1.91+).
5. Manifest policy refusals clear `pending_ota`, force and automatic boot OTA,
   then continue into normal BLE/standby service.
6. Transient failures get at most two boot attempts before the same fail-open
   circuit breaker activates.
7. If a failed OTA request somehow remains persisted, key/switch ON bypasses it
   and starts BLE recovery.
8. Boot OTA performs no cellular/Event upload before the manifest transfer;
   lifecycle telemetry stays on flash until OTA completes or normal logging
   resumes, preserving an unfragmented heap for Wi-Fi TLS.
9. Repeated blocked-OTA checks within and across normal logs share one
   persistent fingerprint, preventing duplicate lifecycle and cellular Events
   uploads until the reason, target, or outcome changes.

## USB recovery rules

1. Prefer a normal patch with boot OTA disabled; a fresh explicit command is
   safer than carrying a failed request across recovery.
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
7. Live campaigns require `--allow-master-push` (wrapper:
   `ALLOW_MASTER_PUSH=1`). Any git, CDN, or Sheet ship failure stops the pass.
8. Events are baselined immediately before each ship; old lifecycle rows do not
   count as current-round progress.

## Production switch-on profile

1. Use `--profile switch-on` for qualification with switch/key ON.
2. Preserve production intervals: 600 seconds key-on and 3600 seconds standby.
3. Require every target-version Power_Log row to use `uplink=cellular`.
4. Do not count a round unless the subsequent clean-heap automatic log also
   completes with `power: ok, gps: ok`.
5. The 60-second `underway` profile is a bench-only pressure test and must not
   be used for winter qualification.

## Dock / standby profile (switch+key off, V50 power)

1. Use harness `--profile dock` — sets `dock_mode=home` (Wi‑Fi standby logs),
   `boot_ota_prefer_wifi=0` (cellular boot OTA — rare updates, safer heap).
2. The winter wrapper uses a **7200s** round timeout with a one-hour dock
   interval; release tooling preserves that cadence.
3. `--reset-v50` sets `boat-p2:v50_full_at_utc` for mAh / % tracking.
4. Expect Power_Log `mode=docked_off`, `uplink=wifi` when home AP reachable.
5. **Boot OTA Wi-Fi ENOMEM**: firmware retries cellular on same boot (`main.py`);
   standby skips auto_log while `min_fw` is ahead (`standby_monitor.py`).
6. **Dock split policy**: `dock_mode=home` → Wi‑Fi logs; boot OTA defaults cellular
   unless `boot_ota_prefer_wifi=1` explicitly set.
7. Dock rounds require the target-version Power Log to show a Wi-Fi SSID.
   A cellular target-version row does not satisfy the round.

See `WINTER_READINESS_CAMPAIGN.md` for the full six-round and transport matrix.

## Quick recovery

| Symptom | Action |
|---------|--------|
| `reboot_queued` loop, no `boot_start` | USB `run_usb_recovery.bat --patch-only --enable-boot-ota`, power cycle |
| ENOMEM on boot OTA | Device fails open; use USB or stage an acknowledged Wi-Fi feature release |
| Stuck after USB | Sheet `auto_ota_on_boot=1`, power cycle |
| At min_fw but still rebooting | Clear `force_ota` / `cmd_ota` on Config |
