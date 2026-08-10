---
name: de-67-2
description: "Create and freeze a code-grounded functional specification (DFS) from WEC.md. Use only when the user explicitly invokes `$de-67-2` or says `DE-67-2`; never trigger this phase implicitly."
---

# DE-67-2 — functional specification

Run only after an explicit `DE-67-2` or `$de-67-2` invocation.

## Phase boundary

- Accept `WEC.md` as the only cross-phase input.
- Preserve it as `.de67/WEC.md` and produce `.de67/DFS.md`; the frozen DFS is phase 3's required
  handoff.
- Do not read or require phase-1 or phase-3 instructions, folders, ledgers, or artifacts.
- Preserve the user's product intent and project language from `WEC.md`. Only the user may change
  either.
- Change no product code or tests in this phase.

## Workflow

1. Identify the working repository, obey its local instructions, and record the inspected branch,
   HEAD, and relevant dirty state.
2. Import `WEC.md` into `.de67/WEC.md`. Move a local source file; copy exact content only when the
   input is an attachment or chat artifact. If the destination already exists, reuse it when
   identical and stop for user resolution when it differs. Never overwrite it silently.
3. Read `.de67/WEC.md` completely. Inspect the real implementation before specifying changes:
   entrypoints, declarations, call sites, readers, writers, persistence, schedulers, tests, and
   relevant configuration.
4. Read [references/dfs-pattern.md](references/dfs-pattern.md) completely and use
   [assets/DFS.md](assets/DFS.md) as the output template.
5. For every affected state or action, identify every current reader, writer, and competing owner.
   Decide and document the authoritative owner, precedence, yield/override rules, and atomic or
   idempotent boundaries. Ask the user when a decision would alter product intent or vocabulary;
   otherwise make the smallest code-grounded design decision that satisfies the WEC.
6. Write `.de67/DFS.md` mechanistically. Name concrete files, symbols, functions, parameters,
   inputs, outputs, preconditions, transitions, postconditions, failure behavior, and persistence
   effects. Mark every absent, wrong, or unproved requirement with a stable line beginning
   `- [ ] 🔴 R-...`. Define the outcome test and production proof that closes each red item.
7. Check the DFS against the current code again, resolve internal contradictions, record its source
   baseline, and freeze it.

## Frozen DFS

After freeze, automated edits are limited to:

- changing an existing `- [ ] 🔴 R-...` item to `[x]` and removing `🔴` after named evidence proves
  that exact requirement; and
- an evidence-implied, nonmaterial clarification to an existing red requirement, followed by an
  immediate refreeze; and
- a phase-3 coordinator expansion after a worker reports a blocker or unexpected production result
  that the current DFS cannot classify. The coordinator must re-inspect the production owner,
  helpers, callers, competing readers and writers, tests, history, and natural execution path. It
  may then append only the uniquely implied same-contract mechanism, ownership decision, proof
  route, and necessary new stable red claim before immediately refreezing.

Those refinements may classify the same behavior or proof boundary. They may not add product
behavior, change project language or permissions, weaken acceptance, rewrite or close an existing
claim, or legitimize an implementation shortcut. A worker reports evidence but never edits or
refreezes the DFS. An ambiguous refinement, multiple materially different designs, or any material
change returns to DE-67-2 and the user.

Do not add task slots, worker profiles, deadlines, dispatch packets, proof-review payloads, or a
coordination matrix to the DFS. Those are not functional specification.
