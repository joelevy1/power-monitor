# Home bench testing (Thonny + PC)

Use this when the unit is **off the boat** — prove **opto → GPIO → mode → BLE/standby**, **sheet logging**, **OTA**, and **self-heal** before the next field trial.

## What you need

| Item | Purpose |
|------|---------|
| **Thonny** + USB to Pico | REPL, copy files, interactive tests |
| **`config.py`**, **`secrets.py`** on Pico | Pins + sheet POST token |
| **Home Wi‑Fi** in `secrets.py` / `wifi_credentials.py` | Log + OTA without modem |
| **Optional:** bench **12 V** supply (current-limited) | Opto Ch5/Ch6 proof |
| **Optional:** SIM7600 **5 V** | Cellular log tests |

## Recommended order

### 1. Host PC (no Pico)

From repo root:

```bash
cd boat_monitor
python3 run_host_tests.py
python3 validate_release.py --check-github
```

All unit tests + release manifest check should pass before you trust OTA.

### 2. Opto / switch / key (USB only is enough for GPIO)

On Pico in Thonny:

```python
import bench_test
bench_test.main()
```

- **Menu 3** — one-shot GPIO (expect all **raw=1** / off with nothing on harness).
- **Menu 4** — live watch; apply **12 V** to **Switch** wire (Ch5 IN+) → **Battery switch GP20** must go **0** / ON.
- Repeat for **Key** → **GP21**.

**Wiring reference:** Ch5 OUT → **header pin 26** (GP20), Ch6 OUT → **pin 27** (GP21). Input LEDs on without GP20/21 low = **output side** not landed (field trial issue).

### 3. Mode + BLE vs standby

```python
import bench_resilience
bench_resilience.status()      # mode, inputs, gpio suffix, ble_wanted
bench_resilience.watch_modes() # toggle switch/key; expect key_on / switch_on_key_off
```

**BLE advertising test (without running main.py):**

```python
bench_resilience.ble_smoke()   # 2 min — scan with LightBlue / iOS app
```

**Production-like BLE/standby** (Thonny **closed**, switch/key ON, power-cycle):

- `main.py` should start **BLE** when GPIO reads ON.
- **1.1.47+:** 60 s GPIO-off hold; no auto-log while phone connected.

### 4. Logging to the sheet

```python
import bench_resilience
bench_resilience.one_log(prefer_wifi=True)   # home Wi‑Fi
```

Check **Power_Log**: `fw`, `uplink`, `mode`, `note` (1.1.46+ should include `gpio sw=… gp20=…`).

Cellular (modem powered):

```python
bench_resilience.one_log(prefer_wifi=False)
```

### 5. OTA / self-update

**Thonny + full pull:** Run `stop_main` (or rename `main.py`) before `bench_pull_firmware.run(reboot=False)` so rewriting `main.py` does not reboot into boot OTA and drop USB (EOF). The pull logs `ota_state: OTA begin…`, writes `version.py` and `main.py` last, and verifies every manifest file before clearing `ota_pending.json`. After **1.1.48+**, boot OTA also **repairs** when `VERSION` matches GitHub but a manifest file is missing (your partial 1.1.47 pull).

**Wi‑Fi bench (Thonny):**

```python
bench_resilience.ota_check()
bench_resilience.ota_apply_wifi()   # reboots if files changed
```

**Production path:** sheet `min_fw_version` = shipped version on `master`; power-cycle; confirm `fw` in Power_Log.

Never set `min_fw_version` above GitHub `master` manifest — see `RELEASE_PROCESS.md`.

### 6. Self-healing behavior

| Mechanism | How to exercise at home |
|-----------|-------------------------|
| **Stall reboot** | Standby, set short `interval_engine_off_s` via sheet (e.g. 120), block Wi‑Fi/cellular → **Events** `standby_stall_reboot` |
| **Degraded / overdue Events** | 1.1.45+ — failed posts or long gap; throttled rows on **Events** |
| **ENOMEM recovery** | 1.1.44+ — `mem_guard`, skip V50_Bank when low heap |
| **Boot OTA** | Power-cycle; 90 s boot window in `main.py` |
| **BLE latch** | Sheet `cmd_ble_latch=1` once → BLE stays up for GPIO debug |

After experiments:

```python
bench_resilience.clear_bench_state()
```

### 7. Diagnostics

```python
import diag_log
diag_log.tail(80)

bench_resilience.upload_diag()   # Events row if network up
```

### 8. Remote stress (PC, unit on boat or bench posting)

```bash
python3 remote_stress_pass.py
```

Polls sheet while driving Config — use when the Pico is left on **standby** overnight.

## Thonny vs `main.py`

| Goal | Thonny |
|------|--------|
| GPIO / I2C / one log / OTA from REPL | OK — use `bench_test` / `bench_resilience` |
| BLE + standby loop as in the field | **Close Thonny**, power-cycle, let **`main.py`** run |
| See `DIAG:` lines | Thonny serial or `diag_log.tail()` |

## Field trial lessons baked into tests

1. **Opter input LED ≠ GPIO** — always verify **GP20/GP21** with menu 4 or `watch_modes()`.
2. **Power_Log `docked_off` with switch on** — opto outputs not on pins 26/27.
3. **BLE connect then drop** — GPIO flutter or reboot to standby; 1.1.47 hold + `cmd_ble_latch`.
4. **Staggered OTA** — one `master` version only; `validate_release.py --check-github`.

## Files

| File | Role |
|------|------|
| `bench_test.py` | I2C, GPIO, LEDs, modem AT |
| `bench_resilience.py` | Mode, log, OTA, BLE smoke, state clear |
| `run_host_tests.py` | All PC-side unit tests |
| `remote_stress_pass.py` | Sheet-driven stress from laptop |
