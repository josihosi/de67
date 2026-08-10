# Frozen kernel

This file is immutable under every automatic mutation. It defines the constitution evaluated by
the accepted parent, never by its candidate.

## State partition

```text
K = (S, FSA, X, H, M, B)
P = (P1, P2, P3)
K intersect P = empty

P1 = orchestration policy
P2 = proof-conformance policy
P3 = broader execution policy
```

`S` is the frozen functional specification. `FSA` is its authoring law. `X` is execution and proof
integrity. `H` is the external deadline law. `M` is mutation governance. `B` is benchmark and
promotion law.

## Functional-specification law

The user-facing agent prepares inspected facts and owner choices. After explicit Gate S consent, a
fresh xhigh specification author performs the imagination round and freezes:

```text
S = (C, E, D, O, A, R)
C = requested contract       E = inspected facts
D = product decisions        O = authoritative state owners
A = acceptance, proof, limits, permissions
R = stable red claims

proof(R_i) = precondition -> owner -> transition -> observation -> artifact -> verdict
```

Only the specification author may author or refreeze a material change through the applicable user
consent path. Coordination may record a non-material evidence-bound clarification only when its
delegated authority is explicit in `S.A`.

Classify materiality by the remaining choice, not by the vocabulary touched:

```text
continuous(dS | S,e) <=> deleting dS leaves evidenced failure unclassified or its proof undefined
                         and player_contract(S + dS) = player_contract(S)
                         and permissions(S + dS) = permissions(S)
                         and count(non_equivalent_admissible_refinements(S,e)) = 1
```

When `continuous` holds, the coordinator records and refreezes the minimal amendment, updates the
same red claim and proof route, and continues the same slot. This may make the only lawful owner or
transition explicit; touching an ownership seam does not by itself make the amendment material.
Return through the material Gate S path only when the requested player contract or permissions
change, or when two or more non-equivalent admissible refinements remain. A uniquely implied
clarification is not a blocker.

```text
dS intersect dP = empty
```

`dS` changes the product contract and starts a new benchmark epoch. `dP` changes coordination
policy while holding `S` and the accepted product frontier fixed. A mutation candidate may emit a
specification-gap receipt, but it cannot author `dS`. The accepted coordinator routes that receipt
through the delegated non-material clarification path or the material user-consent path above.

The semantic functional-specification core remains frozen. The first lineage window seals proof
presence, the semantic manifest, accepted product frontier, and authoritative owner route; every
later window must match. A closed concrete plan maps every condition and negative control to exact
source/binary/fixture/test artifacts. Its seed and coordinates may change under MSW, but each plan
requires a separately appended independent review receipt before dispatch. This ledger refinement
is not a `P2` mutation.

Specification authoring is outside the MSW deletion domain. After `S` freezes, apply MSW only to
candidate execution work:

```text
D_MSW = ledger slots + implementation acts + tests + tooling + review findings

admit(x) <=> deleting x leaves an assigned R_i unmet or unproven
close(x) => do not admit x again unless changed evidence invalidates its proof
```

The coordinator applies this test when composing and revising a ledger. Each worker applies it
within its assigned slot. A verifier applies it to proposed remediation and findings. MSW may
delete candidate work; it may not delete, weaken, reinterpret, or silently close `S`, `A`, `R`, a
slot pass test, or required evidence. A failed evidence route remains an unmet claim, not success.

Before dispatch, prove the slot can decide its claim:

```text
dispatchable(T) <=> every required precondition is proved by an identity-bound artifact
                  or an authorized acquisition act can establish it
```

If `dispatchable(T)` is false, do not dispatch implementation or synthetic-proof work. Admit the
smallest artifact-acquisition slot when authorized; otherwise return the first missing precondition
and required authority as the blocker. A control may validate a discriminator, but it cannot
substitute for the subject state named by the slot.

## Non-bypassable execution integrity

For every ledger slot `T`:

```text
close(T) => worker_ran(T)
            and test_completed(T)
            and pass_test(T)
            and valid_receipt(T)
            and identity_bound_artifacts(T)

execute(Q_C, T) = false
accept(Q_C, T) => exact(source, binary, fixture)
                  and authoritative_route(T)
                  and no_direct_outcome_setting(T)
```

The coordinator writes slots, assigns workers, gates receipts, and advances accepted state. A
worker performs implementation, builds, tests, and live proof. A mutation may alter routing but
cannot erase or weaken these predicates.

A coordinator may repair only a rejected receipt hash without rerunning the worker or test. First
append one `receipt_rejected` event whose independently validated terminal evidence binds the
still-active permit and whose claimed receipt hash genuinely mismatches the existing receipt file.
Then append one `receipt_resealed` event bound to that exact rejection and the corrected receipt
path/hash. The corrected terminal may differ only in that receipt path/hash and must bind the reseal
before acceptance. A permit permits at most one rejection and reseal; an accepted or failed
terminal consumes it permanently.

## Mutable-policy vocabulary

`P1`, `P2`, and `P3` are closed JSON configurations validated by the accepted parent. Their values select
among these strategies; they cannot introduce prose, permissions, acts, owners, tests, or proof
rules.

```text
P1.ready_order:
    fs_order | critical_path_then_fs | unblock_then_critical_path
P1.parallelism:
    conservative_disjoint | maximal_disjoint
P1.profile_route:
    weakest_sufficient | risk_weighted
P1.context_route:
    minimal_contract | minimal_plus_interface
P1.receipt_route:
    receipt_only_if_sufficient | receipt_then_named_selector
P1.retry_route:
    same_worker_changed_evidence | replace_worker_changed_owner
P1.coordinator_flow:
    ledger_dispatch_gate | dependency_wave_gate | discriminator_first_gate
P1.worker_flow:
    implement_test_receipt | discriminate_implement_test_receipt |
    tool_preflight_implement_test_receipt
P1.tooling_route:
    existing_capabilities_first | capability_gap_then_focused_adapter
P1.progress_route:
    terminal_receipt | milestone_then_terminal_receipt

P2.conformance_route:
    minimal_authoritative_conformance | authoritative_owner_then_live_conformance

P3.preflight_route:
    identity_owner_discriminator | owner_discriminator_identity
P3.evidence_route:
    owner_test_artifact_live | artifact_owner_test_live
P3.integration_route:
    accepted_frontier
P3.recovery_route:
    reconcile_then_resume | quarantine_then_replan
P3.live_route:
    cheapest_remaining | final_integration_only
P3.build_route:
    smallest_owner_test_first | targeted_compile_then_owner_test
P3.harness_route:
    observer_before_live | focused_adapter_before_live
```

Every strategy is subordinate to `S.A` and the execution-integrity predicates above. New
primitives require an explicit owner-authorized kernel revision; automatic mutation may only select
or combine already-authorized primitives.

The harness seals `P1.retry_route` with each window. After two terminal failures with the same
stable obligation, worker, receipt semantics, and artifact content hashes, it denies a third
equivalent dispatch before execution. Paths and semantically irrelevant receipt whitespace do not
change that identity. `same_worker_changed_evidence` permits a materially changed causal retry only
with the same worker. `replace_worker_changed_owner` permits it only with a replacement worker and
a changed receipt-bound owner. Both prior failures remain append-only evidence.

Before proof-plan dispatch, the harness validates the separately appended review against the frozen
contract hash, closed plan hash, artifact hash, and exact condition/control mapping hashes. The
permit binds that review and an intended worker; plan author, reviewer, and worker are distinct, and
the terminal worker must match. Helper/mock-only evidence, direct outcome setting, stale reviews,
omitted mappings, or a changed core/contract blocks dispatch. A proof-plan failure counts toward
`P2` only when its assessment binds the reviewed permit and the real `task_failed` that consumed it;
the harness derives its causal fingerprint from the authoritative causal class and frozen owner
facts. `minimal_authoritative_conformance` requires the independent authoritative review receipt;
`authoritative_owner_then_live_conformance` additionally requires authoritative-owner and live
conformance receipts. The exact selected route is sealed through review, permit, terminal, damage,
and benchmark provenance. Zero-dispatch and accepted executions cannot qualify.

Every proposed delta declares an efficiency hypothesis:

```text
h(delta) = (observed_bottleneck, changed_policy_keys, expected_reduction)
expected_reduction in {
    critical_path, serialized_wait, context_tokens,
    repeated_work, build_or_live_cost, idle_time
}

admissible(delta) => expected(fitness(P + delta)) < expected(fitness(P))
                     and Q_FS(P + delta) = 1
```

The benchmark, not the mutation author, decides whether the expected reduction occurred.

## Deadline law

For a ledger window `W` whose task graph is a DAG:

```text
duration(W) = max over dependency paths p of sum(estimate(T) for T in p) + reserve(W)
deadline(W) = start(W) + duration(W)
```

The coordinator sets estimates and reserve before dispatch. The external harness owns `start` and
`deadline`. Once sealed:

```text
rename(T) | split(T) | replace(worker) | revise(ledger) | discover(problem)
    does not change start(W) or deadline(W)
```

Only an explicit new user contract creates a new lineage. Deadline expiry ends `W`: it freezes new
dispatch into `W`, records a missed window, and requires a compact damage assessment. It does not
end the functional-specification program, close a frozen red claim, change the accepted product
frontier, or reset the lineage, any sealed start or deadline, or any event or review history. Later
functional success does not erase the scheduling failure.

## Failure and mutation law

Let a qualifying worker failure be identity-bound evidence that a real worker began the assigned
work and failed or crossed its sealed deadline. Let a failed window be a distinct sealed window
that crossed its deadline without satisfying all required slot gates.

```text
mu_1(K, P1, f_worker) = (K, P1 + delta_1)
domain(delta_1) subseteq P1

N_total = count(distinct failed windows in lineage)
W_review = sequence of latest valid fresh review, or 0
N = count(distinct failed windows after W_review)
N_proof = count(causally distinct proof_plan-owned failed windows after W_review)

N < 3  => domain(delta) subseteq P1
N >= 3 => review by fresh Sol xhigh;
          domain(delta_3) subseteq (P1 union P3)

N_proof >= 3 and the same fresh external review
       => domain(delta_proof) subseteq P2

for every mutation: K' = K
```

The value three and the ledger ceiling ten are requester-authorized design constraints. A renamed
claim, replacement worker, or repeated attempt in one sealed window does not increment `N`.
For `N_proof`, duplicate, renamed, or retried symptoms with one causal fingerprint count once.
Successes do not change `N`. A valid review binds the complete current unreviewed miss set, advances
`W_review`, and therefore resets `N` and `N_proof` to zero without deleting `N_total` or any event.
The next review is due only after three additional distinct misses. Product- and harness-owned
failures do not qualify for mutation and an authoritative causal fingerprint cannot be relabeled.
Mutation evidence is limited to the batch consumed by its review; reviewed failures cannot be
reused in a later mutation batch.

Every failed terminal or missed deadline must seal its append-only evidence, preserve the stable
obligation and accepted frontier, reassess the remaining red claims, and continue through a
materially changed causal retry under the sealed `P1.retry_route` or a successor-window replan.
Each time `N` reaches three, the fresh independent `sol-xhigh` review is an additive continuation
gate, not a terminal state. After that review and any admissible mutation workflow, coordination
resumes whether the result is promotion, rejection, or `no_mutation`. The program stops only for
all-green completion, revoked consent, a material Gate S owner choice, or a genuine external
blocker; no internal round or retry fuse may stop an actionable frozen red claim. A mandatory fuse
may rotate the evaluator only after an identity-bound successor or required-review handoff preserves
that claim, the accepted frontier, all sealed deadlines, and the append-only history.

A successor is materially changed when receipt-bound evidence invalidates a causal premise of the
failed route. Different angles can include exact workspace, artifact, or subject identity;
authoritative-state acquisition; owner or worker assignment; slot decomposition or ordering; and
the build, test, or live-proof route. Before reporting an external blocker, show that authorized
materially distinct directions are unavailable and that the next required act exceeds `S.A` or the
available environment. This search cannot fan out across overlapping state, reset evidence, weaken
acceptance, substitute synthetic evidence for required live proof, or repeat an unchanged route.

Every candidate begins from the last accepted parent. Rejected candidates have no descendants.
Incident facts stay in receipts and benchmarks; they do not become skill addenda. The mutation
guard rejects unknown policy keys or values.

Product recovery and policy benchmarking are separate. Real work advances only an accepted
product frontier; a failed slot quarantines its unaccepted delta without discarding previously
accepted diffs. Each policy candidate benchmarks from an isolated snapshot of that same frontier.
Rejecting the candidate discards its policy and disposable benchmark lane, not accepted product
work.

When a worker was dispatched on a claim its available artifacts and authority could not decide,
seal that as a worker orchestration failure. Mutate `P1`, benchmark the candidate against the same
`S` and accepted product frontier, and resume from that frontier after promotion. The promoted
workflow admits an authorized acquisition slot or another independent ready red claim before it
returns an external-authority blocker. It does not replay the wasted dispatch.

## Benchmark and promotion law

Store the accepted parent's benchmark result. Run only the candidate against the same frozen
benchmark definition and deadline.

Benchmark candidates one at a time. Seal worker-ready evidence as it arrives; no other candidate
may create a coordinator consumption barrier. The first sealed candidate result is the result.
An unchanged rerun cannot replace, average with, or be selected over it without an owner-authorized
benchmark law established before the run.

```text
Q(r) = worker_executed and test_completed and acceptance_passed and evidence_valid

candidate admissible => Q(candidate)

fitness(r) = lexicographic(
    deadline_misses,
    elapsed_seconds,
    exposed_token_use,
    skill_bytes
)

promote(V_next) => Q(V_next)
                   and fitness(V_next) < fitness(V_parent)
```

Lower is better. Unavailable token usage is omitted rather than estimated. A candidate that weakens
quality is rejected before efficiency comparison. If measurements conflict outside this ordering,
return the tradeoff to the user instead of inventing weights.

The accepted parent and its stored result remain the rollback point. Re-baseline the parent only
when the model, harness, platform, or benchmark definition changes enough to create a new comparison
epoch.

## Git promotion law

Bind every candidate to the exact accepted `main` commit in a dedicated branch and worktree. A
candidate may be promoted only when its benchmark passes and `main` still names that parent:

```text
candidate.base = main = V_n
accept(candidate) => fast-forward main to V_n+1
main != candidate.base => stale candidate; rederive and rebenchmark
```

Never merge a rejected candidate or derive descendants from it. Retain its compact receipt outside
the accepted skill tree, then delete or quarantine the branch. Product changes remain in their
product repository; a DE67 mutation branch owns coordination policy only.
