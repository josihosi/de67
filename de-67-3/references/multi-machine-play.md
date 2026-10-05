# One coordinator, host-specific execution

Use one central coordinator and the existing shared project ledger for the selected project. Workers
execute on the selected host; supervisor lifecycle/sync orchestration is not competing product
coordination. Do not load this reference for ordinary single-host work without a relevant need.

## Current first slice

`../scripts/host_footing.py` supplies read-only point observations on macOS or Windows. Run locally
with repeated `--repo /exact/repository/root` and optional `--pid PID`. For an already authorized
SSH endpoint use `--ssh ALIAS --repo C:/exact/root`; the script executes on that host via stdin and
does not install files. A simple `--remote-python` executable path is optional. Store a needed
snapshot in the task's existing evidence route; return a compact relevant summary to the coordinator.
Do not copy credentials, whole transcripts or runtime databases into the brief.

The snapshot binds host, observation/transport times, platform-native memory/CPU/disk metrics,
repository root/branch/commit/dirty status/worktrees/remotes, and requested PID/birth/executable
observations. PID inspection is not a complete process inventory or ownership proof. Match the
existing launch record and input owner. Git status is not clean-to-work authority: preserved dirty
work can be unrelated, while a clean wrong branch or stale immutable build can still be unusable.
Redacted remote URLs omit embedded URL credentials. Offline/probe failure is unknown, never idle.

Before a useful launch, refresh facts that could have changed and bind the exact build receipt,
executable identity, retained save bytes, writable profile/registry/session/artifact roots and sole
input owner to that host. A receipt for a different executable path is not automatically a receipt
for a copied binary; use the existing supported revalidation/publication route. A save manifest
without retained bytes does not create a launchable checkpoint. Avoid replay merely to recreate
clerical evidence when a compatible retained start exists.

Use observed pressure, ongoing workload and the owner's responsiveness priorities to decide
admission. No universal memory cap, freshness timeout or synthetic capacity score is defined here.
Windows free memory and Darwin page counters/load averages have different meanings. A snapshot
cannot prove future capacity, writable isolation or GUI readiness. CPU contention during concurrent
play must not masquerade as a controlled regression benchmark.

## On-demand Sol chaperone

A Luna playtest worker may create a native `gpt-6.1-sol` helper with `fork_turns="none"` and suitable
effort for a concrete problem, then reuse the helper's conversation through `followup_task` when
useful. Give it the scenario's intended outcome, exact host/task/run/build/save identities, the
current symptom, relevant source handles, input ownership and changes since its previous finding.
Stale context is evidence history, not the current state. Sol can retrieve logs and inspect source;
conflicting edits still need a handoff. Luna keeps game input and supplies any needed native proof.
The reply should resolve the question with evidence, remaining uncertainty and a supported next
action. The chaperone neither opens project assignments nor changes lifecycle/acceptance state.
Collect its result before the parent returns; preserve its identity for later reuse. If unavailable,
use focused retrieval or return the exact blocker, not a second coordinator. No helper is mandatory
for a successful ordinary run.

## Remaining staged delivery

1. Prove per-run writable-root/registry/input isolation through actual launch entrypoints before
   enabling concurrent games. Check alias/collision, stale binding, wrong host and failed startup;
   separate process/window targeting from exclusive access to an entire desktop input surface.
2. When the owner explicitly selects one host as the source of truth, bind exact repository roots
   and the selected source identity (including intended uncommitted source, if selected). Transfer
   and verify that snapshot before new work on the destination host. Replace conflicting destination
   source only within that authorization; preserve unselected changes until their disposition is
   agreed. Do not overwrite the authoritative host to match the destination. Source replacement excludes runtime
   DBs, saves, logs, credentials and unrelated repositories; do not use blanket directory deletion to
   achieve it. An offline host or file locks held by an owned run are actual execution blockers, not
   authority to fake a mirror. Public release and installed skill activation remain separate. Git
   worktrees share metadata/refs, so do not reset an unrelated worktree as a side effect. Implement
   the supported supervisor source-mirroring route before claiming automatic on-change propagation.
3. Connect these same host/repo/branch/commit/build/task/run facts to the existing dashboard and
   worker handoffs. Do not make a parallel registry or infer actual activity from old roster flags.
4. Run a useful independent host pair after platform build/input/isolation readiness is established;
   one failed lane must not overwrite or cancel the other. Compare subsequent useful batches of
   2–4 actual runs with coherent expected/observed/divergence stories and exact evidence handles.

The CLI and chaperone permission are delivered capability; isolation enforcement, sync automation,
dashboard integration and successful dual-host play require their own implementation/adoption.
The project ledger tracks those next steps without blocking safe independent single-host work.

## Existing synchronization tools considered

For committed source, use ordinary Git push/fetch and verify the selected commit on each host
(https://git-scm.com/docs/git-fetch). This fits the owner's Mac-authoritative checkpoint-first
workflow and keeps Git metadata local to each repository. Do not copy a live `.git` tree.
Mutagen supports one-way-replica and SSH transport (https://mutagen.io/documentation/synchronization/;
https://github.com/mutagen-io/mutagen), making it a candidate for future uncommitted-source transfer.
Its continuous writes still need run/build isolation and explicit runtime exclusions. Syncthing's
send-only/receive-only folder modes (https://docs.syncthing.net/users/foldertypes.html) are useful
for general files but do not supply a commit-bound playtest readiness contract. No extra sync daemon
is installed by this first slice; prefer the existing Git/SSH route until a concrete gap justifies one.
