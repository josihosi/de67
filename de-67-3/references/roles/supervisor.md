# Supervisor role

```text
S_sup = (DFS completion, ledger, clock gates, child exit, restart generation)
        -> launch once / stop / leave exact recovery state
```

The supervisor is an external process owner. It records process facts and never judges product
work, chooses a worker, diagnoses a miss, edits the DFS, or authors a mutation.

Start unattended delivery with:

```text
python <active-de-67-3-skill>/scripts/coordinator_supervisor.py --state .de67/state/deadlines.sqlite3 --lineage PROJECT --workspace . --run-root .de67/state/coordinator-runs --runner python <active-de-67-3-skill>/scripts/codex_runner.py
```

The runner accepts `--cwd <workspace>` and one prompt on standard input. The supervisor routes that
prompt directly through `references/kernel.md` to `references/roles/coordinator.md`; it does not ask
the child to preload the main router or sibling roles. The bundled runner discovers `codex` on `PATH`, uses the coordinator model
and effort supplied by the supervisor, and records its prompt, JSONL event stream, status, timestamps,
and exit code under ignored `.de67/state/runner-runs/`. `DE67_CODEX` may name an alternate Codex
executable and `DE67_COORDINATOR_SANDBOX` may select the Codex sandbox when the host requires it.

The supervisor is the direct parent and sole owner of restart-generation claims. A successor
executes `DE67_COORDINATOR_ACK_ARGV_JSON` without a shell before dispatch. The retiring coordinator
requests a baton and exits; it never launches or acknowledges its successor.

A successful coordinator exit without a baton does not end supervision while work remains. Wait
without polling or model tokens until the earliest active claim deadline or an already-persisted
incident/mutation gate. At that event, persist one restart generation and launch one acknowledged
successor. The successor routes the deadline mutator; the supervisor does not diagnose the miss or
choose a model. Never launch the same unchanged supervision event twice.

A failed or unacknowledged successor is not silently retried and remains pending. After abnormal
death, confirm the runner tree is gone before releasing that exact failed claim for an explicit
recovery action.

When the user outcome is honestly proved, closure gaps and active work are empty, and no incident or
restart gate remains, launch nothing. A due ordinary random review cannot create post-contract work.
