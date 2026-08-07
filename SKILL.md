---
name: de67
description: Explicit-call two-gate functional-specification and coordination kernel. Use only when the user invokes `$de67` to have the user-facing Codex collect a brief, then—with explicit consent—launch an xhigh specification author to create and freeze the authoritative functional/technical specification, and—with fresh explicit consent—launch a new xhigh coordinator to run a bounded window of atomic implementation tasks.
---

# DE67

v0.4. Turn a request into one held specification, then into small proved work.

## Graph

```text
user <-> F : dialogue, evidence, brief B, consent
B --consent_S--> Q_S{xhigh} : create + hold + freeze S
S --consent_C--> Q_C{xhigh} : hold S + write L{atomic, open<=10} + route W
W_i : one worker, one atomic slot, one proof
```

`F` is the user-facing Codex conversation, not a worker model. `Q_S` and `Q_C` are fresh xhigh
calls. The `$de67` call opens only `F -> B`; each arrow marked `consent` requires a new explicit
user approval bound to the displayed configuration.

## Gate S: create the specification

Have `F` inspect task-relevant evidence and write only a non-normative brief:

```text
B = (goal, current evidence, proposed worktree/branch, unknown owner choices)
```

Display the exact `Q_S` model/effort and ask: “May I start the xhigh specification author?” Stop
until approved.

Have `Q_S` create and hold normative `S`. Before every material `dS`, bind:

```text
I = (why_now, intended_workflow, real_user_path, fake_or_broken, decisive_edge)
```

If `I` exposes an owner choice, send `F` one recommended question with two or three disjoint
options. Let `F` ask through structured input when available and relay the answer.

Write one specification containing only needed sections:

```text
S = (C, E, D, O, A, R)
C = contract; E = inspected facts; D = decisions; O = authoritative owners;
A = acceptance/proof; R = stable unresolved claims
```

Give every red claim an ID. Attach its proof route:

```text
proof(R_i) = preconditions -> production owner -> transition -> artifact -> pass/failure
```

Commit or trace accepted `S` revisions when the project contract calls for it. End with the frozen
specification revision and proposed `Q_C` configuration; do not dispatch implementation.

## Gate C: coordinate the specification

Have `F` display the frozen `S` revision, worktree/branch, `Q_C` model/effort, Prompt A, and the
initial current window. Ask: “May I start the xhigh coordinator for this specification?” Stop until
approved.

Have fresh `Q_C` reread and hold `S`. Accept `dS` only when new evidence breaks `S`; return material
owner choices through `F`.

Before runtime preflight, perform a tooling sufficiency check for the current slot:

```text
U = (observe, stimulate, discriminate, capture)
```

For each required proof, name the smallest existing harness/debug capability that can observe the
authoritative transition, provide any legitimate stimulus, distinguish success from setup noise,
and capture bounded evidence. If a component of `U` is missing, add only the smallest reusable
adapter needed for this slot, then trace it through the changed executable to real game state and
prove the adapter separately. An adapter may expose or observe state; it must not directly set the
claimed gameplay outcome or replace the production route. If `U` cannot be completed without
inventing a generic debug system or bypassing authority, preserve the slot and report the exact
tooling blocker before dispatching a worker.

Preflight the actual executor before dispatch:

```text
H = (source, binary, fixture, profile, credential/provider, harness/tool route)
```

Dispatch only when `H` can reach the claimed route. Otherwise report the first named infrastructure
blocker and preserve the slot; do not spend a worker proving around an unavailable runtime.

Choose current red claims `R_A` from the active roadmap seam, not from the whole specification.
Write a current ledger `L` of zero to ten open slots:

```text
T_i = (R_i, O_i, W_i, P_i, proof_i)
atomic(T_i) = one owner transition + one merge proof
open(L) <= 10
```

The ceiling limits the current window; it is neither a target nor a whole-FS partition. When new
evidence closes or moves `R_A`, derive the next window from current `S`.

Run slots in parallel only when their likely write sets `W`, authoritative owners `O`, and mutable
proof artifacts `P` are disjoint. Unknown intersections serialize.

Select the weakest sufficient worker:

| Profile | Use for |
|---|---|
| Luna medium | narrow mechanical change |
| Luna high | tricky focused proof or fixture |
| Terra medium | multi-file change behind a frozen interface |
| Terra high | coupled production ownership or wiring |
| Sol medium | unresolved owner arbitration or final adversarial review |

## Execute and prove

Use the same worker for its slot’s remediation:

```text
assign -> receipt -> diff + evidence -> Q_C gate -> remediate | close
```

Admit an action, test, or review finding only when deleting it leaves the slot contract unmet or
unproved. Close only when:

```text
G = exact(source,binary,fixture) ∧ setup_before_claim ∧ authoritative_route
    ∧ discriminating_control ∧ production_provenance ∧ not_test_only_credit
```

Apply `G` per slot and to the integrated result. A `G` failure returns the same slot; it does not
create a detached test program or speculative new lane.

## Benchmark record

For a benchmark, report start/dispatch/end timestamps, model profiles, concrete milestones,
diff/commit identities, proofs run, remediation cycles, loop evidence, and token use only when the
runtime exposes it. Report unavailable measurements as unavailable.
