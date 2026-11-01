"""A cover group that moves its Z-Wave JS covers with one multicast frame.

On top of the shared multicast/verify/fallback machinery (``entity.py``) the cover
reports opening/closing itself for the configured travel time, because Z-Wave JS marks
multicast members at the target straight away. Stop is a multicast too (Stop Level
Change, the value HA's zwave_js cover uses), followed by the normal stop as a backstop.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
    STATE_CLOSING,
    STATE_OPENING,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .commands import Command
from .const import CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME
from .entity import ZwaveMulticastGroupEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the multicast group cover."""
    async_add_entities([ZwaveMulticastGroupCover(entry)])


class ZwaveMulticastGroupCover(ZwaveMulticastGroupEntity, CoverEntity):
    """One cover that moves several Z-Wave JS covers with one multicast frame."""

    _group_domain = "cover"

    def __init__(self, entry: ConfigEntry) -> None:
        """Set up from the config entry options."""
        super().__init__(entry, int(entry.options.get(CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME)))
        self._moving: str | None = None  # STATE_OPENING / STATE_CLOSING while travelling

    # ------------------------------------------------------------------ state

    def _positions(self) -> list[float]:
        return [
            pos
            for s in self._member_states()
            if isinstance(pos := s.attributes.get(ATTR_CURRENT_POSITION), (int, float))
        ]

    @property
    def current_cover_position(self) -> int | None:
        """Average position of the members."""
        positions = self._positions()
        return round(sum(positions) / len(positions)) if positions else None

    @property
    def is_closed(self) -> bool | None:
        """Closed when every member is fully closed."""
        positions = self._positions()
        return all(p == 0 for p in positions) if positions else None

    @property
    def is_opening(self) -> bool:
        """Opening while our own travel window runs, or when a member reports it."""
        if self._moving is not None:
            return self._moving == STATE_OPENING
        return any(s.state == STATE_OPENING for s in self._member_states())

    @property
    def is_closing(self) -> bool:
        """Closing while our own travel window runs, or when a member reports it."""
        if self._moving is not None:
            return self._moving == STATE_CLOSING
        return any(s.state == STATE_CLOSING for s in self._member_states())

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Open/close/position always; stop when any member can stop."""
        features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION
        )
        if self._stoppable_members():
            features |= CoverEntityFeature.STOP
        return features

    @property
    def device_class(self) -> str | None:
        """The members' device class when they all agree."""
        classes = {s.attributes.get(ATTR_DEVICE_CLASS) for s in self._member_states()}
        return classes.pop() if len(classes) == 1 else None

    def _stoppable_members(self) -> list[str]:
        return [
            s.entity_id
            for s in self._member_states()
            if int(s.attributes.get(ATTR_SUPPORTED_FEATURES, 0)) & CoverEntityFeature.STOP
        ]

    # ------------------------------------------------------------------ commands

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open every member together."""
        await self._async_move(100, "open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close every member together."""
        await self._async_move(0, "close")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move every member to one position together."""
        position = int(kwargs[ATTR_POSITION])
        await self._async_move(position, f"set_position {position}")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop every member that can stop, with one multicast (plus a backstop)."""
        self._moving = None
        if targets := self._stoppable_members():
            await self._async_send(Command("cover", "stop", stop=True), 0, targets)
        else:
            self._async_cancel("stop")
            self.async_write_ha_state()

    async def _async_move(self, percent: int, label: str) -> None:
        before = self.current_cover_position
        if before is None or percent != before:
            self._moving = STATE_OPENING if before is None or percent > before else STATE_CLOSING
        await self._async_send(Command("cover", label, level=percent))

    def _one_by_one_call(self, cmd: Command) -> tuple[str, dict[str, Any]]:
        if cmd.stop:
            return SERVICE_STOP_COVER, {}
        percent = cmd.level if cmd.level is not None else 100
        if percent >= 100:
            return SERVICE_OPEN_COVER, {}
        if percent <= 0:
            return SERVICE_CLOSE_COVER, {}
        return SERVICE_SET_COVER_POSITION, {ATTR_POSITION: percent}

    @callback
    def _async_settled(self) -> None:
        self._moving = None
