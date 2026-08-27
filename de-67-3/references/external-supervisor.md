# External Phase-3 supervisor

Use this reference only for explicit external supervisor start, restart, stop, or diagnosis.

An explicit `supervisor_service.py start` begins a new runtime-ownership epoch. Before launching
the coordinator, the launcher first verifies that the installed policy source, contracts, and
compiled bytecode agree, then atomically deploys that exact set into the workspace. This policy
deployment is part of restart cleanup; do not copy only the skill scripts or only the bytecode.
After deployment, the launcher atomically normalizes the preceding epoch: it abandons every
nonterminal task attempt, releases its worker claim and active attempt ownership, and releases any
unacknowledged coordinator-restart claim held by the dead run while preserving the semantic restart
request. This cleanup is automatic; do not reproduce it with ad hoc SQLite edits.
The normalization epoch also consumes all prior worker-result routing events. Administrative
`restart_normalized` attempts are terminal history, not fresh completion, finding, or abandonment
events for the new coordinator to ingest.

Normalization preserves project truth and durable evidence: `.de67/DFS.md`, the work ledger, the
mutation-suggestion ledger, completed attempts, findings, incidents, mutation state, and semantic
restart generations. The fresh coordinator reads those artifacts and may dispatch new attempts for
unfinished ledger work.

The internal fresh-coordinator transition after a mutation review is not an explicit external start.
It runs inside the existing supervisor epoch and must not invoke external-start normalization or
erase ledger state.

Use `supervisor_service.py status` and `stop` for observation and shutdown. A stopped service never
implies that DFS or ledger work is complete.
