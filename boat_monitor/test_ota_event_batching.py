"""Host regression for bounded OTA lifecycle backlog flushing."""

import os
import tempfile
from pathlib import Path

import ota_events_flush
import ota_lifecycle


class _Logger:
    _data_open = True

    def __init__(self):
        self.events = []

    def log_event(self, device, event, detail):
        self.events.append((device, event, detail))
        return {"ok": True}


def main():
    original_cwd = os.getcwd()
    original_state = ota_lifecycle.STATE_PATH
    original_pending = ota_lifecycle.PENDING_PATH
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        ota_lifecycle.STATE_PATH = str(Path(tmp) / "lifecycle.json")
        ota_lifecycle.PENDING_PATH = str(Path(tmp) / "pending.json")
        try:
            ota_lifecycle._save_pending(
                [
                    {"device": "boat-p2", "detail": "row=%d" % index}
                    for index in range(5)
                ]
            )
            logger = _Logger()
            assert ota_lifecycle.flush_pending(logger, max_rows=2) == 2
            assert len(logger.events) == 2
            assert len(ota_lifecycle._load_pending()) == 3

            assert ota_lifecycle.flush_pending(logger, max_rows=2) == 2
            assert len(logger.events) == 4
            assert len(ota_lifecycle._load_pending()) == 1

            assert ota_events_flush.UPLOAD_MAX_S <= 30
        finally:
            ota_lifecycle.STATE_PATH = original_state
            ota_lifecycle.PENDING_PATH = original_pending
            os.chdir(original_cwd)

    print("OTA event batching tests OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
