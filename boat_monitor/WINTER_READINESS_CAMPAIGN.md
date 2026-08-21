# Winter readiness campaign

This is the controlled qualification plan for leaving `boat-p2` unattended.
The goal is not merely to observe version labels; every phase must prove that
the intended code, transport, recovery policy, and post-upgrade logging work.

## Baseline — 2026-08-21

- USB loaded firmware `1.1.116` and the fixed `remote_boot_config.py`.
- A cellular `boot_log` and subsequent `auto_log` reached `Power_Log`.
- The latest `ota_capability` reported:
  - `fw=1.1.116`
  - `min_fw=1.1.116`
  - `pending_ota=0`
  - `ota_degraded=0`
  - `boot_ota_backoff=0`
  - `needs_upgrade=0`
- An 8-second hardware watchdog caused repeated resets during legal
  120-second cellular HTTP waits. USB temporarily disabled that watchdog on
  this device. The permanent fix feeds it only while bounded I/O loops are
  progressing.
- The former USB verification gate truncated capability details before
  checking `will_boot_ota`; that was a verifier failure, not a device failure.

## Non-negotiable campaign rules

1. Never set `min_fw_version` ahead of the version published on GitHub
   `master`; `validate_release.py --check-github` must pass first.
2. Never advance to the next round until the current firmware, expected
   transport, and stable post-upgrade log are confirmed.
3. Clear every OTA one-shot before each round:
   `force_ota`, `cmd_ota`, `cmd_ota_force`, device-scoped equivalents,
   `cmd_clear_pending_ota`, and `ota_action`.
4. A failed ship, stale CDN manifest, low-flash event, reboot trap, missing
   `boot_start`, wrong transport, or timeout pauses `min_fw` at the currently
   installed firmware and stops the campaign.
5. Cellular stress manifests contain only `version.py`.
6. A multi-file release on master must be explicitly marked `wifi-feature`,
   contain at most eight files, have no bundle, and install `version.py` last.
   Device policy refuses that manifest over cellular.
7. Routine winter cadence remains one hour while docked. Release tooling must
   not silently restore the five-minute bench interval.
8. Each campaign run requires explicit `ALLOW_MASTER_PUSH=1`; preflight
   failures are never swallowed.

## Qualification phases

### Phase 0 — permanent hardening release

Ship one Wi-Fi-only feature release containing:

1. `resilience.py`
2. `cellular.py`
3. `gps.py`
4. `wifi_uplink.py`
5. `remote_boot_config.py`
6. `version.py` last

Pass criteria:

- Device accepts the release only over Wi-Fi.
- New firmware reports through `Power_Log`.
- Hardware watchdog remains enabled.
- One cellular log and one Wi-Fi log both complete without a reset.
- `standby_prefer_wifi` can be changed through Sheet Config.

### Phase 1 — dock Wi-Fi baseline

Apply:

- `dock_mode=home`
- `standby_prefer_wifi=1`
- `boot_ota_prefer_wifi=0`
- `interval_engine_off_s=3600`
- `interval_engine_on_s=600`

Pass criteria:

- `mode=docked_off`
- `uplink` is the connected SSID, not `cellular`
- no ENOMEM, WDT reset, degraded event, or reboot storm
- a second scheduled log succeeds

### Phase 2 — six complete sequential upgrades

Run six version-only rounds. For every round:

1. Preflight Sheet, watcher, manifest, flash/reboot state, and current version.
2. Publish one version to `master`.
3. Confirm the remote raw manifest.
4. Set exactly that `min_fw_version`.
5. Observe `aware`, `boot_start`, completion, and a target-version Power Log.
6. Require the post-upgrade dock log to use Wi-Fi.
7. Record elapsed time, heap/flash telemetry, transport, and recovery state.
8. Cool down before the next release.

Six passes means six autonomous upgrades without USB, not six version labels
obtained through manual recovery.

### Phase 3 — transport and recovery matrix

After the six-round pass:

| Case | Expected result |
|---|---|
| Wi-Fi routine log | SSID shown in `uplink`; no cellular session |
| Cellular routine log | `uplink=cellular`; modem wakes, posts, and powers down |
| Cellular boot OTA | Version-only update completes and returns to Wi-Fi logging |
| Wi-Fi boot OTA | Version-only update completes with Wi-Fi transport evidence |
| Wi-Fi unavailable | Bounded failure/fallback; no infinite wait or WDT loop |
| Invalid/stale target | Preflight blocks Sheet change |
| Low flash | Immediate pause; no repeated target advancement |
| OTA failure/backoff | Watcher observes it; campaign pauses automatically |
| Power cycle | Device returns without USB and resumes the configured cadence |

Network-loss fault injection that requires physically disabling an access point
must be scheduled with the owner; the campaign must not fake a pass.

### Phase 4 — winter soak

- Restore `min_fw_version` to the installed release.
- Disable campaign one-shots and unnecessary boot OTA.
- Keep dock Wi-Fi-first with cellular fallback.
- Observe at least 24 hours of hourly logs.
- Confirm V50 voltage/energy values, no unexplained gaps, no reboot bursts, and
  no accumulating `.bak`, `.new`, bundle, or diagnostic files.

## Evidence

Store campaign output in ignored runtime files:

- `ota_stress_results.json`
- `boat_monitor/week_away_ota.log`
- `boat_p2_watch_state.json`

Summarize each completed round in this document or a dated companion report.
Do not treat old Sheet history as current-round evidence; event baselines are
captured immediately before each ship.

## Campaign log

### 2026-08-21 — Phase 0 attempt 1: safely paused

- `1.1.117` merged and both GitHub API and raw CDN were verified before the
  Sheet target changed.
- Sheet was configured for Wi-Fi-only boot OTA and `min_fw_version=1.1.117`.
- The Pico remained alive on `1.1.116`; a 6:24 AM Pacific diagnostic event
  reported `power: ok` followed by a GPS/HTTPDATA failure, but no persisted
  Power Log, `remote_config`, capability, or `boot_start` acknowledged the new
  target.
- At 20 minutes the operator applied the emergency brake: `min_fw_version`
  returned to `1.1.116`, boot OTA was disabled, one-shots were cleared, and the
  known cellular/away profile was restored.
- This was not evidence that the Wi-Fi payload failed: the old 20-minute
  `boot_start` deadline was shorter than the one-hour winter log interval, so
  the device might not have fetched the new Sheet policy yet.
- Guardrail correction: dock campaigns now allow 4500 seconds (one 3600-second
  interval plus 15 minutes) for the first `boot_start`. Underway campaigns keep
  the stricter 1200-second gate.

### 2026-08-21 — Phase 0 attempt 2: failed before OTA

- The corrected timing gate was merged and the target was re-armed with stale
  pending-clear commands blank.
- No Power Log or heartbeat appeared during the next scheduled hourly window.
  The final telemetry remained:
  - Power Log: `1.1.116`, cellular, 6:09 AM Pacific.
  - Event: 6:24 AM Pacific, `power: ok` followed by a GPS HTTPDATA prompt
    failure.
- There was no `remote_config`, capability, `aware`, `boot_start`, or reboot
  evidence for the retry. Therefore the device never proved it fetched the new
  Wi-Fi-only policy; the `1.1.117` payload was not attempted.
- Most likely failure: `1.1.116` became blocked in a modem/HTTP operation after
  its temporary on-device watchdog disable. With no watchdog reset and no
  out-of-band command channel, Sheet changes cannot recover a blocked process.
- The emergency brake restored `min_fw_version=1.1.116`, disabled boot OTA,
  restored the known cellular/away profile, and cleared OTA one-shots.
- The six-round campaign did not start.

Required recovery before another campaign attempt:

1. Physically power-cycle V50; USB flashing is not initially required.
2. Confirm a fresh `1.1.116` Power Log and capability row.
3. Do not re-arm `1.1.117` until the device has acknowledged the safe rollback.
4. If it hangs again before acknowledgment, USB-install the `1.1.117` hardening
   files because the old firmware has no remaining remote recovery path.

### 2026-08-21 — Phase 0 attempt 3: Wi-Fi preflight blocked by low flash

- A physical V50 power cycle recovered the blocked process. Fresh cellular
  Power Logs appeared at 7:24 and 7:31 AM Pacific.
- The target was re-armed. At 7:42 AM the Pico acknowledged the Wi-Fi-only
  policy; lifecycle telemetry then showed:
  - `boot_start`, firmware `1.1.116`, `prefer_wifi=True`
  - `device_stats ... fs_free_b=0`
  - `boot_end ... error=low_flash_4096; outcome=failed`
- The preflight correctly refused the six-file payload before any file was
  installed. The Pico returned on `1.1.116`; a second reboot was queued because
  `min_fw` remained ahead during the reporting cycle.
- The emergency brake immediately restored `min_fw_version=1.1.116`, disabled
  boot OTA, restored the cellular/away profile, and cleared pending/one-shot
  state.
- No stress round started and no partial `1.1.117` installation occurred.

Conclusion: winter qualification cannot continue remotely from this flash
state. USB cleanup is required to remove `.bak`, `.new`, bundle, and diagnostic
artifacts. The subsequent full USB push must include `gps.py` as well as the
other watchdog-aware network modules before the hardware watchdog is re-enabled.
