"""A cover group that moves its Z-Wave JS covers with one multicast frame.

A normal cover group calls each member separately, and the Z-Wave controller sends one
acknowledged frame per node, so members start ~1 s apart. This entity sends a single
``targetValue`` multicast to every compatible member instead, so they start together.

Multicast frames are not acknowledged, and after one Z-Wave JS marks every member at
the target straight away, so a member that missed the frame still looks fine. To cover
that, the entity:
  * reports opening/closing itself for the configured travel time,
  * then polls each multicast member's real position and re-sends the normal command
    to any that are not where they should be,
  * falls back to the normal (one-by-one) command when the multicast itself fails.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from zwave_js_server.const import SET_VALUE_SUCCESS
from zwave_js_server.exceptions import BaseZwaveJSServerError
from zwave_js_server.util.multicast import async_multicast_set_value

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    DOMAIN as COVER_DOMAIN,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    SERVICE_STOP_COVER,
    STATE_CLOSING,
    STATE_OPENING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import (
    ATTR_LAST_COMMAND,
    ATTR_LAST_DELIVERY,
    ATTR_LAST_VERIFY,
    ATTR_MULTICAST_FAILURES,
    CONF_ENTITIES,
    CONF_TRAVEL_TIME,
    DEFAULT_TRAVEL_TIME,
    POSITION_TOLERANCE,
    VERIFY_REPORT_WAIT,
    ZWAVE_JS_DOMAIN,
)
from .members import (
    Member,
    parse_unique_id,
    partition,
    percent_to_zwave,
    position_value,
    target_value_data,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the multicast group cover."""
    async_add_entities([ZwaveMulticastGroupCover(entry)])


class _Resolved:
    """Members resolved to their Z-Wave JS client, node and value at command time."""

    def __init__(self) -> None:
        self.members: list[Member] = []
        self.unresolved: list[str] = []
        self.clients: dict[str, Any] = {}  # zwave_js entry_id -> zwave_js_server Client
        self.nodes: dict[str, Any] = {}  # entity_id -> zwave_js_server Node


class ZwaveMulticastGroupCover(CoverEntity):
    """One cover that moves several Z-Wave JS covers with one multicast frame."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Set up from the config entry options."""
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._entity_ids: list[str] = list(entry.options[CONF_ENTITIES])
        self._travel_time = int(entry.options.get(CONF_TRAVEL_TIME, DEFAULT_TRAVEL_TIME))

        self._generation = 0  # bumped by every command; a stale verify gives up
        self._moving: str | None = None  # STATE_OPENING / STATE_CLOSING while travelling
        self._cancel_travel: Callable[[], None] | None = None
        self._verify_task: asyncio.Task | None = None
        self._pending_verify: list[tuple[Member, Any]] = []
        self._target: int | None = None

        self._last_command: str | None = None
        self._last_delivery: str | None = None
        self._last_verify: str | None = None
        self._multicast_failures = 0

    # ------------------------------------------------------------------ lifecycle

    async def async_added_to_hass(self) -> None:
        """Follow the members' states."""
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._entity_ids, self._async_member_changed
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the travel timer and any verify in flight."""
        self._cancel_timers()

    @callback
    def _async_member_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    # ------------------------------------------------------------------ state

    def _member_states(self) -> list[State]:
        return [s for eid in self._entity_ids if (s := self.hass.states.get(eid)) is not None]

    def _positions(self) -> list[float]:
        return [
            pos
            for s in self._member_states()
            if isinstance(pos := s.attributes.get(ATTR_CURRENT_POSITION), (int, float))
        ]

    @property
    def available(self) -> bool:
        """Available while any member is."""
        return any(
            s.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN) for s in self._member_states()
        )

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Members plus what the last command did, for debugging."""
        return {
            ATTR_ENTITY_ID: self._entity_ids,
            ATTR_LAST_COMMAND: self._last_command,
            ATTR_LAST_DELIVERY: self._last_delivery,
            ATTR_LAST_VERIFY: self._last_verify,
            ATTR_MULTICAST_FAILURES: self._multicast_failures,
        }

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
        """Stop every member (one by one; a stop doesn't need to be in sync)."""
        self._generation += 1
        self._cancel_timers()
        self._moving = None
        self._target = None
        self._last_command = "stop"
        self._last_verify = None
        self.async_write_ha_state()
        if targets := self._stoppable_members():
            await self.hass.services.async_call(
                COVER_DOMAIN,
                SERVICE_STOP_COVER,
                {ATTR_ENTITY_ID: targets},
                blocking=True,
                context=self._context,
            )

    async def _async_move(self, percent: int, command: str) -> None:
        self._generation += 1
        self._cancel_timers()
        before = self.current_cover_position
        resolved = self._resolve()
        batches, singles = partition(resolved.members)
        one_by_one = [m.entity_id for m in singles] + resolved.unresolved
        delivered: list[tuple[Member, Any]] = []
        failed = 0

        for batch in batches:
            first = batch[0]
            names = [m.entity_id for m in batch]
            try:
                result = await async_multicast_set_value(
                    client=resolved.clients[first.entry_id],
                    new_value=percent_to_zwave(percent, first.min_value, first.max_value),
                    value_data=target_value_data(first.ref),
                    nodes=[resolved.nodes[m.entity_id] for m in batch],
                )
                ok = result.status in SET_VALUE_SUCCESS
                reason = f"{result.status.name} {result.message or ''}".strip()
            except BaseZwaveJSServerError as err:
                ok, reason = False, str(err)
            if ok:
                delivered.extend((m, resolved.nodes[m.entity_id]) for m in batch)
            else:
                failed += len(batch)
                self._multicast_failures += 1
                _LOGGER.warning(
                    "%s: multicast to %s failed (%s); sending one by one",
                    self.entity_id,
                    names,
                    reason,
                )
                one_by_one.extend(names)

        self._last_command = command
        self._last_delivery = (
            f"multicast {len(delivered)}, one by one {len(one_by_one)}"
            + (f" ({failed} after a failed multicast)" if failed else "")
        )
        self._last_verify = "pending" if delivered else None
        self._target = percent
        if before is None or percent != before:
            self._moving = STATE_OPENING if before is None or percent > before else STATE_CLOSING
        self._pending_verify = delivered
        self._cancel_travel = async_call_later(
            self.hass, self._travel_time, self._async_travel_done
        )
        self.async_write_ha_state()

        if one_by_one:
            await self._async_one_by_one(percent, one_by_one)

    async def _async_one_by_one(self, percent: int, entity_ids: list[str]) -> None:
        """The normal cover service on each member (acknowledged, ~1 s apart)."""
        if percent >= 100:
            service, data = SERVICE_OPEN_COVER, {}
        elif percent <= 0:
            service, data = SERVICE_CLOSE_COVER, {}
        else:
            service, data = SERVICE_SET_COVER_POSITION, {ATTR_POSITION: percent}
        await self.hass.services.async_call(
            COVER_DOMAIN,
            service,
            {ATTR_ENTITY_ID: entity_ids, **data},
            blocking=True,
            context=self._context,
        )

    # ------------------------------------------------------------------ after travel

    @callback
    def _async_travel_done(self, _now: datetime) -> None:
        self._cancel_travel = None
        self._moving = None
        self.async_write_ha_state()
        if self._pending_verify and self._target is not None:
            self._verify_task = self.hass.async_create_background_task(
                self._async_verify(self._generation, self._target, self._pending_verify),
                f"{self.entity_id} multicast verify",
            )
        self._pending_verify = []

    async def _async_verify(
        self, generation: int, percent: int, delivered: list[tuple[Member, Any]]
    ) -> None:
        """Ask each multicast member where it really is; re-send to any that missed."""
        for member, node in delivered:
            try:
                await node.async_poll_value(member.ref.value_id)
            except BaseZwaveJSServerError as err:
                _LOGGER.debug("%s: poll of %s failed: %s", self.entity_id, member.entity_id, err)
        await asyncio.sleep(VERIFY_REPORT_WAIT)
        if generation != self._generation:
            return  # a newer command took over

        missed = []
        for member, _node in delivered:
            state = self.hass.states.get(member.entity_id)
            pos = state.attributes.get(ATTR_CURRENT_POSITION) if state else None
            if not isinstance(pos, (int, float)) or abs(pos - percent) > POSITION_TOLERANCE:
                missed.append(member.entity_id)

        if not missed:
            self._last_verify = "ok"
            self.async_write_ha_state()
            return

        _LOGGER.warning(
            "%s: %s not at %s%% after the multicast; re-sending one by one",
            self.entity_id,
            missed,
            percent,
        )
        self._last_verify = f"re-sent to {', '.join(missed)}"
        self.async_write_ha_state()
        try:
            await self._async_one_by_one(percent, missed)
        except HomeAssistantError as err:
            _LOGGER.error("%s: re-send to %s failed: %s", self.entity_id, missed, err)

    # ------------------------------------------------------------------ helpers

    def _cancel_timers(self) -> None:
        if self._cancel_travel is not None:
            self._cancel_travel()
            self._cancel_travel = None
        if self._verify_task is not None and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = None
        self._pending_verify = []

    def _resolve(self) -> _Resolved:
        """Map each member entity to its Z-Wave JS client, node and position value."""
        resolved = _Resolved()
        ent_reg = er.async_get(self.hass)
        for entity_id in self._entity_ids:
            entry = ent_reg.async_get(entity_id)
            ref = (
                position_value(parse_unique_id(entry.unique_id))
                if entry is not None and entry.platform == ZWAVE_JS_DOMAIN
                else None
            )
            zwave_entry = (
                self.hass.config_entries.async_get_entry(entry.config_entry_id)
                if ref is not None and entry is not None and entry.config_entry_id
                else None
            )
            if ref is None or zwave_entry is None or zwave_entry.state is not ConfigEntryState.LOADED:
                resolved.unresolved.append(entity_id)
                continue
            client = zwave_entry.runtime_data.client
            driver = client.driver
            node = driver.controller.nodes.get(ref.node_id) if driver is not None else None
            if node is None:
                resolved.unresolved.append(entity_id)
                continue
            value = node.values.get(ref.value_id)
            metadata = value.metadata if value is not None else None
            min_value = metadata.min if metadata is not None and metadata.min is not None else 0
            max_value = metadata.max if metadata is not None and metadata.max is not None else 99
            security = node.highest_security_class
            protocol = node.protocol
            resolved.members.append(
                Member(
                    entity_id=entity_id,
                    entry_id=zwave_entry.entry_id,
                    ref=ref,
                    min_value=int(min_value),
                    max_value=int(max_value),
                    security_class=None if security is None else int(security),
                    protocol=None if protocol is None else int(protocol),
                )
            )
            resolved.clients[zwave_entry.entry_id] = client
            resolved.nodes[entity_id] = node
        return resolved
