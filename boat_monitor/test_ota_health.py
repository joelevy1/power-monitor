"""PC-side tests for ota_health.py."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ota_health", ROOT / "ota_health.py")
ota_health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota_health)


def test_enomem_error():
    assert ota_health.enomem_error(OSError(12, "ENOMEM"))
    assert ota_health.enomem_error(Exception("[Errno 12] ENOMEM"))
    assert ota_health.enomem_error(Exception("memory allocation failed, allocating 30068 bytes"))
    assert not ota_health.enomem_error(Exception("low_flash_4096"))
    assert not ota_health.enomem_error(None)


def main():
    test_enomem_error()
    print("ota_health tests OK")


if __name__ == "__main__":
    main()
