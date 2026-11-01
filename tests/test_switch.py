"""Multicast switch group: Binary Switch true/false."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from .conftest import PLUG_A, PLUG_B, set_switch, setup_group, wait

GROUP = "switch.plugs"
DELAY = 3
BINARY_TARGET = {"commandClass": 37, "endpoint": 0, "property": "targetValue"}


async def _setup(hass: HomeAssistant) -> None:
    await setup_group(hass, "switch", "Plugs", [PLUG_A, PLUG_B], verify_delay=DELAY)


async def test_group_mirrors_members(hass: HomeAssistant, zwave) -> None:
    await _setup(hass)
    assert hass.states.get(GROUP).state == "off"
    set_switch(hass, PLUG_B, True)
    await hass.async_block_till_done()
    assert hass.states.get(GROUP).state == "on"


async def test_turn_on_and_off_are_one_multicast(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": GROUP}, blocking=True)
    kwargs = multicast.call_args.kwargs
    assert kwargs["new_value"] is True
    assert kwargs["value_data"] == BINARY_TARGET
    assert kwargs["options"] is None
    assert sorted(n.node_id for n in kwargs["nodes"]) == [30, 31]
    assert hass.states.get(GROUP).state == "on"
    await wait(hass, DELAY)
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    zwave.nodes[30].async_poll_value.assert_awaited_once_with("30-37-0-currentValue")

    await hass.services.async_call("switch", "turn_off", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_count == 2
    assert multicast.call_args.kwargs["new_value"] is False
    assert hass.states.get(GROUP).state == "off"
    assert member_calls == []


async def test_secure_member_is_sent_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    zwave.nodes[30].highest_security_class = 7  # S0
    await _setup(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_count == 0
    assert member_calls == [("switch", "turn_on", {}, [PLUG_A, PLUG_B])]


async def test_long_range_member_is_sent_one_by_one(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    zwave.nodes[31].protocol = 1  # Z-Wave Long Range
    await _setup(hass)
    await hass.services.async_call("switch", "turn_off", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_count == 0
    assert member_calls == [("switch", "turn_off", {}, [PLUG_A, PLUG_B])]


async def test_failed_multicast_retries_then_falls_back(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.const import SetValueStatus

    await _setup(hass)
    multicast.side_effect = None
    multicast.return_value = SimpleNamespace(status=SetValueStatus.FAIL, message="no route")
    await hass.services.async_call("switch", "turn_on", {"entity_id": GROUP}, blocking=True)
    assert multicast.call_count == 2
    assert member_calls == [("switch", "turn_on", {}, [PLUG_A, PLUG_B])]
    state = hass.states.get(GROUP)
    assert state.attributes["multicast_failures"] == 2
    assert state.attributes["last_verify"] is None


async def test_member_that_missed_gets_resent(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    from zwave_js_server.const import SetValueStatus

    await _setup(hass)

    async def _only_a(client, new_value, value_data, nodes=None, options=None):
        set_switch(hass, PLUG_A, True)
        return SimpleNamespace(status=SetValueStatus.SUCCESS_UNSUPERVISED, message=None)

    multicast.side_effect = _only_a
    await hass.services.async_call("switch", "turn_on", {"entity_id": GROUP}, blocking=True)
    await wait(hass, DELAY)
    assert member_calls == [("switch", "turn_on", {}, [PLUG_B])]
    assert hass.states.get(GROUP).attributes["last_verify"] == f"re-sent to {PLUG_B}"


async def test_newer_command_cancels_pending_verify(
    hass: HomeAssistant, zwave, multicast, member_calls
) -> None:
    await _setup(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": GROUP}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": GROUP}, blocking=True)
    await wait(hass, DELAY)
    # Only the turn_off is verified, once per member.
    zwave.nodes[30].async_poll_value.assert_awaited_once()
    assert hass.states.get(GROUP).attributes["last_verify"] == "ok"
    assert member_calls == []
