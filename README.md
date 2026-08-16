# de67

> When things become 67, you must de67.

Software work rarely fails because nobody can write another plan. It fails when the plan grows
sideways, tests become substitutes for the product, agents hand unfinished work around, and the
finish line quietly moves.

de67 is an OpenAI Codex skill for turning that drift back into a short path from an idea to working,
honestly proven code. It separates discussion, specification, and delivery so each phase receives a
small durable artifact instead of inheriting an expanding conversation.

## Three explicit phases

Invoke the phases as skill commands: `de67 1`, `de67 2`, and `de67 3`.

- **de67 1 — Discuss.** Focused questions turn the user's idea and language into `WEC.md`, without
  prematurely designing the implementation.
- **de67 2 — Specify.** A fresh specification owner inspects the real repository and turns the WEC
  into a frozen, code-grounded `.de67/DFS.md`.
- **de67 3 — Deliver.** Coordinators and workers implement the frozen DFS through deadline-bound
  work, production-route proof, independent failure diagnosis, and controlled mutation.

```text
WEC.md  ->  frozen DFS.md  ->  working, proven code
```

Phases never silently start one another. The user chooses the boundary, and accepted progress
survives coordinator or worker replacement.

## Lean coordination

de67 is deliberately hostile to coordination theatre. It tries to minimize prompt churn, handovers,
duplicated contracts, speculative documents, repeated tests, and agents reading material they do not
need. Ordinary work mostly uses GPT-5.6 Sol at low reasoning plus Luna and Terra workers selected for
the task. GPT-5.6 Sol at `xhigh` is reserved for ordinary independent mutation review, while the
rare universal mutation uses `ultra`, rather
than routine implementation.

The clock is deterministic Python, not another language-model agent. It records deadlines, claims,
attempts, evidence, misses, and restart generations without consuming model tokens while it waits.
Mutation is gated and receipt-backed so a failed approach can change without rewriting the user's
goal or erasing accepted work.

## Requirements

de67 is built specifically for **OpenAI Codex**. It is not an Anthropic or generic multi-agent skill.
It requires:

- the current Codex CLI with subagents and reasoning-effort selection;
- access to GPT-5.6 Sol, GPT-5.6 Luna, and GPT-5.6 Terra, including Sol at `xhigh` and `ultra`;
- Python 3.10 or newer, using only the standard library;
- Git and a repository with an upstream branch for guarded routine checkpoints.

The repository is the complete skill package. Its router, phase instructions, templates, clock,
mutation guards, workspace setup, supervisor, and cross-platform Codex runner are kept together so
an agent can install the `de67` folder into the active Codex skills directory without relying on a
personal machine wrapper.

## Optional integrations

Optional integrations live under `integrations/` and are not core DE67 dependencies. Each package
owns its transport-specific requirements, agent installation guidance, tests, and failure boundary.
Core discussion, specification, supervision, clocks, and delivery must keep working when every
integration is absent or broken.

The OpenClaw Discord blocker adapter is in `integrations/openclaw_discord/`. It can relay one genuine
blocked-only owner question and return one authenticated answer through a generic subprocess
contract. OpenClaw is not imported by core DE67 and is not required unless the owner explicitly
configures that adapter.

## Release and lab

This repository is the publishable de67 release. Before enabling method mutation, users should
create their own writable Git repository or fork for a `de67-lab` and install the skill from that
checkout. Accepted mutations are checkpointed there, giving the owner a reviewable history and a
safe place to rewind a harmful change. The folder name is not authoritative; the active checkout and
its Git history are. Stable changes can then be promoted deliberately into a public release instead
of turning every live experiment into an upstream change.

Release maintainers must follow `RELEASE_PROMOTION.md`. In particular, promote lab work by merging a
reviewed candidate into the release repository while preserving release history and tags; never
force-push or copy the lab worktree over the release repository.

## Attributions

- The MSW kernel comes from [@aienginerd on X](https://x.com/aienginerd).
- The imagination round comes from Josef Horvath.
- Phase de67 1's question-driven flow is based on
  [Jekudy's GrillMe skill](https://github.com/Jekudy/grillme-skill).
- Phase de67 1 uses [Simplified Technical English](https://en.wikipedia.org/wiki/Simplified_Technical_English)
  as a practical clarity influence for owner questions. de67 does not claim formal ASD-STE100
  conformance.
- The read-only Phase de67 3 trajectory sidecar was inspired by
  [Slopo's](https://github.com/rafal-qa/slopo) semantic code-similarity approach. de67's independent
  implementation adapts vector proximity to DFS gaps, diffs, tests, and accepted evidence; it does
  not include Slopo code.
- SolAdvisor also influenced de67's advisory approach to agent reasoning and review.

The WEC contract and de67's code-grounded specification, delivery, proof, deadlines, and controlled
method mutation were designed for this skill.

de67 is licensed under [Apache License 2.0](LICENSE).
