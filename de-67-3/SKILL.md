---
name: de-67-3
description: Explicit third phase of de67. Use when the user says `de67 3` to deliver a frozen DFS through deadline-bound work, progressive role disclosure, honest proof, and evidence-driven method mutation. Do not run the discussion or DFS-authoring phases.
---

# de67 3 — delivery router

This file routes Phase 3; it is not the coordinator procedure.

The invocation authorizes implementation of the frozen DFS in the named working repository. Do not
read `de-67-1/` or `de-67-2/`. Never inventory, search, or read `.de67/no-go-zone/`.

Read `references/kernel.md` completely, then inspect
`.de67/state/workspace.json` and verify that `.de67/DFS.md` records `Frozen` or `Refrozen` against an inspected source baseline. A missing configuration,
draft DFS, unresolved material owner choice, or changed user outcome returns to de67 2.

Copy each missing ledger from `assets/environment/` individually. Never overwrite an existing
project file with a template. Machine state stays under `.de67/state/`; the DFS and ledgers are
ordinary project artifacts. Method guidance lives only in this Phase-3 skill under
`assets/environment/`. Never read, create, or mutate workspace-local guideline copies; legacy
`.de67/test-and-task-guidelines.md` and `.de67/orchestrator-guidelines.md` are not active policy.

## Disclose one role

After the kernel, open exactly one role module for the current event:

- normal start, resume, returned work, or continued delivery -> `references/roles/coordinator.md`
- a task-local implementation, exploration, test, build, debug, or operation ->
  `references/roles/worker.md`
- every exact deadline or integrity incident -> `references/roles/deadline-mutator.md`
- a stored ordinary random-improvement gate -> `references/roles/random-mutator.md`
- a persisted random draw with `k = 30`, lane `DFS.md`, and proved `gpt-5.6-sol` at `ultra` ->
  `references/roles/universal-mutator.md`
- accepted evidence or a finding that may change DFS state -> `references/roles/dfs-steward.md`
- unattended launch, restart ownership, or abnormal process recovery ->
  `references/roles/supervisor.md`

Do not preload sibling role modules. The active role may open another module only when a concrete
state transition names that next role. Pass it compact durable state and direct evidence, not a
predecessor transcript.

The coordinator is the default attended role. For unattended work, enter through the supervisor.
Fresh supervisors route their child directly to the coordinator module rather than back through
this router.

## Terminal routing

Ordinary worker results, findings, acceptance, ledger refill, and exploration-to-closure transition
stay with the same coordinator. An applied guarded method or DFS mutation requests a fresh
coordinator and retires the old one. The old coordinator never launches or acknowledges its
successor.
