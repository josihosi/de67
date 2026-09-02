---
name: de67-alignment-audit
description: Manually audit an agentic workflow for contradictory instructions, misleading machine output, and tests that constrain model judgment. Use only when the user asks for an alignment audit or an equivalent review; this is not a de67 phase or a runtime gate.
---

# de67 alignment audit

This is a manual, read-only review surface. It asks whether the complete context presented to an
agent supports the intended outcome. It does not run de67, change a live loop, or authorize fixes.

Before auditing, read:

- [Alignment manifest](references/alignment-manifest.md) for the review principles.
- [Reviewer brief](references/reviewer-brief.md) for scope, delegation, evidence, and reporting.

## Bind the audit

Identify the repository or installed skill, the workflow being reviewed, and whether a live agent
machine is in scope. Preserve explicit exclusions. If a live loop exists, inspect it without
launching, stopping, consuming one-use authority, or changing durable state.

Start from active routing, not a repository-wide Markdown reading exercise. Trace the path a real
agent receives today:

1. applicable `AGENTS.md` or equivalent host/repository policy;
2. selected skill entrypoint and only the references it routes into;
3. active coordinator and worker briefs, ledgers, contracts, or charters;
4. generated prompts, descriptors, action menus, errors, status, and dashboard/TUI output;
5. tests that enforce those active paths.

Classify a discoverable surface as active authority, useful non-authoritative reference, or legacy
residue. Ignore unrelated product documentation. Legacy material matters only when active routing,
search instructions, examples, or ordinary discovery can realistically present it as current
guidance; recommend deletion, relocation, or an unmistakable non-authoritative marker when it can.

## Audit the joined workflow

Compare prose, runtime affordances, machine responses, and executable tests as one instruction
system. Separate mechanical invariants from model judgment. Durable identity, ownership, leases,
single-use transitions, immutable evidence, cleanup, and truthful process state may be strict.
Strategy, wording, task order, proof presentation, and repair choice normally belong to capable
agents unless the requested outcome establishes a real constraint.

Trace every suspected contradiction through the exact active runtime branch before reporting it.
A flag, phrase, historical test, or similarly named mode is not proof that the live workflow uses
it. Identify the step type, caller, inputs, emitted output, consumer, and resulting behavior. When
observed behavior contradicts a static-code inference, investigate the discrepancy and narrow or
withdraw the finding.

Report only findings whose removal or correction is necessary to align the audited workflow with
the manifest and requested outcome. Each finding must identify:

- the active instruction or machine output;
- the concrete conflicting surface or behavior;
- the manifest principle affected;
- a reproducible failure scenario;
- the smallest structural correction;
- the evidence and any remaining uncertainty.

Do not implement corrections unless the user separately asks. End with what should remain strict,
what should become agent judgment, and which apparent concerns were rejected after tracing them.
