# Supervisor role

```text
S_sup = (DFS completion, ledger, clock gates, child exit, restart generation)
        -> launch once / stop / leave exact recovery state
```

The supervisor is an external process owner. It records process facts and never judges product
work, chooses a worker, diagnoses a miss, edits the DFS, or authors a mutation.

Start unattended delivery with:

```text
python <active-de-67-3-skill>/scripts/coordinator_supervisor.py --state .de67/state/deadlines.sqlite3 --lineage PROJECT --workspace . --run-root .de67/state/coordinator-runs --runner <one-shot-runner>
```

The runner accepts `--cwd <workspace>` and one prompt on standard input. The supervisor routes that
prompt directly to `references/roles/coordinator.md`; it does not ask the child to preload the main
router or sibling roles.

The supervisor is the direct parent and sole owner of restart-generation claims. A successor
executes `DE67_COORDINATOR_ACK_ARGV_JSON` without a shell before dispatch. The retiring coordinator
requests a baton and exits; it never launches or acknowledges its successor.

Success without a new acknowledged restart stays stopped. A failed or unacknowledged successor is
not silently retried and remains pending. After abnormal death, confirm the runner tree is gone
before releasing that exact failed claim for an explicit recovery action.

When the user outcome is honestly proved, closure gaps and active work are empty, and no incident or
restart gate remains, launch nothing. A due ordinary random review cannot create post-contract work.
