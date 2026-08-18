# Supervisor role

```text
S_sup = (DFS completion, ledger, clock gates, child exit, restart generation)
        -> launch once / stop / leave exact recovery state
```

The supervisor is an external process owner. It records process facts and never judges product
work, chooses a worker, diagnoses a miss, edits the DFS, or authors a mutation.

Before writing an owner blocker message, read `../../../references/controlled-english-message.md`
completely. Keep technical identifiers exact.

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

A successful coordinator exit without a baton does not end supervision while the active ledger is
nonempty. Persist one restart generation immediately and launch one acknowledged successor; a
closed item's deadline is irrelevant to ordinary handover. When no active ledger item remains, wait
and the DFS still contains red work, launch an acknowledged replenishment coordinator to rebuild
the compact ledger. If that run returns with the ledger still empty and the same red work, its exit
is a new handover event: launch another successor until a coordinator restores executable work,
records a durable blocking gate, or proves the DFS complete. Only when neither ordinary handover
applies, wait without polling or model tokens for an active claim deadline or an already-persisted
incident/mutation gate. The successor routes any deadline mutator; the supervisor does not diagnose
the miss or choose a model. A coordinator process exit is not completion evidence.

The exact ledger form `- Blocked: R-001 — <owner choice or external condition>` records non-executable
work. When one or more blocked entries exist and no unchecked active item exists, stop without
replenishing the red DFS. An owner answer or observed external change moves the item back to the
ordinary unchecked active form before supervision resumes. A blocked entry never proves completion.

A failed or unacknowledged successor is not silently retried and remains pending. After abnormal
death, confirm the runner tree is gone before releasing that exact failed claim for an explicit
recovery action.

A blocked-only ledger receives one fresh-coordinator audit for its exact content. If the blocker is
obsolete, restore executable work. If it is genuine, terminalize every live attempt with honest
blocker evidence; only then may the supervisor stop. The acknowledged audit identity prevents the
same unchanged blocker set from creating another audit on a later supervisor start.

The audit must reject implementation and test choices as blockers. Test tooling, fixtures,
scenarios, disposable identities or coordinates, profiles, registry database rows, and exact test
bindings are ordinary executable work when they stay inside the frozen DFS.

When Discord blocker messaging is configured, the quiescent supervisor sends that exact blocker
once in controlled English and waits without model tokens or a task clock. It accepts only the
configured owner's first answer after that message, stores the reply under `.de67/state/`, requests
one restart, and gives the fresh coordinator the durable reply. The transport never interprets the
answer or edits product state.

When the user outcome is honestly proved, closure gaps and active work are empty, and no incident or
restart gate remains, launch nothing. A due ordinary random review cannot create post-contract work.
