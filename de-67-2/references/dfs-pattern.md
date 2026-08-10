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
DFS is internally consistent and bound to an inspected source baseline.

After its named proof passes, automation may close an existing red item by changing it to `[x]` and
removing `🔴`. It may also make an evidence-implied nonmaterial clarification to an
existing red item, then must refreeze. That exception can clarify the same failure/proof boundary;
it cannot change product intent, vocabulary, required behavior, balance, or ownership. Any material
change or an ambiguous clarification requires the user.

Keep worker selection, task batching, deadlines, dispatch, mutation, and review procedure out of
the DFS. In particular, do not reproduce a multi-row coordination projection or handoff schema.
