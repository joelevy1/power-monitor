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


def _version_tuple(text):
    parts = []
    for piece in str(text or "").strip().split("."):
        try:
            parts.append(int(piece))
        except Exception:
            parts.append(0)
    return tuple(parts)


def _version_lt(a, b):
    return _version_tuple(a) < _version_tuple(b)


def load_manifest(client):
    raw = _http_get_retry(client, ota_config.OTA_MANIFEST_URL)
    data = json.loads(raw)
    try:
        import remote_boot_config

        min_fw = (remote_boot_config.load() or {}).get("min_fw_version")
        manifest_ver = str(data.get("version") or "")
        if min_fw and _version_lt(manifest_ver, min_fw):
            alt = getattr(ota_config, "OTA_MANIFEST_JSdelivr_URL", "")
            if alt:
                alt_raw = _http_get_retry(client, alt)
                alt_data = json.loads(alt_raw)
                if not _version_lt(str(alt_data.get("version") or ""), min_fw):
                    print(
                        "OTA: raw manifest %s behind min_fw %s — using jsDelivr"
                        % (manifest_ver, min_fw)
                    )
                    return alt_data
    except Exception as exc:
        print("OTA: manifest CDN fallback skipped:", exc)
    return data


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


def _prepare_transfer_heap():
    try:
        import gc

        gc.collect()
        gc.collect()
    except Exception:
        pass


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
        try:
            os.remove(bak_path)
        except OSError:
            pass
    except Exception as exc:
        raise OtaError("failed replacing %s: %s" % (path, exc))


def download_file_streaming(client, url, path, min_size=1, attempts=2):
    """Download directly to flash when the transport supports streaming.

    Both Wi-Fi and cellular clients implement download_to_file(). Keeping the
    source body out of the MicroPython heap avoids ENOMEM on larger modules.
    """
    if not hasattr(client, "download_to_file"):
        data = _http_get_retry(client, url, attempts=attempts)
        if len(data) < min_size:
            raise OtaError("%s was too small (%d bytes)" % (path, len(data)))
        write_file(path, data)
        return len(data)

    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            _prepare_transfer_heap()
            try:
                import ota_trace

                ota_trace.note_http_session()
                ota_trace.step("http_stream", url=url[-48:], path=path, attempt=attempt)
            except Exception:
                pass
            try:
                nbytes = client.download_to_file(url, path, timeout_s=120)
            except TypeError:
                nbytes = client.download_to_file(url, path)
            if nbytes < min_size:
                raise OtaError("%s was too small (%d bytes)" % (path, nbytes))
            try:
                import os

                os.remove(path + ".bak")
            except OSError:
                pass
            return nbytes
        except Exception as exc:
            last_exc = exc
            print("OTA: stream attempt %d/%d failed: %s" % (attempt, attempts, exc))
            try:
                import os

                os.remove(path + ".new")
            except OSError:
                pass
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            if attempt < attempts:
                time.sleep(1.5)
    raise OtaError(str(last_exc))


def _ota_prune_bak_files(paths):
    try:
        import os

        for path in paths or []:
            try:
                os.remove(path + ".bak")
            except OSError:
                pass
        try:
            os.remove("ota_release.bmota")
            os.remove("ota_release.bmota.new")
        except OSError:
            pass
    except Exception:
        pass


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
    expected_sha = str(bundle.get("sha256") or "").strip().lower()
    if expected_sha:
        try:
            try:
                import ubinascii as binascii
            except ImportError:
                import binascii
            try:
                import uhashlib as hashlib
            except ImportError:
                import hashlib

            digest = hashlib.sha256()
            with open(bpath, "rb") as bundle_file:
                while True:
                    chunk = bundle_file.read(1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            actual_sha = binascii.hexlify(digest.digest()).decode().lower()
        except Exception as exc:
            raise OtaError("bundle sha256 check failed: %s" % exc)
        if actual_sha != expected_sha:
            raise OtaError("bundle sha256 mismatch")
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
        try:
            import gc

            gc.collect()
        except Exception:
            pass


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
    fw_at_start = current_version()

    try:
        import ota_trace

        ota_trace.begin(
            fw_from=fw_at_start,
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
    try:
        import ota_diag

        ota_diag.upload_bounded(phase="ota_start", prefer_wifi=prefer_wifi, max_total_s=20)
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
        try:
            import ota_health

            ok, reason = ota_health.check_manifest_policy(manifest, used_wifi=used_wifi)
            if not ok:
                print("OTA: manifest policy refused:", reason)
                try:
                    import ota_lifecycle

                    ota_lifecycle.phase(
                        "manifest_refused",
                        inline=False,
                        target_fw=manifest.get("version"),
                        error=reason,
                        file_count=len(manifest.get("files") or []),
                    )
                except Exception:
                    pass
                raise OtaError(reason)
        except OtaError:
            raise
        except Exception as exc:
            print("OTA: manifest policy check skipped:", exc)
        target_version = manifest.get("version", "unknown")
        print("Target version:", target_version)
        file_list = manifest.get("files") or []
        _ota_prune_bak_files([e.get("path") for e in file_list if e.get("path")])
        try:
            import ota_lifecycle

            ota_lifecycle.phase(
                "manifest_ok",
                inline=False,
                target_fw=target_version,
                file_count=len(file_list),
                bundle=1 if manifest.get("bundle") else 0,
            )
        except Exception:
            pass
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
                    import ota_lifecycle

                    ota_lifecycle.phase(
                        "file_start",
                        inline=False,
                        target_fw=target_version,
                        path=path,
                    )
                except Exception:
                    pass
                try:
                    import ota_trace

                    ota_trace.step("per_file_start", path=path)
                except Exception:
                    pass
                downloaded_bytes = download_file_streaming(
                    client,
                    url,
                    path,
                    min_size=min_size,
                )
                try:
                    import ota_diag
                    import ota_lifecycle

                    snap = ota_diag.snapshot()
                    ota_lifecycle.phase(
                        "file_done",
                        inline=False,
                        target_fw=target_version,
                        path=path,
                        bytes=downloaded_bytes,
                        mem_free=snap.get("mem_free"),
                        fs_free_b=snap.get("fs_free_b"),
                    )
                except Exception:
                    pass
                try:
                    import gc

                    gc.collect()
                except Exception:
                    pass
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
                import ota_trace

                extra = ota_trace.stats()
                ota_telemetry.report_boot_ota(
                    "success_pending_reboot",
                    fw_target=target_version,
                    fw_from=fw_at_start,
                    max_s=max_total_s,
                    prefer_wifi=prefer_wifi,
                    elapsed_s=int(extra.get("elapsed_s") or _ota_elapsed_s(start)),
                    http_sessions=extra.get("http_sessions"),
                    transport="bundle" if use_bundle else "per_file",
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
            import ota_diag

            ota_diag.upload_bounded(
                phase="ota_failed",
                prefer_wifi=prefer_wifi,
                max_total_s=25,
                err=str(exc)[:120],
            )
        except Exception:
            pass
        try:
            import ota_trace

            ota_trace.step("error", err=str(exc)[:200])
        except Exception:
            pass
        _upload_trace(
            "failed",
            fw_target=target_version,
            error=str(exc)[:200],
            elapsed_s=int(_ota_elapsed_s(start)),
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
