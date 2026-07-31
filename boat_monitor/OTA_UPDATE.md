# Boat Monitor P2 OTA updates

The Pico can update its MicroPython files from GitHub over the SIM7600 cellular
modem using `ota.py`.

## One-time setup on Pico

Copy these files to the Pico:

- `config.py`
- `main.py`
- `field_console.py`
- `ota.py`
- `ota_config.py`
- `version.py`

Optional debug/service files:

- `bench_test.py`
- `modem_check.py`
- `ble_probe.py`
- `ble_status.py`

## Manual OTA from the Pico REPL

```python
import ota
ota.check()
ota.update()
```

Set `reboot=True` to reboot after replacing files:

```python
ota.update(reboot=True)
```

## Manual OTA from phone service page

1. Connect phone to the Pico Wi-Fi AP.
2. Open `http://192.168.4.1`.
3. Tap `OTA from GitHub`.
4. Wait for the update result.
5. Reboot after a successful update.

## Release process

1. Update the files in `boat_monitor/`.
2. Bump `VERSION` in `version.py`.
3. Bump `version` in `ota_manifest.json`.
4. Commit and merge to `master`.
5. The installed Pico will pull from:

```text
https://raw.githubusercontent.com/joelevy1/power-monitor/master/boat_monitor/ota_manifest.json
```

## Safety notes

- The updater writes each downloaded file to `<name>.new` before replacing the
  current file.
- The previous file is kept as `<name>.bak` where possible.
- Keep device-specific secrets in `secrets.py` on the Pico only. Do not add
  `secrets.py` to `ota_manifest.json`; it is intentionally ignored by git.
- Avoid removing or renaming `ota.py` and `ota_config.py` from the manifest
  unless you have tested the replacement path.
- Keep `bench_test.py` and `modem_check.py` available as recovery/debug tools.
