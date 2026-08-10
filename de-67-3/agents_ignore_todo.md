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
