---
name: de-67-1
description: Explicit first phase of de67. Use when the user says `de67 1` to shape an idea through current-chat multiple choice and produce a user-owned WEC intent and language brief. Do not start specification authoring, coordination, workers, implementation, or mutation.
---

# de67 1 — discussion

Work only in the current user-facing chat. Do not create or delegate to an external discussion bot,
coordinator, reviewer, or worker. Do not read `de-67-2/` or `de-67-3/`.

Before any discussion, read `../references/imagination-round.md`,
`../references/msw-kernel.md`, and `../references/controlled-english.md` completely. Execute the
first two exactly as written. They are verbatim foundations; do not paraphrase, summarize, refactor,
or replace their wording. Apply the controlled-English guideline to owner questions and the WEC.

The outcome is `WEC.md`: an unexpanded WEC, subtitled **user intent and language brief**. It captures
what should exist and how the project should talk about it. It is not a functional specification or
a disguised task list.

## Grill the idea

Maintain a small decision frontier: only choices whose answers could materially change the desired
experience, boundary, terminology, implementation language, or later specification.

For each unresolved choice:

1. Use already-visible project facts or a narrow read-only lookup when that directly answers the
   choice. Do not trace production ownership, call paths, or implementation gaps; that is phase 2.
2. Ask one question at a time with the structured multiple-choice UI when available.
3. Offer two or three mutually exclusive choices. Put the recommended choice first and explain its
   consequence in one sentence. The user may always answer freely.
4. Reflect the answer briefly, update the frontier, and ask only the next dependent question.

Do not impose a round count. Stop when deleting every remaining question would leave the intended
outcome and language unchanged. If a question cannot be answered by discussion, record a small
prototype or reaction check in the WEC instead of grilling indefinitely.

Prefer concrete user-visible contrasts over abstract architecture questions. Ask about internal
mechanics only when the user owns that choice; otherwise leave phase 2 to inspect the code and choose
the smallest compatible mechanism.

## Write the WEC

When the frontier is empty, read `assets/WEC.md` and fill its sections in concise Markdown. Preserve
the user's own words for names, tone, and important constraints. Separate settled decisions from
prototype questions. Do not invent requirements to make the document look complete.

Show the finished WEC in chat. If a file handoff is requested, save it as `WEC.md` outside the target
repository or at that repository's top level—never directly as `.de67/WEC.md`. Phase 2 owns moving
or importing it to `.de67/WEC.md`. End after the WEC; invoking phase 1 does not authorize phase 2 or
phase 3.
