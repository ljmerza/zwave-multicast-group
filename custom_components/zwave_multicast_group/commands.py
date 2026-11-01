"""What each group command sends to each member, and how to tell it arrived.

Pure helpers with no Home Assistant imports, so they can be unit-tested on their own.
The value mapping mirrors Home Assistant's own zwave_js platforms (2026.10):

* cover: 0-100 % scaled onto the value's min/max (``percent_to_zwave``).
* light, Multilevel Switch: off = 0, on with no brightness = 255 ("previous level"),
  brightness 0-255 -> 1-99 (``brightness_to_zwave``). Binary Switch lights: True/False;
  their brightness lives in the Color Switch channels, so a brightness goes one by one.
* switch: Binary Switch True/False.
* fan: off = 0, on with no percentage = 255, percentage -> ceil(% * 99 / 100). Fans that
  HA drives through a per-device value mapping get a percentage one by one.
* cover stop: False to the member's stop value (Window Covering ``levelChangeUp``, or a
  Multilevel Switch cover's Open/Up/On), i.e. Stop Level Change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import LEVEL_TOLERANCE, POSITION_TOLERANCE
from .members import (
    SET_TO_PREVIOUS_VALUE,
    SWITCH_BINARY,
    Member,
    brightness_to_zwave,
    fan_percentage_to_zwave,
    partition,
    percent_to_zwave,
    stop_value_data,
    target_value_data,
)

# zwave_js_server.const.TRANSITION_DURATION_OPTION
TRANSITION_DURATION_OPTION = "transitionDuration"

STATE_ON = "on"
STATE_OFF = "off"


class _OneByOne:
    """Sentinel: this member can't take this command as a shared multicast value."""

    def __repr__(self) -> str:
        return "ONE_BY_ONE"


ONE_BY_ONE: Any = _OneByOne()


@dataclass(frozen=True)
class Command:
    """One group command, in Home Assistant terms.

    ``level`` is the cover position (0-100), light brightness (0-255) or fan percentage
    (0-100); None means "on, at whatever level the device restores". Covers ignore ``on``.
    ``stop`` is a cover stop (no target; nothing to verify).
    """

    domain: str
    label: str
    on: bool = True
    level: int | None = None
    transition: float | None = None
    stop: bool = False


def zwave_value(cmd: Command, member: Member) -> Any:
    """The targetValue to multicast to ``member`` for ``cmd``, or ONE_BY_ONE."""
    if cmd.stop:
        return False if member.stop_property is not None else ONE_BY_ONE
    if cmd.domain == "cover":
        assert cmd.level is not None
        return percent_to_zwave(cmd.level, member.min_value, member.max_value)
    if member.ref.command_class == SWITCH_BINARY:  # switches and Binary Switch lights
        if cmd.on and cmd.level is not None:
            return ONE_BY_ONE  # a Binary Switch light's brightness lives in its colors
        return bool(cmd.on)
    if not cmd.on:
        return 0
    if cmd.level is None:
        return SET_TO_PREVIOUS_VALUE
    if cmd.domain == "light":
        return brightness_to_zwave(cmd.level)
    if cmd.domain == "fan":
        if member.value_mapped:
            return ONE_BY_ONE
        return fan_percentage_to_zwave(cmd.level)
    return ONE_BY_ONE


def value_data(cmd: Command, member: Member) -> dict:
    """The value ``cmd`` sets on ``member``: its stop value or its targetValue."""
    return stop_value_data(member) if cmd.stop else target_value_data(member.ref)


def plan(
    cmd: Command, members: list[Member]
) -> tuple[list[tuple[Any, dict, list[Member]]], list[Member]]:
    """Split members into (value, value_data, batch) multicasts and one-by-one singles."""
    eligible: list[Member] = []
    excluded: list[Member] = []
    for member in members:
        (excluded if zwave_value(cmd, member) is ONE_BY_ONE else eligible).append(member)
    batches, singles = partition(
        eligible,
        lambda m: (repr(zwave_value(cmd, m)), tuple(sorted(value_data(cmd, m).items()))),
    )
    return [
        (zwave_value(cmd, batch[0]), value_data(cmd, batch[0]), batch) for batch in batches
    ], singles + excluded


def multicast_options(cmd: Command, batch: list[Member]) -> dict | None:
    """Set-value options for a light batch: a transition, like HA's zwave_js light.

    HA sends ``transitionDuration`` ("<n>s", or "default" with no transition) only to a
    value that advertises it. One multicast carries one set of options, so it's sent
    only when every member of the batch supports it.
    """
    if cmd.domain != "light" or not batch or not all(m.supports_transition for m in batch):
        return None
    duration = f"{int(cmd.transition)}s" if cmd.transition is not None else "default"
    return {TRANSITION_DURATION_OPTION: duration}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def reached(cmd: Command, member: Member, state: str | None, attrs: Mapping[str, Any]) -> bool:
    """Whether a member's (polled) HA state shows the command arrived."""
    if cmd.stop:
        return True  # no target to check
    if cmd.domain == "cover":
        pos = _number(attrs.get("current_position"))
        return pos is not None and cmd.level is not None and abs(pos - cmd.level) <= POSITION_TOLERANCE
    if state != (STATE_ON if cmd.on else STATE_OFF):
        return False
    if not cmd.on or cmd.level is None:
        return True
    if cmd.domain == "light" and member.ref.command_class != SWITCH_BINARY:
        brightness = _number(attrs.get("brightness"))
        if brightness is None:
            return False
        level = round(brightness / 255 * 99)
        return abs(level - brightness_to_zwave(cmd.level)) <= LEVEL_TOLERANCE
    if cmd.domain == "fan":
        percentage = _number(attrs.get("percentage"))
        return percentage is not None and abs(percentage - cmd.level) <= POSITION_TOLERANCE
    return True
