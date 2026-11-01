"""Shared machinery for every multicast group platform.

A normal group calls each member separately, and the Z-Wave controller sends one
acknowledged frame per node, so members start ~1 s apart. A multicast group sends one
``targetValue`` multicast per compatible batch instead, so they start together.

Multicast frames are not acknowledged, and after one Z-Wave JS marks every member at the
target straight away, so a member that missed the frame still looks fine. So after each
command the group:
  * waits a settle time (a cover's travel time, or a short verify delay),
  * polls each multicast member's real value and re-sends the normal command one by one
    to any that didn't get there,
  * and, when the multicast itself fails, retries it once at once (the first multicast
    after a restart has been seen to fail with ZW0204 and the next to land) before
    falling back to the normal (one-by-one) command.

A cover stop has no target to verify, so after a stop multicast the group also sends
the normal stop to each multicast member as a backstop (a stop to a stopped cover does
nothing).

Platforms supply the Home Assistant side: their state, how to build a ``Command`` and
which normal service call is the one-by-one equivalent.
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

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .commands import (
    TRANSITION_DURATION_OPTION,
    Command,
    multicast_options,
    plan,
    reached,
)
from .const import (
    ATTR_LAST_COMMAND,
    ATTR_LAST_DELIVERY,
    ATTR_LAST_VERIFY,
    ATTR_MULTICAST_FAILURES,
    CONF_ENTITIES,
    VERIFY_REPORT_WAIT,
    ZWAVE_JS_DOMAIN,
)
from .members import (
    Member,
    member_value,
    parse_unique_id,
    stop_value_ids,
    target_value_id,
)

_LOGGER = logging.getLogger(__name__)


class _Resolved:
    """Members resolved to their Z-Wave JS client, node and value at command time."""

    def __init__(self) -> None:
        self.members: list[Member] = []
        self.unresolved: list[str] = []
        self.clients: dict[str, Any] = {}  # zwave_js entry_id -> zwave_js_server Client
        self.nodes: dict[str, Any] = {}  # entity_id -> zwave_js_server Node


class ZwaveMulticastGroupEntity(Entity):
    """Base for a group entity that drives its Z-Wave JS members with multicast."""

    _attr_should_poll = False
    _group_domain: str  # "cover", "light", ... (the members' and the group's domain)

    def __init__(self, entry: ConfigEntry, settle_time: float) -> None:
        """Set up from the config entry options."""
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._entity_ids: list[str] = list(entry.options[CONF_ENTITIES])
        self._settle_time = settle_time

        self._generation = 0  # bumped by every command; a stale verify gives up
        self._cancel_settle: Callable[[], None] | None = None
        self._verify_task: asyncio.Task | None = None
        self._pending_verify: list[tuple[Member, Any]] = []
        self._pending_command: Command | None = None

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
        """Cancel the settle timer and any verify in flight."""
        self._cancel_timers()

    @callback
    def _async_member_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    # ------------------------------------------------------------------ state

    def _member_states(self) -> list[State]:
        return [s for eid in self._entity_ids if (s := self.hass.states.get(eid)) is not None]

    def _valid_states(self) -> list[State]:
        return [
            s for s in self._member_states() if s.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ]

    @property
    def available(self) -> bool:
        """Available while any member is."""
        return bool(self._valid_states())

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

    # ------------------------------------------------------------------ platform hooks

    def _one_by_one_call(self, cmd: Command) -> tuple[str, dict[str, Any]]:
        """The normal service (in the group's domain) and data that does ``cmd``."""
        raise NotImplementedError

    def _member_value_mapped(self, state: State | None) -> bool:
        """Whether HA maps this member's levels with a per-device table."""
        return False

    @callback
    def _async_settled(self) -> None:
        """The settle time ran out (a cover stops showing opening/closing)."""

    # ------------------------------------------------------------------ commands

    async def _async_send(
        self,
        cmd: Command,
        settle_time: float | None = None,
        entity_ids: list[str] | None = None,
    ) -> None:
        """Multicast ``cmd`` to every batch, one by one to the rest, then verify."""
        self._generation += 1
        self._cancel_timers()
        resolved = self._resolve(entity_ids)
        batches, singles = plan(cmd, resolved.members)
        one_by_one = [m.entity_id for m in singles] + resolved.unresolved
        delivered: list[tuple[Member, Any]] = []
        failed = 0
        retried = 0

        for value, data, batch in batches:
            names = [m.entity_id for m in batch]
            ok, reason = await self._async_multicast(resolved, cmd, value, data, batch)
            if not ok:
                self._multicast_failures += 1
                _LOGGER.info(
                    "%s: multicast to %s failed (%s); retrying once", self.entity_id, names, reason
                )
                retried += len(batch)
                ok, reason = await self._async_multicast(resolved, cmd, value, data, batch)
                if not ok:
                    self._multicast_failures += 1
            if ok:
                delivered.extend((m, resolved.nodes[m.entity_id]) for m in batch)
            else:
                failed += len(batch)
                _LOGGER.warning(
                    "%s: multicast to %s failed twice (%s); sending one by one",
                    self.entity_id,
                    names,
                    reason,
                )
                one_by_one.extend(names)

        backstop: list[str] = []
        if cmd.stop:  # nothing to verify: back the stop up with the normal one
            backstop = [m.entity_id for m, _node in delivered]
            delivered = []

        notes = []
        if retried:
            notes.append(f"{retried} needed a multicast retry")
        if failed:
            notes.append(f"{failed} after a failed multicast")
        self._last_command = cmd.label
        self._last_delivery = (
            f"multicast {len(delivered) + len(backstop)}, one by one {len(one_by_one)}"
            + (f", backstop {len(backstop)}" if backstop else "")
            + (f" ({'; '.join(notes)})" if notes else "")
        )
        self._last_verify = "pending" if delivered else None
        self._pending_command = cmd
        self._pending_verify = delivered
        self._cancel_settle = async_call_later(
            self.hass,
            self._settle_time if settle_time is None else settle_time,
            self._async_settle_done,
        )
        self.async_write_ha_state()

        if one_by_one or backstop:
            await self._async_one_by_one(cmd, one_by_one + backstop)

    async def _async_multicast(
        self, resolved: _Resolved, cmd: Command, value: Any, data: dict, batch: list[Member]
    ) -> tuple[bool, str]:
        """One multicast attempt; (landed, reason)."""
        try:
            result = await async_multicast_set_value(
                client=resolved.clients[batch[0].entry_id],
                new_value=value,
                value_data=data,
                nodes=[resolved.nodes[m.entity_id] for m in batch],
                options=multicast_options(cmd, batch),
            )
        except BaseZwaveJSServerError as err:
            return False, str(err)
        reason = f"{result.status.name} {result.message or ''}".strip()
        return result.status in SET_VALUE_SUCCESS, reason

    @callback
    def _async_cancel(self, label: str) -> None:
        """Drop the command in flight (its settle window and verify)."""
        self._generation += 1
        self._cancel_timers()
        self._pending_command = None
        self._last_command = label
        self._last_verify = None

    async def _async_one_by_one(self, cmd: Command, entity_ids: list[str]) -> None:
        """The normal service on each member (acknowledged, ~1 s apart)."""
        service, data = self._one_by_one_call(cmd)
        await self.hass.services.async_call(
            self._group_domain,
            service,
            {ATTR_ENTITY_ID: entity_ids, **data},
            blocking=True,
            context=self._context,
        )

    # ------------------------------------------------------------------ after settling

    @callback
    def _async_settle_done(self, _now: datetime) -> None:
        self._cancel_settle = None
        self._async_settled()
        self.async_write_ha_state()
        if self._pending_verify and self._pending_command is not None:
            self._verify_task = self.hass.async_create_background_task(
                self._async_verify(self._generation, self._pending_command, self._pending_verify),
                f"{self.entity_id} multicast verify",
            )
        self._pending_verify = []

    async def _async_verify(
        self, generation: int, cmd: Command, delivered: list[tuple[Member, Any]]
    ) -> None:
        """Ask each multicast member for its real value; re-send to any that missed."""
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
            if state is None or not reached(cmd, member, state.state, state.attributes):
                missed.append(member.entity_id)

        if not missed:
            self._last_verify = "ok"
            self.async_write_ha_state()
            return

        _LOGGER.warning(
            "%s: %s didn't reach '%s' after the multicast; re-sending one by one",
            self.entity_id,
            missed,
            cmd.label,
        )
        self._last_verify = f"re-sent to {', '.join(missed)}"
        self.async_write_ha_state()
        try:
            await self._async_one_by_one(cmd, missed)
        except HomeAssistantError as err:
            _LOGGER.error("%s: re-send to %s failed: %s", self.entity_id, missed, err)

    # ------------------------------------------------------------------ helpers

    def _cancel_timers(self) -> None:
        if self._cancel_settle is not None:
            self._cancel_settle()
            self._cancel_settle = None
        if self._verify_task is not None and not self._verify_task.done():
            self._verify_task.cancel()
        self._verify_task = None
        self._pending_verify = []

    def _resolve(self, entity_ids: list[str] | None = None) -> _Resolved:
        """Map each member entity to its Z-Wave JS client, node and value."""
        resolved = _Resolved()
        ent_reg = er.async_get(self.hass)
        for entity_id in self._entity_ids if entity_ids is None else entity_ids:
            entry = ent_reg.async_get(entity_id)
            ref = (
                member_value(self._group_domain, parse_unique_id(entry.unique_id))
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
            target = node.values.get(target_value_id(ref))
            change_options = getattr(getattr(target, "metadata", None), "value_change_options", None)
            stop_property = next(
                (prop for prop, vid in stop_value_ids(ref) if vid in node.values), None
            ) if self._group_domain == "cover" else None
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
                    value_mapped=self._member_value_mapped(self.hass.states.get(entity_id)),
                    supports_transition=TRANSITION_DURATION_OPTION in (change_options or ()),
                    stop_property=stop_property,
                )
            )
            resolved.clients[zwave_entry.entry_id] = client
            resolved.nodes[entity_id] = node
        return resolved
