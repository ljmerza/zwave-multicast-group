"""A light group that switches/dims its Z-Wave JS lights with one multicast frame.

On/off and brightness only. Members that also do color keep their color; the group
doesn't offer color (see README "Light").
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
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
    """Add the multicast group light."""
    async_add_entities([ZwaveMulticastGroupLight(entry)])


class ZwaveMulticastGroupLight(ZwaveMulticastGroupEntity, LightEntity):
    """One light that switches several Z-Wave JS lights with one multicast frame."""

    _group_domain = "light"

    def __init__(self, entry: ConfigEntry) -> None:
        """Set up from the config entry options."""
        super().__init__(entry, int(entry.options.get(CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY)))

    # ------------------------------------------------------------------ state

    @property
    def is_on(self) -> bool | None:
        """On when any member is on (like HA's light group)."""
        valid = self._valid_states()
        return any(s.state == STATE_ON for s in valid) if valid else None

    @property
    def brightness(self) -> int | None:
        """Mean brightness of the members that are on."""
        values = [
            b
            for s in self._member_states()
            if s.state == STATE_ON
            and isinstance(b := s.attributes.get(ATTR_BRIGHTNESS), (int, float))
        ]
        return int(sum(values) / len(values)) if values else None

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Brightness unless every member is on/off only."""
        modes = [s.attributes.get(ATTR_SUPPORTED_COLOR_MODES) for s in self._member_states()]
        if modes and all(m and set(m) == {ColorMode.ONOFF} for m in modes):
            return {ColorMode.ONOFF}
        return {ColorMode.BRIGHTNESS}

    @property
    def color_mode(self) -> ColorMode:
        """The one mode the group supports."""
        return next(iter(self.supported_color_modes))

    @property
    def supported_features(self) -> LightEntityFeature:
        """Transition when any member supports it."""
        if any(
            int(s.attributes.get(ATTR_SUPPORTED_FEATURES, 0)) & LightEntityFeature.TRANSITION
            for s in self._member_states()
        ):
            return LightEntityFeature.TRANSITION
        return LightEntityFeature(0)

    # ------------------------------------------------------------------ commands

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn every member on (to a brightness, or each to its previous level)."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        transition = kwargs.get(ATTR_TRANSITION)
        label = "turn_on" if brightness is None else f"turn_on brightness {brightness}"
        await self._async_send(
            Command("light", label, on=True, level=brightness, transition=transition),
            self._settle_for(transition),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn every member off."""
        transition = kwargs.get(ATTR_TRANSITION)
        await self._async_send(
            Command("light", "turn_off", on=False, transition=transition),
            self._settle_for(transition),
        )

    def _settle_for(self, transition: float | None) -> float:
        return self._settle_time + (transition or 0)

    def _one_by_one_call(self, cmd: Command) -> tuple[str, dict[str, Any]]:
        data: dict[str, Any] = {}
        if cmd.transition is not None:
            data[ATTR_TRANSITION] = cmd.transition
        if not cmd.on:
            return SERVICE_TURN_OFF, data
        if cmd.level is not None:
            data[ATTR_BRIGHTNESS] = cmd.level
        return SERVICE_TURN_ON, data
