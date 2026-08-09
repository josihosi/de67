---
name: de67-lab
description: Explicit-call laboratory for evolving DE67 coordination under immutable functional-specification, proof-integrity, deadline, and mutation laws. Use only when the user invokes `$de67-lab` to design, validate, benchmark, or provision a candidate DE67 mutation; do not use it to start production coordination without separate DE67 Gate C consent.
---

# DE67 Lab

Use a frozen constitution around two bounded policy surfaces. Read all three references before any
lab act:

1. `references/kernel.md` — immutable specification, integrity, clock, mutation, and promotion law.
2. `policy/orchestration.json` — `P1`, the single-worker-failure mutation surface.
3. `policy/execution.json` — `P3`, the additional three-window-failure mutation surface.

Treat `contracts/mutation-policy.json`, both scripts, tests, this file, agent metadata, and the
kernel as frozen. A candidate never evaluates its own mutation boundary; run
`scripts/mutation_guard.py` from the accepted parent checkout.

## Lab workflow

```text
accepted parent V_n
    -> sealed failure receipt(s)
    -> scope(worker | coordinator)
    -> candidate V_n+1 from V_n
    -> parent-side mutation validation
    -> candidate-only frozen benchmark
    -> compare(candidate result, stored parent result)
    -> promote | discard candidate and return to V_n
```

For `worker`, require one identity-bound worker failure and permit changes only to
`policy/orchestration.json`. For `coordinator`, require three distinct failed ledger windows in
the same lineage and permit changes to both mutable references. Neither scope may change the
kernel or its enforcement tools.

Do not repair a rejected candidate. Discard it, retain its compact benchmark receipt, identify a
different causal direction, and derive the next candidate from the last accepted parent.

## First ledger window

Before the first worker dispatch of every DE67 lineage, call the deadline harness `open-window`.
That command idempotently deploys the harness when it is absent or version-stale, validates the
ledger DAG, seals its deadline, persists the clock, and starts the detached watcher. Do not replace
it with a prompt timer.

The lab invocation alone does not grant production acts or start a coordinator. Preserve DE67's
separate specification and coordination consent gates.

## Commands

```text
python scripts/deadline_harness.py open-window --lineage-id ... --run-id ... \
  --window-id ... --fs-root /absolute/path/to/specification --ledger ledger.json

python scripts/deadline_harness.py permit-dispatch --lineage-id ... --run-id ... \
  --window-id ... --slot-id ... --worker-profile ...

python scripts/deadline_harness.py status --lineage-id ... --run-id ... --window-id ...

python scripts/deadline_harness.py export-benchmark --lineage-id ... --run-id ... --window-id ...

python scripts/mutation_guard.py validate --candidate candidate --scope worker \
  --lineage-id ... --run-id ... --window-id ... --event-hash ... --intent mutation-intent.json

python scripts/mutation_guard.py compare \
  --baseline-install-root parent-harness-state --baseline-lineage-id ... \
  --baseline-run-id ... --baseline-window-id ... --candidate-skill candidate \
  --candidate-install-root candidate-harness-state --candidate-lineage-id ... \
  --candidate-run-id ... --candidate-window-id ...
```

Use absolute paths when a task crosses worktrees or machines. Return compact receipts and artifact
paths; do not ingest complete worker transcripts merely to operate the lab.
