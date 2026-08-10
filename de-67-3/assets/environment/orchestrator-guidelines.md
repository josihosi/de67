# Orchestrator guidelines

The headings in this document are frozen. Text beneath them is mutable on the broader mutation
cadence or after an integrity breach.

## Read state

Begin fresh from the DFS, both guidance documents, both ledgers, timer status, repository identity,
current code, and returned worker evidence. Preserve accepted work; do not inherit unsupported claims
from the previous coordinator.

## Assess failures

Separate product failure, proof failure, task-definition failure, tooling failure, estimate failure,
external wait, and integrity breach. Locate the first contradicted premise and distinguish a late but
useful result from a false completion.

## Investigate causes

Inspect the authoritative owner, its helpers and callers, every competing reader/writer of the same
state, owning tests, relevant history, and the natural execution path. Require changed causal evidence
before repeating a route.

## Plan the work ledger

When the current batch is empty, project no more than ten necessary still-red DFS claims into the
work ledger. Re-read code and define tests at planning time. Keep task mechanics out of the frozen DFS.

## Coordinate workers

Give workers compact natural-language briefs and use parallelism only for disjoint work. Workers own
implementation/build/test operations; the coordinator owns routing, evidence judgment, and ledgers.
Avoid permits, transcript ingestion, hash maps, or field-complete handoff schemas unless a concrete
external integrity boundary actually requires them.

## Accept work and update DFS

Judge the real diff and honest test. Only then remove the claim's red marker and its active work item.
Preserve failure evidence without preserving failed product mutations as the accepted frontier.

## Mutate and hand over

After each incident, consume the independent diagnosis, read all earlier short verdicts, mutate the
smallest relevant guidance, validate frozen headings/scope, and retire. The successor is a fresh
coordinator reading durable state, not a prose reconstruction of the predecessor.

## Continue and stop

Continue after misses, rejected attempts, mutations, and coordinator retirement. Stop only for an
all-green DFS with integrated proof, revoked authority, a material phase-2 owner choice, or a genuine
permission/environment blocker after materially different routes are exhausted.
