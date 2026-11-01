"""Config flow for Z-Wave Multicast Group (a helper, like HA's own group helper).

Pick the group type from a menu first; each config entry is one group of one domain.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import Any, cast

from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)

from .const import (
    CONF_ENTITIES,
    CONF_GROUP_TYPE,
    CONF_TRAVEL_TIME,
    CONF_VERIFY_DELAY,
    DEFAULT_TRAVEL_TIME,
    DEFAULT_VERIFY_DELAY,
    DOMAIN,
    GROUP_TYPES,
    MAX_TRAVEL_TIME,
    MAX_VERIFY_DELAY,
    MIN_TRAVEL_TIME,
    MIN_VERIFY_DELAY,
    ZWAVE_JS_DOMAIN,
)
from .members import member_value, parse_unique_id

try:  # HA 2026.10+ validates flow schemas with probatio (voluptuous fork, same API)
    import probatio as vol
except ImportError:  # pragma: no cover - older HA
    import voluptuous as vol

# Gates and garage doors open access to the house; they stay on their own controls.
UNSAFE_COVER_CLASSES = frozenset({"gate", "garage"})


def _delay_field(group_type: str) -> tuple[str, int, int, int]:
    if group_type == "cover":
        return CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME, MIN_TRAVEL_TIME, MAX_TRAVEL_TIME
    return CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY, MIN_VERIFY_DELAY, MAX_VERIFY_DELAY


def options_schema(group_type: str) -> vol.Schema:
    """Members plus the travel time (covers) or verify delay (everything else)."""
    key, default, low, high = _delay_field(group_type)
    return vol.Schema(
        {
            vol.Required(CONF_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=group_type, integration=ZWAVE_JS_DOMAIN, multiple=True
                )
            ),
            vol.Required(key, default=default): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=low,
                    max=high,
                    step=1,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


def config_schema(group_type: str) -> vol.Schema:
    """Name plus the options."""
    return vol.Schema({vol.Required("name"): selector.TextSelector()}).extend(
        options_schema(group_type).schema
    )


def _member_error(group_type: str, entry: er.RegistryEntry | None, entity_id: str) -> str | None:
    unsupported = "not_position_cover" if group_type == "cover" else "unsupported_member"
    if (
        entry is None
        or entity_id.split(".", 1)[0] != group_type
        or entry.platform != ZWAVE_JS_DOMAIN
        or member_value(group_type, parse_unique_id(entry.unique_id)) is None
        or entry.entity_category in (EntityCategory.CONFIG, EntityCategory.DIAGNOSTIC)
    ):
        return unsupported
    if group_type == "cover" and (
        (entry.device_class or entry.original_device_class) in UNSAFE_COVER_CLASSES
    ):
        return "unsafe_member"
    return None


def validator(
    group_type: str,
) -> Callable[[SchemaCommonFlowHandler, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]:
    """Need 2+ Z-Wave JS members this group type can multicast to."""

    async def _validate(
        handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        entity_ids: list[str] = user_input[CONF_ENTITIES]
        if len(entity_ids) < 2:
            raise SchemaFlowError("too_few_entities")
        ent_reg = er.async_get(handler.parent_handler.hass)
        for entity_id in entity_ids:
            if error := _member_error(group_type, ent_reg.async_get(entity_id), entity_id):
                raise SchemaFlowError(error)
        key = _delay_field(group_type)[0]
        user_input[key] = int(user_input[key])
        return {CONF_GROUP_TYPE: group_type, **user_input}

    return _validate


async def choose_options_step(options: dict[str, Any]) -> str:
    """Options step for the entry's group type."""
    return cast(str, options[CONF_GROUP_TYPE])


CONFIG_FLOW: dict[str, SchemaFlowMenuStep | SchemaFlowFormStep] = {
    "user": SchemaFlowMenuStep(GROUP_TYPES),
    **{
        group_type: SchemaFlowFormStep(
            config_schema(group_type), validate_user_input=validator(group_type)
        )
        for group_type in GROUP_TYPES
    },
}
OPTIONS_FLOW: dict[str, SchemaFlowFormStep] = {
    "init": SchemaFlowFormStep(next_step=choose_options_step),
    **{
        group_type: SchemaFlowFormStep(
            options_schema(group_type), validate_user_input=validator(group_type)
        )
        for group_type in GROUP_TYPES
    },
}


class ZwaveMulticastGroupConfigFlow(SchemaConfigFlowHandler, domain=DOMAIN):
    """Create a Z-Wave multicast group."""

    VERSION = 1
    MINOR_VERSION = 2  # 1.2 added options["group_type"] (1.1 entries are all covers)

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Use the group name as the entry title."""
        return cast(str, options["name"])
