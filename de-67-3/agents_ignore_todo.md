# Frozen agent backlog — ignore during DE-67 runs

This is a human maintenance note with no DE-67 runtime authority. Routers, coordinators, workers,
reviewers, and watchers must not read, execute, summarize, mutate, or copy it into project `.de67/`
state. Only Josef or an agent directly tasked with maintaining this note may change it.

## Tomorrow

- Investigate exposing a cheap Luna-class model to both the supervising Codex session and DE-67
  coordinators. Verify explicit model selection and actual spawned-thread identity; retain strong
  Sol review for genuinely ambiguous causal work and independent mutation review.
- Design the smallest useful messaging service for coordinator, worker, reviewer, and watcher event
  delivery. Prefer direct bounded messages over polling, transcript handovers, or durable packet
  bureaucracy; define ownership, authentication, retention, and failure behavior before building it.

## Phase 3 simplification after the live run

- Reduce the always-read Phase 3 bootstrap. It currently loads about 643 lines / 5,089 words before
  the DFS or code. Keep only DFS authority, the coordinator/worker loop, the immutable task clock,
  mutation-triggered restart, and terminal completion in the core path.
- Load finding/DFS expansion, deadline or integrity review, random mutation, and supervisor recovery
  instructions only when their state is actually present. Remove duplicated procedures from the
  main skill, kernel, mutable guidelines, templates, and tests instead of choosing a new canonical
  copy for every repetition.
- Keep model choice in the proved workspace roster and mutable worker guidance. The frozen path only
  needs a self-contained task prompt and a clock started at dispatch. Worker reuse or replacement is
  a coordinator choice; newly spawned workers do not inherit coordinator context.
- Replace symbolic `S` / `dS` notation with plain same-contract and DFS-authority language. Revisit
  byte-identical insertion-only DFS expansion: preserve the user outcome, accepted claims, red claim
  identities, and proof strength, but do not forbid a necessary local refinement merely because its
  wording is not append-only.
- Give each task-relevant DFS slice stable unique anchors. Let the work ledger point to a range such
  as `A01 -> A02`; the coordinator greps the two anchors and reads only the text between them. Never
  renumber anchors, preserve them through mutations, and when the ledger is empty scan the red-claim
  index before opening one selected slice.
- Keep completed work only in the checked DFS. Keep the active ledger compact, expose only a small
  recent window of short failure verdicts at startup, and fetch a long diagnosis only for the exact
  anomaly being investigated.
- Automate only repetitive mechanical work that is easy to prove: successful mutation-ledger
  clearing, cadence resolution, restart queuing, and disposal of finished task notes. Leave product
  acceptance, proof strength, DFS meaning, and causal replanning to the coordinator.
- Remove tests that require identical policy sentences in multiple files. Test behavior instead:
  ordinary task results keep the coordinator, while an applied mutation or explicit recovery event
  requests a fresh one.
