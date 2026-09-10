# How de67 works

de67 separates discussion, specification, and autonomous delivery. Each phase receives a small,
durable artifact instead of inheriting an expanding conversation.

## The three phases

```mermaid
flowchart LR
    Idea([Idea]) --> P1["de67 1<br/>Discuss"]
    P1 -->|WEC.md| P2["de67 2<br/>Specify"]
    P2 -->|Frozen DFS.md| P3["de67 3<br/>Deliver"]
    P3 --> Product([Working, proven software])
```

The user starts each phase explicitly. Phase 1 preserves intent. Phase 2 grounds that intent in the
repository and freezes the delivery specification. Phase 3 implements and proves the frozen work.

## The de67 3 delivery loop

The external supervisor owns process lifetime. The coordinator owns semantic trajectory. Workers
implement, investigate, test, and repair. SQLite preserves tasks, claims, deadlines, findings,
evidence, and restart generations across process boundaries.

```mermaid
flowchart TD
    S[External supervisor] --> C[Coordinator]
    C --> K{Read policy, DFS,<br/>ledger, and clock}
    K -->|executable work| T[Open or select task]
    T --> W[Spawn Luna or Terra worker]
    W --> R[Durable worker result]
    R --> C
    C -->|gap remains or switch route| K
    C -->|live worker or external wait| Wait[Wait for an event]
    Wait --> C
    C -->|DFS proved| Done([Complete])
    C -->|mutation is due| Retire[Retire coordinator]
    Retire --> S
```

A worker result can be evidence, an ordinary failure, an abandonment, or a formal finding. The same
coordinator receives it and decides what it means. The supervisor checks mechanical possibility; it
does not replace the coordinator's judgment with administrative routing.

Parallel workers are permitted when their work is independent. A due mutation blocks new dispatch,
but already-live worker turns must return and stop editing before review begins. Their tasks can remain
unfinished and resumable after the review.

## Mutation without losing the work

Mutation changes the delivery method, not the requested product outcome. It runs with no coordinator
or worker active and produces a guarded, receipt-backed change before delivery resumes.

```mermaid
flowchart TD
    Signal[Deadline or integrity incident,<br/>owner trigger, or scheduled review] --> Quiet{Workers quiet?}
    Quiet -->|no| Finish[Let live worker turns return]
    Finish --> Quiet
    Quiet -->|yes| Review[Fresh independent mutation reviewer]
    Review --> Candidate[Smallest evidence-backed method change]
    Candidate --> Guard{Policy and contracts pass?}
    Guard -->|no| Preserve[Preserve current method and record the failure]
    Guard -->|yes| Apply[Promote change and mutation receipt]
    Apply --> Fresh[Start a fresh coordinator]
    Fresh --> Continue[Continue the durable ledger]
```

`Owner-authorized [trigger]: ...` requests review as soon as workers are quiet.
`Owner-authorized [defer]: ...` queues the same mandatory input for the next regularly due review
without interrupting ordinary delivery.

## Built on Codex

de67 supplies the specification, work ledger, deadline state, policy, and review lifecycle.
The [Codex App Server](https://learn.chatgpt.com/docs/app-server) supplies the native conversations,
turns, tools, and streamed events used by persistent workers and live input. The coordinator can
adapt its approach within this workflow, but de67 is not a runtime-independent orchestration
framework. Moving it to another agent platform would require implementation and new validation.

A returned turn is not a completed task. The coordinator can resume a named worker with its useful
context intact, including under a fresh coordinator after review. Git checkpoints are chosen
snapshots; a failed push is repairable and does not itself stop the delivery loop.

The optional [dashboard](../integrations/dashboard/README.md) reads this state for the owner.
The separately installed [Discord package](../integrations/openclaw_discord/SETUP.md) offers direct
owner input and a distinct blocked-only contact route. Neither is a core prerequisite.
