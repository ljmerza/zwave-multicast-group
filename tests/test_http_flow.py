"""The config flow over HA's HTTP API, like the frontend (and ha-mcp) start it.

Exercises form serialization, which the flow-manager tests in test_config_flow.py skip.
"""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.zwave_multicast_group.const import DOMAIN


async def test_flow_starts_over_http(hass: HomeAssistant, hass_client, zwave) -> None:
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
    assert body["type"] == "form"
    assert [f["name"] for f in body["data_schema"]] == ["name", "entities", "travel_time"]


async def test_helper_is_listed(hass: HomeAssistant, hass_client, zwave) -> None:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    resp = await client.get("/api/config/config_entries/flow_handlers?type=helper")
    assert resp.status == 200
    assert DOMAIN in await resp.json()
