"""The pure conversions match the Home Assistant code they copy (catches drift on HA bumps)."""

from __future__ import annotations

import math

import pytest

from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage

from custom_components.zwave_multicast_group import members


def test_fan_mapping_matches_ha_zwave_js_fan() -> None:
    for percentage in range(1, 101):
        expected = math.ceil(percentage_to_ranged_value((1, 99), percentage))
        assert members.fan_percentage_to_zwave(percentage) == expected, percentage
    for level in range(1, 100):
        assert members.zwave_to_fan_percentage(level) == ranged_value_to_percentage((1, 99), level)


def test_brightness_matches_ha_zwave_js_light() -> None:
    light = pytest.importorskip("homeassistant.components.zwave_js.light")
    for brightness in range(256):
        assert members.brightness_to_zwave(brightness) == light.byte_to_zwave_brightness(brightness)


def test_set_to_previous_value_matches_library() -> None:
    from zwave_js_server.const.command_class.multilevel_switch import SET_TO_PREVIOUS_VALUE

    assert members.SET_TO_PREVIOUS_VALUE == SET_TO_PREVIOUS_VALUE


def test_stop_properties_match_library() -> None:
    from zwave_js_server.const.command_class.multilevel_switch import (
        COVER_ON_PROPERTY,
        COVER_OPEN_PROPERTY,
        COVER_UP_PROPERTY,
    )
    from zwave_js_server.const.command_class.window_covering import (
        WINDOW_COVERING_LEVEL_CHANGE_UP_PROPERTY,
    )

    assert members.MULTILEVEL_SWITCH_STOP_PROPERTIES == (
        COVER_OPEN_PROPERTY,
        COVER_UP_PROPERTY,
        COVER_ON_PROPERTY,
    )
    assert members.WINDOW_COVERING_STOP_PROPERTY == WINDOW_COVERING_LEVEL_CHANGE_UP_PROPERTY
