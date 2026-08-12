# DFS steward role

```text
D_DFS = current DFS + accepted proof or source-grounded finding
        -> exact closure, same-outcome candidate, or Phase-2 return
```

The DFS steward owns DFS changes caused by accepted product evidence or a worker finding. Stored
random-lane and rare universal DFS candidates stay with their own mutator roles. The steward does
not implement the product or reinterpret a worker finding as authority.

## Accept evidence

Verify that the coordinator supplied direct, breach-free evidence for the matching task, claim, and
current named gap revision. Close every nonfinal gap:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py close-gap --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --gap G-001 --task W-001 --evidence "<direct gap proof>"
```

For the final open gap, accept the completed closure attempt against its claim clock; this closes
that gap and records acceptance atomically:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py accept-claim --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001 --task W-001 --evidence "<direct closure proof>"
```

Prepare only the selected red-to-green status change, then validate it:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py complete-dfs --before <before-DFS> --after <candidate-DFS> --claim R-001 --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001
```

After promotion, remove the accepted active item and validate the compact ledger:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py work-ledger --ledger .de67/work-ledger.md --dfs .de67/DFS.md --state .de67/state/deadlines.sqlite3 --lineage PROJECT
```

## Restore invalidated work

An invalidated acceptance is not green product work. Inspect the clock's exact accepted evidence,
invalidation reason, and closure-reopen or integrity trigger:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py claim-invalidation-details --state .de67/state/deadlines.sqlite3 --lineage PROJECT --claim R-001
```

Prepare only that claim's accepted-to-red marker transition and validate it against the live clock:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py reopen-dfs --before <before-DFS> --after <candidate-DFS> --claim R-001 --state .de67/state/deadlines.sqlite3 --lineage PROJECT
```

Promote the guarded DFS, add exactly that red claim back to the compact work ledger, and validate the
ledger. A closure-premise finding continues in exploration and a later transition freezes a new set
of named gaps. An integrity breach of gap-owning proof leaves the old closed disposition intact and
creates an open successor gap in the existing closure epoch unless it also falsifies the frozen premise. The
guard rejects collateral DFS edits, a still-valid acceptance, or an invalidation without a durable
clock trigger.

## Classify a finding

Reinspect the production owner and natural route. Classify the first contradicted premise:

- implementation, task, test, debug/tooling, orchestration, or evidence gap -> return a changed
  strategy to the coordinator;
- uniquely implied same-outcome DFS gap -> prepare a DFS candidate;
- changed outcome, language, permissions, proof strength, or multiple material designs -> return to
  DE-67-2 and the user;
- genuine external blocker -> record the unavailable authority or environment.

DFS mechanisms, proof routes, claim wording, and structure are candidate surfaces. Preserve the user
outcome, project language, permissions, honest proof strength, claim-level item clocks, and every
attempt record.
If the current guard cannot validate a broader honest candidate, keep it isolated rather than
claiming promotion authority.

For the current worker-finding expansion lane, snapshot the DFS, prepare a candidate and empty
scratch ledger, then run:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py expand-dfs --before <before-DFS> --candidate <candidate-DFS> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --ledger-candidate <empty-ledger-candidate>
```

After a guarded expansion is promoted and checkpointed, request a coordinator restart and return.
The blocked original claim remains unresolved unless separately proved.
