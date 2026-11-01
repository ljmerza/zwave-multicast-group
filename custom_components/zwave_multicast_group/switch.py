"""A switch group that switches its Z-Wave JS Binary Switches with one multicast frame."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .commands import Command
from .const import CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY
from .entity import ZwaveMulticastGroupEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the multicast group switch."""
    async_add_entities([ZwaveMulticastGroupSwitch(entry)])


class ZwaveMulticastGroupSwitch(ZwaveMulticastGroupEntity, SwitchEntity):
    """One switch that switches several Z-Wave JS switches with one multicast frame."""

    _group_domain = "switch"

    def __init__(self, entry: ConfigEntry) -> None:
        """Set up from the config entry options."""
        super().__init__(entry, int(entry.options.get(CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY)))

    @property
    def is_on(self) -> bool | None:
        """On when any member is on (like HA's switch group)."""
        valid = self._valid_states()
        return any(s.state == STATE_ON for s in valid) if valid else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn every member on."""
        await self._async_send(Command("switch", "turn_on", on=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn every member off."""
        await self._async_send(Command("switch", "turn_off", on=False))

    def _one_by_one_call(self, cmd: Command) -> tuple[str, dict[str, Any]]:
        return (SERVICE_TURN_ON if cmd.on else SERVICE_TURN_OFF), {}
