---
name: de-67-3
description: Explicit third phase of DE-67. Use when the user invokes `$de-67-3` or says `DE-67-3` to implement a frozen DFS through deadline-bound coordinator and worker tasks, diagnose every miss independently, mutate Markdown guidance, and continue from the accepted frontier. Do not run the discussion or DFS-authoring phases.
---

# DE-67-3 — delivery and mutation

This invocation authorizes implementation of the frozen DFS in the named working repository. Do not
read `de-67-1/` or `de-67-2/`. Read this file, then `references/kernel.md`; load project state only
from `.de67/` and the working code.

Ensure `.de67/` exists. Copy each missing guideline or ledger from `assets/environment/` individually,
import the frozen DFS as `.de67/DFS.md` when it is not already there, and create `.de67/state/` for
machine clock state. The Markdown documents are normal project artifacts; only machine state belongs
under `.de67/state/`. Ensure `.de67/state/` is ignored by the working repository. Never overwrite an
existing state file with a template.
The skill's `assets/` and `references/kernel.md` are frozen resources; mutate only the project-local
`.de67/` copies described below.

Proceed only when `.de67/DFS.md` records `Frozen` or `Refrozen` against an inspected source baseline.
A missing/draft DFS or unresolved material owner choice returns to DE-67-2 rather than becoming an
implementation guess.

Required project state:

- `DFS.md` — mostly frozen functional specification and red work items.
- `test-and-task-guidelines.md` — mutable task preparation, worker, test, and estimate guidance;
  its headings are frozen.
- `orchestrator-guidelines.md` — mutable coordination and failure-investigation guidance; its
  headings are frozen.
- `work-ledger.md` — the current batch of no more than ten still-red DFS claims.
- `mutation-suggestions.md` — append-only short verdict history, full current diagnoses, manual
  suggestions, and mutation dispositions.

The normative mutable surface is exactly the DFS and the two guideline documents. The ledgers carry
current/history state; they are not additional policy surfaces.

## Start or resume

Use a fresh coordinator. It reads both guideline files, the DFS, both ledgers, deadline status, the
actual Git/worktree state, and relevant current code. It does not inherit a predecessor's story as
fact. When clock state exists, reconcile late worker results and expired timers before planning more
work:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py list --state .de67/state/deadlines.sqlite3
```

If the work ledger has no active item, select up to ten necessary remaining red DFS claims. Ten is
the user-authorized ceiling, not a target. Re-read the affected code and tests, define the smallest
honest passing evidence, and record concise natural-language work items. Do not copy a permanent
coordination matrix into the DFS.

For each ready work item, choose the weakest sufficient worker/model, define the outcome and test,
and make an evidence-informed duration estimate. Start its timer at actual dispatch:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py start --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --claim R-001 --estimate-seconds 900
```

`PROJECT` is one stable implementation-lineage identity for this `.de67/` environment; the state
database binds it on first use and rejects a reset to another lineage.

The coordinator may dispatch multiple workers in parallel when code, state, dependencies, and proof
surfaces are disjoint. Unknown overlap serializes. Handoffs are compact prose: desired outcome,
relevant code/claim, the passing test, and material boundaries. A worker returns what changed, test
results, paths, and any uncertainty. If blocked or surprised by production behavior, the worker
returns expected versus observed behavior and direct evidence immediately; it does not guess around
the finding or edit the DFS. Do not require JSON receipts, artifact hash maps, permits, fixed terminal
schemas, or full transcript ingestion.

Remain live while work is outstanding. Use the platform's non-polling worker wait or deadline wakeup
when available, and act on whichever worker result or deadline arrives first. The detached SQLite
watcher is durable interruption protection; it records a miss but does not replace the independent
review and mutation transaction. A resumed coordinator reconciles any recorded incident immediately.

## Worker findings and the third mutation lane

A worker that encounters a blocker or unexpected production result records a non-success finding:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py finding --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --kind blocker --evidence "<expected, observed, and direct evidence>"
```

An on-time finding stops that task clock without accepting work, closing its DFS claim, or adding a
miss. A late finding preserves the already-earned miss, so the ordinary deadline mutation and this
DFS review are independent lanes. A finding is immutable; retry under a new task identity after the
coordinator dispositions it.

The worker cannot choose the mutation. The coordinator re-inspects the exact production owner,
helpers, primitives, callers, competing readers and writers, owning tests, relevant history, and the
natural execution route. Name the first contradicted premise, then classify the finding:

- implementation, task, test, tooling, or evidence gap: replan or use the applicable guidance lane;
- uniquely implied same-contract specification gap: expand and refreeze the DFS;
- changed behavior, project language, permissions, acceptance strength, or multiple materially
  different designs: return to DE-67-2 and the user;
- genuine external blocker: record the unavailable authority or environment after materially
  different authorized routes were checked.

For a specification gap, snapshot the current DFS, append the smallest necessary mechanistic fact,
ownership/precedence decision, proof route, and at least one new stable red claim. Preserve every
existing claim's identity, text, order, and status and preserve the accepted product frontier. Record
the finding, diagnosis, added red IDs, and disposition in `mutation-suggestions.md`, then validate:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py expand-dfs --before <before-DFS> --after <candidate-DFS> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001
```

Only after validation may the coordinator promote and refreeze the DFS. Keep the blocked original
claim red. Project a newly added prerequisite into the current work ledger only when it is necessary
now and the active ceiling remains satisfied; otherwise it waits for a later refill. Retire the
coordinator after a DFS expansion so a fresh coordinator reconciles the expanded contract.

## Accept work

Inspect the actual diff and run or verify the smallest honest test through the real owner route. A
passing result closes its work item. Record that acceptance with `deadline_harness.py complete` and
a concise natural-language evidence reference. Then prepare the one-line DFS status candidate and
verify that it belongs to the same accepted, breach-free task:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py complete-dfs --before <before-DFS> --after <candidate-DFS> --claim R-001 --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001
```

After validation, promote the candidate DFS, remove the item from the active ledger, and run
`mutation_guard.py work-ledger` against the live ledger and DFS. Preserve concise evidence, not a
receipt bureaucracy.

A late result may still be accepted when it passes, but lateness is never erased. Failed work keeps
the red claim alive. Replan from changed evidence rather than repeat an unchanged tactic.

## Every deadline miss

The per-task clock is immutable once started. When it expires, record exactly one miss and immediately
start this transaction:

1. Give a fresh independent reviewer the task description, intended test, relevant code/diff,
   worker progress or report if any, and direct evidence of the first divergence.
2. Prefer `gpt-5.6-sol` at `xhigh` for this X-type causal review. If unavailable, use the strongest
   independent implementation-capable reviewer available; the worker and coordinator do not review
   their own miss.
3. Append the review to `mutation-suggestions.md`: a short verdict, one explanatory paragraph,
   direct evidence references, and a suggested mutation naming the relevant guideline section.
4. Read the full current diagnosis and every earlier short verdict. Decide whether this failure
   recurs because earlier mutations did not address it.
5. Snapshot the two current guideline files as the read-only baseline, then apply the smallest
   supported change to candidate copies of `test-and-task-guidelines.md`. On cumulative miss units
   3, 6, 9, and so on, also mutate `orchestrator-guidelines.md` in the same transaction.
6. Validate the candidate against canonical headings, baseline, and the exact stored incident with
   `mutation_guard.py guidelines --state ... --lineage ... --task ... --incident-kind ...`; only then
   replace the live guideline bodies. The guard derives ordinary versus broader scope from SQLite;
   the coordinator never supplies the miss count.
7. Retire the current coordinator. A fresh coordinator reads the mutated state and resumes from the
   accepted product frontier.

Useful short verdicts include `goal unclear`, `task unclear`, `test undefined`, `test overdefined`,
`test unachievable`, `wrong worker or model`, `tooling unchecked`, `estimate unsound`, `competing
owner missed`, `integrity breach`, and `external wait`. These are examples, not a closed vocabulary.

Manual mutation proposals may be appended to the same suggestion ledger at any time. The next
mutation round considers and dispositions them; a suggestion is evidence, not automatic authority.

## Integrity breaches

The mnemonic is deliberately sharp: **one puppy dies for every deadline miss; three puppies die for
cheating**. No harm is literal. Operationally, a miss adds one miss unit; a detected integrity breach
adds three, invalidates the claimed completion, restores the red claim, and triggers both guidance
mutations plus a fresh coordinator.

Cheating means moving or resetting a deadline, weakening a DFS outcome or test to claim success,
fabricating or hiding evidence, marking a red claim complete without accepted proof, or changing
task/lineage identity to evade history. Record the concrete reason with the deadline harness. Honest
uncertainty or a truthful failure is not cheating.

## DFS changes during phase 3

The coordinator may:

- remove one red marker after accepted evidence;
- make an evidence-required, uniquely implied non-material mechanistic clarification when it
  preserves the user outcome, terminology, permissions, and acceptance strength; record and
  refreeze it;
- after a stored worker blocker or unexpected-result finding and the source-grounded review above,
  append the uniquely implied same-contract mechanism, ownership/proof detail, and necessary stable
  red claims, validate the expansion, and refreeze it.

Existing claims and accepted work are never renamed, deleted, reopened, or closed by expansion. A
DFS mutation never substitutes for a deadline-triggered guidance mutation; if both conditions occur,
run both lanes. Return to DE-67-2 and the user for changed product behavior/language/permissions,
weaker acceptance, or multiple materially different admissible designs. Never mutate the DFS merely
to make current work pass.

## Continue and stop

Refill the work ledger from remaining red claims when the current batch is worked off. Mutation,
rejected work, a missed deadline, a retired coordinator, or an internal tool failure is continuation,
not project completion. Stop only when every DFS red marker is gone and integrated proof passes, the
user revokes authority, a material owner choice requires phase 2, or the next act is genuinely outside
the available permissions/environment after materially different routes were checked.
