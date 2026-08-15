"""Tests for sheets_config_policy canonical merge."""

from sheets_config_policy import pick_canonical_value


def test_dock_mode_prefers_away():
    assert pick_canonical_value("dock_mode", ["home", "away"]) == "away"
    assert pick_canonical_value("dock_mode", ["away", "home"]) == "away"


def test_dock_mode_cellular_when_standby_wifi_off():
    assert pick_canonical_value(
        "dock_mode",
        ["home"],
        {"standby_prefer_wifi": "0"},
    ) == "away"


def test_standby_prefer_wifi_zero_wins():
    assert pick_canonical_value("standby_prefer_wifi", ["1", "0"]) == "0"


if __name__ == "__main__":
    test_dock_mode_prefers_away()
    test_dock_mode_cellular_when_standby_wifi_off()
    test_standby_prefer_wifi_zero_wins()
    print("test_sheets_config_policy OK")
