# HACS default submission: zwave-multicast-group

Working notes for getting `ljmerza/zwave-multicast-group` into the HACS default list. Delete this
file once the hacs/default PR is merged.

Sources, read 2026-10-31:
[publish/start](https://hacs.xyz/docs/publish/start/),
[publish/include](https://hacs.xyz/docs/publish/include/),
[publish/integration](https://hacs.xyz/docs/publish/integration/),
[publish/action](https://hacs.xyz/docs/publish/action/),
the hacs/default [PR template](https://github.com/hacs/default/blob/master/.github/PULL_REQUEST_TEMPLATE.md)
and [checks workflow](https://github.com/hacs/default/blob/master/.github/workflows/checks.yml),
the HACS validators in `hacs/integration` (`custom_components/hacs/validate/*.py`),
HA's [brand images](https://developers.home-assistant.io/docs/core/integration/brand_images/) page,
and the [home-assistant/brands](https://github.com/home-assistant/brands) image spec.

## Requirement checklist

Status: **met** (already true), **fixed** (fixed on branch `chore/hacs-default`), **owner**
(needs an outward step, see below).

| # | Requirement | Where it's checked | Status |
|---|---|---|---|
| 1 | Public GitHub repo | general | met |
| 2 | Repo description set | HACS `description` check | met. It says "a cover group". Update it if lights, switches or fans land before the release. |
| 3 | Repo has topics | HACS `topics` check | met. Set after the first CI run, which failed on this. |
| 4 | Issues enabled | HACS `issues` check | met |
| 5 | Not archived | HACS `archived` check | met |
| 6 | OSI license GitHub can identify | HACS `license` check | met (MIT, detected as `mit`) |
| 7 | README present | HACS `information` check | met. HACS and manual install sections added. |
| 8 | `hacs.json` in repo root with `name` | HACS `hacsjson` check | met. Keys are `name`, `render_readme`, `homeassistant: 2026.10.0`. Left unchanged. |
| 9 | One integration under `custom_components/<domain>/` | integration structure | met |
| 10 | `manifest.json` has `domain`, `documentation`, `issue_tracker`, `codeowners`, `name`, `version` | HACS `integration_manifest` check | met |
| 11 | Manifest `categories` (warning only) | HACS `integration_categories` check | fixed. `["helpers"]`, same as core `switch_as_x`. |
| 12 | Brand assets, at least `brand/icon.png` in the integration dir | HACS `brands` check | fixed. The icons were added locally, then trimmed (see below). |
| 13 | Brand images to spec: PNG, icon 256x256, `icon@2x.png` 512x512, transparency preferred, trimmed | brands spec | fixed. Logo and `dark_` files are optional (HA falls back to the icon), so none were added. |
| 14 | Domain doesn't clash with a core integration | hacs/default `core_domain_conflict` | met. There is no `homeassistant/components/zwave_multicast_group` in core. |
| 15 | Doesn't override or beta-test a core integration | include rules | met |
| 16 | HACS action in the repo and passing with no `ignore` | include rules, PR template | owner. The workflow is in place and passes locally. It needs a green run on GitHub. |
| 17 | Hassfest action in the repo and passing | include rules, PR template, hacs/default `hassfest` | met. Passed on GitHub and locally on this branch. |
| 18 | At least one full GitHub release, published after the actions pass | hacs/default `releases` check, PR template | owner |
| 19 | Submitter owns the repo | hacs/default `owner` check | met (`ljmerza`) |
| 20 | PR from a personal fork, on a new branch off `master`, editable | include rules, hacs/default `editable` check | owner |
| 21 | Entry added to `integration` in sorted order (`str.casefold`) | hacs/default lint `sorted` / `jq` | owner. It goes right after `ljmerza/utilities_email_tracker`. |
| 22 | `country` key if limited to some countries | include rules | n/a. Works anywhere. |
| 23 | PR template filled in, no review requests | PR template | owner. The body is below. |

### What the first CI run reported, and what happened to each

Run 41263646667 (Validate on `48a952c`):

- `topics` failed. Fixed on GitHub since then.
- `brands` failed because there was no `brand/icon.png`. Fixed. The brand dir is committed and trimmed.
- Warning "The integration manifest has no categories". Fixed with `categories: ["helpers"]`.
- Warning "Node.js 20 is deprecated ... actions/checkout@v4, astral-sh/setup-uv@v6". Fixed with
  `actions/checkout@v7` and `astral-sh/setup-uv@v10.3.3`. setup-uv stopped publishing major tags at
  v8, so it's pinned to a full version.
- The Test workflow also warns that setup-uv's cache glob matched no lockfile. It's harmless, so I
  left it.

### Brand icon

`icon.png` (256x256) and `icon@2x.png` (512x512) were already the right size, RGBA, with transparent
corners, in `custom_components/zwave_multicast_group/brand/`. That location is read by HA 2026.3+,
and `hacs.json` already needs 2026.10. The one gap was trimming. The generator drew the navy tile at
8..248 on a 256 grid, so there was a transparent border of about 3% around it, and the brands spec
asks for no transparent spacing around the subject. I regenerated both with the same design, scaled
so the tile reaches the edges. The rounded corners stay transparent.

The script is a copy of the original `make_icon.py` with every coordinate mapped
`(v - 8) * 256 / 240`. It isn't committed. Re-render with
`uv run make_icon_trimmed.py custom_components/zwave_multicast_group/brand`.

## Validation run on this branch

- **hassfest**:
  `docker run --rm -v "$PWD":/github/workspace:ro ghcr.io/home-assistant/hassfest:latest` gives
  `Integrations: 1`, `Invalid integrations: 0`, and no warnings.
- **HACS**: the HACS action reads the repo through the GitHub API at a remote ref, so it can't check
  unpushed commits. I ran HACS's own schemas instead (`HACS_MANIFEST_JSON_SCHEMA`,
  `INTEGRATION_MANIFEST_JSON_SCHEMA`, `INTEGRATION_MANIFEST_CATEGORIES_SCHEMA`, taken from
  `hacs/integration` `custom_components/hacs/utils/validate.py`) plus the `brands` and `information`
  file checks, against this branch. All pass. Run on `48a952c`, the same script reproduces the CI
  result: `brands` fails and there's no categories warning. The checks that depend on GitHub settings
  (topics, description, issues, license, archived) were read with `gh repo view` and are all fine.
- **Tests**: `ruff check .` is clean. The pytest suite passes on HA 2026.10.4. No Python changed.

## Owner steps, in order

1. **Merge the branches.** Merge `chore/hacs-default` into `main`, and `feat/multidomain` too if it
   should go in the first public release.
2. **Pick the version.** `manifest.json` says `0.1.1`, and that version was never released. If
   multidomain is in, bump `version` to `0.2.0`. Either way, rename `## [Unreleased]` in
   `CHANGELOG.md` to `## [X.Y.Z] - <date>` and point its link at the tag.
3. **Optional:** update the GitHub repo description if it no longer says only "cover group".
4. **Push `main`.**
5. **Confirm Actions are green on that push.** You need Validate (both the `HACS` and `Hassfest` jobs)
   and Test. The HACS job log must show no failed checks, and the workflow has no `ignore` key. If it ran
   before the push finished, re-run it from the Actions tab (Run workflow, enabled by
   `workflow_dispatch`). Copy the two **job** URLs (`.../actions/runs/<run>/job/<job>`) for the PR.
6. **Create the GitHub release.** Tag `vX.Y.Z` on that commit, title `vX.Y.Z`, notes from the
   CHANGELOG section. It must be a real release, not just a tag. This has to come after step 5,
   because the hacs/default check validates the **latest release**, so that release must contain
   `brand/` and the categories. The brands Marketplace-icon sync also reads the latest release.
7. **Fork `hacs/default`** from your personal account (an org fork makes the PR non-editable). Create
   a branch off `master`, for example `add-zwave-multicast-group`.
8. **Edit `integration`.** Add `"ljmerza/zwave-multicast-group",` on a new line right after
   `"ljmerza/utilities_email_tracker",` (before `"lloydw/hass-spanet",`). That's the only change.
9. **Open the PR** against `hacs/default:master` with the title and body below. Don't request
   reviews, don't comment, and don't merge `master` into it unless a maintainer asks.
10. **After it merges** (it can take up to 8 hours to appear), change the README badge from
    `HACS-Custom` to `HACS-Default` and delete this file.

## hacs/default PR

Title (same format as your merged #11022 / #8529):

```text
Adds new integration [ljmerza/zwave-multicast-group]
```

Body. Fill in the three links, and only leave a box ticked if it's true:

```markdown
## Checklist

<!-- Do not open a pull request before you have completed all these, it will be closed. -->

- [x] I've read the [publishing documentation](https://hacs.xyz/docs/publish/start).
- [x] I've added the [HACS action](https://hacs.xyz/docs/publish/action) to my repository.
- [x] (For integrations only) I've added the [hassfest action](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) to my repository.
- [x] The actions are passing without any disabled checks in my repository.
- [x] I've added a link to the action run on my repository below in the links section.
- [x] I've created a new release of the repository after the validation actions were run successfully.

## Links

Link to current release: <https://github.com/ljmerza/zwave-multicast-group/releases/tag/vX.Y.Z>
Link to successful HACS action (without the `ignore` key): <https://github.com/ljmerza/zwave-multicast-group/actions/runs/RUN_ID/job/HACS_JOB_ID>
Link to successful hassfest action (if integration): <https://github.com/ljmerza/zwave-multicast-group/actions/runs/RUN_ID/job/HASSFEST_JOB_ID>
```

### Release notes for vX.Y.Z (draft)

```markdown
First public release.

- Z-Wave Multicast Group helper. It moves Z-Wave JS covers with one `targetValue` multicast so they start together, tracks opening and closing for the travel time, then checks each member's real position and re-sends to any that missed the frame
- Falls back to one command per member when the multicast fails
- Brand icon, shown by Home Assistant 2026.3 and newer
- No longer depends on `zwave_js` at setup, which could leave Z-Wave JS in `setup_error` during boot

Needs Home Assistant 2026.10 or newer. Tested on 2026.10.4.
```

Add the lights, switches and fans line if multidomain is in.
