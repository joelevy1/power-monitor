"""Host-side tests for mem_guard helpers."""

import mem_guard


def test_is_enomem():
    assert mem_guard.is_enomem(OSError(12, "ENOMEM"))
    assert mem_guard.is_enomem(Exception("[Errno 12] ENOMEM"))
    assert not mem_guard.is_enomem(OSError(11, "EAGAIN"))


def test_low_heap_threshold():
    assert mem_guard.low_heap_threshold() == 22000


def test_heap_ok_for_https_post():
    # On host gc.mem_free is large — should pass
    assert mem_guard.heap_ok_for_https_post()
    assert not mem_guard.skip_network_diag_upload()


def test_skip_followup_after_log_fail():
    assert mem_guard.skip_followup_after_log_fail("power: failed: [Errno 12] ENOMEM")
    assert not mem_guard.skip_followup_after_log_fail("power: ok")


if __name__ == "__main__":
    test_is_enomem()
    test_low_heap_threshold()
    test_heap_ok_for_https_post()
    test_skip_followup_after_log_fail()
    print("test_mem_guard OK")
