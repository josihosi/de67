---
name: de-67-1
description: Develop an idea with the user through active discussion, concrete proposals, and focused questions, preserving an evolving WEC intent brief. Use for de67 1; do not start specification or delivery.
---

# de67 1 — develop the idea together

Stay in the current user-facing conversation. The result is `WEC.md`, subtitled **user intent and
language brief**. The user owns the intended outcome and language. This phase does not delegate the
conversation, inspect production call paths, or authorize specification, implementation, or mutation.

Use the shared [framing](../references/imagination-round.md) and
[MSW decision rule](../references/msw-kernel.md) when they are not already in context. Keep questions
and summaries in clear, natural language; consult the [writing guidance](../references/controlled-english.md)
only when an artifact needs it.

## Advance the conversation

Contribute thinking as well as questions. Turn the user's idea into a provisional picture of the
experience, offer a concrete example or possibility, and explain the consequential tradeoff or
hidden assumption it exposes. Invite correction. Distinguish the user's decisions from your
proposals; agreement with one example does not settle every detail around it.

Explore the layers that could change this idea: the normal user journey, the difficult case,
interacting responsibilities, what would make the result convincing, and where a small prototype
could settle uncertainty. For agentic work, consider what an agent must know at the decision point,
what can be retrieved later, and what must survive interruption or handoff. Follow the relevant
thread; these are lenses, not a checklist to run on every idea. Leave production ownership and
implementation design to phase 2 unless the user is explicitly choosing a product constraint.

Mix open conversation with structured multiple-choice questions. Use choices when concrete
alternatives help the user decide; offer a reasoned recommendation and allow a free answer. Use an
open invitation when the user is still discovering the idea. Ask the next consequential question
instead of handing the user a questionnaire or making them supply all the momentum. Answer the
user's own question before advancing yours.

Use visible project facts or a narrow read-only lookup when they settle a discussion choice. Research
only when its result could change the intended behavior, terminology, or boundary. Do not begin code
ownership tracing or fill missing product intent with an implementation you imagined.

## Preserve progress before the conversation is complete

Keep a concise evolving synthesis in the conversation: settled intent, proposed ideas, consequential
open choices, and the next useful question or reaction test. Refresh it when the idea materially
changes or the user pauses, asks for a draft, or returns later. Resume from that synthesis rather
than restarting the interview. Do not require every question to be answered before giving the user
a useful WEC draft. Label unresolved choices and assumptions visibly; do not turn them into consent.

When the intended outcome and boundaries are clear enough for code-grounded specification, use
[the WEC template](assets/WEC.md) to present the brief. Include only sections that help preserve this
idea. Carry prototype questions forward when further abstract discussion would not settle them.
No fixed question count or exhaustive discovery exercise is required.

Show the brief in chat. Save a file only when requested, as `WEC.md` outside the target repository or
at its top level, never directly as `.de67/WEC.md`. Phase 2 owns importing it. A draft or completed
WEC does not start phase 2 or phase 3.
