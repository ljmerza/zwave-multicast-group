# zwave-multicast-group

Home Assistant custom integration (domain `zwave_multicast_group`, a helper). Groups Z-Wave JS
covers, lights, switches or fans into one entity that commands them with one `zwave_js`
multicast frame so they act together. One config entry = one group of one domain
(`options["group_type"]`). Built 2026-10-31 for the Bonus Room roller shades (nodes 142/143); see
`../ai/hvac/automations.md` §7c for how the house uses it.

## Layout

- `members.py`, `commands.py`, `const.py`: pure logic. **No Home Assistant imports**, so keep
  it that way. `members.py` parses unique IDs, filters which values each domain accepts and
  batches members; `commands.py` maps a group command to each member's Z-Wave value (or
  `ONE_BY_ONE`), and decides from a member's state whether the command arrived.
- `entity.py`: the shared machinery every platform inherits. Resolve members → multicast
  per batch (one immediate retry) → one-by-one for the rest → settle time → poll →
  re-send one by one to members that missed. Stop: multicast, then the normal stop as a
  backstop (no target to verify).
- `cover.py`, `light.py`, `switch.py`, `fan.py`: state mirroring, building a `Command`, and the
  normal service that is the one-by-one equivalent (`_one_by_one_call`).
- `config_flow.py`: `SchemaConfigFlowHandler` helper flow with a group-type menu, like HA's
  group helper. HA 2026.10 validates flow schemas with `probatio` (a voluptuous fork); the
  import falls back to voluptuous on older HA.
- `__init__.py`: forwards to the entry's one platform; `async_migrate_entry` turns 1.1
  entries (0.1.x, no `group_type`) into 1.2 cover groups.
- Reaches into `zwave_js` via its config entry `runtime_data.client` (not a public API).
  Re-check on HA upgrades. `tests/test_parity.py` checks the copied conversions against
  HA's own code.

## Rules learned the hard way

- After a multicast, Z-Wave JS marks members at the target **immediately**. Never use member
  state to decide "did it move" until after the travel time / verify delay plus a poll.
- Only non-secure, classic (not Long Range) members are batched. S0 can't multicast, and S2
  gains nothing.
- HA's own Window Covering open/close uses `levelChangeUp/Down` (start level change); this
  integration multicasts `targetValue` instead. That was the only path tested live.
- The first multicast after an HA restart failed live with ZW0204 ("did not acknowledge";
  multicast is unacknowledged, likely zwave-js #7198) and the next one landed. Hence one
  immediate retry before the one-by-one fallback, which loses the sync.
- Value mapping must mirror HA's zwave_js platforms (`light.py`, `fan.py`, `cover.py` in
  `projects/hass/core`), including 255 = "previous level" for Multilevel Switch on.
- Don't add `zwave_js` to `dependencies` or `after_dependencies` in the manifest: a hard
  dependency once cancelled zwave_js's own setup during boot.
- Never group locks, sirens, barriers/garage doors, gates, climate or config parameters
  (see README "Not supported, on purpose").

## Tests

```bash
uv run --no-project --python 3.14 \
  --with pytest-homeassistant-custom-component==0.13.375 \
  --with zwave-js-server-python==0.73.1 pytest -q -p no:cacheprovider -W ignore::RuntimeWarning
uv run --no-project --with ruff ruff check .
```

Pure modules alone: `uv run --no-project --with pytest pytest -q --noconftest
tests/test_members.py tests/test_commands.py`.

The plugin pins `homeassistant` (0.13.375 = 2026.10.4), so bump it with HA. Never
`pip install --user` on z2; use `uv run`.

## Deploy

Bind-mounted into the `hass` container by `../../docker-compose.home.yml`:
`projects/hass/zwave-multicast-group/custom_components/zwave_multicast_group` →
`/config/custom_components/zwave_multicast_group`. Changes need an HA restart.
