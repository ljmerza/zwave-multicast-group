# Z-Wave Multicast Group

A Home Assistant helper that groups Z-Wave JS covers into one cover entity and moves them
with a **single Z-Wave multicast frame**, so they start at the same moment.

## Why

A normal cover group calls each member separately. The Z-Wave controller then sends one
acknowledged frame per device, waiting for each acknowledgement before the next, so the
members start about a second apart. On a pair of roller shades that's a visible stagger.

Home Assistant doesn't multicast group calls yet (see
[feature-requests #3976](https://github.com/orgs/home-assistant/discussions/3976) and
[architecture #1308](https://github.com/home-assistant/architecture/discussions/1308)).
Until it does, this helper gives you a group entity that does.

## What it does

- **Open / close / set position**: one `targetValue` multicast to every compatible member.
- **Opening / closing state**: shown for the configured travel time. After a multicast,
  Z-Wave JS marks members at the target immediately, so the group tracks travel itself.
  Toggling mid-travel stops the covers, like a normal group.
- **Stop**: sent to each member normally. A stop doesn't need to be in sync.
- **Delivery check**: multicast frames are not acknowledged. After the travel time the
  group asks each multicast member for its real position and re-sends the normal command
  to any that are not where they should be.
- **Fallback**: if the multicast itself fails, the normal command goes to each member.

Members are multicast together only when they are on the same Z-Wave JS controller,
use the same position value (command class, endpoint, property key, range), are
**non-secure**, and are classic Z-Wave, not Long Range. Everything else gets the
normal per-device command. S0 can't multicast, S2 multicast falls back to per-node
follow-ups with no sync gain, and Long Range nodes can't share a multicast with mesh nodes.

Supported members: Z-Wave JS covers that report a position (Multilevel Switch and
Window Covering command classes). Tilt is not supported yet.

## Install

HACS → custom repository → `https://github.com/ljmerza/zwave-multicast-group` (Integration),
or copy `custom_components/zwave_multicast_group` into your config's `custom_components/`.
Restart Home Assistant.

Tested on Home Assistant 2026.10.4 with zwave-js-server-python 0.73.1.

## Set up

Settings → Devices & services → Helpers → Create helper → **Z-Wave Multicast Group**:

- **Name**: becomes the entity, e.g. `cover.bonus_room_blinds`.
- **Members**: two or more Z-Wave JS covers.
- **Travel time**: seconds the slowest member needs end to end (default 60).

## Attributes

| Attribute | Meaning |
|---|---|
| `entity_id` | Members |
| `last_command` | `open`, `close`, `set_position N`, `stop` |
| `last_delivery` | e.g. `multicast 2, one by one 0`; notes a failed multicast |
| `last_verify` | `pending`, `ok`, or `re-sent to <members>` |
| `multicast_failures` | Failed multicasts since Home Assistant started |

## Development

```bash
# pure helpers only
uv run --no-project --with pytest pytest -q tests/test_members.py
# everything, against a real in-memory Home Assistant (plugin pins homeassistant==2026.10.4)
uv run --no-project --python 3.14 \
  --with pytest-homeassistant-custom-component==0.13.375 \
  --with zwave-js-server-python==0.73.1 pytest -q
```
