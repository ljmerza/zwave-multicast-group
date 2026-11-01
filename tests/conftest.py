"""Fixtures: a fake Z-Wave JS controller with two non-secure Window Covering shades.

Run: uv run --no-project --python 3.14 \
       --with pytest-homeassistant-custom-component==0.13.375 pytest -q
(0.13.375 pins homeassistant==2026.10.4; bump both together.)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

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


def _node(node_id: int, security: int = -1) -> SimpleNamespace:
    value_id = f"{node_id}-106-0-currentValue-13"
    return SimpleNamespace(
        node_id=node_id,
        highest_security_class=security,
        protocol=0,
        values={value_id: SimpleNamespace(metadata=SimpleNamespace(min=0, max=99))},
        async_poll_value=AsyncMock(),
    )


def set_member(hass: HomeAssistant, entity_id: str, position: int, state: str | None = None) -> None:
    """Set a member cover's state like HA's zwave_js cover would."""
    hass.states.async_set(
        entity_id,
        state or ("closed" if position == 0 else "open"),
        {"current_position": position, "supported_features": FEATURES, "device_class": "window"},
    )


@pytest.fixture
def zwave(hass: HomeAssistant, enable_custom_integrations):
    """A loaded-looking zwave_js entry with nodes 142/143 and their registry entries."""
    # The group depends on zwave_js; mark it set up instead of loading the real one
    # (which would need a Z-Wave JS server and USB libraries).
    hass.config.components.add("zwave_js")
    nodes = {nid: _node(nid) for nid in MEMBERS.values()}
    client = SimpleNamespace(driver=SimpleNamespace(controller=SimpleNamespace(nodes=nodes)))
    entry = MockConfigEntry(domain="zwave_js", title="Z-Wave JS")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    entry.runtime_data = SimpleNamespace(client=client)

    ent_reg = er.async_get(hass)
    for entity_id, node_id in MEMBERS.items():
        ent_reg.async_get_or_create(
            "cover",
            "zwave_js",
            f"{HOME_ID}.{node_id}-106-0-currentValue-13",
            suggested_object_id=entity_id.split(".", 1)[1],
            config_entry=entry,
        )
        set_member(hass, entity_id, 100)
    return SimpleNamespace(entry=entry, client=client, nodes=nodes)


@pytest.fixture
def multicast(hass: HomeAssistant):
    """Patch the multicast call; by default it 'lands' and HA marks members at target."""
    from zwave_js_server.const import SetValueStatus

    async def _land(client, new_value, value_data, nodes=None, options=None):
        percent = round(new_value / 99 * 100)
        for entity_id, node_id in MEMBERS.items():
            if any(n.node_id == node_id for n in nodes):
                set_member(hass, entity_id, percent)
        return SimpleNamespace(status=SetValueStatus.SUCCESS, message=None)

    with patch(
        "custom_components.zwave_multicast_group.cover.async_multicast_set_value",
        side_effect=_land,
    ) as mock:
        yield mock


@pytest.fixture
def one_by_one():
    """Record the normal (one-by-one) commands the group sends: (percent, entity_ids)."""
    from custom_components.zwave_multicast_group.cover import ZwaveMulticastGroupCover

    calls: list[tuple[int, list[str]]] = []

    async def _record(self, percent, entity_ids):
        calls.append((percent, sorted(entity_ids)))

    with patch.object(ZwaveMulticastGroupCover, "_async_one_by_one", _record):
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
