---
name: de67-lab
description: Explicit-call DE67 coordination and mutation lab. Use when the user invokes `$de67-lab` to author or refine a frozen functional specification, coordinate its implementation after separate explicit Gate C consent, or evolve coordination policy under immutable proof, deadline, and promotion laws. Invocation alone grants neither consent gate.
---

# DE67 Lab

Use a frozen constitution around three bounded policy surfaces. Read all four references before any
lab act:

1. `references/kernel.md` — immutable specification, integrity, clock, mutation, and promotion law.
2. `policy/orchestration.json` — `P1`, the single-worker-failure mutation surface.
3. `policy/proof.json` — `P2`, the proof-conformance mutation surface.
4. `policy/execution.json` — `P3`, the additional three-window-failure mutation surface.

Treat `contracts/mutation-policy.json`, both scripts, tests, this file, agent metadata, and the
kernel as frozen. A candidate never evaluates its own mutation boundary; run
`scripts/mutation_guard.py` from the accepted parent checkout.

## Lab workflow

```text
accepted parent V_n
    -> sealed failure receipt(s)
    -> scope(worker | coordinator)
    -> candidate V_n+1 from V_n
    -> parent-side mutation validation
    -> candidate-only frozen benchmark
    -> compare(candidate result, stored parent result)
    -> promote | discard candidate and return to V_n
```

For `worker`, require one identity-bound worker failure and permit changes only to
`policy/orchestration.json`. For `coordinator`, require three distinct unreviewed failed ledger
windows in the same lineage for `P1`/`P3`; permit `P2` mutation only when the reviewed batch
contains three causally distinct proof-plan-owned failed windows. A valid fresh review consumes its
exact batch and advances the review watermark. Successes do not move that watermark. Neither scope
may change the kernel or its enforcement tools.

## Production coordination

Invocation opens briefing only. Follow the kernel Gate S path to author or refreeze the semantic
functional specification, then stop. Before Gate C, display the exact frozen specification
revision, accepted product frontier, branch/worktree, fresh xhigh coordinator identity, proposed
initial ledger, and requested acts. Start production coordination only after separate explicit
Gate C consent; never infer it from Gate S.

The coordinator is never a worker. It may maintain the ledger, prepare dispatch packets, gate
compact receipts and targeted diffs, accept or quarantine slot output, and advance the accepted
product frontier. Assign every implementation, tooling, build, test, live-operation, and
remediation act to an identity-bound worker.

Until every frozen red claim and explicitly required integrated proof is green:

1. Derive no more than ten necessary atomic slots from the current specification under the kernel
   MSW implementation domain. Ten is the requester-authorized ceiling, not a target.
2. Preflight owner, authority, dispatchability, and the exact source/binary/fixture/test evidence;
   bind and independently review a liquid proof plan where the claim requires one.
3. Seal the ledger window. Dispatch dependency-ready disjoint slots using the selected `P1`
   routes and the weakest sufficient available worker profiles; unknown overlap serializes.
4. Require workers to implement, test, and return compact receipts. Gate every terminal against
   the frozen acceptance predicates and advance only accepted output.
5. Derive the next ledger from the remaining red claims.

Seal every failed terminal or missed deadline and classify it under the kernel mutation law. A
failed terminal ends only its consumed permit and evidence route; a missed deadline ends only its
sealed window. Neither ends the functional-specification program or closes a frozen red claim.
Append the required evidence, preserve the accepted product frontier, reassess the remaining red
claims, and continue through a materially changed causal retry or replan. For a qualifying failure,
run the isolated lab mutation workflow from the accepted parent and promote only a validated strict
improvement. Whether a candidate is promoted or rejected, or no mutation is admissible, resume
product coordination from the accepted frontier. Mutation benchmarks never perform or receive
credit for product recovery.

Changed evidence must change the next attempt. Before repeating a route, challenge its causal
assumptions and select the smallest evidence-bound different angle: verify the exact workspace,
artifact, and subject identity; acquire missing authoritative state; change the owner or worker when
causal evidence warrants it; reorder or decompose the build, test, and live-proof route; isolate a
smaller honest discriminator; or derive a new slot graph. Do not spend a round on an unchanged
retry, weaken proof, or manufacture an outcome. A failed tactic is not an external blocker while an
authorized materially distinct route remains.

When failed production evidence narrows an existing red claim to one admissible clarification,
apply the kernel `continuous(dS | S,e)` test. If it passes and `S.A` delegates refinement, record and
refreeze the minimal amendment, update that claim's proof route, and continue the same slot without
asking the user. Do not classify by words such as `owner` or `authority`: return to Gate S only for
a changed player contract or permissions, or for two or more non-equivalent admissible choices.

Stop only for all-green completion, revoked consent, a material Gate S owner choice, or a genuine
external blocker. An external blocker exists only when authorized materially distinct routes are
demonstrably unavailable and the required next act lies outside the granted permissions or
environment. A failed terminal, missed deadline, required review, rejected mutation, internal round
or retry fuse, or absence of another independent ready claim is not a stop condition while any
frozen red claim has an admissible changed-evidence retry or replan. A mandatory evaluator fuse may
retire the current coordinator only after it seals an identity-bound successor or required-review
handoff carrying the same red claims, accepted frontier, prior sealed deadlines, and append-only
history.

Concrete proof plans are liquid ledger data, not `P2`. The lineage seals proof presence, semantic
manifest, accepted frontier, and authoritative owner route. A closed plan maps every condition and
control to exact source/binary/fixture/test artifacts. Append an independent `proof_reviewed` event,
then permit proof dispatch with `--worker-identity`; author, reviewer, and worker must differ. Only a
reviewed permit consumed by a real `task_failed` can receive a harness-derived proof-plan causal
fingerprint. `minimal_authoritative_conformance` requires that independent authoritative receipt;
`authoritative_owner_then_live_conformance` additionally requires bound owner and live-conformance
receipts. The selected route follows review, permit, terminal, damage, and benchmark provenance. A
truthful preflight blocker stays zero-dispatch.

Do not repair a rejected candidate. Discard it, retain its compact benchmark receipt, identify a
different causal direction, and derive the next candidate from the last accepted parent.

## Ledger windows

Before any worker dispatch in each new ledger window, call the deadline harness `open-window`.
That command idempotently deploys the harness when it is absent or version-stale, validates the
ledger DAG, seals its deadline, persists the clock, and starts the detached watcher. Do not replace
it with a prompt timer.

Each task must bind `id`, `claim_id`, `intended_task`, `pass_test`, `owner`, `worker_profile`,
`preconditions`, `authoritative_route`, `evidence_requirements`, `estimate_seconds`,
`estimate_provenance`, and `depends_on`. If the ledger states `reserve_seconds`, also state
`reserve_provenance`. Keep stable claims and their obligations unchanged across ledger revisions;
only scheduling details may move.

If a valid worker/test/artifact result is rejected only because its receipt hash is wrong, append
the rejected terminal payload as one `receipt_rejected` event. The harness must prove that hash
mismatches the existing receipt file. Append one `receipt_resealed` event bound to that rejection
event hash and corrected receipt path/hash, then submit the otherwise unchanged `task_accepted`
payload with the reseal event hash. Do not issue another worker permit or rerun the test.

After two equivalent terminal failures, the harness rejects a third unchanged dispatch. For a
materially changed causal retry, pass a pre-execution causal-evidence JSON binding receipt semantics
and sorted artifact content hashes with `permit-dispatch --causal-evidence`; the sealed P1
`retry_route` determines whether the same or a replacement worker is admissible.

If the authoritative subject or preconditions are absent before dispatch, record one
`preflight_blocked` event and complete the zero-dispatch window honestly. After three distinct
deadline misses since the latest valid lineage review, gate the next window and new permits on a
fresh external `sol-xhigh` review sealed with `record-lineage-review`. The review must bind the
complete current unreviewed batch; it resets that batch to zero without deleting the historical
misses. Success never resets the batch. Healthy late work may still finish and record its terminal
receipt; seal the required review before final `completed`. Its deadline miss remains in the
lineage. After sealing the review and completing any admissible `P1`/`P3` and separately qualifying
`P2` mutation workflow, resume coordination from the accepted frontier. Review completion,
`no_mutation`, or candidate rejection is not functional completion.

For mutation benchmarks, seal `benchmark_binding` in the ledger: exact candidate Git identity,
product frontier, target failure, changed policy keys, and expected reduction. Repeat the same
mutation identity plus observed reductions in the terminal completion event.

Run mutation benchmarks serially: consume each worker-ready receipt before starting or processing
another candidate. The first sealed candidate result is authoritative. Do not rerun, select, or
aggregate results unless an owner-authorized benchmark law already defines that operation.

The lab invocation alone does not grant production acts or start a coordinator. Preserve DE67's
separate specification and coordination consent gates.

## Commands

```text
python scripts/deadline_harness.py open-window --lineage-id ... --run-id ... \
  --window-id ... --fs-root /absolute/path/to/specification --ledger ledger.json

python scripts/deadline_harness.py record --lineage-id ... --run-id ... \
  --window-id ... --kind proof_reviewed --payload proof-review.json

python scripts/deadline_harness.py permit-dispatch --lineage-id ... --run-id ... \
  --window-id ... --slot-id ... --worker-profile ... --worker-identity ...

python scripts/deadline_harness.py status --lineage-id ... --run-id ... --window-id ...

python scripts/deadline_harness.py record-lineage-review --lineage-id ... --run-id ... \
  --window-id ... --payload review.json

python scripts/deadline_harness.py export-benchmark --lineage-id ... --run-id ... --window-id ...

python scripts/mutation_guard.py validate --candidate candidate --scope worker \
  --lineage-id ... --run-id ... --window-id ... --event-hash ... --intent mutation-intent.json \
  --accepted-ref main --product-frontier product-frontier.json \
  --baseline-benchmark baseline-benchmark.json

python scripts/mutation_guard.py compare \
  --baseline-install-root parent-harness-state --baseline-lineage-id ... \
  --baseline-run-id ... --baseline-window-id ... --candidate-skill candidate \
  --candidate-install-root candidate-harness-state --candidate-lineage-id ... \
  --candidate-run-id ... --candidate-window-id ... \
  --validation-receipt validation-receipt.json

python scripts/mutation_guard.py promote --candidate candidate \
  --validation-receipt validation-receipt.json \
  --comparison-receipt comparison-receipt.json
```

Use absolute paths when a task crosses worktrees or machines. Return compact receipts and artifact
paths; do not ingest complete worker transcripts merely to operate the lab. `promote` emits a
validated fast-forward command plan; execute that plan separately from the accepted checkout.
