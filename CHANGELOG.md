# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). The version in
`custom_components/zwave_multicast_group/manifest.json` matches the release tag (without the `v`).

## [Unreleased]

### Added

- Brand icon (`brand/icon.png`, `brand/icon@2x.png`), shown by Home Assistant 2026.3 and newer.
- `categories: ["helpers"]` in the manifest.
- HACS and manual install instructions, badges, and a bug report template.

### Changed

- CI uses `actions/checkout@v7` and `astral-sh/setup-uv@v10.3.3` (Node 24), and the Validate
  workflow can be started by hand.

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

[Unreleased]: https://github.com/ljmerza/zwave-multicast-group/commits/main
[0.1.1]: https://github.com/ljmerza/zwave-multicast-group/commit/44d6679
[0.1.0]: https://github.com/ljmerza/zwave-multicast-group/commit/48a952c
