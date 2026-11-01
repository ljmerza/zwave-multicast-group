"""Behaviour of the multicast group cover in a real (in-memory) Home Assistant."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.zwave_multicast_group.const import DOMAIN

from .conftest import LEFT, RIGHT, set_member

GROUP = "cover.bonus_blinds"
TRAVEL = 45


async def _setup_group(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bonus Blinds",
        options={"name": "Bonus Blinds", "entities": [LEFT, RIGHT], "travel_time": TRAVEL},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _after_travel(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=TRAVEL + 1))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=TRAVEL + 10))
    await hass.async_block_till_done()


async def test_group_mirrors_members(hass: HomeAssistant, zwave) -> None:
    await _setup_group(hass)
    state = hass.states.get(GROUP)
    assert state.state == "open"
    assert state.attributes["current_position"] == 100
    assert state.attributes["entity_id"] == [LEFT, RIGHT]
    assert state.attributes["supported_features"] == 15

    set_member(hass, LEFT, 0)
    set_member(hass, RIGHT, 0)
    await hass.async_block_till_done()
    assert hass.states.get(GROUP).state == "closed"


async def test_close_sends_one_multicast_then_verifies(
    hass: HomeAssistant, zwave, multicast, one_by_one
) -> None:
    await _setup_group(hass)
    await hass.services.async_call("cover", "close_cover", {"entity_id": GROUP}, blocking=True)

    assert multicast.call_count == 1
    kwargs = multicast.call_args.kwargs
    assert kwargs["new_value"] == 0
    assert kwargs["value_data"] == {
        "commandClass": 106,
        "endpoint": 0,
        "property": "targetValue",
        "propertyKey": 13,
    }
    assert sorted(n.node_id for n in kwargs["nodes"]) == [142, 143]
    assert one_by_one == []

    # Members already read closed (optimistic), but the group shows the travel.
    state = hass.states.get(GROUP)
    assert state.state == "closing"
    assert state.attributes["last_delivery"] == "multicast 2, one by one 0"
    assert state.attributes["last_verify"] == "pending"

    await _after_travel(hass)
    state = hass.states.get(GROUP)
    assert state.state == "closed"
    assert state.attributes["last_verify"] == "ok"
    for node in zwave.nodes.values():
        node.async_poll_value.assert_awaited_once()
    assert one_by_one == []


async def test_member_that_missed_the_multicast_gets_resent(
    hass: HomeAssistant, zwave, multicast, one_by_one
) -> None:
    await _setup_group(hass)

    async def _left_misses(client, new_value, value_data, nodes=None, options=None):
        from zwave_js_server.const import SetValueStatus

        set_member(hass, RIGHT, 0)  # only the right shade got it
        return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)

    multicast.side_effect = _left_misses
    await hass.services.async_call("cover", "close_cover", {"entity_id": GROUP}, blocking=True)
    await _after_travel(hass)

    assert one_by_one == [(0, [LEFT])]
    assert hass.states.get(GROUP).attributes["last_verify"] == f"re-sent to {LEFT}"


async def test_failed_multicast_falls_back_to_one_by_one(
    hass: HomeAssistant, zwave, multicast, one_by_one
) -> None:
    await _setup_group(hass)
    from zwave_js_server.exceptions import FailedZWaveCommand

    multicast.side_effect = FailedZWaveCommand("msg", 0, "Unable to set value via multicast")
    await hass.services.async_call("cover", "open_cover", {"entity_id": GROUP}, blocking=True)

    assert one_by_one == [(100, [LEFT, RIGHT])]
    state = hass.states.get(GROUP)
    assert state.attributes["multicast_failures"] == 1
    assert "after a failed multicast" in state.attributes["last_delivery"]
    assert state.attributes["last_verify"] is None  # nothing was multicast, nothing to verify


async def test_secure_member_is_sent_one_by_one(
    hass: HomeAssistant, zwave, multicast, one_by_one
) -> None:
    zwave.nodes[143].highest_security_class = 1  # S2 authenticated
    await _setup_group(hass)
    await hass.services.async_call("cover", "close_cover", {"entity_id": GROUP}, blocking=True)

    assert multicast.call_count == 0  # a lone non-secure member isn't worth a multicast
    assert one_by_one == [(0, [LEFT, RIGHT])]


async def test_toggle_mid_travel_stops_and_cancels_verify(
    hass: HomeAssistant, zwave, multicast, one_by_one, member_service_calls
) -> None:
    await _setup_group(hass)
    await hass.services.async_call("cover", "close_cover", {"entity_id": GROUP}, blocking=True)
    assert hass.states.get(GROUP).state == "closing"

    await hass.services.async_call("cover", "toggle", {"entity_id": GROUP}, blocking=True)
    assert ("stop_cover", sorted([LEFT, RIGHT])) in member_service_calls
    assert hass.states.get(GROUP).attributes["last_command"] == "stop"

    await _after_travel(hass)
    for node in zwave.nodes.values():
        node.async_poll_value.assert_not_awaited()
    assert one_by_one == []


async def test_set_position(hass: HomeAssistant, zwave, multicast, one_by_one) -> None:
    await _setup_group(hass)
    await hass.services.async_call(
        "cover", "set_cover_position", {"entity_id": GROUP, "position": 50}, blocking=True
    )
    assert multicast.call_args.kwargs["new_value"] == 50
    assert hass.states.get(GROUP).state == "closing"  # 100 -> 50
