"""Parse Z-Wave JS cover entities and split them into multicast batches.

Pure helpers with no Home Assistant imports, so they can be unit-tested on their own.

A Z-Wave JS entity's unique ID is ``<home_id>.<value_id>`` and a value ID is
``<node>-<command class>-<endpoint>-<property>[-<property key>]``, e.g.
``4170970308.143-106-0-currentValue-13``.
"""

from __future__ import annotations

from dataclasses import dataclass

SWITCH_MULTILEVEL = 38
WINDOW_COVERING = 106
SUPPORTED_COMMAND_CLASSES = (SWITCH_MULTILEVEL, WINDOW_COVERING)

# Window Covering parameters with an even key are the "no position" variants
# (zwave_js_server.const.command_class.window_covering.NO_POSITION_PROPERTY_KEYS).
NO_POSITION_KEYS = frozenset(range(0, 24, 2))

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
    if ref.command_class == WINDOW_COVERING and ref.property_key in NO_POSITION_KEYS:
        return None
    return ref


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


def partition(members: list[Member]) -> tuple[list[list[Member]], list[Member]]:
    """Split members into multicast batches (2+ members) and one-by-one singles."""
    groups: dict[tuple, list[Member]] = {}
    singles: list[Member] = []
    for member in members:
        key = multicast_key(member)
        if key is None:
            singles.append(member)
        else:
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
