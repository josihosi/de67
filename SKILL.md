---
name: de67
description: Route Codex work through de67 discussion, code-grounded specification, delivery, release packaging, or an optional alignment audit. Use when the user says `de67 1`, `de67 2`, `de67 3`, `de67 release`, or `de67 alignment audit`, invokes `$de67`, or asks Codex to install or integrate de67. Do not use for an ordinary worker assignment merely because its packet path or metadata mentions `.de67`. Route to exactly one surface and never preload unrelated instructions.
---

# de67 router

This file routes; it does not run a phase.

Match the user's command and read exactly one entrypoint:

- `de67 1`: read `de-67-1/SKILL.md` for the current-chat discussion and WEC.
- `de67 2`: read `de-67-2/SKILL.md` for code inspection and DFS authoring.
- `de67 3`: read `de-67-3/SKILL.md` for implementation, deadlines, and mutation.
- `de67 release` or an explicit request to package/release the de67 skill: read
  `release-packaging/SKILL.md` for release preparation and release-facing documentation.
- `de67 alignment audit`: read `alignment-audit/SKILL.md` for a manual, read-only review of
  agent-facing instructions, machine responses, and active workflow tests.

Open the exact selected entrypoint directly; do not inventory or read sibling phase folders for
background or completeness. These reading boundaries apply when running a phase. An explicit request
to inspect or improve the workflow may follow the relevant surfaces without starting those phases.

The handoff artifacts are the interface: phase 2 receives `WEC.md`;
phase 3 receives the frozen `DFS.md` and Phase-2-initialized `.de67/` clock state.

## Execution placement

Resolve the execution host before delegating or launching `de67 2` or `de67 3`:

- Identify the current host with `hostname`; never infer it from the cwd spelling, the device that
  initiated the request, or a remembered SSH route.
- Prefer Josef's Mac mini whenever the exact target workspace exists there. If already on
  `Josefs-Mac-mini.local`, use that local workspace directly and never hand off or SSH back to the
  same Mac.
- From Windows, use the `remote-mac` skill for a one-shot native Mac handoff when that exact
  workspace exists on the Mac mini. If it does not exist there, use the exact Windows workspace;
  do not create or copy a Mac workspace solely to satisfy this preference.
- Verify path, branch, HEAD, recent activity, and dirty state before selecting among similarly named
  worktrees. The presence of a DE67 source checkout does not establish the product workspace.

`de67 1` remains in the current conversation; this placement rule applies to the repository-owning
specification and delivery phases.

The alignment audit is an optional manual tool, not a fourth phase. It does not receive phase
handoffs, join the delivery loop, mutate the method, or become a completion gate. Route there only
when the user asks to audit agentic workflow alignment, contradictory instructions, or rules and
tests that may be boxing agents in.

Release packaging is a maintenance route, not a fourth phase or a phase-3 completion gate.
Load it only for de67 skill release work; a request to release a product using de67 does not select it.

If `$de67` is invoked without a selected route or a clear task, ask one structured multiple-choice question listing the
three phases, put the recommended phase first, and route after the answer. Do not infer implementation
consent from a discussion or specification request.

## Install or integrate

When the user supplies the de67 repository and asks Codex to install or integrate it:

1. Require the OpenAI Codex CLI and Python 3.10 or newer. Git is required only for repository work
   or publishing generalized method changes. de67 is Codex-specific.
2. Phase 3 bootstraps mutable guidance into the project workspace. Local delivery and mutation do
   not require a writable de67 source checkout or network access. A user-owned `de67-lab` checkout
   is useful only when the owner chooses to generalize and publish a local improvement.
3. Preserve the repository as one intact skill folder with all phase folders, scripts, references,
   assets, and agent metadata. The checkout may be named `de67-lab`; the skill identity remains
   `$de67`.
4. Verify that `codex` and `python` resolve in the execution environment. Phase 3's bundled runner
   invokes the local Codex CLI; do not replace it with a machine-specific wrapper.
5. Use Astra high for the Phase-2 owner and Astra medium for the Phase-3 mutation reviewer.
   Ordinary delivery keeps a Sol low coordinator and Luna/Terra workers. Verify the required models
   in the target runtime; report unavailable capability rather than silently substituting a model.
6. Run the skill validator when available, then run the bundled Python tests before reporting the
   installation complete.
