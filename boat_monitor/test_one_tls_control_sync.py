"""Host tests for one-TLS Apps Script POSTs and periodic dock control sync."""

import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_original_boat_status = sys.modules.get("boat_status")
if _original_boat_status is None:
    boat_status = types.ModuleType("boat_status")
    boat_status.read_status = lambda: {}
    sys.modules["boat_status"] = boat_status

import log_session
import remote_boot_config
import sheets_log
import wifi_uplink

if _original_boat_status is None:
    sys.modules.pop("boat_status", None)


REDIRECT = (
    b"HTTP/1.1 302 Found\r\n"
    b"Location: https://script.googleusercontent.com/macros/echo?key=abc\r\n"
    b"Content-Length: 0\r\n\r\n"
)
OK = b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n{"ok":true}'


class FakeSocket:
    def __init__(self, response):
        self.response = response
        self.read = False

    def settimeout(self, _value):
        pass

    def connect(self, _addr):
        pass

    def write(self, _data):
        pass

    def recv(self, _size):
        if self.read:
            return b""
        self.read = True
        return self.response

    def close(self):
        pass


def _request_with_responses(url, responses, accept=True):
    sockets = []

    def make_socket():
        sock = FakeSocket(responses[len(sockets)])
        sockets.append(sock)
        return sock

    saved = {
        "socket": sys.modules.get("socket"),
        "ussl": sys.modules.get("ussl"),
        "power": wifi_uplink.set_request_power_mode,
    }
    sys.modules["socket"] = types.SimpleNamespace(
        getaddrinfo=lambda host, port: [(None, None, None, None, (host, port))],
        socket=make_socket,
    )
    sys.modules["ussl"] = types.SimpleNamespace(
        wrap_socket=lambda sock, **_kwargs: sock
    )
    wifi_uplink.set_request_power_mode = lambda idle=False: None
    try:
        result = wifi_uplink.WifiHttp().http_post_json(
            url, "{}", accept_apps_script_redirect=accept
        )
        return result, len(sockets)
    finally:
        wifi_uplink.set_request_power_mode = saved["power"]
        for name in ("socket", "ussl"):
            old = saved[name]
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def test_trusted_redirect_acceptance_is_one_tls():
    result, socket_count = _request_with_responses(
        "https://script.google.com/macros/s/id/exec", [REDIRECT]
    )
    assert socket_count == 1
    assert result["_apps_script_redirect_accepted"] is True
    assert result["status"] == 302
    assert "commands" not in result
    for status in (301, 302, 303):
        assert wifi_uplink._trusted_apps_script_redirect(
            "POST",
            "https://script.google.com/macros/s/id/exec",
            status,
            "https://script.googleusercontent.com/macros/echo",
        )
    for location in (
        "http://script.googleusercontent.com/macros/echo",
        "https://script.googleusercontent.com:444/macros/echo",
        "https://evilscript.googleusercontent.com/macros/echo",
        "https://googleusercontent.com/macros/echo",
    ):
        assert not wifi_uplink._trusted_apps_script_redirect(
            "POST",
            "https://script.google.com/macros/s/id/exec",
            302,
            location,
        )
    assert not wifi_uplink._trusted_apps_script_redirect(
        "POST",
        "https://example.test/macros/s/id/exec",
        302,
        "https://script.googleusercontent.com/macros/echo",
    )


def test_untrusted_and_default_redirects_are_followed():
    evil_redirect = REDIRECT.replace(
        b"script.googleusercontent.com", b"attacker.example"
    )
    result, socket_count = _request_with_responses(
        "https://script.google.com/macros/s/id/exec", [evil_redirect, OK]
    )
    assert result == '{"ok":true}'
    assert socket_count == 2

    result, socket_count = _request_with_responses(
        "https://script.google.com/macros/s/id/exec", [REDIRECT, OK], accept=False
    )
    assert result == '{"ok":true}'
    assert socket_count == 2

    result, socket_count = _request_with_responses(
        "https://example.test/post", [REDIRECT, OK]
    )
    assert result == '{"ok":true}'
    assert socket_count == 2


def test_synthetic_response_never_applies_commands():
    logger = sheets_log.SheetsLogger(
        url="https://script.google.com/macros/s/id/exec", token="token"
    )
    synthetic = {
        "_apps_script_redirect_accepted": True,
        "status": 302,
        "commands": {"reboot": True},
    }
    remote = types.ModuleType("remote_control")
    remote.apply_from_log_response = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("synthetic response reached remote control")
    )
    old = sys.modules.get("remote_control")
    sys.modules["remote_control"] = remote
    try:
        assert logger._apply_remote_from_response(synthetic, "boat-p2") == []
    finally:
        if old is None:
            sys.modules.pop("remote_control", None)
        else:
            sys.modules["remote_control"] = old
    sync_logger = sheets_log.SheetsLogger(
        url="https://script.google.com/macros/s/id/exec",
        token="token",
        prefer_wifi=False,
        cellular_control_sync=True,
    )
    sync_logger._used_cellular = True
    assert sync_logger.uplink_label() == "cellular_control_sync"


def test_wifi_log_row_requires_direct_response_body():
    calls = []
    synthetic = {
        "_apps_script_redirect_accepted": True,
        "status": 302,
        "location": "https://script.googleusercontent.com/macros/echo",
    }

    class FakeHttp:
        def http_post_json(self, url, body, **kwargs):
            calls.append((url, body, kwargs))
            return synthetic

    fake_wifi = types.ModuleType("wifi_uplink")
    fake_wifi.WifiHttp = FakeHttp
    fake_wifi.WifiError = RuntimeError
    old = sys.modules.get("wifi_uplink")
    sys.modules["wifi_uplink"] = fake_wifi
    try:
        logger = sheets_log.SheetsLogger(
            url="https://script.google.com/macros/s/id/exec", token="token"
        )
        logger._wifi_ssid = "DockNet"
        result = logger.log_row("Events", {"device": "boat-p2"})
        assert result is synthetic
        assert calls[0][2]["accept_apps_script_redirect"] is False
        assert '"consume_commands": true' in calls[0][1]
    finally:
        if old is None:
            sys.modules.pop("wifi_uplink", None)
        else:
            sys.modules["wifi_uplink"] = old


def test_counter_persistence_nth_selection_and_return_to_wifi():
    original_path = remote_boot_config.PATH
    original_sheets = sys.modules.get("sheets_log")
    calls = []
    transport = {"wifi_falls_back": False, "cellular_sync_fails": False}

    class FakeLogger:
        def __init__(
            self,
            prefer_wifi,
            keep_wifi_connected=None,
            cellular_control_sync=False,
        ):
            self.prefer_wifi = prefer_wifi
            self.cellular_control_sync = cellular_control_sync
            self._used_cellular = (not prefer_wifi) or transport["wifi_falls_back"]
            transport["wifi_falls_back"] = False
            self._last_power_success = False
            self._last_remote_actions = []
            calls.append(
                ("select", prefer_wifi, cellular_control_sync, keep_wifi_connected)
            )

        def log_power_and_gps(self, **kwargs):
            if self.cellular_control_sync and transport["cellular_sync_fails"]:
                transport["cellular_sync_fails"] = False
                calls.append(("power_failed", kwargs["note"]))
                return "power: failed: simulated cellular timeout, gps: skipped"
            self._last_power_success = True
            calls.append(("power", kwargs["note"]))
            return "power: ok, gps: ok"

        def close_data(self, mode=None):
            calls.append(("close", mode))

    fake_sheets = types.ModuleType("sheets_log")
    fake_sheets.SheetsLogger = FakeLogger
    sys.modules["sheets_log"] = fake_sheets
    old_status = log_session.read_status
    old_wifi = log_session._wifi_uplink_configured
    log_session.read_status = lambda: {
        "device": "boat-p2",
        "mode": "docked_off",
        "engine": {},
        "house": {},
        "v50": {},
    }
    log_session._wifi_uplink_configured = lambda: True

    with tempfile.TemporaryDirectory() as tmp:
        remote_boot_config.PATH = str(Path(tmp) / "remote_boot_config.json")
        remote_boot_config.save({"cellular_control_sync_every_logs": 3})
        try:
            for _ in range(3):
                log_session.log_power_and_gps(
                    "auto_log",
                    prefer_wifi=True,
                    periodic_cellular_sync=True,
                )
            selections = [item for item in calls if item[0] == "select"]
            assert [item[1] for item in selections] == [True, True, False]
            assert selections[-1][2] is True
            assert "cellular_control_sync" in [
                item for item in calls if item[0] == "power"
            ][-1][1]
            assert (
                remote_boot_config.load()[
                    remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY
                ]
                == 0
            )

            log_session.log_power_and_gps(
                "auto_log",
                prefer_wifi=True,
                periodic_cellular_sync=True,
            )
            selections = [item for item in calls if item[0] == "select"]
            assert selections[-1][1] is True

            # A normal Wi-Fi connection failure that falls back to cellular
            # also satisfies the command-sync requirement.
            state = remote_boot_config.load()
            state[remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY] = 1
            remote_boot_config.save(state)
            transport["wifi_falls_back"] = True
            log_session.log_power_and_gps(
                "auto_log",
                prefer_wifi=True,
                periodic_cellular_sync=True,
            )
            assert (
                remote_boot_config.load()[
                    remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY
                ]
                == 0
            )

            # A failed due cellular sync must open the next cycles back to
            # Wi-Fi instead of trapping every future Power_Log on cellular.
            state = remote_boot_config.load()
            state[remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY] = 2
            remote_boot_config.save(state)
            transport["cellular_sync_fails"] = True
            log_session.log_power_and_gps(
                "auto_log",
                prefer_wifi=True,
                periodic_cellular_sync=True,
            )
            state = remote_boot_config.load()
            assert state[remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY] == 0
            assert (
                state[remote_boot_config.CELLULAR_CONTROL_SYNC_BACKOFF_KEY]
                == remote_boot_config.CELLULAR_CONTROL_SYNC_FAILURE_BACKOFF_LOGS
            )

            log_session.log_power_and_gps(
                "auto_log",
                prefer_wifi=True,
                periodic_cellular_sync=True,
            )
            selections = [item for item in calls if item[0] == "select"]
            assert selections[-1][1] is True
            assert (
                remote_boot_config.load()[
                    remote_boot_config.CELLULAR_CONTROL_SYNC_BACKOFF_KEY
                ]
                == remote_boot_config.CELLULAR_CONTROL_SYNC_FAILURE_BACKOFF_LOGS
                - 1
            )

            # A manual session remains Wi-Fi even if the persisted count is due.
            state = remote_boot_config.load()
            state[remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY] = 2
            remote_boot_config.save(state)
            log_session.log_power_and_gps("manual", prefer_wifi=True)
            selections = [item for item in calls if item[0] == "select"]
            assert selections[-1][1] is True

            # If watchdog/reset interrupts the modem before the logger returns,
            # the claim itself must make the next boot choose Wi-Fi.
            state = remote_boot_config.load()
            state.pop(remote_boot_config.CELLULAR_CONTROL_SYNC_BACKOFF_KEY, None)
            state[remote_boot_config.CELLULAR_CONTROL_SYNC_COUNT_KEY] = 2
            remote_boot_config.save(state)
            assert remote_boot_config.claim_cellular_control_sync() is True
            claimed = remote_boot_config.load()
            assert claimed[
                remote_boot_config.CELLULAR_CONTROL_SYNC_IN_PROGRESS_KEY
            ] is True
            assert remote_boot_config.cellular_control_sync_due() is False
            remote_boot_config.note_cellular_control_sync_power_success(False)
            recovered = remote_boot_config.load()
            assert (
                recovered["last_cellular_control_sync_outcome"]
                == "interrupted_backoff"
            )
            assert (
                recovered[remote_boot_config.CELLULAR_CONTROL_SYNC_BACKOFF_KEY]
                == remote_boot_config.CELLULAR_CONTROL_SYNC_FAILURE_BACKOFF_LOGS
                - 1
            )
        finally:
            remote_boot_config.PATH = original_path
            log_session.read_status = old_status
            log_session._wifi_uplink_configured = old_wifi
            if original_sheets is None:
                sys.modules.pop("sheets_log", None)
            else:
                sys.modules["sheets_log"] = original_sheets


def test_remote_setting_is_bounded_and_zero_disables():
    original_path = remote_boot_config.PATH
    with tempfile.TemporaryDirectory() as tmp:
        remote_boot_config.PATH = str(Path(tmp) / "remote_boot_config.json")
        try:
            applied = remote_boot_config.apply_settings(
                {"cellular_control_sync_every_logs": 0}
            )
            assert applied == ["cellular_control_sync_every_logs=0"]
            assert remote_boot_config.cellular_control_sync_due() is False
            remote_boot_config.apply_settings(
                {
                    "cellular_control_sync_every_logs":
                    remote_boot_config.CELLULAR_CONTROL_SYNC_MAX + 1
                }
            )
            assert remote_boot_config.effective_cellular_control_sync_every_logs() == 0
        finally:
            remote_boot_config.PATH = original_path


def main():
    test_trusted_redirect_acceptance_is_one_tls()
    test_untrusted_and_default_redirects_are_followed()
    test_synthetic_response_never_applies_commands()
    test_wifi_log_row_requires_direct_response_body()
    test_counter_persistence_nth_selection_and_return_to_wifi()
    test_remote_setting_is_bounded_and_zero_disables()
    print("one-TLS control sync tests OK")


if __name__ == "__main__":
    main()
