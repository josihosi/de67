---
name: de67-release-packaging
description: Prepare a release of the de67 skill, including comparison with the previous release, optional integrations, and concise agent-facing documentation. Loaded through the de67 release route.
---

# de67 release packaging

Prepare a reproducible release candidate of the de67 skill. This is a maintenance route,
not a delivery phase. Do not start phase 3 or load its operating instructions merely to package it.

Read [release promotion](../RELEASE_PROMOTION.md) for repository identity, history preservation,
candidate construction, validation, and publication. Keep that procedure authoritative rather
than duplicating it here. Respect the requested checkpoint: preparation does not itself authorize
publication or changes to an active run.

## Establish what is being released

Identify the actual source checkout and host, candidate revision, previous published release/tag,
and release destination. Inspect current Git state and compare both commits and the complete tree
against the previous release. Account for dirty changes and release-only fixes explicitly. A running
Mac workspace, an installed skill, and the lab checkout can differ; establish provenance before
claiming that a candidate contains the current work. Use an isolated candidate when a live checkout
must remain active.

Use the differences and implementation evidence to update release notes, requirements, setup,
migration instructions, and explanations. Do not simply carry forward the previous README or claim
that ongoing work is proven. Follow links into implementation and tests as needed, without loading
unrelated phase instructions for background.

## Optional packages

The dashboard/hosting page and OpenClaw/Discord connection are optional integrations:

- [Dashboard setup](../integrations/dashboard/README.md) and
  [dashboard constraints](../integrations/dashboard/AGENTS.md).
- [OpenClaw/Discord setup](../integrations/openclaw_discord/README.md) and
  [adapter constraints](../integrations/openclaw_discord/AGENTS.md).

Package each integration as a separately installable artifact alongside the core skill, with its
own concise agent-facing entrypoint. Merely labeling a folder optional is insufficient. Select an
artifact format that fits the existing package and verify installation from the extracted artifact;
do not assume these are Codex marketplace plugins or introduce a new plugin framework by default.
Each package must include the code/resources it needs and clearly state any required core version.

Assume OpenAI Codex and capable models. Give the installing agent the useful facts, not a long
scripted conversation: what the integration does; software/services/accounts the user needs;
configuration or credentials the user must supply; the supported installation and configuration
commands; how to start, verify, and remove it. Separate what Codex can do from user-only account or
authorization steps. These instructions should let Codex both explain the prerequisites to an
interested user and perform the authorized setup. Keep secrets out of the artifact.

Inspect the candidate's actual integration seams before describing them. Keep core installation and
operation independent of both packages. Explain how an agent installs, configures, verifies, and
removes each on another person's machine, including dependencies and configuration inputs without
shipping local credentials, account IDs, or machine paths. Distinguish local dashboard serving from
optional network hosting. Document the shipped Discord behavior precisely; do not conflate blocker
contact with any separate direct-input route. Link supporting documentation when that distinction
matters. Validate optional-package isolation using the release-promotion procedure.

## Main README contract

Keep the main README short and use this order:

1. Two or three plain sentences explaining use: planning an idea, specifying the intended work in
   a frozen document grounded in the code, and orchestrating implementation and verification.
2. One small fenced command block, before any screenshot:

   ```text
   de67 1   plan and discuss the idea
   de67 2   inspect the code and freeze the specification
   de67 3   orchestrate implementation, testing, and repair
   ```

3. A real dashboard screenshot from the release candidate, cropped from the top through roughly
   half to two-thirds of the radar plot. Keep it legible and free of private information. Capture
   and inspect the rendered crop; do not substitute a mockup or treat it as runtime proof.
4. A compact set of descriptive links for installation, phase behavior, architecture and durable
   artifacts, optional dashboard/hosting, optional OpenClaw/Discord, troubleshooting, and release
   details. Keep required attribution and license discoverable.

The linked material primarily serves agents setting up de67 on another person's computer or
answering questions about it. Put detailed commands, prerequisites, configuration, verification,
and failure diagnosis there rather than expanding the main README. Reuse accurate existing pages;
create a focused page only where a real information gap exists. Every link must resolve to an
existing, relevant document, and every documented command must match the candidate.

Inspect the final README rendering, image crop, and links. Ask Josef to review README wording at
the release checkpoint; he wants to edit it himself after agent changes.

## Checkpoint

Present the exact candidate and previous-release baseline, meaningful changes, optional-package
boundaries, README/image result, validation evidence, and unresolved release decisions. Distinguish
completed preparation from publication. Stop at an owner-requested checkpoint; otherwise continue
within the release authorization already given, following the promotion procedure.
