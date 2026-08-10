# DE-67-3 kernel

This is the compact invariant layer. The two guideline bodies may evolve; these laws do not.

## Working state

```text
S = (C, E, D, O, A, R)
```

- `C`: user-facing contract and project language.
- `E`: current code and observed facts.
- `D`: design decisions.
- `O`: authoritative state owners and precedence over competing systems.
- `A`: acceptance conditions and honest proof routes.
- `R`: stable red work claims.

The DFS owns `S`. The work ledger is only a current projection of `R`.

```text
active(work ledger) <= min(10, remaining_red(DFS))
```

Ten is an explicit ceiling. It is not a quota, batch target, or reason to combine tasks.

## Necessity and proof

Admit a task, test, mutation, or review only when deleting it would leave a requested outcome unmet
or unproven. Close it once the smallest reliable evidence proves it. Re-proving closed work or adding
handoff fields that do not change the decision is waste.

An honest proof route is:

```text
precondition -> authoritative owner -> transition -> observation -> artifact -> verdict
```

Focused tests can isolate a seam. They do not replace a required natural or integrated route.

## Roles and parallelism

The coordinator plans, dispatches, checks evidence, updates ledgers/DFS, diagnoses, and mutates
guidance. Workers implement, build, test, or operate. A coordinator may perform read-only code
investigation, but it does not quietly become an implementation worker.

Parallel work is admissible only when code, state, dependencies, and proof surfaces do not collide.
Unknown ownership is a dependency to investigate, not permission to race.

## Per-task clock

For task `i`:

```text
deadline_i = actual_dispatch_i + evidence_based_estimate_i
```

Once recorded, `actual_dispatch_i`, `deadline_i`, task identity, claim identity, and lineage cannot be
reset or renamed. Completion after the deadline does not subtract the miss.

```text
deadline miss                 -> miss_units += 1
integrity breach              -> miss_units += 3
broader mutation is due       <=> floor(new_units / 3) > floor(old_units / 3)
```

Thus ordinary cumulative misses 3, 6, 9, ... mutate both guidance files. Every incident still gets
its own independent causal review.

## Mutation transaction

```text
incident
  -> independent review
  -> append short verdict + full diagnosis + suggestion
  -> compare all earlier short verdicts
  -> mutate task/test guidance
  -> if broader cadence: mutate orchestrator guidance too
  -> validate frozen headings and scope
  -> fresh coordinator
  -> continue from accepted product frontier
```

The diagnosis identifies the first contradicted premise, not merely the last visible error. Inspect
the real source owner, helpers, other readers/writers, callers, tests, relevant history, tooling, and
the difference between a focused setup and natural execution.

## Controlled DFS mutation

Status mutation is exact:

```text
- [ ] 🔴 R-123 — requirement
+ [x] R-123 — requirement
```

It is allowed only after accepted evidence. A non-material clarification `dS` is allowed only when:

```text
continuous(dS | S, evidence)
  <=> deleting dS leaves the evidenced failure unclassified or its proof undefined
      AND user contract and project language are unchanged
      AND permissions and acceptance strength are unchanged
      AND exactly one admissible refinement remains
```

When worker evidence cannot be classified by the current DFS:

```text
worker finding
  -> source-grounded causal review
  -> first contradicted DFS premise
  -> minimal dS
  -> necessity test
  -> proof route and new stable red claim
  -> structural validation
  -> refreeze
  -> fresh coordinator
```

The source review covers the production owner, helpers, primitives, callers, competing readers and
writers, owning tests, relevant history, and natural execution. `dS` may append only a uniquely
implied same-contract mechanism, ownership/precedence fact, proof route, and necessary red claim.
Every existing claim and the accepted product frontier remain byte-stable in identity, text, order,
and status. A worker reports evidence but cannot author `dS`.

```text
dS ∩ guidance_policy_change = ∅
```

A finding before its deadline can activate `dS` without a miss. A late finding can independently
activate both `dS` and the deadline mutation. Task, test, tooling, evidence, or external-authority
gaps are not specification gaps. Otherwise return to DE-67-2 for user-owned refreeze.

## Fitness

Fitness is lexicographic:

```text
deliver the requested behavior
  > preserve correctness and proof
  > reduce elapsed time, tokens, and handoff surface
```

An efficient wrong result is unfit. Among equally correct routes, prefer the leaner route. A failure
must improve the causal guidance before retry; mutation volume is not fitness.

## Persistence

Accepted code and green claims form the product frontier. A failed candidate has no descendants, but
its causal evidence remains in the mutation ledger. No miss, mutation, reviewer result, or coordinator
retirement ends the DFS program while a red claim has an authorized materially different route.
