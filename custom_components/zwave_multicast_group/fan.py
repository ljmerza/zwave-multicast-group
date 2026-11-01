"""A fan group that runs its Z-Wave JS Multilevel Switch fans with one multicast frame.

On/off and percentage only; preset modes stay on the members. Fans that Home Assistant
drives with a per-device speed table (``percentage_step`` other than 1) get a percentage
one by one, because the shared 1-99 mapping would pick a different speed for them.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PERCENTAGE_STEP,
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .commands import Command
from .const import CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY
from .entity import ZwaveMulticastGroupEntity

PARALLEL_UPDATES = 0

SERVICE_SET_PERCENTAGE = "set_percentage"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the multicast group fan."""
    async_add_entities([ZwaveMulticastGroupFan(entry)])


class ZwaveMulticastGroupFan(ZwaveMulticastGroupEntity, FanEntity):
    """One fan that runs several Z-Wave JS fans with one multicast frame."""

    _group_domain = "fan"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(self, entry: ConfigEntry) -> None:
        """Set up from the config entry options."""
        super().__init__(entry, int(entry.options.get(CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY)))

    # ------------------------------------------------------------------ state

    @property
    def is_on(self) -> bool | None:
        """On when any member is on (like HA's fan group)."""
        valid = self._valid_states()
        return any(s.state == STATE_ON for s in valid) if valid else None

    @property
    def percentage(self) -> int | None:
        """Mean percentage of the members (like HA's fan group)."""
        values = [
            p
            for s in self._member_states()
            if isinstance(p := s.attributes.get(ATTR_PERCENTAGE), (int, float))
        ]
        return int(sum(values) / len(values)) if values else None

    @property
    def percentage_step(self) -> float:
        """Any whole percent (members with a speed table round it themselves)."""
        return 1

    # ------------------------------------------------------------------ commands

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn every member on (to a percentage, or each to its previous speed)."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
            return
        await self._async_send(Command("fan", "turn_on", on=True))

    async def async_set_percentage(self, percentage: int) -> None:
        """Set every member to one percentage."""
        if percentage <= 0:
            await self.async_turn_off()
            return
        await self._async_send(
            Command("fan", f"set_percentage {percentage}", on=True, level=percentage)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn every member off."""
        await self._async_send(Command("fan", "turn_off", on=False))

    def _one_by_one_call(self, cmd: Command) -> tuple[str, dict[str, Any]]:
        if not cmd.on:
            return SERVICE_TURN_OFF, {}
        if cmd.level is None:
            return SERVICE_TURN_ON, {}
        return SERVICE_SET_PERCENTAGE, {ATTR_PERCENTAGE: cmd.level}

    def _member_value_mapped(self, state: State | None) -> bool:
        step = state.attributes.get(ATTR_PERCENTAGE_STEP) if state is not None else None
        return not isinstance(step, (int, float)) or abs(step - 1) > 1e-6
