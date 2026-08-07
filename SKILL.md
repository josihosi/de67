---
name: de67
description: Explicit-call functional-specification design and permission-gated coordination kernel. Use only when the user invokes `$de67` to let a front agent draft one authoritative functional/technical specification and, after new explicit approval, launch one xhigh coordinator to finalize the specification, write a bounded ledger, and route implementation workers by complexity. The call alone never authorizes coordinator or subagent launch.
---

# DE67 — Specification Design and Coordination

Draft v0.3. Produce one traceable contract, then offer permission-gated coordination without
becoming an implementer.

## Invocation and launch boundary

Activate this workflow only through the explicit callmark `$de67`. The call authorizes:

- loading this skill and task-relevant evidence;
- discussing, drafting, writing, or refining the named functional specification;
- updating the specification's authorized Git/GitHub trace artifacts.

Treat each invocation's wording as the specification mutation boundary. Preserve unrelated files
and existing user changes. Implementation, builds, tests, coordinator launch, and subagent launch
remain outside that authority.

Use this state transition:

```text
idle --$de67--> specification
specification --checkpoint ready--> awaiting_launch_consent
awaiting_launch_consent --new explicit approval--> coordination
```

At the specification checkpoint:

1. Identify the exact specification revision and open red claims.
2. Present the proposed repository/worktree/branch, coordinator model and effort, Prompt A version,
   ten-slot ceiling, and initial owner lanes.
3. Ask a direct conversational question: "May I start this coordinator?"
4. Stop and wait for the user's new explicit affirmative response.

Treat launch permission as one-shot and bound to that stated configuration. A material change to
the specification revision, repository/worktree/branch, coordinator profile, prompt, or execution
contract returns the state to `awaiting_launch_consent`. Only the new affirmative response crosses
the gate; the `$de67` invocation and earlier general permission leave it closed.

## Roles

```text
user <-> F{Luna|Terra}: dialogue, evidence intake, propose dS, consent gate, reports
consent -> Q{xhigh}: holds S, validates/writes dS, freezes S, writes L, routes/inspects W
W{Luna|Terra|Sol}: implement one ledger slot at the weakest sufficient profile
```

Before consent, `F` may write the requested draft and trace only. After consent, `Q` owns the
normative `S`: any specification mutation is its accepted `dS`, and `F` remains the user relay.

## State model

Represent the work as:

```text
S = (C, E, D, O, A, R)
```

- `C`: requested outcomes and scope
- `E`: inspected evidence and current-state facts
- `D`: decisions and explicit assumptions
- `O`: authoritative owner graph
- `A`: acceptance checks and their required evidence
- `R`: unresolved claims, each with a stable red ID

A claim belongs in `R` exactly when deleting it leaves `C` unmet or unproved. Maintain one normative
specification; roadmaps, queues, tests, and GitHub records reference it rather than restating it.

## Phase 1 — Design or refine the specification

### 1. Reconstruct the real workflow

Inspect the request, conversation, existing specifications, source, tests, issues, and runtime
evidence that materially constrain the outcome. Imagine the normal user path and the edge case that
would make an apparently complete result feel false.

Before mutating the normative specification, bind:

```text
I = (why_now, intended_workflow, real_user_path, fake_or_broken, decisive_edge)
```

If `I` exposes a material owner choice, `Q` sends `F` one recommended question with 2–3 disjoint
options; `F` asks the user through structured input when available and relays the answer. Otherwise
record the smallest consistent assumption. Never let a subagent manufacture owner consent.

Bind:

```text
C = goal + requirements + acceptance + failure cases + smallest useful vertical slice
```

For ambiguous attended work, ask the owner. For unattended work, use the smallest reading consistent
with stated intent and record it in `D`.

### 2. Separate desired behavior from present evidence

Classify each relevant claim as:

- specified and proved;
- specified but unproved;
- contradicted by current evidence;
- scaffolding without a production path;
- historical context only.

Tests prove only the path they exercise. A structure or helper without a production caller remains
red.

### 3. Write one normative specification

Use only sections needed by the domain. Prefer this order:

1. purpose and user-visible contract;
2. scope and supersession;
3. lifecycle or state model;
4. functional behavior;
5. authoritative owners and override precedence;
6. persistence, performance, and platform behavior;
7. conformance against current evidence;
8. red acceptance ledger.

Give unresolved claims stable IDs such as `R1`, `R2`. Use `- [ ] 🔴` while open and `- [x]` when the
named acceptance evidence closes them. Preserve IDs across refinements.

When several AI systems consume common primitives, specify the primitive once and keep each
consumer's policy, memory, and movement owner separate. A useful concurrency model is:

```text
parallel(i,j) iff W_i ∩ W_j = ∅ and O_i ∩ O_j = ∅ and P_i ∩ P_j = ∅
```

where `W` is the likely write set, `O` the authoritative state owners, and `P` mutable proof
artifacts. Unknown intersections serialize.

### 4. Put proof logic inside the specification

Attach an evidence contract to every red claim:

```text
proof(R_i) = (preconditions, causal boundary, real route, expected transition,
              positive and negative controls, artifact identity, pass, failure)
```

Name which setup may be staged and where staged control ends. Distinguish unit/helper evidence,
changed-executable integration, live interaction, persistence, performance, and platform proof.
Specify the smallest observer or harness visibility needed to see the subject while keeping the
gameplay owner authoritative. Define failure as the first reproducible seam that prevents the
expected transition, so remediation has a concrete input.

### 5. Maintain one compact Git/GitHub trace

Commit each accepted specification revision. When an issue or PR is already in scope, maintain one
trace thread or section instead of creating a stream of planning comments. Otherwise prepare the
trace block for the owner and use the Git commit as the durable local record.

```markdown
### Specification trace — <revision>
- Spec: <path + commit>
- Inputs: <issues, discussion, source/runtime evidence>
- Contract delta: <what changed>
- Decisions: <stable IDs and rationale>
- Evidence: <what is proved>
- Red claims: <open IDs>
- Ledger: <task slots and current owners>
```

Record rejected expansions in one line when they matter to the owner. Keep secrets, raw private
conversation, and unnecessary transcripts out of GitHub.

## Phase 2 — Coordinate implementation

Enter this phase only after crossing `awaiting_launch_consent` with the explicit approval described
above. Record the approved configuration in the trace before launch.

Use an **xhigh contract-first coordinator (Prompt A)**. Its role is to partition, assign, inspect
evidence, update the trace, and halt. Subagents implement.

### Execution kernel

For each task slot, bind its covered red claims and merge proof as the local contract:

```text
K(T_i) = covered_red_ids + required_merge_proof

while exists claim c where deleting c leaves K(T_i) unmet or unproved:
    do the smallest reliable act for c
    prove c at its specified evidence class
halt and report
```

Plans, implementation ideas, tests, reviews, and discovered defects enter as claims rather than
automatic work. A closed claim stays closed unless changed evidence reopens its contract. Apply the
project's review-round fuse when present; after its final round, report remaining contract gaps
instead of growing a new remediation loop.

### Ledger fuse

Partition `R` into owner-level work packages `T` such that:

```text
union coverage(T) = R
primary_owner(T_i) is unique
|T| <= 10
```

- Ten task slots are a ceiling.
- Assign one subagent to each slot.
- Send remediation and follow-up to that same subagent and slot.
- Fold tests, review findings, and discovered defects into the task owning the affected contract.
- Once ten slots exist, complete them or halt with the unrepresentable claims; create no task 11.
- Keep the current critical path and only proven-disjoint lanes active.
- Remove finished detail from the live queue while retaining the Git/GitHub trace.

### Assignment palette

Choose one profile when the slot starts:

| Profile | Fit |
|---|---|
| Luna medium | Mechanical, narrow, well-specified work |
| Luna high | Tricky bounded proof, fixtures, or platform validation |
| Terra medium | Multi-file implementation behind a frozen interface |
| Terra high | State ownership, new interfaces, or coupled production wiring |
| Sol medium | Ambiguous owner arbitration, cross-boundary persistence, or final adversarial review |

Scale later slots down after earlier slots remove uncertainty. Keep Sol medium exceptional because
its breadth is useful precisely where the owner graph is unclear.

### Prompt A table

The xhigh coordinator reads the normative specification and outputs at most ten compact rows:

| Slot / dependency | Red IDs covered | Assigned subagent job | AI profile | Parallel condition | Merge proof |
|---|---|---|---|---|---|

Each red ID has one primary slot. Group claims only when they share the production owner and honest
proof route. Preserve the vertical dependency chain; separate consumer policies after their shared
interface is stable.

### Execution transition

For each active slot:

```text
assign -> receipt -> implement -> return(diff, evidence) -> Q evaluates
       -> same-slot remediation, or close red IDs and advance
```

The coordinator accepts evidence only when it covers the specified route and changed artifact. It
updates the specification, ledger, and trace at a real state boundary. It starts another lane only
after re-evaluating `parallel(i,j)`.

Admit a test or review only when deleting it leaves its slot contract unproved. Close a slot only
when:

```text
G = exact(source,binary,fixture) and setup_before_claim and authoritative_route
    and discriminating_control and not manufactured_outcome and not test_only_gameplay
```

Apply MSW to integrity findings: reopen only when deleting the finding would leave the contract
falsely green. Run `G` per slot and once across the final integrated task.

Halt when every `R` is closed, when the ten-slot representation is insufficient, or when authority
outside the task is required.

## Evaluation hooks

For prompt and coordinator experiments, record per run:

- specification revision and prompt version;
- coordinator model/effort and worker profile per slot;
- task count, concurrent lanes, and task growth;
- coordinator and worker tokens;
- elapsed time, commits, red claims closed, and remediation cycles;
- production-path proofs versus helper-only proofs;
- stop reason.

Compare runs by contract coverage, evidence quality, progress per token, rework, and whether the
ledger stayed finite. Change one prompt variable per experiment when practical.
