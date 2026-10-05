# External Phase-3 supervisor

Use this reference only for explicit external supervisor start, restart, stop, or diagnosis.

An explicit `supervisor_service.py start` begins a new runtime-ownership epoch. Before launching
the coordinator, the launcher first verifies that the installed policy source, contracts, and
compiled bytecode agree, then atomically deploys that exact set into the workspace. This policy
deployment is part of restart cleanup; do not copy only the skill scripts or only the bytecode.
After deployment, the launcher records the new runtime epoch and releases any unacknowledged
coordinator-restart claim held by the dead run, preserving the semantic restart request.
A process or model restart preserves unfinished tasks, named-worker ownership, checkpoints and
claim deadlines. Resume that work through the existing worker message path after reconciling its
transport. Completed work and accepted proof remain unchanged.

For an older task administratively terminalized as `restart_normalized`, repeat its existing
`start` with the original attempt estimate. This restores only administrative restart retirement;
it does not reopen genuine completion, abandonment or deadline retirement, change clocks, or create
a replacement task. Use the supported API, never ad hoc SQLite edits.

The internal coordinator resume after a mutation review is not an explicit external start.
It runs inside the existing supervisor epoch and must not invoke external-start normalization or
erase ledger state.

The coordinator chooses when to run `scripts/repository_checkpoint.py`. A checkpoint records a
Git snapshot, not task completion or acceptance; unfinished task rows do not prohibit it. The
command preserves its commit/push recovery identity and reports Git failures for repair. The
supervisor does not require a checkpoint at startup, review exit or coordinator continuation.

A due internal review distinguishes a returned worker turn from its unfinished task. Returned
named assignments retain their claims and evidence while clocks retire for review. The resumed
coordinator may resume the same worker with `message`; an active or uncertain turn still prevents
exclusive review. External process restarts preserve these records as described above.

Use `supervisor_service.py status` and `stop` for observation and shutdown. A stopped service never
implies that FS or ledger work is complete.

If an interrupted review exhausts its bounded corrective turn, its error includes the exact
supported start command. The authorized reviewer finishes the same review and records its one
resume handoff first; then start the stopped service to consume that handoff. Do not turn repeated
owner conversation into an unbounded automatic model loop or restart an unresolved gate blindly.
When recovery machinery blocks useful work, first consider removing the unnecessary condition.
If it protects a real ownership/evidence boundary, retain it and give the responsible agent a short,
executable correction within its authority. A recovery message must name what is wrong and the
supported operation that can actually fix it; do not prescribe forbidden state edits.
