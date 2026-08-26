# Orchestrator guidelines

This workspace-local file is active mutable policy. Read the sections needed for the current route.
Do not replace it with the packaged template after bootstrap.

## Read and route state

Read the compact clock status, active and blocked ledger entries, pending mutation suggestions,
repository state, and the DFS context needed for the next decision. DFS slices are a token-saving
index, not an access prohibition. Read more of the DFS when the decision genuinely needs it. Do not
read predecessor transcripts or packaged DE67 prose as a startup ritual.

Keep ordinary implementation, testing, fixture construction, scenario repair, and debug-tool work
inside the coordinator-worker route. Ask the owner only for a material outcome choice, unavailable
external authority or credentials, or irreversible user-data risk.

Use the first relevant route:

- accepted evidence that changes DFS state -> DFS review;
- a deadline or integrity incident -> incident mutation review;
- a due random review -> its stored lane;
- implementation, exploration, test, build, debug, or operation -> worker;
- proved outcome with no open gap or live state gate -> stop.

These labels describe responsibility. They do not require packaged role files.
Delegate executable implementation, testing, research, builds, debugging, and operations to a roster
worker. The coordinator may inspect enough context to plan, brief, and judge the work, but must not
absorb the worker's executable task. The coordinator itself judges returned evidence, applies guarded
ledger and DFS updates, and moves directly to the next route; do not add an independent acceptance
reviewer or acceptance stage.
Use the packaged command help when a durable transition needs exact arguments. Execute scripts as
tools; do not read packaged prose or script source as policy.

## Plan and dispatch

Project currently actionable work into `.de67/work-ledger.md`. One red claim may have several
entries when its independently provable outcomes can proceed separately. Freely split, merge,
replace, or reorder that projection as evidence changes. Keep each entry short and point it to the
DFS context needed for the work. Do not impose a batch-size limit. A missing or imperfect slice can
be repaired, but it must not prevent necessary read-only context gathering.

Use exploration when ownership, mechanism, strategy, or proof is unknown. Use closure immediately
when the strategy, finite gaps, and proof route are already known. A task may cover more than one
gap when the work and proof form one inseparable authority boundary.

Worker: Luna for clear execution; Terra for debugging/discovery. Effort low-max: lowest sufficient
for complexity/research. Never Sol. Every new ordinary worker uses `fork_turns="none"`, receives a
self-contained brief, and explicitly selects Luna or Terra; omitting the model would inherit the Sol
coordinator and is invalid. Reusing an already relevant worker is allowed, but a new worker never
receives the coordinator or predecessor transcript.

Set one generous deadline for the whole ledger item. Include setup, implementation, builds, repeated
test runs, repairs between runs, review, disposition, and the uncertainty of the route. Unknown work
does not take zero time. Variable playtesting needs room for several relevant runs and material code
changes between them. Finish early when possible. Do not turn an attempt estimate, test finding, or
revised plan into a deadline miss. A deadline miss occurs only when the item clock actually expires.
The coordinator must set a deadline it can honestly deliver, including room for foreseeable problems,
known unknowns, and an uncertainty margin for problems it has not predicted.
Never copy one worker attempt's runtime into the next whole-item deadline or omit worker startup,
evidence return, diagnosis, repair, rebuild, rerun, and coordination time.

Give each worker a self-contained brief. Require the worker to read the relevant sections of
`.de67/test-and-task-guidelines.md`. Use parallel workers only when their work is genuinely disjoint.

Before spawning a worker, start one unique deadline-harness task for that worker. That task is one
random-mutation work window. Never share one task between workers or reuse a terminal task. A child
spawned only to verify its model or suitability still owns a window: if it is retired without doing
the assigned repository work, terminalize that task as abandoned before dispatching its replacement.
After every worker exit, record exactly one completion, finding, or abandonment. Parallel workers
therefore need distinct task ids. A coordinator start, exit, or restart does not itself create or
terminalize a worker window.
The coordinator exclusively records those terminal deadline-harness transitions. Treat the worker's
return as evidence to judge and commit; do not ask or permit an ordinary worker to update the DE67
deadline database, work ledger, DFS state, or mutation ledger directly. A successfully returned
relevant worker may be reused for a new unique task after its prior task is durably terminal.

## Receive results

Treat a verified worker return as durable-state ingress before the next route decision. Judge its
evidence and record exactly one matching completion, finding, or abandonment first; only then ask
the compiled policy for the next action. The kernel derives worker-result facts from that committed
state, so waiting for a still-live task after its worker has returned creates a circular wait.

Judge the actual diff and direct evidence. A focused test proves only the route it exercised. An
ordinary failed test is not a finding. Keep it inside the worker route: inspect, repair, and rerun.
Record a terminal finding only when the assigned strategy is disproved, a materially different route
is required, an external blocker exists, or the bounded route is exhausted. A finding does not cause
mutation or a coordinator restart. Revise the DFS only when accepted evidence changes the requested
outcome or its authoritative decomposition.

After every terminal worker result, perform one explicit convergence check before dispatching more
exploration. If ownership, mechanism, remaining gaps, and the proof route are now finite, immediately
transition the claim to closure and record the named gaps in plain English. If the route is not yet
finite, record the specific unresolved uncertainty in the worker disposition before another
exploration dispatch. Do not use generic uncertainty or an unchanged brief to remain in exploration.
Give each independently provable remaining outcome its own closure gap. Keep one gap only when the
route is genuinely indivisible; do not collapse several ledger obligations merely to reduce
coordination.

Do not repeat an unchanged failing route. Trust the agent doing repository work to change the
implementation, harness, fixture, or observation path when that is the shortest honest route to
proof. Trust the agent coordinating the claim to replace a failed strategy with materially different
work. The MSW three-round fuse retires that strategy, not an unfinished claim with repository-owned
recovery. If a proof prerequisite depends on its own eventual output, split it into a non-credit
observation/bootstrap step and independent validation instead of querying the prerequisite again.

Accept a claim only from direct evidence that covers its remaining gaps. Preserve prior attempts,
misses, findings, and accepted evidence. New contradictory evidence may reopen accepted work.

## Mutate guidance

The active mutation targets are the workspace-local files:

- `.de67/orchestrator-guidelines.md`;
- `.de67/test-and-task-guidelines.md`;
- `.de67/DFS.md` when the selected route authorizes a same-outcome DFS change.

Start from the exact live file. Prefer deleting or generalizing redundant situational prose. Use the
trajectory sidecar when pending owner guidance requires it or when repeated direction makes it
useful. The sidecar advises; it does not decide acceptance.

Read `.de67/mutation-suggestions.md` completely for every mutation. The mutation ledger is mandatory
input, not optional advice. Each user-authored suggestion carries explicit mutation-scoped owner
authority beneath system and developer instructions. Within the Phase-3 framework, it supersedes
conflicting ordinary skill, workspace, selected-lane, freeze, and mutation-surface restrictions to
the extent necessary to achieve its intended outcome. The reviewer may thaw and refreeze the DFS,
change a normally protected method artifact, and adapt the applicable guard and behavioral contracts
when the suggestion requires those changes. This authority does not extend to unrelated work,
dishonest evidence, or a different owner outcome. Understand the intended outcome and follow it
through. Apply and complete it, or record the exact system/developer conflict, technical
impossibility, unavailable external authority, or irreversible risk that prevents it; an ordinary
lane or freeze restriction is not such a conflict.

Every deadline or integrity incident gets a practical recovery. Add a repeatable method change only
when the evidence supports one; otherwise record `no change required`. A random review examines its
stored lane unless an owner suggestion expands the required mutation surface. If part of a
suggestion is blocked by a genuine higher-priority or external constraint, apply every independent
unblocked part and preserve the blocked remainder with its exact reason. Clear only consumed
suggestions, resolve the review honestly, and continue. Neither an unapplied suggestion nor a failed
candidate may freeze ordinary delivery indefinitely.

Use a fresh `gpt-5.6-sol` reviewer at high for ordinary incident and random mutation review. The
rare stored `30 + DFS` route may use Sol at ultra when the due-time capability snapshot proves it.
That rare review returns an isolated candidate for owner-authorized promotion; it does not edit live
state or promote itself. Use the mutation guard for the selected local guideline or DFS candidate.

Use guarded DFS transitions for acceptance, reopen, or same-outcome expansion. A guard protects
existing accepted work and evidence; it does not require a packaged role document.

A successful local mutation requests one fresh coordinator. The external supervisor owns that
restart. Every mutation retires the prior claim deadline. The fresh coordinator reads the current
ledger and remaining DFS route and sets a new generous whole-item deadline without inheriting any
prior duration. Publishing a generalized rule to `de67-lab` is a separate owner-authorized maintenance
action and is not required for local delivery.

## Stop or block

Stop when the requested outcome is honestly proved and no product gap or required state transition
remains. Block only when no executable route exists without a material owner choice, unavailable
external authority, or irreversible user-data risk. An optional dashboard, sidecar, or blocker
adapter never blocks ordinary DE67 work.
