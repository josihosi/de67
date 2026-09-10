# Persistent workers and context for DE67

Sol can keep a named library of worker conversations in each workspace. A standing job describes the worker's useful role; each assignment carries its own current outcome, evidence and authority. A fresh Sol coordinator can reuse a worker after its worker turn returns, including after mutator steering. An unfinished assignment can resume
under the fresh coordinator once the previous execution owner is gone. Reuse is a judgment about useful context, not a mandatory allocation rule.

The existing context tool shows the compact worker catalog alongside task and receipt discovery. Sol can select a relevant worker, revise its idle job description, model or effort, or create another worker for substantially different work. The initial assignment starts a real App Server conversation; later assignments resume its actual thread UUID.

Named workers intentionally use `danger-full-access` in this workflow, as requested by the owner.

## Coordinator use

Run the CLI from the current coordinator environment so its session and run identity can be checked:

```text
python de-67-3/scripts/worker_library.py --workspace WORKSPACE list
python de-67-3/scripts/worker_library.py --workspace WORKSPACE create night-evidence --job "Interpret night-route evidence and distinguish observations from hypotheses" --model gpt-5.6-luna --effort medium
python de-67-3/scripts/worker_library.py --workspace WORKSPACE assign night-evidence --task TASK --packet PREPARED_PACKET --sha256 PACKET_SHA256 --state DEADLINE_STATE --lineage LINEAGE
python de-67-3/scripts/worker_library.py --workspace WORKSPACE message night-evidence --message "The current source establishes that the caller exists. Revise the missing-caller hypothesis against this evidence."
python de-67-3/scripts/worker_library.py --workspace WORKSPACE wait night-evidence
```

Use the actual assignment command and prepared packet identity returned by the policy kernel. `describe`, `status` and `retire` provide job inspection, idle updates and retirement. Existing native collaboration remains available for native child agents.

Sol writes the current brief from the frozen outcome, relevant source, accepted results, changed owner or mutator guidance, and the remaining uncertainty. It can use selected context bundles without loading the whole context library or replaying the worker's history. Coding guidance can explain interfaces and invariants; testing guidance can explain material premises and distinguishing observations. Detail should help the work and remain revisable.

## Lifecycle and evidence

The registry verifies the current coordinator, workspace, task, recorded packet and current owner-contract revision. A worker cannot hold two assignments, and a different coordinator cannot take over its live task. The shared App Server connection receives worker events; completed public final messages become result artifacts and nonterminal checkpoints. Sol retains result-receipt and terminal-decision authority.

Uncertain `turn/start` delivery is reconciled using exact client identities and observed events or thread history. It is never automatically replayed as another generation. A stopped server preserves the conversation and interruption evidence. Native worker-parent checks and the existing deadline and mutation guards remain in force.

Only explicitly marked, identical standing sections from the same worker's confirmed earlier packet are omitted on reuse. Current task text, selected context and owner corrections remain present. Complete packets and delivery metadata remain available for audit. Token accounting attributes persistent workers and their helpers to the selected coordinator's actual assignment windows, excluding their earlier assignments.

## Platform and evidence limits

The persistent App Server route uses Unix sockets on macOS/Linux. Native Windows retains the CLI
route and shared logic; it does not yet provide these persistent workers. The bundled detached
service launcher is macOS-only. See [installation](install.md) for the precise requirements.

Development simulations exercised related-worker reuse and a correction delivered to the same
worker UUID by a fresh coordinator. They established coordination behavior, not gameplay outcomes
or measured savings against a matched token-use control. The bundled tests cover final-message
collection, uncertain delivery, recovery, owner freshness, packets, and usage attribution. Current
release verification belongs in the [release notes](releases/3.0.0.md).
