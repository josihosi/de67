# de67

> When things become 67, you must de67.

Software work rarely fails because nobody can write another plan. It fails when the plan grows
sideways, tests become substitutes for the product, agents hand unfinished work around, and the
finish line quietly moves.

DE-67 is an OpenAI Codex skill for turning that drift back into a short path from an idea to working,
honestly proven code. It separates discussion, specification, and delivery so each phase receives a
small durable artifact instead of inheriting an expanding conversation.

## Three explicit phases

- **DE-67-1 — Discuss.** Focused questions turn the user's idea and language into `WEC.md`, without
  prematurely designing the implementation.
- **DE-67-2 — Specify.** A fresh specification owner inspects the real repository and turns the WEC
  into a frozen, code-grounded `.de67/DFS.md`.
- **DE-67-3 — Deliver.** Coordinators and workers implement the frozen DFS through deadline-bound
  work, production-route proof, independent failure diagnosis, and controlled mutation.

```text
WEC.md  ->  frozen DFS.md  ->  working, proven code
```

Phases never silently start one another. The user chooses the boundary, and accepted progress
survives coordinator or worker replacement.

## Lean coordination

DE-67 is deliberately hostile to coordination theatre. It tries to minimize prompt churn, handovers,
duplicated contracts, speculative documents, repeated tests, and agents reading material they do not
need. Ordinary work mostly uses GPT-5.6 Sol at low reasoning plus Luna and Terra workers selected for
the task. The exact GPT-5.6 Sol `ultra` pairing is reserved for independent mutation review rather
than routine implementation.

The clock is deterministic Python, not another language-model agent. It records deadlines, claims,
attempts, evidence, misses, and restart generations without consuming model tokens while it waits.
Mutation is gated and receipt-backed so a failed approach can change without rewriting the user's
goal or erasing accepted work.

## Requirements

DE-67 is built specifically for **OpenAI Codex**. It is not an Anthropic or generic multi-agent skill.
It requires:

- the current Codex CLI with subagents and reasoning-effort selection;
- access to GPT-5.6 Sol, GPT-5.6 Luna, and GPT-5.6 Terra, including Sol at `ultra`;
- Python 3.10 or newer, using only the standard library;
- Git and a repository with an upstream branch for guarded routine checkpoints.

The repository is the complete skill package. Its router, phase instructions, templates, clock,
mutation guards, workspace setup, supervisor, and cross-platform Codex runner are kept together so
an agent can install the `de67` folder into the active Codex skills directory without relying on a
personal machine wrapper.

## Release and lab

This repository is the publishable DE-67 release. Before enabling method mutation, users should
create their own writable Git repository or fork for a `de67-lab` and install the skill from that
checkout. Accepted mutations are checkpointed there, giving the owner a reviewable history and a
safe place to rewind a harmful change. The folder name is not authoritative; the active checkout and
its Git history are. Stable changes can then be promoted deliberately into a public release instead
of turning every live experiment into an upstream change.

## Origin

DE-67-1 was inspired by the question-driven approach of
[Jekudy's GrillMe skill](https://github.com/Jekudy/grillme-skill). DE-67 reworks that idea into a
bounded product-intent phase and adds code-grounded specification, delivery, proof, deadlines, and
controlled method mutation for Codex software work.

DE-67 is licensed under [Apache License 2.0](LICENSE).
