"""Config flow for Z-Wave Multicast Group (a helper, like HA's own group helper)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)

from .const import (
    CONF_ENTITIES,
    CONF_TRAVEL_TIME,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
    MAX_TRAVEL_TIME,
    MIN_TRAVEL_TIME,
    ZWAVE_JS_DOMAIN,
)
from .members import parse_unique_id, position_value

try:  # HA 2026.10+ validates flow schemas with probatio (voluptuous fork, same API)
    import probatio as vol
except ImportError:  # pragma: no cover - older HA
    import voluptuous as vol

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITIES): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="cover", integration=ZWAVE_JS_DOMAIN, multiple=True
            )
        ),
        vol.Required(CONF_TRAVEL_TIME, default=DEFAULT_TRAVEL_TIME): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_TRAVEL_TIME,
                max=MAX_TRAVEL_TIME,
                step=1,
                unit_of_measurement="s",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)

CONFIG_SCHEMA = vol.Schema({vol.Required("name"): selector.TextSelector()}).extend(
    OPTIONS_SCHEMA.schema
)


async def _validate(handler: SchemaCommonFlowHandler, user_input: dict[str, Any]) -> dict[str, Any]:
    """Need 2+ Z-Wave JS covers that report a position."""
    entity_ids: list[str] = user_input[CONF_ENTITIES]
    if len(entity_ids) < 2:
        raise SchemaFlowError("too_few_entities")
    ent_reg = er.async_get(handler.parent_handler.hass)
    for entity_id in entity_ids:
        entry = ent_reg.async_get(entity_id)
        if (
            entry is None
            or entry.platform != ZWAVE_JS_DOMAIN
            or position_value(parse_unique_id(entry.unique_id)) is None
        ):
            raise SchemaFlowError("not_position_cover")
    user_input[CONF_TRAVEL_TIME] = int(user_input[CONF_TRAVEL_TIME])
    return user_input


CONFIG_FLOW = {"user": SchemaFlowFormStep(CONFIG_SCHEMA, validate_user_input=_validate)}
OPTIONS_FLOW = {"init": SchemaFlowFormStep(OPTIONS_SCHEMA, validate_user_input=_validate)}


class ZwaveMulticastGroupConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Create a Z-Wave multicast cover group."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Use the group name as the entry title."""
        return cast(str, options["name"])
