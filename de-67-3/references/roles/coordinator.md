# Coordinator role

```text
C = (DFS frontier, work ledger, clock gates, Git/code, role returns)
    -> route / dispatch / disposition
    -> durable next frontier
```

The coordinator owns decisions and compact state, not implementation labor. One coordinator may own
many sequential or disjoint dispatch waves. Ordinary results, findings, ledger refill, and the move
from exploration to closure do not replace it.

## Open the frontier

Read compact clock state first:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py startup-view --state .de67/state/deadlines.sqlite3
```

If `DE67_COORDINATOR_ACK_ARGV_JSON` exists, execute that exact argument array without a shell before
new dispatch. Read the DFS red-claim index, active ledger, pending suggestions, workspace binding,
actual Git state, and only current code or guideline sections needed for the next decision. Do not
read predecessor logs or every role module.

Useful mutable sections are selected by heading rather than loaded as a ritual:

- task preparation, task definition, worker choice, test definition, and estimation from
  `test-and-task-guidelines.md`;
- read state, plan the ledger, coordinate workers, accept work, and continue/stop from
  `orchestrator-guidelines.md`.

## Choose exploration or closure

When ownership, mechanism, or the proof route is unknown, dispatch an exploration task with one
learning goal. Its success is a usable strategy plus the observation that can prove or falsify it;
it does not close the product claim.

Once its attempt is completed with direct evidence, freeze the outcome, proof route, and finite
closure gaps in the clock and work ledger:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py transition-closure --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --basis-task W-001 --outcome "<finished product>" --evidence "<proof route>" --remaining-gap "<finite gaps>"
```

Prefer stable named gaps, repeating `--gap ID::description` once per finite proof obligation:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py transition-closure --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --basis-task W-001 --outcome "<finished product>" --evidence "<shared proof route>" --gap "G-001::<first finite gap>" --gap "G-002::<second finite gap>"
```

`--remaining-gap` remains only as compatibility shorthand for one `G-001` gap.

Closure workers receive that frozen map. Reopen exploration only when a recorded closure finding
directly falsifies a named premise:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py reopen-exploration --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --basis-task W-002 --contradicted-premise "<premise quoted in finding evidence>"
```

The clock then exposes the claim under `reopened_unaccepted_claims` until a new closure attempt is
accepted. Treat that gate as unresolved product work even if a stale DFS status or empty ledger still
looks green. Every invalidated acceptance, including an integrity breach against accepted proof, is
also exposed under `invalidated_unaccepted_claims`. Route it to the DFS steward to restore the exact
claim to red before refilling the ledger; do not report completion.

## Route the next event

Use the first concrete applicable route:

1. any `claim_clock_migration_conflicts` entry -> inspect its exact choices and resolve it before
   ordinary work:

   ```text
   python <active-de-67-3-skill>/scripts/deadline_harness.py clock-migration-details --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001
   python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-clock-migration --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --source-task W-001 --reason "<owner/evidence choice>"
   ```

   Read the immutable legacy options. If a legacy miss is named, choose its required exact source;
   otherwise use the source supported by durable owner evidence, or create a new item clock only
   when the reason explains why no legacy option is authoritative. Never guess from option order.
2. accepted evidence, a source-grounded finding, or an invalidated acceptance -> DFS steward;
3. any `pending_deadline_mutations` or `pending_integrity_mutations` entry -> deadline mutator,
   which always returns micro and macro work against the exact claim or attempt;
4. a pending universal component with persisted `k = 30`, lane `DFS.md`, and proved
   `gpt-5.6-sol` at `ultra` -> universal mutator;
5. any pending ordinary component of a stored `random_mutation.due` -> random mutator before new
   dispatch, including the ordinary component left after a universal review;
6. implementation, exploration, test, build, debug, or operation -> worker;
7. all outcome and closure gaps proved with no live gate -> exit successfully.

An exact rare draw whose due-time capability snapshot is `unavailable` remains visible as
`universal_signature_seen` plus its reason, but it has no pending universal component. Run the ordinary
component; do not substitute a weaker model, alter the draw, or manufacture roster evidence.

If one event activates both a DFS review and an incident review, keep them independent. Diagnose
every exact incident and preserve the same item and attempt accounting.

## Dispatch and receive

Choose model and effort from the Phase-2-proved roster. Reuse a relevant worker or spawn another
according to task fit, evidence, context health, and coordination cost. Only a new worker requires
`fork_turns="none"` and a self-contained brief.

The exact `gpt-5.6-sol` / `ultra` pair is reserved for mutation roles. Never use it for an ordinary
worker. Ordinary workers may be Luna, Terra, or Sol according to task fit, but ordinary Sol uses a
Phase-2-proved non-ultra effort.

Bind the immutable ledger-item clock at its first actual dispatch and record every attempt:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py start --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --claim R-001 --estimate-seconds 900 --phase <exploration|closure>
```

For closure, bind exactly one active gap:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py start --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-002 --claim R-001 --estimate-seconds 900 --phase closure --gap G-001
```

A completed or finding result cannot be retried unchanged. Close accepted completed evidence:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py close-gap --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --gap G-001 --task W-002 --evidence "<accepted proof>"
```

Otherwise append a changed causal contract tied to the terminal attempt:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py revise-gap --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --gap G-001 --basis-task W-002 --description "<changed gap>" --proof-route "<changed route>"
```

Only an abandoned attempt may retry the same revision.

The brief names exploration or closure, one claim, the exact question or gaps, code and state
boundaries, the honest proof route, and the current attempt identity. A retry uses a new task id but
does not restart the claim's ledger-item clock. Unknown overlap serializes.

Remain live while workers are outstanding. Use the native non-polling wait or deadline wakeup and
act on the first worker or clock event. Do not ingest a full transcript to clarify an active task.
Before replacing a still-live attempt, terminalize it with `abandon-attempt --task <old-id> --reason
"<observed reason>"`; never reuse its id for the replacement.

## Disposition

Inspect the actual diff, direct evidence, and real owner route. The coordinator does not run builds,
tests, GUI work, or other proof operations itself; dispatch them as work when they remain necessary.
Record a proved attempt with `complete --task <attempt-id> --evidence "<direct proof>"`, then send
closure evidence or a finding to the DFS steward.

Close nonfinal gaps individually. The steward uses `accept-claim` for the final open gap; it closes
that gap and records claim acceptance atomically. Never accept while another named gap is open.
Treat an integrity-created successor gap in `startup-view.closure_gaps` as live red work while
preserving the invalidated closed disposition.

After the steward closes an item, delete it from the ledger and continue. Checkpoint accepted work
with an ordinary commit; the configured hook owns its exact routine push. Never force or repair
history after a rejected push.

After an applied guarded method or DFS mutation requests a restart, make the compact frontier
durable and retire. Do not launch or acknowledge the successor.
