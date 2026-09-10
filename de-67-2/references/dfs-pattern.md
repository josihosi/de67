# Portable DFS pattern

The DFS translates user-owned intent into a code-grounded behavioral contract. It states what the
product must do, which production mechanisms own it, what is missing, and what evidence proves it.
It is not a worker plan.

## Inspect before specifying

For each WEC behavior:

1. Locate the production entrypoint and trace the current call path.
2. Find the state declaration and every direct or indirect reader and writer.
3. Inspect defaults, configuration, serialization, migrations, caches, timers, schedulers,
   callbacks, error paths, debug hooks, and tests that can create or advance the same state.
4. Compare current behavior with the WEC. Credit only code reached by the production path; a helper
   or unit-tested structure is not implemented merely because it exists.
5. Record source identities precisely enough that a later coordinator can recheck drift.

Search beyond similarly named functions. Competing ownership often hides in generic update loops,
event handlers, save/load reconstruction, fallback behavior, optional automation, or test/debug
shortcuts.

## Write mechanisms, not aspirations

Each requirement should name, where applicable:

- files and symbols;
- function or method signatures and the parameters whose meaning changes;
- input facts and their source;
- preconditions and invariants;
- the authoritative state transition;
- outputs and postconditions;
- persistence, concurrency, error, retry, and compatibility behavior; and
- current implementation status with direct code evidence.

Do not prescribe a new function merely for symmetry. Name a new symbol only when the inspected code
has no suitable owner and the contract needs one.

## Preserve usable design reasoning

Transfer the understanding a later agent needs to make a good next decision. For a consequential
mechanism, explain the causal relationship, why the proposed change fits the inspected code, and
which competing explanation or tempting shortcut would fail the outcome. State the observation
that would invalidate the design or require reinspection. A worked transition or counterexample is
useful when it conveys this more clearly than another list of requirements.

Keep requirements and acceptance strength distinct from implementation tactics. Workers may change
tactics inside the frozen contract. Record a concrete starting route without making its command
order, helper names, or incidental steps additional acceptance gates.

Make this reasoning available where it is used: keep a red claim's mechanism, relevant owner
relationships, proof route, and source references together or linked by stable IDs. Reference shared
facts once. Omit unrelated implementation history, speculative alternatives, and empty template
fields. Concision means preserving decision value, not compressing away the explanation. Do not add
another handoff schema or prescribe the coordinator's context-management procedure.

## Resolve competing owners

For every affected state or action, build a compact ownership table:

| State or action | Readers | Writers / competing owners | Decision |
|---|---|---|---|
| `<state>` | `<files and symbols>` | `<files and symbols>` | `<authoritative owner; precedence and yield rule>` |

A complete decision states:

- who alone creates or advances durable truth;
- which existing systems may temporarily override an action;
- when control transfers and what identity/version binds the transfer;
- how the losing owner yields without mutating the winner; and
- how duplicate, stale, or replayed transitions become no-ops or failures.

Prefer shared physical or data primitives with separate policy owners over a universal state owner.

## Mark missing work

Use stable, unique identifiers and this exact opening form:

```markdown
- [ ] 🔴 R-001 — <missing, wrong, or unproved production behavior>
  - Code gap: `<file/symbol and present behavior>`
  - Required mechanism: `<smallest change that satisfies the contract>`
  - Proof: `<outcome test and observable evidence>`
```

Use `[x]` only for behavior present on the inspected production path with proportionate evidence.
Do not split one causal defect into several IDs merely to create more tasks. Do not hide an unproved
route behind a green helper test.

## Define outcome proof

Bind proof to the route the user or calling system will actually exercise:

```text
preconditions -> authoritative owner -> transition -> observable outcome -> artifact -> pass/fail
```

Include the smallest positive and negative controls that distinguish the claimed mechanism. Name
identity/provenance requirements when stale source, binaries, fixtures, or state could create a
false green. State disallowed shortcuts such as direct state setting, mocks, synthetic outcome
credit, or a competing owner advancing the transition.

## Freeze and refreeze

Record `Draft` while resolving code evidence and user-owned choices; record `Frozen` only after the
DFS is internally consistent and bound to an inspected source baseline. On refreeze, preserve each
durably accepted claim's terminal `Implementation status:` block and its `DE67:DELIVERY-STATUS`
receipt markers inside the stable DFS slice. Keep current requirements outside that replaceable
projection. Historical acceptance retains its original scope; new proof obligations remain red.
The workspace-setup compatibility check exercises the real projection against copied durable state.

After its named proof passes, automation may close an existing red item by changing it to `[x]` and
removing `🔴`. It may also make an evidence-implied nonmaterial clarification to an
existing red item, then must refreeze.

A phase-3 coordinator may also expand a frozen DFS when direct worker evidence reveals a blocker or
unexpected production result that no current claim classifies. Before doing so, re-inspect the exact
owner, helpers, callers, competing readers and writers, tests, relevant history, and natural route;
name the first contradicted DFS premise. Expansion is append-only with respect to existing stable
claims and may add only the uniquely implied same-contract mechanism, ownership or precedence fact,
proof route, and necessary new `- [ ] 🔴 R-...` claim. Preserve accepted work and immediately
refreeze. The worker reports the finding but cannot edit the DFS.

These exceptions cannot change product intent, vocabulary, permissions, required behavior, balance,
or acceptance strength. Multiple materially different designs, changed user-visible behavior, or an
ambiguous refinement requires DE-67-2 and the user.

Keep worker selection, task batching, deadlines, dispatch, mutation, and review procedure out of
the DFS. In particular, do not reproduce a multi-row coordination projection or handoff schema.
