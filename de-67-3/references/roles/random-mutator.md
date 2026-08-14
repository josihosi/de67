# Random mutator role

```text
M_random = stored cycle + fixed lane + compact evidence
           -> one bounded improvement candidate or guarded DFS no-op
           -> resolution + restart
```

The ordinary attempt cadence remains one uniformly drawn terminal-window interval in `[10, 30]`
and one stored lane. Do not redraw the interval, reselect a friendlier lane, or infer a new cadence.
Already-dispatched workers keep their original briefs and clocks.

If the persisted draw is exactly `k = 30` with lane `DFS.md` and its universal component is still
pending, stop and route that component to the universal mutator. When it returns resolved, perform
this ordinary stored-lane review for the same cycle. Do not resolve one component as the other or
redraw either obligation.

Use a fresh independent `gpt-5.6-sol` reviewer at `ultra`, Josef's selected mutation profile. Read
the selected target, the current DFS information necessary to preserve the outcome, the latest ten
short failure verdicts, and pending suggestions. Fetch long evidence only for an exact anomaly that
can change the decision. The selected profile does not expand this ordinary lane's authority.

Return one to three concrete inefficiencies ranked by causal importance, direct evidence, a small
candidate for the stored lane, an optional accompanying broad normal-method candidate, and proposed
treatment of pending suggestions. The method candidate may affect the Phase-3 router, role modules,
assets/guidance, tests and debug tools, or nonprotected orchestration scripts. It preserves the
kernel, deadline harness, mutation guard, their hard tests, item clocks, and attempt accounting.

Prepare baseline and candidate directories containing the two canonical guideline assets plus the
workspace DFS. Change only the stored target there. A guideline draw promotes only the matching
`de67-lab/de-67-3/assets/environment/` file; a DFS draw promotes only `.de67/DFS.md`. Never create or
mutate workspace-local guideline copies. For a DFS draw, use a source-grounded same-outcome candidate
or the exact guarded no-op when no honest change is available. If broad method learning is supported,
copy the complete active Phase-3 tree as both the starting baseline and candidate, change only the
candidate, and pass both optional flags:

```text
python <active-de-67-3-skill>/scripts/mutation_guard.py random-review --baseline <lane-baseline-dir> --candidate <lane-candidate-dir> --state .de67/state/deadlines.sqlite3 --lineage PROJECT --cycle N --ledger-candidate <ledger-candidate> --method-baseline <active-live-method-snapshot> --method-candidate <complete-method-candidate>
```

The legacy selected-lane target must still change, except for its guarded DFS no-op; a method
candidate accompanies rather than replaces that decision. After an applied verdict, promote and
checkpoint method changes only in `de67-lab`; checkpoint a DFS change only in the product repository;
then consume the workspace scratch ledger. A guarded DFS no-op changes neither the DFS nor scratch
ledger. Record the applied component and guard evidence:

```text
python <active-de-67-3-skill>/scripts/deadline_harness.py resolve-random-mutation --state .de67/state/deadlines.sqlite3 --lineage PROJECT --cycle N --component ordinary --evidence "<guard result and actual target/section>"
```

Resolution queues one fresh-coordinator generation. Return to the old coordinator so it can retire;
it never launches the successor. Failed validation resolves nothing.
