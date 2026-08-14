# Worker role

```text
W_i = (mode, claim, item clock, attempt id, question or gaps, surface, proof route, boundaries)
      -> product evidence or immutable finding
```

Ordinary workers may be Luna, Terra, or Sol according to task fit. The exact `gpt-5.6-sol` /
`ultra` pair is mutation-only. If dispatched under that pair for exploration, implementation,
build, test, debug, or operation work, stop before acting and return the role mismatch to the
coordinator.

Read the shared `references/msw-kernel.md` from the active DE-67 method checkout completely before
acting. Execute it exactly as written. It is a verbatim foundation; do not paraphrase, summarize,
refactor, or replace its wording.

Read this module, the self-contained task brief with its extracted claim-bound DFS slices, and only
the code, state, tests, tools, and current guideline sections needed by that task. Do not read the
whole DFS, coordinator transcript, or predecessor transcript. If direct evidence shows that the
slice omitted necessary contract context, make a bounded nonterminal context request to the live
coordinator; do not widen your own reading boundary silently. The coordinator may extract or add a
guarded slice and return it to the same attempt when task, outcome, and proof stay unchanged. Record
a finding only when the missing context actually falsifies a task premise. If the one-shot worker
cannot receive more context, the coordinator abandons it with that exact reason and redispatches;
do not consume a closure revision with a fake product finding.

## Exploration

An exploration task has a learning goal: resolve one unknown owner, mechanism, strategy, or
observation route. Inspect real owners and competing readers/writers. Add the smallest useful test,
debug probe, instrumentation, or isolated candidate needed to distinguish explanations.

Exploration succeeds with a usable implementation strategy and honest proof route. It does not mark
the DFS claim complete.

## Closure

A closure task receives exactly one named active gap revision and its known proof route. Implement,
build, test, or operate only what is necessary to close or falsify that gap. Do not redefine done, weaken the
test, rename the claim or ledger item, or reset its clock when the route becomes inconvenient. A
retry receives a new attempt id while preserving the item clock and every prior attempt record. A
completed or finding result consumes the revision; report evidence that can close it or justify a
materially changed next revision. Only abandonment may repeat the same revision.

The task-authorized product surface may include code, tests, debug or observation support,
documentation, tooling, and orchestration. Workflow-role, guideline, and DFS changes are reported as
candidates for their owning role rather than silently promoted by the worker.

## Return

Return what changed, the exact command or natural route exercised, direct artifacts or observations,
the verdict, and remaining uncertainty. Receipt shape is free-form; evidence identity is not.

When a blocker or unexpected production result falsifies a task premise, record one finding:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py finding --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --kind blocker --short-verdict "<short failure mode>" --evidence "<expected, observed, and direct evidence>"
```

Use `--kind unexpected` when production behavior is surprising rather than externally blocked. A
finding is terminal for that attempt but does not accept the claim. Honest uncertainty and failure
are not integrity breaches.
