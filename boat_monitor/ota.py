"""
Boat Monitor P2 - manifest-driven OTA updater. Prefers Wi-Fi (wifi_uplink.py)
over the cellular SIM7600 modem (cellular.py) when a known network is
configured and reachable -- no cellular data usage, no modem needed, and
much faster. Falls back to cellular automatically if Wi-Fi isn't configured
or fails to connect.

Run manually from the Pico:

    import ota
    ota.update()

Safe to prefer Wi-Fi here specifically because main.py runs this OTA check
BEFORE BLE ever starts -- Wi-Fi and BLE share one radio on the Pico W and
cannot run at the same time (see ensure_wifi_off() in ble_service.py). Do
not call ota.update()/check() while BLE is active.

The updater downloads ota_manifest.json, then either one release bundle
(ota_release.bmota — one HTTP GET on cellular) or each listed file from
GitHub raw URLs. Files are written as .new first, then the previous copy is
kept as .bak where possible.
"""

import time

try:
    import ujson as json
except ImportError:
    import json

import ota_config


class OtaError(Exception):
    pass


def current_version():
    try:
        import version

        return getattr(version, "VERSION", "unknown")
    except Exception:
        return "unknown"


def load_manifest(client):
    data = _http_get_retry(client, ota_config.OTA_MANIFEST_URL)
    return json.loads(data)


def _http_get_retry(client, url, attempts=3):
    """Retry manifest/file downloads — Pico Wi-Fi TLS often aborts once (errno 103)."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            try:
                import ota_trace

                ota_trace.note_http_session()
                ota_trace.step("http_get", url=url[-48:], attempt=attempt)
            except Exception:
                pass
            try:
                return client.http_get(url, timeout_s=30)
            except TypeError:
                return client.http_get(url)
        except Exception as exc:
            last_exc = exc
            print("OTA: GET attempt %d/%d failed: %s" % (attempt, attempts, exc))
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            if attempt < attempts:
                time.sleep(1.5)
    raise OtaError(str(last_exc))


def write_file(path, data):
    tmp_path = path + ".new"
    bak_path = path + ".bak"

    print("Writing", tmp_path)
    with open(tmp_path, "w") as f:
        f.write(data)

    try:
        # Remove stale backup before replacing current file.
        import os

        try:
            os.remove(bak_path)
        except OSError:
            pass
        try:
            os.rename(path, bak_path)
        except OSError:
            pass
        os.rename(tmp_path, path)
    except Exception as exc:
        raise OtaError("failed replacing %s: %s" % (path, exc))


def _min_sizes_from_manifest(manifest):
    out = {}
    for entry in manifest.get("files") or []:
        path = entry.get("path")
        if path:
            out[path] = entry.get("min_size", 1)
    return out


def _download_bundle_to_path(client, bundle):
    url = bundle.get("url")
    if not url:
        raise OtaError("bundle missing url")
    expected_size = bundle.get("size")
    path = bundle.get("path") or "ota_release.bmota"

    if hasattr(client, "download_to_file"):
        try:
            import ota_trace

            ota_trace.note_http_session()
            ota_trace.step("bundle_download_to_file", path=path)
        except Exception:
            pass
        try:
            import gc

            gc.collect()
        except Exception:
            pass
        nbytes = client.download_to_file(url, path, timeout_s=180)
        if expected_size and nbytes != expected_size:
            raise OtaError("bundle size %d != manifest %d" % (nbytes, expected_size))
        return path

    if hasattr(client, "http_get_bytes"):
        try:
            import ota_trace

            ota_trace.note_http_session()
            ota_trace.step("bundle_http_get_bytes")
        except Exception:
            pass
        blob = client.http_get_bytes(url)
    else:
        blob = _http_get_retry(client, url)
        if isinstance(blob, str):
            blob = blob.encode("utf-8", "ignore")
    if expected_size and len(blob) != expected_size:
        raise OtaError("bundle size %d != manifest %d" % (len(blob), expected_size))
    with open(path, "wb") as out:
        out.write(blob)
    return path


def _download_bundle_blob(client, bundle):
    """Legacy: load entire bundle into RAM (avoid on Pico when possible)."""
    path = _download_bundle_to_path(client, bundle)
    with open(path, "rb") as f:
        return f.read()


def apply_bundle(client, manifest):
    bundle = manifest.get("bundle")
    if not bundle:
        return False

    print("OTA: single bundle download")
    try:
        import ota_trace

        ota_trace.step("bundle_download_start", size=bundle.get("size"))
    except Exception:
        pass
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    bpath = _download_bundle_to_path(client, bundle)
    try:
        import ota_bundle
    except Exception as exc:
        raise OtaError("ota_bundle missing: %s" % exc)

    min_sizes = _min_sizes_from_manifest(manifest)
    written = {}

    def _write(path, text):
        min_size = min_sizes.get(path, 1)
        if len(text) < min_size:
            raise OtaError("%s was too small (%d bytes)" % (path, len(text)))
        try:
            import ota_trace

            ota_trace.step("extract_write", path=path, bytes=len(text))
        except Exception:
            pass
        write_file(path, text)
        written[path] = True

    count = ota_bundle.extract_from_file(bpath, _write)
    print("OTA: extracted %d files from bundle" % count)

    for path in min_sizes:
        if path not in written:
            raise OtaError("bundle missing %s" % path)

    try:
        import os

        bpath = bundle.get("path") or "ota_release.bmota"
        try:
            os.remove(bpath)
        except OSError:
            pass
        for suffix in (".new", ".bak"):
            try:
                os.remove(bpath + suffix)
            except OSError:
                pass
    except Exception:
        pass

    return True


def apply_manifest_files(client, manifest):
    files = manifest.get("files", [])
    if not files:
        raise OtaError("manifest has no files")

    for entry in files:
        path = entry["path"]
        url = entry["url"]
        min_size = entry.get("min_size", 1)

        print("Updating", path)
        data = _http_get_retry(client, url)
        if len(data) < min_size:
            raise OtaError("%s was too small (%d bytes)" % (path, len(data)))
        write_file(path, data)


def apply_manifest(client, manifest):
    """Legacy name — per-file download (no bundle)."""
    apply_manifest_files(client, manifest)


def _get_client(prefer_wifi=True):
    """Prefer Wi-Fi over cellular when prefer_wifi is True -- see module
    docstring for why this is only safe when BLE is NOT active (e.g. the
    boot-time OTA check). Callers that can run while BLE is connected --
    e.g. the "ota" BLE command in ble_service.py -- MUST pass
    prefer_wifi=False so this never touches the Wi-Fi radio and only uses
    the cellular modem (separate UART hardware, no conflict with BLE).

    Returns (client, used_wifi); used_wifi tells the caller which teardown
    to run.
    """
    if prefer_wifi:
        try:
            import wifi_uplink

            nets = wifi_uplink.load_networks()
            if not nets:
                raise OtaError(
                    "no Wi-Fi networks on Pico — save wifi_known_networks.py from GitHub "
                    "(boat_monitor/) or copy wifi_credentials.example.py to wifi_credentials.py"
                )
        except OtaError:
            raise
        except Exception:
            pass

        try:
            import wifi_uplink

            ssid = wifi_uplink.connect(timeout_s=15)
            if not ssid:
                time.sleep(2)
                ssid = wifi_uplink.connect(timeout_s=15)
            if ssid:
                print("OTA: using Wi-Fi (%s)" % ssid)
                return wifi_uplink.WifiHttp(), True
        except Exception as exc:
            print("OTA: Wi-Fi attempt failed:", exc)

        allow_cell = True
        try:
            import config as cfg

            allow_cell = getattr(cfg, "ALLOW_CELLULAR_WIFI_FALLBACK", True)
        except ImportError:
            pass
        if prefer_wifi and wifi_uplink.load_networks() and allow_cell:
            print("OTA: Wi-Fi unreachable — trying cellular")
        elif prefer_wifi:
            raise OtaError("Wi-Fi could not connect (cellular fallback disabled or no networks)")

    print("OTA: using cellular")
    from cellular import Sim7600Modem

    client = Sim7600Modem()
    client.ensure_data()  # always resets the modem first -- see cellular.py
    return client, False


def _ota_elapsed_s(start):
    return time.time() - start


def _check_ota_deadline(start, max_total_s, where):
    if max_total_s is None:
        return
    if _ota_elapsed_s(start) >= max_total_s:
        raise OtaError("OTA exceeded max_total_s=%s at %s" % (max_total_s, where))


def _close_client(client, used_wifi):
    if used_wifi:
        try:
            import wifi_uplink

            wifi_uplink.disconnect()
        except Exception as exc:
            print("OTA: wifi_uplink.disconnect() warning:", exc)
        return

    client.close_data()  # cellular.py handles HTTPTERM/NETCLOSE (Phase 2.4 discipline)


def update(reboot=False, prefer_wifi=None, max_total_s=None):
    print("Boat Monitor OTA update")
    print("Current version:", current_version())
    print("Manifest:", ota_config.OTA_MANIFEST_URL)
    if prefer_wifi is None:
        try:
            import ble_policy

            prefer_wifi = ble_policy.ota_prefer_wifi()
        except Exception:
            prefer_wifi = True
    print("OTA prefer_wifi:", prefer_wifi)
    if max_total_s is not None:
        print("OTA max_total_s:", max_total_s)

    start = time.time()
    target_version = None
    used_wifi = None
    client = None
    trace_uploaded = False

    try:
        import ota_trace

        ota_trace.begin(
            fw_from=current_version(),
            prefer_wifi=prefer_wifi,
            max_total_s=max_total_s,
            source="ota.update",
        )
    except Exception:
        pass

    def _upload_trace(outcome, **extra):
        nonlocal trace_uploaded
        if trace_uploaded:
            return
        try:
            import ota_trace

            ota_trace.upload(
                outcome=outcome,
                prefer_wifi=prefer_wifi,
                max_total_s=50,
                fw_target=target_version or extra.get("fw_target"),
                **extra,
            )
            trace_uploaded = True
        except Exception:
            pass

    _check_ota_deadline(start, max_total_s, "start")
    try:
        import gc

        gc.collect()
    except Exception:
        pass

    client, used_wifi = _get_client(prefer_wifi=prefer_wifi)
    try:
        try:
            import ota_trace

            ota_trace.step("uplink_ready", transport="wifi" if used_wifi else "cellular")
        except Exception:
            pass
        _check_ota_deadline(start, max_total_s, "after connect")
        manifest = load_manifest(client)
        _check_ota_deadline(start, max_total_s, "after manifest")
        target_version = manifest.get("version", "unknown")
        print("Target version:", target_version)
        try:
            import ota_trace

            ota_trace.step("manifest_ok", target=target_version)
        except Exception:
            pass

        if target_version == current_version():
            print("Already at target version.")
            try:
                import remote_boot_config

                remote_boot_config.clear_pending_ota_if_current()
            except Exception:
                pass
            _upload_trace("no_upgrade", fw_target=target_version)
            return False

        _check_ota_deadline(start, max_total_s, "before payload")
        use_bundle = bool(manifest.get("bundle"))
        if use_bundle:
            try:
                import ota_bundle  # noqa: F401
            except Exception:
                print("OTA: bundle in manifest but ota_bundle.py missing — per-file fallback")
                use_bundle = False
        try:
            import ota_trace

            ota_trace.step(
                "payload_mode",
                mode="bundle" if use_bundle else "per_file",
                file_count=len(manifest.get("files") or []),
            )
        except Exception:
            pass
        if use_bundle:
            apply_bundle(client, manifest)
        else:
            files = manifest.get("files", [])
            for entry in files:
                _check_ota_deadline(start, max_total_s, "before %s" % entry.get("path"))
                path = entry["path"]
                url = entry["url"]
                min_size = entry.get("min_size", 1)
                print("Updating", path)
                try:
                    import ota_trace

                    ota_trace.step("per_file_start", path=path)
                except Exception:
                    pass
                data = _http_get_retry(client, url)
                if len(data) < min_size:
                    raise OtaError("%s was too small (%d bytes)" % (path, len(data)))
                write_file(path, data)

        print("Update complete.")
        print("Reboot required to run new files.")
        try:
            import ota_trace

            ota_trace.step("payload_complete", elapsed_s=int(_ota_elapsed_s(start)))
        except Exception:
            pass

        _upload_trace(
            "success",
            fw_target=target_version,
            transport="bundle" if use_bundle else "per_file",
        )

        if reboot:
            try:
                import ota_telemetry

                ota_telemetry.report_boot_ota(
                    "success_pending_reboot",
                    fw_target=target_version,
                    max_s=max_total_s,
                    prefer_wifi=prefer_wifi,
                    source="ota.update",
                )
            except Exception:
                pass
            import machine

            time.sleep(1)
            machine.reset()

        return True
    except Exception as exc:
        try:
            import ota_trace

            ota_trace.step("error", err=str(exc)[:200])
        except Exception:
            pass
        _upload_trace(
            "failed",
            fw_target=target_version,
            error=str(exc)[:200],
        )
        raise
    finally:
        _close_client(client, used_wifi)


def check(prefer_wifi=None):
    if prefer_wifi is None:
        try:
            import ble_policy

            prefer_wifi = ble_policy.ota_prefer_wifi()
        except Exception:
            prefer_wifi = True
    client, used_wifi = _get_client(prefer_wifi=prefer_wifi)
    try:
        manifest = load_manifest(client)
        print("Current:", current_version())
        print("Available:", manifest.get("version", "unknown"))
        print("Notes:", manifest.get("notes", ""))
        return manifest
    finally:
        _close_client(client, used_wifi)
