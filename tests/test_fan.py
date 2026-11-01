"""Multicast fan group: Multilevel Switch fans, percentage -> 1-99."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from .conftest import FAN_A, FAN_B, FAN_MAPPED, set_fan, setup_group, wait

GROUP = "fan.porch"
DELAY = 5
MULTILEVEL_TARGET = {"commandClass": 38, "endpoint": 0, "property": "targetValue"}


async def _setup(hass: HomeAssistant, entities=(FAN_A, FAN_B)) -> None:
    await setup_group(hass, "fan", "Porch", list(entities), verify_delay=DELAY)


async def test_group_mirrors_members(hass: HomeAssistant, zwave) -> None:
    await _setup(hass)
    state = hass.states.get(GROUP)
    assert state.state == "off"
    assert state.attributes["percentage"] == 0
    assert state.attributes["percentage_step"] == 1

    set_fan(hass, FAN_A, 60)
    await hass.async_block_till_done()
    state = hass.states.get(GROUP)
    assert state.state == "on"
    assert state.attributes["percentage"] == 30  # mean over members, like HA's fan group


async def test_set_percentage_is_one_multicast(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": GROUP, "percentage": 50}, blocking=True
    )
    kwargs = multicast.call_args.kwargs
    assert kwargs["new_value"] == 50  # ceil(50 * 99 / 100)
    assert kwargs["value_data"] == MULTILEVEL_TARGET
    assert sorted(n.node_id for n in kwargs["nodes"]) == [40, 41]
    await wait(hass, DELAY)
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    assert member_calls == []


async def test_turn_on_previous_speed_and_off(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass)
    await hass.services.async_call("fan", "turn_on", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_args.kwargs["new_value"] == 255
    await hass.services.async_call(
        "fan", "turn_on", {"entity_id": GROUP, "percentage": 33}, blocking=True
    )
    assert multicast.call_args.kwargs["new_value"] == 33
    await hass.services.async_call("fan", "turn_off", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_args.kwargs["new_value"] == 0
    assert hass.states.get(GROUP).state == "off"
    await wait(hass, DELAY)
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    assert member_calls == []


async def test_speed_table_fan_gets_its_percentage_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass, (FAN_A, FAN_B, FAN_MAPPED))
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": GROUP, "percentage": 66}, blocking=True
    )
    assert sorted(n.node_id for n in multicast.call_args.kwargs["nodes"]) == [40, 41]
    assert member_calls == [("fan", "set_percentage", {"percentage": 66}, [FAN_MAPPED])]

    # Off (0) means the same to every fan, so all three share the multicast.
    member_calls.clear()
    await hass.services.async_call("fan", "turn_off", {"entity_id": GROUP}, blocking=True)
    assert sorted(n.node_id for n in multicast.call_args.kwargs["nodes"]) == [40, 41, 42]
    assert member_calls == []


async def test_secure_member_is_sent_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    zwave.nodes[40].highest_security_class = 2  # S2 access control
    await _setup(hass)
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": GROUP, "percentage": 50}, blocking=True
    )
    assert multicast.call_count == 0
    assert member_calls == [("fan", "set_percentage", {"percentage": 50}, [FAN_A, FAN_B])]


async def test_failed_multicast_retries_then_falls_back(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.exceptions import FailedZWaveCommand

    await _setup(hass)
    multicast.side_effect = FailedZWaveCommand("msg", 204, "did not acknowledge")
    await hass.services.async_call("fan", "turn_on", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_count == 2
    assert member_calls == [("fan", "turn_on", {}, [FAN_A, FAN_B])]


async def test_member_that_missed_gets_resent(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.const import SetValueStatus

    await _setup(hass)

    async def _only_a(client, new_value, value_data, nodes=None, options=None):
        set_fan(hass, FAN_A, 75)
        return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)

    multicast.side_effect = _only_a
    await hass.services.async_call(
        "fan", "set_percentage", {"entity_id": GROUP, "percentage": 75}, blocking=True
    )
    await wait(hass, DELAY)
    assert member_calls == [("fan", "set_percentage", {"percentage": 75}, [FAN_B])]
