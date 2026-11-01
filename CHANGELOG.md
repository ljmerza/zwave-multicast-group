# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The version in
`custom_components/zwave_multicast_group/manifest.json` matches the release tag (without the `v`).

## [0.2.0] - 2026-10-31

First release. 0.1.x were never published.

### Added

- Light, switch and fan groups next to covers. Pick the type from a menu when creating the
  helper; one helper entry is one group of one type. Lights multicast on, off, brightness and
  transition (Multilevel Switch dimmers) or on/off (Binary Switch), switches on/off, fans on, off
  and percentage.
- Stop is a multicast too, with the normal per-member stop sent right after as a backstop.
- One immediate retry when a multicast fails, before falling back to one command per member.
  The first multicast after a Home Assistant restart failed once in live testing with ZW0204
  ("did not acknowledge"), and the next one landed.
- `verify_delay` option for lights, switches and fans (covers keep `travel_time`).
- Config entry migration 1.1 → 1.2: existing groups become cover groups.
- Brand icon (`brand/icon.png`, `brand/icon@2x.png`), shown by Home Assistant 2026.3 and newer.
- `categories: ["helpers"]` in the manifest.
- HACS and manual install instructions, badges, and a bug report template.

### Changed

- CI uses `actions/checkout@v7` and `astral-sh/setup-uv@v10.3.3` (Node 24), and the Validate
  workflow can be started by hand.

### Not supported, on purpose

- Locks, sirens, barriers/garage doors, gates, climate and config parameters. See the README.

## [0.1.1] - 2026-10-31

### Fixed

- No longer declares `zwave_js` as a manifest dependency. Waiting on its setup from inside this
  integration's setup could leave Z-Wave JS in `setup_error` when Home Assistant cancelled the
  request during boot. Members are resolved when a command runs, so the dependency was never
  needed.

## [0.1.0] - 2026-10-31

### Added

- Z-Wave Multicast Group helper: a cover group that moves Z-Wave JS covers with one
  `targetValue` multicast so they start together.
- Opening and closing state tracked for a configured travel time.
- Delivery check after the travel time that re-sends the normal command to members that missed
  the multicast.
- Fallback to one command per member when the multicast fails.

[0.2.0]: https://github.com/ljmerza/zwave-multicast-group/releases/tag/v0.2.0
[0.1.1]: https://github.com/ljmerza/zwave-multicast-group/commit/44d6679
[0.1.0]: https://github.com/ljmerza/zwave-multicast-group/commit/48a952c
