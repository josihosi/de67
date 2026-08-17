# Promoting de67-lab into de67

`de67-lab` is the writable method-development repository. `de67` is the release-facing repository.
A release promotion carries accepted lab behavior into the release repository while preserving the
release repository's own history, tags, identity, and release review. It is a merge and release
operation, not a force-push or directory replacement.

The default is a full lab product takeover: when the same tracked package path differs, the reviewed
lab candidate wins. Preserve release-side implementation only when the owner explicitly names it or
evidence shows that the lab never absorbed a still-required release fix. Do not keep stale release
code merely because it differs.

This file is human/agent release guidance. It has no DE67 runtime authority and must not be copied
into project `.de67/` state.

## Surfaces that must remain intact

- The complete `de67` Git history, including prior release merge commits and tags such as `v0.1.0`.
- The `de67` remote and branch protections. Routine lab automation continues to push only to the
  lab remote; promotion to `de67` is an explicit owner-authorized operation.
- `LICENSE`, attribution, public README language, router identity, phase command names, and
  `agents/openai.yaml` metadata unless the release change explicitly and visibly updates them.
- The three-phase boundary: a release must not make one phase silently invoke another.
- The publishable package boundary: repository source, tests, optional integrations, references,
  and assets may ship; lab runtime state, Git hooks, local remotes, installed-skill copies,
  coordinator runs, SQLite files, caches, and machine-specific paths may not.
- Optional integrations remain optional. Core tests and ordinary supervision must pass with each
  integration absent, unconfigured, and broken.
- Release-facing version notes and the new release tag are created in `de67`, not retroactively in
  lab history.

## Current repository relationship

The repositories descend from common history but can contain unique commits. The release side owns
its previous checkpoint and release merges; the lab side owns later accepted method evolution.
Preserve both sides by merging the reviewed lab commit into a release branch based on current
`de67/main`.

Never infer that this paragraph is still current. Re-run the checks below for every promotion.

## Promotion procedure

1. Establish exact inputs.

   - Require clean worktrees in both repositories or stop and account for owner-owned changes.
   - Record the lab candidate commit, current release `main`, merge base, remotes, and tags.
   - Fetch deliberately when current remote truth is required. Do not mutate either worktree merely
     to compare it.

2. Inventory both sides before merging.

   - List commits unique to lab and commits unique to release.
   - Identify release-only tracked paths and the narrow protected release surfaces below. Ordinary
     shared package paths come from the lab candidate by default.
   - Check README, `SKILL.md`, `agents/openai.yaml`, phase metadata, `LICENSE`, optional-integration
     documentation, and release tags explicitly even when Git reports no conflict.

3. Merge without rewriting release history.

   - Create a release-candidate branch from current `de67/main`.
   - Merge the exact reviewed lab candidate with a merge commit. Do not force-push lab `main` over
     release `main`, replace the release `.git` directory, or copy an unfiltered lab directory.
   - Resolve ordinary product conflicts in favor of the reviewed lab candidate. Release owns only
     its Git history/tags and explicitly reviewed public version/identity metadata.

4. Prove the publishable tree.

   - Run the skill validator when available and the complete bundled Python suite on the supported
     platforms relevant to the changes.
   - Test installation from a clean checkout, not from an existing installed skill or lab runtime.
   - Verify core operation with optional integrations absent.
   - For every promoted integration, run its focused tests plus missing-command, malformed-output,
     and removal controls.
   - Search the tracked tree for machine-specific absolute paths, secrets, runtime state, caches,
     coordinator outputs, and accidental lab remote configuration.
   - Inspect `git diff --check`, the complete candidate diff from the prior release tag, and the
     final tracked file list.

5. Prepare the release boundary.

   - Add concise release notes describing user-visible method and packaging changes, compatibility,
     optional integrations, and any migration action.
   - Confirm the intended semantic version with the owner. This file does not select a version or
     authorize publication.
   - Commit the release-specific metadata on the release-candidate branch.
   - Present the exact candidate commit, validation evidence, preserved release-only changes, and
     tag target for owner approval.

6. Publish only after explicit authorization.

   - Merge or fast-forward the reviewed release-candidate branch according to the release
     repository's current policy.
   - Create the annotated release tag on the approved commit and push only the intended release
     branch and tag.
   - Do not change lab routine-push configuration to point at `de67`.

## Required takeover report

Before publishing, report:

- lab candidate commit, release parent commit, merge base, candidate commit, and proposed tag;
- commits and tracked paths unique to each side before the merge;
- any release-only tracked path and any deliberate exception to the default lab-wins rule;
- validator and test results from a clean release candidate;
- installation proof and supported Python/Codex requirements;
- core-without-integrations proof;
- OpenClaw adapter present, absent, malformed, and live/disposable-route proof;
- remaining dirty worktrees or live services, clearly separated from the release candidate;
- confirmation that no force push, automatic checkpoint push, service restart, or installed-skill
  replacement was used to manufacture the candidate.
