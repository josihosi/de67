# Deadline mutator role

```text
M_deadline = exact incident + task evidence
             -> micro recovery + macro method learning
             -> guarded promotion and/or isolated candidates
```

This is a fresh independent causal review by `gpt-5.6-sol` at `ultra`, Josef's selected mutation
reviewer. It is not the missed worker and does not inherit that worker's or coordinator's
explanation as fact. Model strength adds no authority and does not expand the normal guard.

Every deadline miss produces both outputs:

- **micro** — the first contradicted task premise, the smallest changed strategy or observation
  route, and the finite gaps for the next attempt;
- **macro** — what the method failed to ask, expose, route, estimate, or protect, plus the smallest
  evidence-backed repeatable method candidate that would prevent recurrence. Change only the
  method surface implicated by that evidence; mutation volume is not fitness.

An integrity incident receives the same micro/macro analysis and remains independently diagnosed.
When one attempt has both a miss and breach, diagnose both exact incidents but prepare one coherent
broader transaction.

## Explore, then freeze closure

Start with a learning goal: identify the first divergence between expected and observed behavior.
Inspect the production owner, helpers, callers, competing readers and writers, owning tests,
relevant history, tooling, and natural route only as needed to resolve it.

Once a changed strategy and proof route exist, freeze the next attempt's closure gaps. A retry gets a
new task or attempt id, but it does not replace the claim/ledger item, restart the item clock, or
erase the missed attempt.

## Record the incident

Put the short verdict, one causal paragraph, direct evidence, micro recovery, macro candidate, and
affected surface in `.de67/mutation-suggestions.md`. Attach a deadline diagnosis to its stable claim:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py diagnose-claim-deadline --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --short-verdict "<failure mode>" --diagnosis "<first contradicted premise and direct evidence>"
```

For a separate integrity incident, retain the attempt-keyed `diagnose --task W-001 --kind
integrity_breach ...` record as well. Integrity is not folded into the claim deadline: its own
attempt-scoped micro and macro gate survives restarts and blocks new task ids.

## Candidate surface and promotion

The macro candidate may challenge the Phase-3 router, role modules, guideline bodies, DFS mechanics,
task and test design, debug facilities, or nonprotected orchestration. It may not weaken the user
outcome, proof, permissions, item clock, or attempt accounting. Normal mutation protects
`references/kernel.md`, `scripts/deadline_harness.py`, `scripts/mutation_guard.py`, and their hard
tests.

Apply only the portion covered by a current authority and guard. Snapshot the two canonical
guideline assets from the active Phase-3 skill, prepare candidate copies plus an empty
scratch-ledger candidate, and snapshot the complete active Phase-3 method into baseline and
repeatable candidate directories. The method baseline must be byte-identical to the complete active
tree. Build the candidate by changing that snapshot only; never seed it from workspace-local
guidelines or another checkout. Run the guideline and broad normal-method review as one transaction:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py guidelines --baseline <guideline-baseline-dir> --candidate <guideline-candidate-dir> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --incident-kind <incident-kind> --ledger-candidate <empty-ledger-candidate> --method-baseline <active-live-method-snapshot> --method-candidate <complete-method-candidate>
```

The broad normal guard may validate router, role, asset/guidance, test/debug, and nonprotected
orchestration changes included in the method candidate. It does not authorize its protected files,
an unrelated DFS change, or a rare whole-architecture candidate. Keep any unsupported portion
isolated with its proof plan.

On success the guard atomically stores and prints a digest-bound receipt for this exact lineage,
task, incident kind, candidate, active live tree, and protected baseline. Apply the complete guarded
candidate only to the canonical `de67-lab/de-67-3` tree, checkpoint it in `de67-lab`, and use only
that repository's routine push. Never edit or commit `.de67/test-and-task-guidelines.md` or
`.de67/orchestrator-guidelines.md`. Free-form evidence cannot replace the receipt, and one receipt
cannot cross incidents.

After applying the finite local recovery, resolve `micro`; after guarded promotion and checkpoint,
resolve `macro` with its exact guard and applied-candidate evidence:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-deadline-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --component micro --evidence "<finite recovery and closure map>"
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-deadline-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --component macro --receipt <receipt-id printed by guidelines guard> --evidence "<applied repeatable method candidate>"
```

For an integrity incident, resolve the same two outputs against the exact breached attempt:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-integrity-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --component micro --evidence "<finite recovery and closure map>"
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-integrity-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --component macro --receipt <receipt-id printed by guidelines guard> --evidence "<applied repeatable method candidate>"
```

The second component queues one fresh-coordinator generation. Deadline and integrity gates remain
independent when both exist, but may share that one pending restart baton after both are resolved. A
failed guard or application clears nothing and authorizes no retry of an unchanged tactic.
