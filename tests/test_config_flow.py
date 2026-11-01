"""Config and options flow: group-type menu, per-domain steps, member validation."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.zwave_multicast_group.const import DOMAIN

from .conftest import (
    DIM_A,
    DIM_B,
    FAN_A,
    FAN_B,
    HOME_ID,
    LEFT,
    PLUG_A,
    PLUG_B,
    RIGHT,
    setup_group,
)


async def _start(hass: HomeAssistant, group_type: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": group_type}
    )


async def test_menu_offers_every_group_type(hass: HomeAssistant, zwave) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    assert list(result["menu_options"]) == ["cover", "fan", "light", "switch"]


async def test_create_cover_group(hass: HomeAssistant, zwave) -> None:
    result = await _start(hass, "cover")
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cover"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Bonus Room Blinds", "entities": [LEFT, RIGHT], "travel_time": 45},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bonus Room Blinds"
    assert result["options"]["group_type"] == "cover"
    assert result["options"]["entities"] == [LEFT, RIGHT]
    assert result["options"]["travel_time"] == 45
    assert result["result"].minor_version == 2
    assert hass.states.get("cover.bonus_room_blinds") is not None


@pytest.mark.parametrize(
    ("group_type", "entities", "entity_id"),
    [
        ("light", [DIM_A, DIM_B], "light.den"),
        ("switch", [PLUG_A, PLUG_B], "switch.den"),
        ("fan", [FAN_A, FAN_B], "fan.den"),
    ],
)
async def test_create_other_groups(
    hass: HomeAssistant, zwave, group_type: str, entities: list[str], entity_id: str
) -> None:
    result = await _start(hass, group_type)
    assert result["step_id"] == group_type
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Den", "entities": entities, "verify_delay": 4}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        "group_type": group_type,
        "name": "Den",
        "entities": entities,
        "verify_delay": 4,
    }
    assert hass.states.get(entity_id) is not None


async def test_needs_two_members(hass: HomeAssistant, zwave) -> None:
    result = await _start(hass, "cover")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "entities": [LEFT], "travel_time": 45}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "too_few_entities"}


async def test_rejects_non_zwave_cover(hass: HomeAssistant, zwave) -> None:
    hass.states.async_set("cover.template_thing", "open", {"current_position": 100})
    result = await _start(hass, "cover")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "x", "entities": [LEFT, "cover.template_thing"], "travel_time": 45},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "not_position_cover"}


async def test_rejects_member_of_another_domain(hass: HomeAssistant, zwave) -> None:
    from homeassistant.data_entry_flow import InvalidData

    result = await _start(hass, "light")
    with pytest.raises(InvalidData):  # the entity selector already pins the domain
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "x", "entities": [DIM_A, PLUG_A], "verify_delay": 5}
        )


@pytest.mark.parametrize(
    ("domain", "value_id", "group_type"),
    [
        ("switch", "60-112-0-12", "switch"),  # configuration parameter switch
        ("switch", "61-135-0-value", "switch"),  # indicator switch
        ("light", "62-51-0-currentColor", "light"),  # Color Switch-only light
        ("light", "63-32-0-currentValue", "light"),  # Basic CC light
        ("fan", "64-68-0-mode", "fan"),  # thermostat fan mode
        ("cover", "65-102-0-currentState", "cover"),  # barrier operator (garage door)
        ("cover", "66-106-0-currentValue-23", "cover"),  # slat tilt only
    ],
)
async def test_rejects_unsupported_zwave_values(
    hass: HomeAssistant, zwave, domain: str, value_id: str, group_type: str
) -> None:
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create(
        domain, "zwave_js", f"{HOME_ID}.{value_id}", config_entry=zwave.entry
    )
    good = {"cover": LEFT, "light": DIM_A, "switch": PLUG_A, "fan": FAN_A}[group_type]
    delay = {"travel_time": 30} if group_type == "cover" else {"verify_delay": 5}
    result = await _start(hass, group_type)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "entities": [good, entry.entity_id], **delay}
    )
    expected = "not_position_cover" if group_type == "cover" else "unsupported_member"
    assert result["errors"] == {"base": expected}


async def test_rejects_config_category_entity(hass: HomeAssistant, zwave) -> None:
    from homeassistant.const import EntityCategory

    ent_reg = er.async_get(hass)
    led = ent_reg.async_get_or_create(
        "light",
        "zwave_js",
        f"{HOME_ID}.1-37-0-currentValue",
        config_entry=zwave.entry,
        entity_category=EntityCategory.CONFIG,
    )
    result = await _start(hass, "light")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "entities": [DIM_A, led.entity_id], "verify_delay": 5}
    )
    assert result["errors"] == {"base": "unsupported_member"}


async def test_rejects_gate(hass: HomeAssistant, zwave) -> None:
    ent_reg = er.async_get(hass)
    gate = ent_reg.async_get_or_create(
        "cover",
        "zwave_js",
        f"{HOME_ID}.70-38-0-currentValue",
        config_entry=zwave.entry,
        original_device_class="gate",
    )
    result = await _start(hass, "cover")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "entities": [LEFT, gate.entity_id], "travel_time": 30}
    )
    assert result["errors"] == {"base": "unsafe_member"}


async def test_cover_options_flow(hass: HomeAssistant, zwave) -> None:
    entry = await setup_group(
        hass, "cover", "Bonus Blinds", [LEFT, RIGHT], travel_time=45
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cover"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": [LEFT, RIGHT], "travel_time": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["travel_time"] == 30
    assert entry.options["group_type"] == "cover"


async def test_light_options_flow(hass: HomeAssistant, zwave) -> None:
    entry = await setup_group(hass, "light", "Den", [DIM_A, DIM_B], verify_delay=5)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "light"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": [DIM_A, DIM_B], "verify_delay": 9}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["verify_delay"] == 9
