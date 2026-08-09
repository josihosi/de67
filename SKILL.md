---
name: de67
description: Explicit-call two-gate functional-specification and artifact-first coordination kernel. Use only when the user invokes `$de67` to create or refine a held functional specification, thenâ€”after separate explicit consentâ€”run an xhigh coordinator that assigns rolling windows of atomic work to workers, gates compact evidence, and continues until the specification is proved or genuinely blocked.
---

# DE67

v0.6. Hold one specification; coordinate workers through small, proved windows without ingesting
their execution streams.

## Roles and consent

```text
user <-> F
F --consent_S--> Q_S{xhigh} : author and freeze S
F --consent_C--> Q_C{xhigh} : coordinate S
Q_C --> W_i : implement and prove one slot
W_i --> Q_C : compact receipt J_i
```

`F` is the user-facing Codex. `Q_S` and `Q_C` are fresh xhigh calls. Invoking `$de67` opens only the
briefing step. Display the exact model, effort, branch/worktree, and proposed action before each
consent gate. Never infer Gate C consent from Gate S consent.

`Q_C` coordinates. It may hold `S`, propose `dS`, write the ledger and proof contracts,
inspect targeted diffs and receipts, and accept or reject work. It must not implement product,
test, harness, or debug-tool code; build binaries; operate the live application; or run a worker's
test loop. Assign every execution slot to a worker. If no suitable worker can run, report that as
the executor blocker instead of becoming the worker.

## Gate S â€” specification

Have `F` inspect relevant evidence and prepare only:

```text
B = (goal, facts, branch/worktree, unknown owner choices)
```

After consent, have `Q_S` perform the imagination round before every material specification change:

```text
I = (why_now, intended_workflow, real_user_path, fake_or_broken, decisive_edge)
```

If `I` exposes a material owner choice, return it through `F` with one recommended question and two
or three disjoint options. Write one normative specification:

```text
S = (C, E, D, O, A, R)
C = contract              E = inspected facts
D = product decisions     O = authoritative state owners
A = acceptance/proof and execution policy
R = stable red claims
```

In `A`, name any required integrated proof; authorized limits and their authority; the applicable
MSW fuse policy and its authority; and the execution acts Gate C may propose. If no authoritative
fuse, cap, or integrated proof applies, record noneâ€”never invent one.

Give every `R_i` a stable ID and production proof route:

```text
proof(R_i) = preconditions -> owner -> transition -> observable fact -> artifact -> pass/fail
```

Trace accepted revisions as the project requires. Freeze `S`, propose the exact Gate C
configuration, and stop. Do not dispatch implementation from Gate S.

## Gate C â€” ledger

`Prompt A` is the context-minimized Gate C packet: the frozen `S`, applicable DE67 coordination
rules, branch/worktree identity, granted acts, and proposed initial window. It excludes the prior
conversation and worker transcripts.

Have `F` display the frozen `S` revision, branch/worktree, exact `Q_C` model and effort, Prompt A,
proposed initial window, and allowed acts per slot: `edit`, `test_build`, `live`, and `commit`. Ask
for explicit Gate C consent and stop until granted. An act is denied unless that consent or an
applicable project authority grants it; a worker returns `blocked` instead of substituting another
act.

After fresh consent, have `Q_C` reread and hold the frozen `S`. Select the next necessary red claims
and write only necessary atomic slots, subject to the window cap and authority recorded in `S.A`.
For this DE67 definition, the requester-set ceiling is ten; record that provenance. Ten is not a
target. Never add filler.

```text
T_i = (R_i, owner, write_set, proof_artifacts, hypotheses, discriminator,
       worker_profile, allowed_acts, pass_test, coordinator_gate)

atomic(T_i) = one authoritative transition + one slot acceptance proof
```

Write the pass test before dispatch. `Q_C` specifies what must be proved; the worker writes any
necessary test code and executes it. Run slots concurrently only when owner, write set, and mutable
proof artifacts are disjoint. Unknown overlap serializes.

Before dispatch, bind the critical path:

```text
P_i = (next_coordinator_decision, worker_output_needed, nonoverlapping_Q_C_work)
```

`nonoverlapping_Q_C_work` is limited to ledger maintenance, dispatch-packet preparation, receipt
gating, and bounded diff/selector inspection. It never includes edits, builds, tests, live
operation, or duplication of a worker task.

Dispatch only when the worker owns a bounded sidecar or isolated write scope needed by that next
decision. Never assign the same investigation or implementation to both `Q_C` and a worker. If the
worker result blocks the next decision, wait for its receipt rather than duplicating the work.

Choose the weakest sufficient profile:

| Profile | Use |
|---|---|
| Luna medium | mechanical local change |
| Luna high | focused fixture, proof, or tricky local change |
| Terra medium | multi-file work behind a stable interface |
| Terra high | coupled production ownership or wiring |
| Sol medium | unresolved owner arbitration or bounded named acceptance risk |

Resolve the requested profile against actually exposed worker capabilities before dispatch. Never
claim a role, model, or effort ran unless runtime metadata proves it. If no available profile is
sufficient under the granted authority, return the executor blocker rather than silently falling
back.

Use an isolated worker worktree/branch when exact binary provenance or experimental instrumentation
would otherwise dirty the coordinator's canonical tree. Promote only accepted slot output. Do not
commit transient diagnostic variants to the canonical development branch. Isolation does not prove
merge safety; ledger write-set ownership remains authoritative.

Construct a context-minimized dispatch packet:

```text
D_i = (slot, necessary_S_extract, owner, write_set, interfaces, git_base,
       allowed_acts, pass_test, artifact_destination, J_schema, forbidden_actions)
```

Use no inherited conversation when `D_i` is sufficient; otherwise include only the turns necessary
to understand the slot. Every worker prompt must carry `D_i` and prohibit raw-output return. An
ambiguity outside `D_i` returns as `blocked`; the worker must not redesign the architecture, broaden
the slot, or invent another diagnostic lane.

On a failed spawn, inspect worker capacity once at the dispatch boundary: reuse or close completed
workers, wait for relevant live workers, or report the executor blocker. Never fall back to local
implementation by `Q_C`.

## Tooling and causal preflight

Before dispatch, bind:

```text
U = (observe, stimulate, discriminate, capture)
H = (source, binary, fixture, profile, provider, tool_route)
K = (competing_hypotheses, existing_discriminators, chosen_discriminator, expected_branch)
```

Name the smallest existing capability that supplies each component of `U`. Add a tooling adapter
only when existing artifacts cannot discriminate `K`. An adapter may expose state, select an
existing subject, or capture evidence; it must not set the claimed outcome, replace the production
owner, alter scenario geometry/timing, or create a second truth owner.

Reject a diagnostic whose result would merely request another unspecified diagnostic. Every
diagnostic must decide a named branch in `K`. Prefer offline artifact analysis and focused
production-owner tests before another complete live lifecycle. Use a full live run only when it is
the cheapest remaining discriminator or the final integration proof.

## Artifact-first execution

Workers own builds, waits, live interaction, and verbose output. Redirect raw stdout/stderr and
large reports to artifact files. A flag named `compact` is not proof that returned output is small;
verify the actual tool boundary. Neither worker nor coordinator should ingest raw run streams when
a selector can decide the claim.

Return one fixed-schema receipt:

```text
J_i = (slot, status, observed_worker_identity,
       worktree, git_base, git_head, git_status,
       changed_paths, source_binary_fixture_identity,
       verdict, decisive_facts, first_failure, artifact_paths, changed_evidence,
       judgment_calls_if_material, gaps_if_blocking)
```

`decisive_facts` contains only facts needed by the pass test. `artifact_paths` point to the complete
logs, screenshots, JSON, and reports. `changed_evidence` states why a retry can answer something the
previous attempt could not.

```text
valid(J_i) := no embedded raw log, transcript, source/diff listing, report JSON,
              or multi-line OCR dump
```

Represent evidence with identities, verdict facts, selectors, hashes, and paths. Reject an invalid
receipt and request the named selector; do not summarize its embedded dump inside `Q_C`.

`Q_C` reads `J_i`, a targeted diff for the slot's write set, and the smallest named extraction that
settles a disputed fact. It must not read the worker transcript, an entire probe report, a full
build log, a recursive artifact dump, or an unbounded source/diff listing. If a receipt is
insufficient, return a precise extraction request or correction to the same worker. Never silently
repair a worker patch. Claim the requested model/profile only when runtime metadata establishes the
observed worker identity. The worker owns long waits; `Q_C` waits for its receipt without polling,
narrating unchanged progress, or replaying output.

## Remediation and fuse

```text
assign -> J_i -> Q_C gate -> close | same-worker remediation | new red claim
```

Permit a retry only when `changed_evidence` changes the tested implementation, causal
discriminator, or proof route and names the previously excluded branch of `K` that the retry can
now decide. A new log label, extra narration, renamed seam, or fresh artifact of the same unaltered
experiment does not reset the retry basis.

Apply the MSW round fuse to the causal parent claim, not its latest label:

```text
equivalent(c1,c2) := both seek the same authoritative transition under the same S.A acceptance
```

Renaming the seam, adding visibility, or discovering another internal state along that transition
does not create a fresh fuse. When the fuse closes a slot red, record the first unresolved
discriminator. Move to another independent ready FS claim; if none exists, exit with a blocker
receipt for `F`. Do not keep the coordinator alive and do not restart the same claim automatically.
Use only the fuse policy and round meaning recorded with authority in `S.A`.

A proved failure may refine `S` only when deleting the amendment would leave the requested outcome
unclassified or unprovable:

```text
failure -> minimal dS -> MSW necessity -> stable R_new + proof route
```

Preserve the requested outcome. Mark whether the amendment changes behavior or makes an invariant
explicit. Gate C consent delegates `Q_C` authority to record and refreeze only a non-material,
evidence-bound amendment and update the ledger. Return material product, geometry, balance,
authority, or owner choices through `F`; after fresh consent, have `Q_S` author/refreeze that
material `dS`. Do not use refinement to legitimize an implementation convenience.

## Acceptance integrity

Close a slot only when:

```text
G = exact(source,binary,fixture)
    âˆ§ setup_before_claim
    âˆ§ authoritative_production_route
    âˆ§ discriminating_control
    âˆ§ identity_bound_artifact
    âˆ§ not_test_only_credit
```

Audit the accepted result for direct outcome-setting, mocked/helper-only proof presented as
gameplay, handwritten success artifacts, stale binaries, duplicate registries, hidden fixture
mutation, and unrelated work. A failed `G` returns the same slot; it does not create a detached test
program. Commission an independent verifier only for a named unresolved acceptance risk and give it
a bounded packet. Do not make `Q_C` rerun worker verification or commission a full accumulated-diff
review. Do not add a generic final review after all FS claims and integrated proofs are green.

## State, commits, and continuation

Keep transient investigation in worker artifacts and receipts. Update durable Plan/TODO/TESTING or
technical documentation only when a red claim opens/closes, `S` changes, a window closes, or a
handoff is necessary. Store hashes, verdicts, and artifact paths rather than replaying historical
narrative. Make one coherent accepted slot commit when project policy permits; exact-provenance
checkpoint commits belong on the worker lane until acceptance.

When a window closes, derive the next necessary window from current `S`. Continue until every red
claim is green and any `S.A.integrated_proof` explicitly named in the frozen specification passes.
If none is named, imply no additional integration run or review. Stop earlier only for a fuse with
no independent ready work, a material user choice, an external blocker, or revoked consent. Exit
rather than idle; resume later from `S`, the ledger, and compact receiptsâ€”not prior transcripts.

## Benchmark

Record start/dispatch/end timestamps, model profiles, slot and commit identities, proof artifacts,
remediation cycles, raw-output expansions, live-run count, and token use only when exposed. Attribute
usage per participant when available. Never estimate unavailable usage.
