"""Unit tests for the pure command helpers (no Home Assistant needed).

Run: uv run --no-project --with pytest pytest -q tests/test_commands.py
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

# Load the integration's pure modules under a stand-in package, so the real package
# __init__ (which imports Home Assistant) isn't run.
_PKG = Path(__file__).parents[1] / "custom_components" / "zwave_multicast_group"
_pkg = types.ModuleType("zmg_pure")
_pkg.__path__ = [str(_PKG)]
sys.modules.setdefault("zmg_pure", _pkg)
commands = importlib.import_module("zmg_pure.commands")
members = importlib.import_module("zmg_pure.members")

Command = commands.Command
ONE_BY_ONE = commands.ONE_BY_ONE


def _member(entity_id, node, cc, *, key=None, mapped=False, transition=False, stop=None, lo=0, hi=99):
    prop_suffix = f"-{key}" if key is not None else ""
    ref = members.ValueRef(f"{node}-{cc}-0-currentValue{prop_suffix}", node, cc, 0, "currentValue", key)
    return members.Member(
        entity_id, "zw", ref, lo, hi, -1, 0,
        value_mapped=mapped, supports_transition=transition, stop_property=stop,
    )


DIMMER = _member("light.a", 20, 38)
BINARY = _member("light.b", 22, 37)
PLUG = _member("switch.a", 30, 37)
FAN = _member("fan.a", 40, 38)
MAPPED_FAN = _member("fan.b", 42, 38, mapped=True)
SHADE = _member("cover.a", 143, 106, key=13, stop="levelChangeUp")


def test_light_values_mirror_ha_zwave_js():
    on = Command("light", "turn_on")
    assert commands.zwave_value(on, DIMMER) == 255
    assert commands.zwave_value(on, BINARY) is True
    dim = Command("light", "turn_on", level=128)
    assert commands.zwave_value(dim, DIMMER) == 50
    assert commands.zwave_value(dim, BINARY) is ONE_BY_ONE
    off = Command("light", "turn_off", on=False)
    assert commands.zwave_value(off, DIMMER) == 0
    assert commands.zwave_value(off, BINARY) is False


def test_switch_values():
    assert commands.zwave_value(Command("switch", "on"), PLUG) is True
    assert commands.zwave_value(Command("switch", "off", on=False), PLUG) is False


def test_fan_values():
    assert commands.zwave_value(Command("fan", "on"), FAN) == 255
    assert commands.zwave_value(Command("fan", "pct", level=66), FAN) == 66
    assert commands.zwave_value(Command("fan", "pct", level=66), MAPPED_FAN) is ONE_BY_ONE
    assert commands.zwave_value(Command("fan", "on"), MAPPED_FAN) == 255
    assert commands.zwave_value(Command("fan", "off", on=False), MAPPED_FAN) == 0


def test_cover_values_and_stop():
    assert commands.zwave_value(Command("cover", "open", level=100), SHADE) == 99
    stop = Command("cover", "stop", stop=True)
    assert commands.zwave_value(stop, SHADE) is False
    assert commands.value_data(stop, SHADE)["property"] == "levelChangeUp"
    no_stop = _member("cover.b", 9, 38)
    assert commands.zwave_value(stop, no_stop) is ONE_BY_ONE


def test_plan_splits_by_value_and_command_class():
    other_binary = _member("light.c", 23, 37)
    other_dimmer = _member("light.d", 21, 38)
    batches, singles = commands.plan(
        Command("light", "turn_off", on=False), [DIMMER, BINARY, other_dimmer, other_binary]
    )
    assert [(v, [m.entity_id for m in b]) for v, _d, b in batches] == [
        (0, ["light.a", "light.d"]),
        (False, ["light.b", "light.c"]),
    ]
    assert singles == []

    batches, singles = commands.plan(
        Command("light", "turn_on", level=10), [DIMMER, BINARY, other_dimmer, other_binary]
    )
    assert [[m.entity_id for m in b] for _v, _d, b in batches] == [["light.a", "light.d"]]
    assert {m.entity_id for m in singles} == {"light.b", "light.c"}


def test_plan_splits_stop_by_property():
    up_a = _member("cover.a", 1, 38, stop="Up")
    up_b = _member("cover.b", 2, 38, stop="Up")
    open_c = _member("cover.c", 3, 38, stop="Open")
    batches, singles = commands.plan(Command("cover", "stop", stop=True), [up_a, open_c, up_b])
    assert [(d["property"], [m.entity_id for m in b]) for _v, d, b in batches] == [
        ("Up", ["cover.a", "cover.b"])
    ]
    assert singles == [open_c]


def test_multicast_options_only_when_every_member_supports_transition():
    a = _member("light.a", 20, 38, transition=True)
    b = _member("light.b", 21, 38, transition=True)
    c = _member("light.c", 24, 38)
    assert commands.multicast_options(Command("light", "on"), [a, b]) == {
        "transitionDuration": "default"
    }
    assert commands.multicast_options(Command("light", "on", transition=2.7), [a, b]) == {
        "transitionDuration": "2s"
    }
    assert commands.multicast_options(Command("light", "on", transition=2), [a, c]) is None
    assert commands.multicast_options(Command("switch", "on"), [a, b]) is None


def test_reached():
    r = commands.reached
    assert r(Command("cover", "x", level=50), SHADE, "open", {"current_position": 51})
    assert not r(Command("cover", "x", level=50), SHADE, "open", {"current_position": 60})
    assert r(Command("switch", "on"), PLUG, "on", {})
    assert not r(Command("switch", "on"), PLUG, "off", {})
    assert r(Command("light", "on"), DIMMER, "on", {"brightness": 3})
    assert r(Command("light", "on", level=128), DIMMER, "on", {"brightness": 129})
    assert not r(Command("light", "on", level=128), DIMMER, "on", {"brightness": 255})
    assert not r(Command("light", "on", level=128), DIMMER, "on", {})
    assert r(Command("light", "off", on=False), DIMMER, "off", {})
    assert r(Command("fan", "pct", level=66), FAN, "on", {"percentage": 66})
    assert not r(Command("fan", "pct", level=66), FAN, "on", {"percentage": 33})
    assert not r(Command("fan", "pct", level=66), FAN, "unavailable", {})
    assert r(Command("cover", "stop", stop=True), SHADE, "open", {})
