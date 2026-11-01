"""The config flow over HA's HTTP API, like the frontend (and ha-mcp) start it.

Exercises form serialization, which the flow-manager tests in test_config_flow.py skip.
"""

from __future__ import annotations

import asyncio

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.zwave_multicast_group.const import DOMAIN


@pytest.mark.parametrize(
    ("group_type", "delay_field"),
    [("cover", "travel_time"), ("light", "verify_delay"), ("switch", "verify_delay"),
     ("fan", "verify_delay")],
)
async def test_flow_starts_over_http(
    hass: HomeAssistant, hass_client, zwave, group_type: str, delay_field: str
) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await asyncio.wait_for(
        client.post(
            "/api/config/config_entries/flow",
            json={"handler": DOMAIN, "show_advanced_options": False},
        ),
        timeout=10,
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["type"] == "menu"
    assert body["menu_options"] == ["cover", "fan", "light", "switch"]

    resp = await asyncio.wait_for(
        client.post(
            f"/api/config/config_entries/flow/{body['flow_id']}",
            json={"next_step_id": group_type},
        ),
        timeout=10,
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    assert body["type"] == "form"
    assert body["step_id"] == group_type
    assert [f["name"] for f in body["data_schema"]] == ["name", "entities", delay_field]


async def test_helper_is_listed(hass: HomeAssistant, hass_client, zwave) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.get("/api/config/config_entries/flow_handlers?type=helper")
    assert resp.status == 200
    assert DOMAIN in await resp.json()
