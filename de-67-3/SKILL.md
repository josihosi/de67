---
name: de-67-3
description: Explicit third phase of de67. Use when the user says `de67 3` to deliver a frozen DFS through deadline-bound work, progressive role disclosure, honest proof, and evidence-driven method mutation. Do not run the discussion or DFS-authoring phases.
---

# de67 3 — delivery router

This file routes Phase 3; it is not the coordinator procedure.

The invocation authorizes implementation of the frozen DFS in the named working repository. Do not
read `de-67-1/` or `de-67-2/`. Never inventory, search, or read `.de67/no-go-zone/`.

This router is bootstrap material. A launcher may read it to initialize Phase 3. Runtime decisions
come from the compiled policy kernel, not packaged or workspace guideline prose. Packaged scripts
may be executed as tools.

Inspect `.de67/state/workspace.json` and verify that `.de67/DFS.md` records `Frozen` or `Refrozen`
against an inspected source baseline. A missing configuration, draft DFS, unresolved material owner
choice, or changed user outcome returns to de67 2.

Copy each missing environment artifact individually. Never overwrite an existing project file.
Machine state stays under `.de67/state/`; the DFS and ledgers remain ordinary project artifacts.
The machine-canonical runtime policy is `.de67/phase3-policy.d67`, compiled from the branch's Phase-3
policy source and bound to its canonical digest. Guideline Markdown is retained only as a legacy
differential fixture during this experiment; runtime coordinators must not read it as policy.

Before every route decision, execute `scripts/policy_kernel.py decide` against the local compiled
policy, workspace, and deadline database. The returned action names the only policy reads and
obligations that enter the next brief. Unknown, corrupt, ambiguous, or unsupported policy fails
closed instead of falling back to prose.

Policy mutations operate on a candidate machine source and contract corpus under `.de67/state/`.
Promote the candidate source and compiled bytecode together only after `policy_kernel.py guard`
proves every contract, temporal invariant, mutation-ledger route, deadline wake, and rule necessity.
The successful promotion requests one fresh coordinator; failed candidates have no authority.

## Route locally

The supervisor launches a coordinator against the compiled workspace policy. The coordinator asks
the kernel for the next transition and routes only the returned minimal brief. Deadline, integrity,
random, DFS, universal, worker, blocker, acceptance, and restart routes are policy actions over
durable state. Product strategy and evidence judgment remain model work inside the selected route.

## Terminal routing

Ordinary worker results, test failures, acceptance, ledger refill, and exploration-to-closure
transition stay with the same coordinator. A formal terminal finding also stays with that
coordinator; it is reserved for a disproved strategy, materially different route, external blocker,
or exhausted bounded route. An applied method or DFS mutation requests a fresh coordinator and
retires the old one. The external supervisor launches and acknowledges the successor.
