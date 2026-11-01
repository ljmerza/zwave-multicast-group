# zwave-multicast-group

Home Assistant custom integration (domain `zwave_multicast_group`, a helper). Groups Z-Wave JS
covers into one cover entity that moves them with one `zwave_js` multicast frame so they start
together. Built 2026-10-31 for the Bonus Room roller shades (nodes 142/143); see
`../ai/hvac/automations.md` §7c for how the house uses it.

## Layout

- `custom_components/zwave_multicast_group/members.py`: pure logic (unique-id parsing,
  batching, % ↔ Z-Wave conversion). **No Home Assistant imports**, so keep it that way.
- `cover.py`: the entity. Multicast → travel window (opening/closing) → poll real positions →
  re-send one by one to members that missed. Falls back to one-by-one when the multicast fails.
- `config_flow.py`: `SchemaConfigFlowHandler` helper flow. HA 2026.10 validates flow schemas
  with `probatio` (a voluptuous fork); the import falls back to voluptuous on older HA.
- Reaches into `zwave_js` via its config entry `runtime_data.client` (not a public API).
  Re-check on HA upgrades.

## Rules learned the hard way

- After a multicast, Z-Wave JS marks members at the target **immediately**. Never use member
  state to decide "did it move" until after the travel time plus a poll.
- Only non-secure, classic (not Long Range) members are batched. S0 can't multicast, and S2
  gains nothing.
- HA's own Window Covering open/close uses `levelChangeUp/Down` (start level change); this
  integration multicasts `targetValue` instead. That was the only path tested live.

## Tests

```bash
uv run --no-project --python 3.14 \
  --with pytest-homeassistant-custom-component==0.13.375 \
  --with zwave-js-server-python==0.73.1 pytest -q -p no:cacheprovider
```

The plugin pins `homeassistant` (0.13.375 = 2026.10.4), so bump it with HA. Never
`pip install --user` on z2; use `uv run`.

## Deploy

Bind-mounted into the `hass` container by `../../docker-compose.home.yml`:
`projects/hass/zwave-multicast-group/custom_components/zwave_multicast_group` →
`/config/custom_components/zwave_multicast_group`. Changes need an HA restart.
