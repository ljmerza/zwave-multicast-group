"""Fixtures: a fake Z-Wave JS controller with non-secure members of every group type.

- covers 142/143: Window Covering shades (the Bonus Room pair)
- lights 20/21: Multilevel Switch dimmers (transition capable); 22: Binary Switch + color
- switches 30/31: Binary Switch plugs
- fans 40/41: Multilevel Switch fans; 42: a fan HA drives with a 3-speed table

Run: uv run --no-project --python 3.14 \
       --with pytest-homeassistant-custom-component==0.13.375 \
       --with zwave-js-server-python==0.73.1 pytest -q
(0.13.375 pins homeassistant==2026.10.4; bump both together.)
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

# Import the integration at collection time, before HA's test harness sets up its own
# ``custom_components`` package, so patches below can find these modules.
from custom_components.zwave_multicast_group import entity as group_entity

HOME_ID = 4170970308
LEFT = "cover.bonus_left"
RIGHT = "cover.bonus_right"
MEMBERS = {LEFT: 143, RIGHT: 142}
FEATURES = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.SET_POSITION
    | CoverEntityFeature.STOP
)

DIM_A, DIM_B, COLOR_BULB = "light.den_a", "light.den_b", "light.den_color"
PLUG_A, PLUG_B = "switch.plug_a", "switch.plug_b"
FAN_A, FAN_B, FAN_MAPPED = "fan.porch_a", "fan.porch_b", "fan.porch_mapped"

# entity_id -> (node, value_id of the entity's primary currentValue)
ENTITIES = {
    LEFT: (143, "143-106-0-currentValue-13"),
    RIGHT: (142, "142-106-0-currentValue-13"),
    DIM_A: (20, "20-38-0-currentValue"),
    DIM_B: (21, "21-38-0-currentValue"),
    COLOR_BULB: (22, "22-37-0-currentValue"),
    PLUG_A: (30, "30-37-0-currentValue"),
    PLUG_B: (31, "31-37-0-currentValue"),
    FAN_A: (40, "40-38-0-currentValue"),
    FAN_B: (41, "41-38-0-currentValue"),
    FAN_MAPPED: (42, "42-38-0-currentValue"),
}
TRANSITION_NODES = {20, 21}


def _value(lo: int = 0, hi: int = 99, change_options: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(min=lo, max=hi, value_change_options=list(change_options))
    )


def _node(node_id: int, value_id: str, security: int = -1) -> SimpleNamespace:
    target_id = value_id.replace("currentValue", "targetValue")
    options = ("transitionDuration",) if node_id in TRANSITION_NODES else ()
    values = {value_id: _value(), target_id: _value(change_options=options)}
    if "-106-" in value_id:  # Window Covering stops via levelChangeUp
        values[value_id.replace("currentValue", "levelChangeUp")] = _value()
    return SimpleNamespace(
        node_id=node_id,
        highest_security_class=security,
        protocol=0,
        values=values,
        async_poll_value=AsyncMock(),
    )


def set_member(hass: HomeAssistant, entity_id: str, position: int, state: str | None = None) -> None:
    """Set a member cover's state like HA's zwave_js cover would."""
    hass.states.async_set(
        entity_id,
        state or ("closed" if position == 0 else "open"),
        {"current_position": position, "supported_features": FEATURES, "device_class": "window"},
    )


def set_light(hass: HomeAssistant, entity_id: str, brightness: int | None) -> None:
    """A zwave_js light: brightness 0/None = off. The color bulb has no brightness mode."""
    on = bool(brightness)
    if entity_id == COLOR_BULB:
        attrs = {"supported_color_modes": ["hs"], "supported_features": 0}
    else:
        attrs = {"supported_color_modes": ["brightness"], "supported_features": 32}
    if on:
        attrs["brightness"] = brightness
        attrs["color_mode"] = "hs" if entity_id == COLOR_BULB else "brightness"
    hass.states.async_set(entity_id, "on" if on else "off", attrs)


def set_switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    hass.states.async_set(entity_id, "on" if on else "off", {})


def set_fan(hass: HomeAssistant, entity_id: str, percentage: int) -> None:
    step = 100 / 3 if entity_id == FAN_MAPPED else 1.0
    hass.states.async_set(
        entity_id,
        "on" if percentage else "off",
        {"percentage": percentage, "percentage_step": step, "supported_features": 49},
    )


def apply_value(hass: HomeAssistant, entity_id: str, value) -> None:
    """Mark a member at a multicast value, as Z-Wave JS does right after a multicast."""
    domain = entity_id.split(".", 1)[0]
    current = hass.states.get(entity_id)
    if domain == "cover":
        set_member(hass, entity_id, round(value / 99 * 100))
    elif domain == "switch" or entity_id == COLOR_BULB:
        if domain == "switch":
            set_switch(hass, entity_id, bool(value))
        else:
            set_light(hass, entity_id, 255 if value else 0)
    elif domain == "light":
        if value == 255:  # previous level: keep the brightness it had, else full
            value = round((current.attributes.get("brightness") or 255) / 255 * 99)
        set_light(hass, entity_id, round(value / 99 * 255))
    elif domain == "fan":
        if value == 255:
            value = 99
        set_fan(hass, entity_id, int(value * 100 // 99))


@pytest.fixture
def zwave(hass: HomeAssistant, enable_custom_integrations):
    """A loaded-looking zwave_js entry with every fake node and its registry entry."""
    # The group doesn't depend on zwave_js; mark it set up instead of loading the real
    # one (which would need a Z-Wave JS server and USB libraries).
    hass.config.components.add("zwave_js")
    nodes = {node_id: _node(node_id, value_id) for node_id, value_id in ENTITIES.values()}
    client = SimpleNamespace(driver=SimpleNamespace(controller=SimpleNamespace(nodes=nodes)))
    entry = MockConfigEntry(domain="zwave_js", title="Z-Wave JS")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(client=client)

    ent_reg = er.async_get(hass)
    for entity_id, (_node_id, value_id) in ENTITIES.items():
        domain, object_id = entity_id.split(".", 1)
        ent_reg.async_get_or_create(
            domain,
            "zwave_js",
            f"{HOME_ID}.{value_id}",
            suggested_object_id=object_id,
            config_entry=entry,
        )
    for entity_id in MEMBERS:
        set_member(hass, entity_id, 100)
    for entity_id in (DIM_A, DIM_B, COLOR_BULB):
        set_light(hass, entity_id, 0)
    for entity_id in (PLUG_A, PLUG_B):
        set_switch(hass, entity_id, False)
    for entity_id in (FAN_A, FAN_B, FAN_MAPPED):
        set_fan(hass, entity_id, 0)
    return SimpleNamespace(entry=entry, client=client, nodes=nodes)


def node_of(entity_id: str) -> int:
    return ENTITIES[entity_id][0]


@pytest.fixture
def multicast(hass: HomeAssistant):
    """Patch the multicast call; by default it 'lands' and HA marks members at target."""
    from zwave_js_server.const import SetValueStatus

    async def _land(client, new_value, value_data, nodes=None, options=None):
        if value_data["property"] != "targetValue":
            return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)  # a stop
        node_ids = {n.node_id for n in nodes}
        for entity_id, (node_id, _value_id) in ENTITIES.items():
            if node_id in node_ids:
                apply_value(hass, entity_id, new_value)
        return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)

    with patch.object(group_entity, "async_multicast_set_value", side_effect=_land) as mock:
        yield mock


@pytest.fixture
def one_by_one():
    """Record the normal (one-by-one) commands a group sends: (level, entity_ids)."""
    calls: list[tuple[int | None, list[str]]] = []

    async def _record(self, cmd, entity_ids):
        calls.append((cmd.level, sorted(entity_ids)))

    with patch.object(group_entity.ZwaveMulticastGroupEntity, "_async_one_by_one", _record):
        yield calls


@pytest.fixture
def member_service_calls(hass: HomeAssistant):
    """Spy on cover.* service calls that target members (e.g. the group's stop)."""
    from homeassistant.core import ServiceRegistry

    calls: list[tuple[str, list[str]]] = []
    real = ServiceRegistry.async_call

    async def _spy(self, domain, service, service_data=None, *args, **kwargs):
        ids = (service_data or {}).get("entity_id")
        if domain == "cover" and isinstance(ids, list) and set(ids) <= set(MEMBERS):
            calls.append((service, sorted(ids)))
        return await real(self, domain, service, service_data, *args, **kwargs)

    with patch.object(ServiceRegistry, "async_call", _spy):
        yield calls


@pytest.fixture
def member_calls(hass: HomeAssistant):
    """Capture (and swallow) the normal service calls a group sends to its members.

    Records (domain, service, data without entity_id, sorted entity_ids).
    """
    from homeassistant.core import ServiceRegistry

    calls: list[tuple[str, str, dict, list[str]]] = []
    real = ServiceRegistry.async_call

    async def _spy(self, domain, service, service_data=None, *args, **kwargs):
        data = dict(service_data or {})
        ids = data.pop("entity_id", None)
        if isinstance(ids, list) and ids and set(ids) <= set(ENTITIES):
            calls.append((domain, service, data, sorted(ids)))
            return None
        return await real(self, domain, service, service_data, *args, **kwargs)

    with patch.object(ServiceRegistry, "async_call", _spy):
        yield calls


async def setup_group(
    hass: HomeAssistant, group_type: str, title: str, entities: list[str], **options
) -> MockConfigEntry:
    """Add and set up a group entry the way the config flow stores it (1.2)."""
    entry = MockConfigEntry(
        domain="zwave_multicast_group",
        title=title,
        version=1,
        minor_version=2,
        options={"group_type": group_type, "name": title, "entities": entities, **options},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def wait(hass: HomeAssistant, seconds: float) -> None:
    """Let ``seconds`` pass, then the verify's report wait too."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds + 1))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds + 10))
    await hass.async_block_till_done()
