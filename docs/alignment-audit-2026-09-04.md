# DE67 context and authoring audit — 2026-09-04

Scope: the Mac lab package, installed DE67, and the active C-AOL delivery context. Preserve the
three phases, separate role contexts, worker orchestration, and durable receipt lifecycle.
Repetition across isolated roles is necessary when each role needs the instruction; textual
similarity alone is not a deletion criterion.

## Changes

- Phase 1 contributes provisional ideas, examples, tradeoffs, and focused questions. It preserves
  settled intent separately from proposals and open choices in a resumable draft.
- Phase 2 uses Astra high. DFS guidance carries causal reasoning, relevant owner interactions,
  falsifiers, and useful starting tactics beside the claim, distinguishing tactics from acceptance.
- The ordinary mutation reviewer uses Astra medium. The coordinator remains Sol low and ordinary
  workers remain Luna/Terra. The separate stored universal-review capability route is unchanged.
- The alignment audit follows actual producer/consumer routes and context timing. Its duplicated
  reviewer brief is folded into the entrypoint. Shared writing guidance is shorter and conditional;
  existing role entrypoints retain their necessary instructions. No new delivery gate was added.
- The shared MSW guidance no longer imposes an unconditional three-round stop or rejects a needed
  correction merely because an earlier pass could have discovered it.
- The DFS template no longer simultaneously permits closure and forbids status changes.
- Exploration routing selects primary ledger identities rather than references inside other items.
  A live R-029 packet had received R-030's objective through an incidental cross-reference.
  Multiple primary entries for the same claim remain supported; each retains its objective and
  frontier. Waiting work and the first open boundary survive later history summaries.
- Mutation requests remain a consumable queue. Completed entries are deleted. Both routing readers
  stop at the end of the pending section, so historical bullets cannot become fresh requests.
  The live queue's consumed sections were removed; their exact prior content was already committed.

## Evidence

The cross-reference regression generated a packet with the wrong objective before the correction.
The consumed-history regression returned three requests instead of the single deferred request.
Both pass after correction. A read-only call over the live ledger now selects R-029's own objective.
The Phase-3 suite passed 382 tests with two skips, and the root suite passed 27 tests. After the
final multi-entry/frontier correction, all 59 policy-kernel tests passed again. All five skill
entrypoints pass the skill validator.

The independent authoring simulation produced a concrete next conversational response and a usable
pause/resume WEC without treating proposals as consent. A Phase-2 classification exercise preserved
requirements, rationale, tactics, and proof limits without importing coordination policy. These
checks demonstrate bounded authoring behavior, not a complete product delivery run.

## Separate C-AOL findings

Source inspection identified two downstream harness concerns; this method change does not claim
that they are fixed or that a live exploit/failure was reproduced:

- `tools/openclaw_harness/cockpit_file_bridge.py`: `response_slice` and
  `FreshObservationSequence.accept_observation` read receipt paths directly, unlike
  `response_artifact`, which validates the resolved namespace. Route all consumers through common
  path, request identity, binding, schema, and digest validation; test a changed receipt and path
  escape with temporary artifacts.
- `tools/openclaw_harness/scenario_registry_cli.py` and `startup_harness.py`: ordinary registry launch
  and some early failure paths can emit full reports despite the quiet-output objective. Establish
  ordinary-launch scope and test explicit compact output through failure finalization before repair.

The old registry-status bulk response is already fixed. Receipt-backed successor continuity and
role-local constraints remain valuable. No live scenario, clock transition, or worker restart was
used to manufacture audit evidence.
