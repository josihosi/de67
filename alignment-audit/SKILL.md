---
name: de67-alignment-audit
description: Audit an agentic workflow for contradictory context, misleading machine output, unnecessary reading, and rules or tests that obstruct agent judgment. A manual review, not a de67 phase or runtime gate.
---

# de67 alignment audit

Use the [alignment manifest](references/alignment-manifest.md) as a review lens. The requested outcome
owns the audit's scope; the manifest does not create extra work or runtime authority. An audit is
read-only unless correction work is already authorized in the current task. Keep findings and
implemented corrections distinct.

## Follow the context an agent actually receives

Bind the repository or installed skill, workflow, live-runtime scope, and explicit exclusions.
Start from active routing: applicable host/repository guidance, the selected entrypoint and its
necessary references, generated coordinator/worker briefs, current state, machine responses, and
consumer code or tests. Follow historical material only when an active path exposes it as relevant
or authoritative. Do not inventory unrelated documentation or `.de67/no-go-zone/`.

Trace a suspected defect from producer through emitted context to the consuming decision. Inspect
what the agent receives before it acts, what it can retrieve, and what survives waiting, handoff,
mutation, or restart. Check whether necessary information is deferred until too late, dropped
before consumption, repeatedly rediscovered, or displaced by old history. A compact response is
useful only if it preserves the next decision and makes its full evidence reachable.

Distinguish active authority, useful reference, and legacy residue. File size, a strict phrase, a
symbol name, or a stale test is not a finding by itself. Use a focused reproduction when behavior is
uncertain; a direct instruction contradiction may be established from the exact emitted text and
its applicable authority. Do not claim a runtime failure from static inspection alone. Narrow or
withdraw a finding when the actual route contradicts it.

For a large workflow, independent reviewers may inspect separate owners concurrently. Give each
reviewer the manifest, exact roots and entrypoints, exclusions, and its producer/consumer boundary.
Choose a model and effort appropriate to that question. Do not duplicate the same broad read across
reviewers. Reviewers do not launch scenarios, consume authority, wake or stop agents, or mutate live
state. The lead resolves disagreements against the actual route.

## Judge structure by what it enables

Preserve mechanical truth: identity, ownership, single-use transitions, durable evidence, honest
cleanup, and contradictions. Strategy, retrieval depth, task order, wording, and repair choice belong
to agents unless a real product or safety constraint requires otherwise. Examine tests for the same
boundary; a test can preserve an accidental process just as prose can.
For worker dispatch, include the manifest’s model and reasoning-effort judgment lens: follow the
available options and selection directive through the actual call, then assess outcomes and cost.

Report the necessary corrections with enough evidence to connect the active surface, affected
outcome, demonstrated failure or uncertainty, and smallest remedy. Do not fill a fixed finding form
when a short explanation proves the point. Include important rejected concerns when they change the
conclusion. End with what should remain strict and what judgment should return to agents.

Do not promote the audit or manifest into an automatic approval gate, recurring runtime read, or
another coordinator. Apply authorized corrections only within their scope; otherwise present them
for the user's decision.
