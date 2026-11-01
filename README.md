# Z-Wave Multicast Group

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub Release](https://img.shields.io/github/v/release/ljmerza/zwave-multicast-group)](https://github.com/ljmerza/zwave-multicast-group/releases)
[![Validate](https://github.com/ljmerza/zwave-multicast-group/actions/workflows/validate.yml/badge.svg)](https://github.com/ljmerza/zwave-multicast-group/actions/workflows/validate.yml)
[![Test](https://github.com/ljmerza/zwave-multicast-group/actions/workflows/test.yml/badge.svg)](https://github.com/ljmerza/zwave-multicast-group/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/ljmerza/zwave-multicast-group)](LICENSE)

A Home Assistant helper that groups Z-Wave JS covers, lights, switches or fans into one
entity and commands them with a **single Z-Wave multicast frame**, so they act at the same
moment.

## Why

A normal group calls each member separately. The Z-Wave controller then sends one
acknowledged frame per device, waiting for each acknowledgement before the next, so the
members start about a second apart. On a pair of roller shades, or a row of lights,
that's a visible stagger.

Home Assistant doesn't multicast group calls yet (see
[feature-requests #3976](https://github.com/orgs/home-assistant/discussions/3976) and
[architecture #1308](https://github.com/home-assistant/architecture/discussions/1308)).
Until it does, this helper gives you a group entity that does.

## What it does

One helper entry is one group of one type, like Home Assistant's own group helper.

| Group | Members | Multicast | Not offered by the group |
|---|---|---|---|
| Cover | Z-Wave JS covers that report a position (Multilevel Switch, Window Covering) | open, close, set position, **stop** | tilt; gates and garage doors can't be added |
| Light | Z-Wave JS lights on a Multilevel Switch (dimmers) or Binary Switch | on, off, brightness, transition | color, color temperature, effects |
| Switch | Z-Wave JS Binary Switches | on, off | |
| Fan | Z-Wave JS Multilevel Switch fans | on, off, percentage | preset modes |

For every group type:

- **One multicast per compatible batch**. Members are batched when they are on the same
  Z-Wave JS controller, use the same value (command class, endpoint, property key,
  range), are **non-secure**, and are classic Z-Wave, not Long Range. Everything else
  gets the normal per-device command. S0 can't multicast, S2 multicast falls back to
  per-node follow-ups with no sync gain, and Long Range nodes can't share a multicast
  with mesh nodes.
- **Retry, then fallback**: if a multicast fails, it is retried once straight away (the
  first multicast after a restart has been seen to fail with ZW0204 while the next one
  lands). If the retry fails too, the normal command goes to each member.
- **Delivery check**: multicast frames are not acknowledged, and Z-Wave JS marks every
  member at the target as soon as the frame is sent. After the travel time (covers) or
  verify delay (everything else), the group asks each multicast member for its real
  value and re-sends the normal command to any that didn't get there.
- **State** mirrors the members like Home Assistant's group helpers: on if any member
  is on, light brightness is the mean of the members that are on, fan percentage and
  cover position are the mean of all members.

What each command sends mirrors Home Assistant's own zwave_js entities:

- **Cover**: position 0-100 % scaled onto the value's range, to `targetValue`. The group
  shows opening/closing for the travel time, because members already read "arrived".
  **Stop** sets the stop value to false (Window Covering `levelChangeUp`; a Multilevel
  Switch cover's `Open`/`Up`/`On`), then sends the normal stop to each member as a
  backstop, since a stop has no target to check.
  Home Assistant's own Window Covering open/close uses `levelChangeUp/Down`; this group
  multicasts `targetValue` instead.
- **Light (dimmer)**: on = 255 (the device restores its previous level), off = 0,
  brightness 0-255 → 1-99. A transition is passed as `transitionDuration` when every
  member of the batch supports it, otherwise the batch goes without one. The verify
  waits for the transition on top of the verify delay.
- **Light (Binary Switch)**: on/off is `true`/`false`. These are color lights whose
  brightness lives in the color channels, so a brightness goes to them one by one.
- **Switch**: `true`/`false`.
- **Fan**: on = 255 (previous speed), off = 0, percentage → `ceil(% × 99 / 100)`. A fan that
  Home Assistant drives with a per-device speed table (`percentage_step` other than 1)
  gets percentages one by one, because the shared mapping would pick a different speed.

### Not supported, on purpose

- **Locks, sirens, garage doors / barriers, gates**: security-relevant. An unacknowledged
  frame that some members miss, or a fallback that unlocks/opens one at a time, is not a
  trade worth one second of sync. Gate and garage covers are refused by the set-up form.
- **Climate, thermostat fan modes, humidifiers**: stateful mode values with no visible
  stagger to fix.
- **Configuration parameters, indicators, Basic CC and Color Switch-only lights,
  config/diagnostic entities**: not group material, or no `targetValue` that means the
  same thing on every device.
- **Cover tilt**: Home Assistant finds tilt through three different device-specific
  paths (Window Covering slat angles on a 0-50-99 scale, a second Multilevel Switch
  endpoint, a Fibaro proprietary value), so there is no one value to batch. Tilt-only
  Window Covering entities can't be added to a cover group.
- **Light color**: members can have different color channels, and Home Assistant's
  Binary Switch color lights track their last color in memory. Set color on the members.

## Install

Needs Home Assistant 2026.10 or newer with the Z-Wave JS integration set up. Tested on
Home Assistant 2026.10.4 with zwave-js-server-python 0.73.1.

### HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ljmerza&repository=zwave-multicast-group&category=integration)

1. Click the button above, or open HACS and search for **Z-Wave Multicast Group**.
   If the search finds nothing, add it as a custom repository first: HACS → ⋮ →
   **Custom repositories** → `https://github.com/ljmerza/zwave-multicast-group`, type
   **Integration**.
2. Click **Download**.
3. Restart Home Assistant.

### Manual

1. Download the source zip of the
   [latest release](https://github.com/ljmerza/zwave-multicast-group/releases/latest).
2. Copy `custom_components/zwave_multicast_group` into the `custom_components/` folder of
   your Home Assistant config (create it if it doesn't exist).
3. Restart Home Assistant.

## Set up

Settings → Devices & services → Helpers → Create helper → **Z-Wave Multicast Group**, then
pick **Cover group**, **Fan group**, **Light group** or **Switch group**:

- **Name**: becomes the entity, e.g. `cover.bonus_room_blinds`.
- **Members**: two or more Z-Wave JS entities of that type.
- **Travel time** (covers): seconds the slowest member needs end to end (default 60).
- **Verify delay** (lights, switches, fans): seconds before the delivery check (default 5).

Groups created by 0.1.x are migrated to cover groups on first start.

## Attributes

| Attribute | Meaning |
|---|---|
| `entity_id` | Members |
| `last_command` | e.g. `open`, `set_position 50`, `stop`, `turn_on brightness 128`, `set_percentage 66` |
| `last_delivery` | e.g. `multicast 2, one by one 0`; notes a retry, a failed multicast, a stop backstop |
| `last_verify` | `pending`, `ok`, or `re-sent to <members>` |
| `multicast_failures` | Failed multicast attempts (a retry counts too) since Home Assistant started |

## Development

```bash
# pure helpers only
uv run --no-project --with pytest pytest -q --noconftest tests/test_members.py tests/test_commands.py
# everything, against a real in-memory Home Assistant (plugin pins homeassistant==2026.10.4)
uv run --no-project --python 3.14 \
  --with pytest-homeassistant-custom-component==0.13.375 \
  --with zwave-js-server-python==0.73.1 pytest -q
```
