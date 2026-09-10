# Diagnose a de67 installation

Use the exact interpreter, Codex executable, user, and working directory of the failing process.
Read the current error and the relevant script's `--help` before changing configuration.

| Symptom | Check and next action |
| --- | --- |
| Skill cannot be found | Confirm one complete `de67/` directory in a skill directory scanned by this Codex installation; start a fresh task. |
| Python syntax/import failure | Verify Python 3.10+ and install App Server requirements in the interpreter named by `agent_transport_python`. |
| App Server unavailable | Confirm the installed Codex supports `app-server --listen unix://...`; this transport is macOS/Linux only. Inspect the run's `app-server.log`. |
| Model or tool unavailable | Verify the account's actual capabilities with a disposable turn; do not silently substitute models or treat process startup as tool proof. |
| Service will not start | The bundled detached launcher requires macOS and `tmux`. Use its `status` result and recorded stdout/stderr; inspect existing ownership before any restart. |
| FS conflict or stale pointer | Inspect `FS.md` and the hash-bound `DFS.md` pointer through `specification.py`; preserve both and resolve the actual conflicting content. |
| Worker returned but task remains open | Return is an execution event, not acceptance. The coordinator can resume the named worker or decide the task's terminal outcome from evidence. |
| Owner wait repeatedly relaunches work | Inspect the current ledger route and clock facts. Unchecked work does not by itself make an owner-blocked route executable. |
| Checkpoint push failed | Inspect the configured product remote/ref and Git error. A checkpoint is a recoverable snapshot; it does not prove task completion. |
| Dashboard empty or stale | Verify the workspace, clock path, session source, and optional sidecar. A failed source should affect only its own panel. |
| Discord unavailable | Follow the selected relay's setup page. Check owner/channel binding, credentials in private configuration, and the exact service environment. |

Keep optional failures separate from core delivery. Do not reset clocks, replay uncertain messages,
or restart a live product merely to make a status display green. Report the failed operation, its
evidence, and the next necessary action.
