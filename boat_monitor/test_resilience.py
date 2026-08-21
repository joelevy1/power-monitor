#!/usr/bin/env python3
"""Host checks for bounded hardware-watchdog feeding."""

from __future__ import annotations

import resilience


class FakeTime:
    def __init__(self):
        self.now_ms = 0

    def ticks_ms(self):
        return self.now_ms

    @staticmethod
    def ticks_diff(new, old):
        return new - old

    def sleep(self, seconds):
        self.now_ms += int(float(seconds) * 1000)


class FakeWdt:
    def __init__(self):
        self.feeds = 0

    def feed(self):
        self.feeds += 1


def main():
    original_time = resilience.time
    original_wdt = resilience._wdt
    original_last_feed = resilience._last_watchdog_feed_ms
    fake_time = FakeTime()
    fake_wdt = FakeWdt()
    try:
        resilience.time = fake_time
        resilience._wdt = fake_wdt
        resilience._last_watchdog_feed_ms = 0

        resilience.feed_watchdog_if_due()
        assert fake_wdt.feeds == 0
        fake_time.now_ms = resilience.WDT_FEED_INTERVAL_MS - 1
        resilience.feed_watchdog_if_due()
        assert fake_wdt.feeds == 0
        fake_time.now_ms += 1
        resilience.feed_watchdog_if_due()
        assert fake_wdt.feeds == 1

        before = fake_wdt.feeds
        resilience.sleep_with_watchdog(8, sleep_fn=fake_time.sleep)
        assert fake_time.now_ms == resilience.WDT_FEED_INTERVAL_MS + 8000
        assert fake_wdt.feeds >= before + 3

        resilience._wdt = None
        resilience.feed_watchdog()
        resilience.feed_watchdog_if_due()
        print("resilience watchdog tests OK")
        return 0
    finally:
        resilience.time = original_time
        resilience._wdt = original_wdt
        resilience._last_watchdog_feed_ms = original_last_feed


if __name__ == "__main__":
    raise SystemExit(main())
