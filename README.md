# DE-67

> **D** is the 4th letter. **E** is the 5th. Then comes **6, 7** — one step past Order 66.

Sometimes work stops proceeding in order: the plan grows sideways, tests repeat, agents hand the
problem around, and the finish line quietly moves away. DE-67 turns that drift back into a path from
an idea to working, honestly proven code.

DE-67 has three explicit phases. The router opens only the phase you invoke:

- `DE-67-1` — **Discuss.** Shape the idea through focused multiple choice and produce `WEC.md`, the
  user's intent and language brief.
- `DE-67-2` — **Specify.** Inspect the real code and turn the WEC into a code-grounded, frozen
  `.de67/DFS.md`.
- `DE-67-3` — **Deliver.** Implement the frozen DFS with deadline-bound work, independent failure
  review, and controlled mutation that preserves accepted progress.

The artifacts form the handoff:

```text
WEC.md  ->  frozen DFS.md  ->  delivery and mutation
```

A phase never silently starts the next one. Invoke the phase you need in chat:

```text
DE-67-1
DE-67-2
DE-67-3
```

Start with phase 1 for a new idea, phase 2 when the WEC exists, or phase 3 when the DFS is frozen and
ready to build.
