"""Unit tests for the pure member/batching helpers (no Home Assistant needed).

Run: uv run --with pytest pytest -q
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

# Load members.py directly so the package __init__ (which imports Home Assistant) isn't run.
_PATH = Path(__file__).parents[1] / "custom_components" / "zwave_multicast_group" / "members.py"
_spec = importlib.util.spec_from_file_location("zmg_members", _PATH)
members = importlib.util.module_from_spec(_spec)
sys.modules["zmg_members"] = members  # dataclasses look the module up while building
_spec.loader.exec_module(members)

Member = members.Member


def _member(entity_id, node, *, entry="zw", cc=106, key=13, security=-1, protocol=0, lo=0, hi=99):
    ref = members.ValueRef(f"{node}-{cc}-0-currentValue-{key}", node, cc, 0, "currentValue", key)
    return Member(entity_id, entry, ref, lo, hi, security, protocol)


def test_parse_unique_id_window_covering():
    ref = members.parse_unique_id("4170970308.143-106-0-currentValue-13")
    assert ref == members.ValueRef("143-106-0-currentValue-13", 143, 106, 0, "currentValue", 13)


def test_parse_unique_id_multilevel_switch_no_key():
    ref = members.parse_unique_id("4170970308.12-38-0-currentValue")
    assert ref.node_id == 12 and ref.command_class == 38 and ref.property_key is None


def test_parse_unique_id_rejects_non_value_ids():
    assert members.parse_unique_id("4170970308.143.node_status") is None
    assert members.parse_unique_id("no-dot-here") is None
    assert members.parse_value_id("a-b-c-d") is None


def test_position_value_filters():
    pv = members.position_value
    assert pv(members.parse_unique_id("1.143-106-0-currentValue-13")) is not None  # outbound bottom
    assert pv(members.parse_unique_id("1.143-106-0-currentValue-12")) is None  # no-position key
    assert pv(members.parse_unique_id("1.143-106-0-targetValue-13")) is None  # not the current value
    assert pv(members.parse_unique_id("1.143-37-0-currentValue")) is None  # binary switch CC
    assert pv(members.parse_unique_id("1.12-38-0-currentValue")) is not None
    assert pv(None) is None


def test_target_value_data():
    ref = members.parse_unique_id("1.143-106-0-currentValue-13")
    assert members.target_value_data(ref) == {
        "commandClass": 106,
        "endpoint": 0,
        "property": "targetValue",
        "propertyKey": 13,
    }
    ref = members.parse_unique_id("1.12-38-0-currentValue")
    assert "propertyKey" not in members.target_value_data(ref)


def test_partition_bonus_room_pair_is_one_batch():
    left, right = _member("cover.left", 143), _member("cover.right", 142)
    batches, singles = members.partition([left, right])
    assert batches == [[left, right]] and singles == []


def test_partition_excludes_secure_long_range_and_unknown_security():
    plain_a, plain_b = _member("cover.a", 1), _member("cover.b", 2)
    s2 = _member("cover.s2", 3, security=1)
    s0 = _member("cover.s0", 4, security=7)
    unknown = _member("cover.unknown", 5, security=None)
    lr = _member("cover.lr", 6, protocol=1)
    batches, singles = members.partition([plain_a, s2, plain_b, s0, unknown, lr])
    assert batches == [[plain_a, plain_b]]
    assert {m.entity_id for m in singles} == {"cover.s2", "cover.s0", "cover.unknown", "cover.lr"}


def test_partition_splits_incompatible_values_and_controllers():
    a, b = _member("cover.a", 1), _member("cover.b", 2)
    other_key = _member("cover.c", 3, key=15)
    other_cc_1, other_cc_2 = _member("cover.d", 4, cc=38, key=None), _member("cover.e", 5, cc=38, key=None)
    other_ctrl = _member("cover.f", 6, entry="zw2")
    other_range = _member("cover.g", 7, hi=100)
    batches, singles = members.partition([a, other_key, b, other_cc_1, other_ctrl, other_cc_2, other_range])
    assert [[m.entity_id for m in batch] for batch in batches] == [
        ["cover.a", "cover.b"],
        ["cover.d", "cover.e"],
    ]
    assert {m.entity_id for m in singles} == {"cover.c", "cover.f", "cover.g"}


def test_single_compatible_member_goes_one_by_one():
    batches, singles = members.partition([_member("cover.a", 1)])
    assert batches == [] and [m.entity_id for m in singles] == ["cover.a"]


def test_percent_conversion_matches_ha_zwave_js():
    assert members.percent_to_zwave(100, 0, 99) == 99
    assert members.percent_to_zwave(0, 0, 99) == 0
    assert members.percent_to_zwave(50, 0, 99) == 50
    assert members.percent_to_zwave(150, 0, 99) == 99
    assert members.percent_to_zwave(-5, 0, 99) == 0
    assert members.zwave_to_percent(99, 0, 99) == 100
    assert members.zwave_to_percent(6, 0, 99) == 6
    assert members.zwave_to_percent(5, 5, 5) == 0
