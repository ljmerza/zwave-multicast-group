"""Config and options flow."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.zwave_multicast_group.const import DOMAIN

from .conftest import LEFT, RIGHT


async def test_create_group(hass: HomeAssistant, zwave) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Bonus Room Blinds", "entities": [LEFT, RIGHT], "travel_time": 45},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bonus Room Blinds"
    assert result["options"]["entities"] == [LEFT, RIGHT]
    assert result["options"]["travel_time"] == 45
    assert hass.states.get("cover.bonus_room_blinds") is not None


async def test_needs_two_members(hass: HomeAssistant, zwave) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "entities": [LEFT], "travel_time": 45}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "too_few_entities"}


async def test_rejects_non_zwave_cover(hass: HomeAssistant, zwave) -> None:
    hass.states.async_set("cover.template_thing", "open", {"current_position": 100})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "x", "entities": [LEFT, "cover.template_thing"], "travel_time": 45},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_position_cover"}
