"""Parse Z-Wave JS entities and split them into multicast batches.

Pure helpers with no Home Assistant imports, so they can be unit-tested on their own.

A Z-Wave JS entity's unique ID is ``<home_id>.<value_id>`` and a value ID is
``<node>-<command class>-<endpoint>-<property>[-<property key>]``, e.g.
``4170970308.143-106-0-currentValue-13``.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
import math

SWITCH_BINARY = 37
SWITCH_MULTILEVEL = 38
WINDOW_COVERING = 106
SUPPORTED_COMMAND_CLASSES = (SWITCH_MULTILEVEL, WINDOW_COVERING)

# Window Covering parameters with an even key are the "no position" variants
# (zwave_js_server.const.command_class.window_covering.NO_POSITION_PROPERTY_KEYS).
NO_POSITION_KEYS = frozenset(range(0, 24, 2))
# Vertical / horizontal slats angle (WindowCoveringPropertyKey 10/11, 22/23). HA's
# zwave_js cover maps these to tilt with its own slat scale (open = 50), not position.
SLAT_ANGLE_KEYS = frozenset({10, 11, 22, 23})

# Stop values, as HA's zwave_js cover picks them: Window Covering stops by setting
# levelChangeUp (same parameter key) to False; a Multilevel Switch cover by setting the
# first of Open / Up / On to False (both are Stop Level Change).
WINDOW_COVERING_STOP_PROPERTY = "levelChangeUp"
MULTILEVEL_SWITCH_STOP_PROPERTIES = ("Open", "Up", "On")

# Multilevel Switch "restore the previous non-zero level"
# (zwave_js_server.const.command_class.multilevel_switch.SET_TO_PREVIOUS_VALUE).
SET_TO_PREVIOUS_VALUE = 255

CURRENT_VALUE = "currentValue"
TARGET_VALUE = "targetValue"

# zwave_js_server.const.SecurityClass.NONE / Protocols.ZWAVE
SECURITY_NONE = -1
PROTOCOL_ZWAVE = 0


@dataclass(frozen=True)
class ValueRef:
    """A parsed Z-Wave JS value ID."""

    value_id: str
    node_id: int
    command_class: int
    endpoint: int
    property_: str
    property_key: int | str | None


@dataclass(frozen=True)
class Member:
    """One cover entity in a multicast group, resolved to its Z-Wave value."""

    entity_id: str
    entry_id: str  # zwave_js config entry (one controller / client)
    ref: ValueRef
    min_value: int
    max_value: int
    security_class: int | None
    protocol: int | None
    # HA maps this member's levels with its own per-device table (zwave_js fans with a
    # value mapping), so a level computed here can't be shared with it.
    value_mapped: bool = False
    # The member's targetValue accepts a transitionDuration option.
    supports_transition: bool = False
    # Property that stops this cover (set to False), if it has one.
    stop_property: str | None = None


def parse_value_id(value_id: str) -> ValueRef | None:
    """Parse ``143-106-0-currentValue-13``; None if it isn't a value ID."""
    parts = value_id.split("-")
    if len(parts) < 4:
        return None
    try:
        node_id, command_class, endpoint = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    property_key: int | str | None = None
    if len(parts) > 4:
        raw = "-".join(parts[4:])
        property_key = int(raw) if raw.lstrip("-").isdigit() else raw
    return ValueRef(value_id, node_id, command_class, endpoint, parts[3], property_key)


def parse_unique_id(unique_id: str) -> ValueRef | None:
    """Parse a Z-Wave JS entity unique ID (``<home_id>.<value_id>``)."""
    _, sep, value_id = unique_id.partition(".")
    if not sep or "-" not in value_id:
        return None
    return parse_value_id(value_id)


def position_value(ref: ValueRef | None) -> ValueRef | None:
    """Return the ref if it is a cover position value we can multicast, else None."""
    if ref is None or ref.command_class not in SUPPORTED_COMMAND_CLASSES:
        return None
    if ref.property_ != CURRENT_VALUE:
        return None
    if ref.command_class == WINDOW_COVERING and (
        ref.property_key in NO_POSITION_KEYS or ref.property_key in SLAT_ANGLE_KEYS
    ):
        return None
    return ref


def _current_value_of(ref: ValueRef | None, command_classes: tuple[int, ...]) -> ValueRef | None:
    if ref is None or ref.command_class not in command_classes or ref.property_ != CURRENT_VALUE:
        return None
    return ref


def light_value(ref: ValueRef | None) -> ValueRef | None:
    """A light whose on/off (and level) is a Multilevel or Binary Switch currentValue.

    Lights driven only by Color Switch or by Basic CC are left out.
    """
    return _current_value_of(ref, (SWITCH_MULTILEVEL, SWITCH_BINARY))


def switch_value(ref: ValueRef | None) -> ValueRef | None:
    """A Binary Switch currentValue (not config parameters, indicators or barriers)."""
    return _current_value_of(ref, (SWITCH_BINARY,))


def fan_value(ref: ValueRef | None) -> ValueRef | None:
    """A Multilevel Switch fan (not Thermostat Fan Mode)."""
    return _current_value_of(ref, (SWITCH_MULTILEVEL,))


MEMBER_VALUE = {
    "cover": position_value,
    "fan": fan_value,
    "light": light_value,
    "switch": switch_value,
}


def member_value(domain: str, ref: ValueRef | None) -> ValueRef | None:
    """The ref if a ``domain`` group can drive it, else None."""
    check = MEMBER_VALUE.get(domain)
    return check(ref) if check is not None else None


def target_value_data(ref: ValueRef) -> dict:
    """ValueDataType for the target position that matches a current position value."""
    data: dict = {
        "commandClass": ref.command_class,
        "endpoint": ref.endpoint,
        "property": TARGET_VALUE,
    }
    if ref.property_key is not None:
        data["propertyKey"] = ref.property_key
    return data


def target_value_id(ref: ValueRef) -> str:
    """Value ID of the targetValue that pairs with a currentValue."""
    value_id = f"{ref.node_id}-{ref.command_class}-{ref.endpoint}-{TARGET_VALUE}"
    if ref.property_key is not None:
        value_id += f"-{ref.property_key}"
    return value_id


def stop_value_ids(ref: ValueRef) -> list[tuple[str, str]]:
    """(property, value ID) candidates for a cover's stop value, in HA's order."""
    base = f"{ref.node_id}-{ref.command_class}-{ref.endpoint}"
    if ref.command_class == WINDOW_COVERING:
        return [(WINDOW_COVERING_STOP_PROPERTY, f"{base}-{WINDOW_COVERING_STOP_PROPERTY}-{ref.property_key}")]
    if ref.command_class == SWITCH_MULTILEVEL:
        return [(prop, f"{base}-{prop}") for prop in MULTILEVEL_SWITCH_STOP_PROPERTIES]
    return []


def stop_value_data(member: Member) -> dict:
    """ValueDataType for a member's stop value (it must have one)."""
    assert member.stop_property is not None
    ref = member.ref
    data: dict = {
        "commandClass": ref.command_class,
        "endpoint": ref.endpoint,
        "property": member.stop_property,
    }
    if ref.command_class == WINDOW_COVERING and ref.property_key is not None:
        data["propertyKey"] = ref.property_key
    return data


def multicast_key(member: Member) -> tuple | None:
    """Members with the same key can share one multicast frame; None = never multicast.

    Only non-secure classic Z-Wave nodes are batched: S0 cannot multicast at all, S2
    multicast falls back to per-node follow-ups (no sync gain), and Long Range nodes
    cannot share a multicast with mesh nodes. An unknown security class is treated as
    "maybe secure" and sent one by one.
    """
    if member.security_class != SECURITY_NONE:
        return None
    if member.protocol not in (None, PROTOCOL_ZWAVE):
        return None
    ref = member.ref
    return (
        member.entry_id,
        ref.command_class,
        ref.endpoint,
        ref.property_key,
        member.min_value,
        member.max_value,
    )


def partition(
    members: list[Member], extra_key: Callable[[Member], Hashable] | None = None
) -> tuple[list[list[Member]], list[Member]]:
    """Split members into multicast batches (2+ members) and one-by-one singles.

    ``extra_key`` further splits batches (e.g. by the exact value and value ID a
    command sends).
    """
    groups: dict[tuple, list[Member]] = {}
    singles: list[Member] = []
    for member in members:
        key = multicast_key(member)
        if key is None:
            singles.append(member)
        else:
            if extra_key is not None:
                key = (*key, extra_key(member))
            groups.setdefault(key, []).append(member)
    batches: list[list[Member]] = []
    for group in groups.values():
        if len(group) >= 2:
            batches.append(group)
        else:
            singles.extend(group)
    return batches, singles


def percent_to_zwave(percent: float, min_value: int, max_value: int) -> int:
    """0-100 % to the device range (same formula as HA's zwave_js cover)."""
    fraction = max(min(1.0, percent / 100), 0.0)
    return round(fraction * (max_value - min_value)) + min_value


def zwave_to_percent(value: float, min_value: int, max_value: int) -> int:
    """Device range to 0-100 % (same formula as HA's zwave_js cover)."""
    if max_value == min_value:
        return 0
    return round((value - min_value) / (max_value - min_value) * 100)


def brightness_to_zwave(brightness: float) -> int:
    """0-255 brightness to a 0-99 level (HA zwave_js ``byte_to_zwave_brightness``)."""
    if brightness > 0:
        return max(1, round((brightness / 255) * 99))
    return 0


def zwave_to_brightness(level: float) -> int:
    """0-99 level to 0-255 brightness (HA zwave_js light ``brightness``)."""
    return round((level / 99) * 255)


def fan_percentage_to_zwave(percentage: float) -> int:
    """Fan % to a 0-99 level, as HA's zwave_js fan does with the 1-99 speed range."""
    if percentage <= 0:
        return 0
    # ceil(percentage_to_ranged_value((1, 99), percentage)) in HA 2026.10
    return min(99, math.ceil(percentage * 99 / 100))


def zwave_to_fan_percentage(level: float) -> int:
    """0-99 level to fan % (``ranged_value_to_percentage((1, 99), level)``)."""
    return int(level * 100 // 99)
