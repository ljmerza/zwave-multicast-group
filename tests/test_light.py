"""Multicast light group: on/off/brightness for Multilevel and Binary Switch lights."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import COLOR_BULB, DIM_A, DIM_B, set_light, setup_group, wait

GROUP = "light.den"
DELAY = 5
MULTILEVEL_TARGET = {"commandClass": 38, "endpoint": 0, "property": "targetValue"}


async def _setup(hass: HomeAssistant, entities=(DIM_A, DIM_B)) -> None:
    await setup_group(hass, "light", "Den", list(entities), verify_delay=DELAY)


async def test_group_mirrors_members(hass: HomeAssistant, zwave) -> None:
    await _setup(hass)
    state = hass.states.get(GROUP)
    assert state.state == "off"
    assert state.attributes["supported_color_modes"] == ["brightness"]
    assert state.attributes["supported_features"] == 32  # transition

    set_light(hass, DIM_A, 200)
    await hass.async_block_till_done()
    state = hass.states.get(GROUP)
    assert state.state == "on"
    assert state.attributes["brightness"] == 200  # mean of members that are on

    set_light(hass, DIM_B, 100)
    await hass.async_block_till_done()
    assert hass.states.get(GROUP).attributes["brightness"] == 150


async def test_turn_on_is_one_multicast_to_previous_level(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass)
    await hass.services.async_call("light", "turn_on", {"entity_id": GROUP}, blocking=True)

    assert multicast.call_count == 1
    kwargs = multicast.call_args.kwargs
    assert kwargs["new_value"] == 255  # SET_TO_PREVIOUS_VALUE, like HA's zwave_js light
    assert kwargs["value_data"] == MULTILEVEL_TARGET
    assert kwargs["options"] == {"transitionDuration": "default"}
    assert sorted(n.node_id for n in kwargs["nodes"]) == [20, 21]
    assert member_calls == []
    state = hass.states.get(GROUP)
    assert state.state == "on"
    assert state.attributes["last_delivery"] == "multicast 2, one by one 0"
    assert state.attributes["last_verify"] == "pending"

    await wait(hass, DELAY)
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    for node_id in (20, 21):
        zwave.nodes[node_id].async_poll_value.assert_awaited_once_with(f"{node_id}-38-0-currentValue")
    assert member_calls == []


async def test_brightness_and_transition(hass: HomeAssistant, zwave, multicast, member_calls) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": GROUP, "brightness": 128, "transition": 2}, blocking=True
    )
    kwargs = multicast.call_args.kwargs
    assert kwargs["new_value"] == 50  # byte_to_zwave_brightness(128)
    assert kwargs["options"] == {"transitionDuration": "2s"}
    assert hass.states.get(GROUP).attributes["brightness"] == 129  # 50/99*255

    # The verify waits for the transition on top of the delay.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DELAY + 1))
    await hass.async_block_till_done()
    zwave.nodes[20].async_poll_value.assert_not_awaited()
    await wait(hass, DELAY + 2)
    zwave.nodes[20].async_poll_value.assert_awaited_once()
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    assert member_calls == []


async def test_turn_off(hass: HomeAssistant, zwave, multicast, member_calls) -> None:
    set_light(hass, DIM_A, 255)
    set_light(hass, DIM_B, 255)
    await _setup(hass)
    await hass.services.async_call("light", "turn_off", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_args.kwargs["new_value"] == 0
    assert hass.states.get(GROUP).state == "off"
    await wait(hass, DELAY)
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"


async def test_secure_member_is_sent_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    zwave.nodes[21].highest_security_class = 0  # S2 unauthenticated
    await _setup(hass)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": GROUP, "brightness": 255}, blocking=True
    )
    assert multicast.call_count == 0
    assert member_calls == [("light", "turn_on", {"brightness": 255}, [DIM_A, DIM_B])]


async def test_failed_multicast_retries_then_falls_back(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.exceptions import FailedZWaveCommand

    await _setup(hass)
    multicast.side_effect = FailedZWaveCommand("msg", 204, "did not acknowledge")
    await hass.services.async_call(
        "light", "turn_off", {"entity_id": GROUP, "transition": 1}, blocking=True
    )
    assert multicast.call_count == 2
    assert member_calls == [("light", "turn_off", {"transition": 1}, [DIM_A, DIM_B])]
    assert hass.states.get(GROUP).attributes["multicast_failures"] == 2


async def test_member_that_missed_gets_resent(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.const import SetValueStatus

    await _setup(hass)

    async def _only_b(client, new_value, value_data, nodes=None, options=None):
        set_light(hass, DIM_B, 128)
        return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)

    multicast.side_effect = _only_b
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": GROUP, "brightness": 128}, blocking=True
    )
    await wait(hass, DELAY)
    assert member_calls == [("light", "turn_on", {"brightness": 128}, [DIM_A])]
    assert hass.states.get(GROUP).attributes["last_verify"] == f"re-sent to {DIM_A}"


async def test_binary_switch_light_brightness_goes_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    """A Binary Switch (+ color) light can't share a level; on/off it can."""
    await _setup(hass, (DIM_A, DIM_B, COLOR_BULB))
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": GROUP, "brightness": 128}, blocking=True
    )
    assert multicast.call_count == 1
    assert sorted(n.node_id for n in multicast.call_args.kwargs["nodes"]) == [20, 21]
    assert member_calls == [("light", "turn_on", {"brightness": 128}, [COLOR_BULB])]


async def test_mixed_light_off_splits_by_command_class(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    """Two Binary Switch lights share a False multicast, the dimmers share a 0."""
    from .conftest import HOME_ID, _node

    from homeassistant.helpers import entity_registry as er

    zwave.nodes[23] = _node(23, "23-37-0-currentValue")
    er.async_get(hass).async_get_or_create(
        "light", "zwave_js", f"{HOME_ID}.23-37-0-currentValue",
        suggested_object_id="den_color_2", config_entry=zwave.entry,
    )
    hass.states.async_set("light.den_color_2", "off", {"supported_color_modes": ["hs"]})
    await _setup(hass, (DIM_A, DIM_B, COLOR_BULB, "light.den_color_2"))
    await hass.services.async_call("light", "turn_off", {"entity_id": GROUP}, blocking=True)

    sent = sorted(
        (c.kwargs["value_data"]["commandClass"], c.kwargs["new_value"],
         sorted(n.node_id for n in c.kwargs["nodes"]))
        for c in multicast.call_args_list
    )
    assert sent == [(37, False, [22, 23]), (38, 0, [20, 21])]
    assert member_calls == []


async def test_onoff_only_members_make_an_onoff_group(hass: HomeAssistant, zwave) -> None:
    hass.states.async_set(DIM_A, "off", {"supported_color_modes": ["onoff"]})
    hass.states.async_set(DIM_B, "off", {"supported_color_modes": ["onoff"]})
    await _setup(hass)
    assert hass.states.get(GROUP).attributes["supported_color_modes"] == ["onoff"]
