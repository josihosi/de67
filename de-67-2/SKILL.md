---
name: de-67-2
description: "Create and freeze a code-grounded functional specification (DFS) from WEC.md. Use only when the user explicitly says `de67 2`; never trigger this phase implicitly."
---

# de67 2 — functional specification

Run only after an explicit `de67 2` invocation.

Read `../references/msw-kernel.md` completely and execute it exactly as written. It is a verbatim
foundation; do not paraphrase, summarize, refactor, or replace its wording.

## Phase owner

The invocation agent delegates this whole phase once to a fresh owner using
`fork_turns="none"`, `model="gpt-5.6-sol"`, and `reasoning_effort="high"`. Give it only the
workspace, the WEC source or exact WEC text, and this phase's `SKILL.md` path. Mark it as the phase
owner so it does not delegate ownership again. That owner inspects, specifies, freezes, prepares
the workspace, and checkpoints the result; the invocation agent does not duplicate its work.

## Phase boundary

- Accept `WEC.md` as the only cross-phase input.
- Preserve it as `.de67/WEC.md` and produce `.de67/DFS.md`; the frozen DFS is phase 3's required
  handoff.
- Do not read or require phase-1 or phase-3 instructions, ledgers, or artifacts. The shared
  workspace-setup helper is infrastructure, not another phase's instructions.
- Never inventory or read an existing `.de67/no-go-zone/`.
- Preserve the user's product intent and project language from `WEC.md`. Only the user may change
  either.
- Change no product code or tests in this phase.

## Workflow

Treat these as outcome gates, not a packet-writing script. Use code-grounded judgment inside each
gate and create no coordination artifact unless it is named here.

1. Identify the working repository, obey its local instructions, and record the inspected branch,
   HEAD, and relevant dirty state.
2. Import `WEC.md` into `.de67/WEC.md`. Move a local source file; copy exact content only when the
   input is an attachment or chat artifact. If the destination already exists, reuse it when
   identical and stop for user resolution when it differs. Never overwrite it silently.
3. Read `.de67/WEC.md` completely.
4. Audit only active workflow or specification documents at the repository root or directly named
   by authoritative agent guidance. Preserve `AGENTS.md`/`Agents.md`, contributing and licence
   files, `README.md`, technical/design documentation, product code, tests, and unrecognized docs.
   Carry still-binding product requirements into WEC/DFS when they preserve the user's intent;
   ask when they would change it. Move only competing plan/specification/coordination history to
   tracked `.de67/no-go-zone/<original-relative-path>`. If authoritative guidance directly points
   to a moved plan, reconcile that reference with the current WEC/DFS flow. Do not broadly delete
   or archive documents.
5. Inspect the real implementation before specifying changes:
   entrypoints, declarations, call sites, readers, writers, persistence, schedulers, tests, and
   relevant configuration.
6. Read [references/dfs-pattern.md](references/dfs-pattern.md) completely and use
   [assets/DFS.md](assets/DFS.md) as the output template.
7. For every affected state or action, identify every current reader, writer, and competing owner.
   Decide and document the authoritative owner, precedence, yield/override rules, and atomic or
   idempotent boundaries. Ask the user when a decision would alter product intent or vocabulary;
   otherwise make the smallest code-grounded design decision that satisfies the WEC.
8. Write `.de67/DFS.md` mechanistically. Name concrete files, symbols, functions, parameters,
   inputs, outputs, preconditions, transitions, postconditions, failure behavior, and persistence
   effects. Mark every absent, wrong, or unproved requirement with a stable line beginning
   `- [ ] 🔴 R-...`. Define the outcome test and production proof that closes each red item.
9. Check the DFS against the current code again, resolve internal contradictions, record its source
   baseline, and freeze it.
10. Prepare and prove the native worker choices needed by phase 3. Preserve any existing project
   configuration while setting the trusted project's `.codex/config.toml` agent default to Luna;
   do not pin a default effort:

   ```toml
   [agents]
   default_subagent_model = "gpt-5.6-luna"
   ```

   Start a fresh probe coordinator after that configuration exists. A Luna probe omits `model` and
   supplies `reasoning_effort`; a Terra probe supplies both `model="gpt-5.6-terra"` and
   `reasoning_effort`. Every probe uses `fork_turns="none"` and a unique task-local nonce prompt;
   success means it returns that nonce without inherited conversation. Probe only useful pairs, but
   prove both models and more than one effort level. Record only successful model/effort pairs. If
   the installed runner rejects the project agent default, update that runner to a compatible
   version and repeat the probes; do not invent an alias, a custom role taxonomy, or a model matrix.
11. After freeze, perform the one-time workspace setup. Ensure `.de67/state/` is ignored, keep the
   current branch's configured upstream as the sole managed automatic target. A checkpoint repository
   is pushed only as a separate one-shot action after the user explicitly requests it; never persist
   it in the hook or clock configuration. Run:

   ```text
   python <parent-of-this-phase-folder>/scripts/workspace_setup.py setup --workspace . --target REMOTE BRANCH --worker-capability MODEL REASONING_EFFORT [--worker-capability MODEL REASONING_EFFORT]
   ```

   The helper binds one stable lineage clock, records its machine-only configuration under
   `.de67/state/`, installs a guarded post-commit upstream hook, and immediately pushes the
   already-committed backlog. It never commits, switches branches, force-pushes, or launches a
   coordinator. A dirty tree is allowed because only committed `HEAD` is pushed. If the upstream,
   remote URL, branch, or an existing unmanaged hook conflicts, stop and report it rather than
   weakening the guard. If setup succeeds but only its immediate backlog push fails, continue with
   the scoped local commit below; the hook preserves the failure status and retries on the next
   commit. Git setup is outside the DFS and does not add dispatch policy to it.
   The machine-only configuration records the successful worker pairs; it is an availability roster,
   not a worker profile or dispatch policy.
12. Checkpoint only `.de67/WEC.md`, `.de67/DFS.md`, the proved `.codex/config.toml` agent default,
   required no-go-zone moves and direct reference reconciliation, and a required ignore-rule
   change; preserve every unrelated dirty path. The installed hook pushes that commit, so do not run
   a second routine push.

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
change returns to de67 2 and the user.

Do not add task slots, worker profiles, deadlines, dispatch packets, proof-review payloads, or a
coordination matrix to the DFS. Those are not functional specification.
