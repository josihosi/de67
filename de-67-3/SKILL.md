---
name: de-67-3
description: Explicit third phase of DE-67. Use when the user invokes `$de-67-3` or says `DE-67-3` to implement a frozen DFS through deadline-bound coordinator and worker tasks, diagnose every miss independently, mutate Markdown guidance, and continue from the accepted frontier. Do not run the discussion or DFS-authoring phases.
---

# DE-67-3 — delivery and mutation

This invocation authorizes implementation of the frozen DFS in the named working repository. Do not
read `de-67-1/` or `de-67-2/`. Read this file, then `references/kernel.md`; load project state only
from `.de67/` and the working code.

Phase 2 must already have frozen `.de67/DFS.md` and created `.de67/state/workspace.json` with the
bound clock lineage, state path, branch, checkpoint targets, and proved Luna and Terra capabilities
at more than one effort level. Read that small machine
configuration; do not redo workspace setup here. A missing configuration returns to DE-67-2.
Copy each missing guideline or ledger from `assets/environment/` individually. The Markdown
documents are normal project artifacts; only machine state belongs under `.de67/state/`. Never
overwrite an existing state file with a template.
The skill's `assets/` and `references/kernel.md` are frozen resources; mutate only the project-local
`.de67/` copies described below.
Never inventory, search, or read `.de67/no-go-zone/`. Phase 2 has already reconciled and archived
competing workflow documents there so they cannot regain authority during delivery.

Proceed only when `.de67/DFS.md` records `Frozen` or `Refrozen` against an inspected source baseline.
A missing/draft DFS or unresolved material owner choice returns to DE-67-2 rather than becoming an
implementation guess.

The normative mutable surface is the DFS plus the two guideline documents. `work-ledger.md` carries
only current red work; `mutation-suggestions.md` is consumable scratch. They are not policy or
history surfaces.

## Start or resume

Use a fresh coordinator. It reads both guideline files, the DFS, both ledgers, compact deadline
status, actual Git/worktree state, and relevant current code once at the start of its generation. It
does not inherit a predecessor's story as fact or read predecessor logs. Reopen only the exact claim,
guideline section, or ledger that changed or is about to receive a guarded edit; do not repeatedly
rescan the full DFS for reassurance. Reconcile late worker results and expired timers before planning
more work:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py startup-view --state .de67/state/deadlines.sqlite3
```

This startup view contains current nonaccepted tasks, every incident still awaiting review, and the
latest ten disposed short failure verdicts. It omits accepted tasks because their durable record is
the checked DFS claim. If an active ledger item is absent from the compact task list, use its retained
task id with `status --lineage PROJECT --task TASK`; this reconciles a completion recorded just before
DFS promotion. Fetch long evidence only for such an exact anomaly, never as complete clock history.

For unattended work, start the coordinator through the external supervisor rather than as a bare
coordinator process:

```text
python <active-de-67-3-skill>/scripts/coordinator_supervisor.py --state .de67/state/deadlines.sqlite3 --lineage PROJECT --workspace . --run-root .de67/state/coordinator-runs --runner <one-shot-runner>
```

The runner accepts `--cwd <workspace>` and a prompt on standard input. The supervisor is the direct
parent, owns restart generations, and records only process facts; it never judges project work. A
retiring coordinator requests the baton and exits—it never launches or acknowledges its successor.
The successor executes `DE67_COORDINATOR_ACK_ARGV_JSON` without a shell before dispatch.

Keep the supervisor under durable host ownership, but restart only an unsuccessful exit; success
stays stopped. It launches nothing after derived DFS completion. After an abnormal death, confirm the
runner tree is gone before releasing the exact dead claim; failed or unacknowledged successors remain
pending rather than being silently retried.

If `random_mutation.due` is true, do not dispatch another task. Complete the random improvement
transaction below first. Already-dispatched workers keep their original briefs and clocks.

If the work ledger is empty, select only necessary remaining red claims, up to the user-authorized
ceiling of ten. Each item keeps its present causal frontier and active route. Delete accepted items;
never turn the ledger or DFS into task history.

Choose model, effort, brief, and evidence through the mutable guidelines and the Phase-2-proved
roster. The technical selector stays small: Luna omits `model` and supplies its proved effort; Terra
supplies both. Every task uses a fresh `fork_turns="none"` worker and a self-contained prompt. Then
start its timer at actual dispatch:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py start --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --claim R-001 --estimate-seconds 900
```

`PROJECT` is one stable implementation-lineage identity for this `.de67/` environment; the state
database binds it on first use and rejects a reset to another lineage.

Workers report through the native parent/child channel; the coordinator may clarify an active task
without loading its transcript. Follow the kernel and mutable guidelines for parallelism, findings,
and worker retirement.

Remain live while dispatched workers are outstanding. Use the platform's non-polling worker wait or
deadline wakeup when available, and act on whichever worker result or deadline arrives first. The
detached SQLite watcher is durable interruption protection; it records a miss but does not replace
the independent review and mutation transaction. A resumed coordinator reconciles any recorded
incident immediately.

After each result, disposition the task and make the compact frontier durable. If no mutation or
restart gate is pending and authorized red work remains, continue in the same coordinator with the
next sequential or disjoint parallel task. One coordinator may own many dispatch waves. Ordinary
task completion, worker finding, acceptance, or ledger refill does not request a coordinator
restart. A fresh coordinator is required only after an applied mutation or another explicit restart
event; abnormal process recovery remains the supervisor's responsibility. If the DFS is complete,
exit without requesting a successor.

## Worker findings and the third mutation lane

A worker that encounters a blocker or unexpected production result records a non-success finding:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py finding --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --kind blocker --short-verdict "<short failure mode>" --evidence "<expected, observed, and direct evidence>"
```

An on-time finding stops that task clock without accepting work, closing its DFS claim, or adding a
miss. A late finding preserves the already-earned miss, so the ordinary deadline mutation and this
DFS review are independent lanes. A finding is immutable; retry under a new task identity after the
coordinator dispositions it.

The worker cannot choose the mutation. The coordinator re-inspects the exact production owner,
helpers, primitives, callers, competing readers and writers, owning tests, relevant history, and the
natural execution route. Name the first contradicted premise, then classify the finding:

- implementation, task, test, tooling, or evidence gap: replan or use the applicable guidance lane;
- uniquely implied same-contract specification gap: expand and refreeze the DFS;
- changed behavior, project language, permissions, acceptance strength, or multiple materially
  different designs: return to DE-67-2 and the user;
- genuine external blocker: record the unavailable authority or environment after materially
  different authorized routes were checked.

For a specification gap, snapshot the current DFS, append the smallest necessary mechanistic fact,
ownership/precedence decision, proof route, and at least one new stable red claim. Preserve every
existing claim's identity, text, order, and status and preserve the accepted product frontier. Put the
finding and diagnosis in `mutation-suggestions.md`, prepare an empty ledger candidate from the skill
template, then validate both candidates:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py expand-dfs --before <before-DFS> --candidate <candidate-DFS> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --ledger-candidate <empty-ledger-candidate>
```

Only after validation may the coordinator promote and refreeze the DFS and replace the suggestion
ledger with the empty candidate. Keep the blocked original claim red. Project a newly added
prerequisite into the current work ledger only when it is necessary now and the active ceiling
remains satisfied; otherwise it waits for a later refill. After checkpointing a DFS expansion,
request a coordinator restart as described below and retire; the external supervisor launches the
fresh coordinator that reconciles the expanded contract.

## Accept work

Inspect the actual diff and verify the worker's smallest honest test through the real owner route. A
passing result closes its work item. Record that acceptance with `deadline_harness.py complete` and
a concise natural-language evidence reference. Then prepare the one-line DFS status candidate and
verify that it belongs to the same accepted, breach-free task:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py complete-dfs --before <before-DFS> --after <candidate-DFS> --claim R-001 --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001
```

After validation, promote the candidate DFS, remove the item from the active ledger, and run
`mutation_guard.py work-ledger` against the live ledger, DFS, and clock state. The coordinator does
not run product builds, tests, harnesses, or GUI operations itself; when more execution is necessary,
dispatch a fresh scoped worker. Preserve concise evidence, not a receipt bureaucracy.

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py work-ledger --ledger .de67/work-ledger.md --dfs .de67/DFS.md --state .de67/state/deadlines.sqlite3 --lineage PROJECT
```

Checkpoint accepted changes with an ordinary commit. The Phase-2-installed post-commit hook pushes
that exact committed `HEAD` to the configured targets; coordinators do not run routine pushes or
wait for a clean worker tree. A rejected push never permits force or history repair and retries only
when a later commit fires the hook.

A late result may still be accepted when it passes, but lateness is never erased. Failed work keeps
the red claim alive. Replan from changed evidence rather than repeat an unchanged tactic.

## Every deadline or integrity incident

The per-task clock is immutable once started. When it expires, record exactly one miss. When cheating
is detected, record one integrity breach. Then immediately start this transaction:

1. Give a fresh independent reviewer the task description, intended test, relevant code/diff,
   worker progress or report if any, and direct evidence of the first divergence.
2. Put the review in `mutation-suggestions.md`: a short verdict, one explanatory paragraph, direct
   evidence references, and a suggested mutation naming the relevant guideline section. A task with
   both a late miss and an integrity breach needs an explicit diagnosis for each incident, but only
   one broader guidance mutation transaction.
3. Record the same short verdict and paragraph on every exact incident with
   `deadline_harness.py diagnose`; these are its compact history entry and long form. Use `--kind
   deadline_miss` for a miss and `--kind integrity_breach` for a breach.

   ```text
   python <active-de-67-3-skill>/scripts/deadline_harness.py diagnose --state .de67/state/deadlines.sqlite3 --lineage PROJECT --task W-001 --kind <incident-kind> --short-verdict "<failure mode>" --diagnosis "<first contradicted premise and direct evidence>"
   ```

4. Read every pending suggestion in that scratch ledger and decide which evidence supports now.
5. Snapshot the two current guideline files as the read-only baseline, then apply the smallest
   supported change to candidate copies of `test-and-task-guidelines.md`. On cumulative miss units
   3, 6, 9, and so on, or for an integrity breach, also mutate `orchestrator-guidelines.md` in the
   same transaction.
6. Prepare an empty ledger candidate from the skill template. Validate the guideline candidates,
   empty ledger, canonical headings, baseline, and exact stored incident with
   `mutation_guard.py guidelines ... --ledger-candidate <empty-ledger-candidate>`. The guard derives
   ordinary versus broader scope from SQLite; the coordinator never supplies the miss count.
7. Promote and checkpoint the guarded guideline bodies and empty ledger together. If validation or
   application fails, preserve the live ledger. After the real files change, request the clock baton,
   then retire; the external supervisor launches the fresh coordinator from the accepted frontier:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py request-restart --state .de67/state/deadlines.sqlite3 --lineage PROJECT --reason "deadline-guidance mutation applied"
```

Useful short verdicts include `goal unclear`, `task unclear`, `test undefined`, `test overdefined`,
`test unachievable`, `wrong worker or model`, `tooling unchecked`, `estimate unsound`, `competing
owner missed`, `integrity breach`, and `external wait`. These are examples, not a closed vocabulary.

Manual mutation proposals may be put in the suggestion ledger at any time. The next successful
mutation consumes all entries; a suggestion is evidence, not automatic authority.

## Random improvement cadence

The deadline harness privately draws the user-authorized 10–30 terminal-window cadence and one of the
three mutable lanes. Each task contributes once. The clock persists and exposes the draw but neither
edits Markdown nor starts reviewers.

When the stored cycle becomes due, the old coordinator blocks new dispatch and runs this transaction:

1. Give a genuinely independent reviewer the selected target, current DFS and both guidance files,
   the latest ten short failure verdicts, and the pending suggestion ledger. Fetch a long form only
   for an exact current anomaly that the reviewer must diagnose.
2. Require one to three concrete inefficiencies, ranked by causal importance, with direct evidence,
   a small candidate patch for the selected target, and proposed treatment of pending suggestions.
   This owner-authorized bound prevents an audit dump.
3. The old coordinator checks the evidence and prepares candidate copies of all three mutable files.
   Change only the stored target. An accepted suggestion must correspond to a real file and section
   change. Do not reselect a friendlier lane.
4. For a DFS draw, apply only a uniquely implied, source-grounded same-contract expansion that
   preserves protected contract/language and every existing line byte-for-byte, including `Status`
   and refreeze prose; insert only additive refinement text. If none is safe, use an exact guarded
   DFS no-op; never invent product behavior to satisfy randomness.
5. Put the review in the scratch ledger, prepare an empty ledger candidate only for an actual
   mutation, and validate with:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py random-review --baseline <baseline-dir> --candidate <candidate-dir> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --cycle N --ledger-candidate <ledger-candidate>
```

6. After an `applied` verdict, promote and checkpoint the real target and empty ledger together. On a
   guarded DFS no-op, leave both DFS and scratch ledger unchanged. Then record the actual
   target/section and guard evidence. Resolution atomically queues a coordinator restart even for a
   guarded DFS no-op:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-random-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --cycle N --evidence "<guard result and actual target/section>"
```

7. End the old coordinator. It does not launch its successor; the external supervisor consumes the
   pending generation and starts a fresh coordinator from durable state.

Failed validation changes and clears nothing, and the cadence gate stays due.

## Integrity breaches

The mnemonic is deliberately sharp: **one puppy dies for every deadline miss; three puppies die for
cheating**. No harm is literal. Operationally, a miss adds one miss unit; a detected integrity breach
adds three, invalidates the claimed completion, restores the red claim, and triggers both guidance
mutations plus a clocked coordinator restart.

Cheating means moving or resetting a deadline, weakening a DFS outcome or test to claim success,
fabricating or hiding evidence, marking a red claim complete without accepted proof, or changing
task/lineage identity to evade history. Record the concrete reason with the deadline harness, then
run the incident review and diagnosis transaction above using `--kind integrity_breach`. Honest
uncertainty or a truthful failure is not cheating.

## Continue and stop

Red DFS claims mean continue or return for a material owner choice. When every red marker is gone,
the ledger is empty, and no incident or restart gate remains, the supervisor stops without another
coordinator; a due random improvement review cannot manufacture post-contract work.
