# Phase 3 token audit — September 16, 2026

Workspace: `Cataclysm-AOL-hostile-ecology-dev`, the workspace served by the running
dashboard. Latest coordinator launch on disk: `restart-72`, September 16. This audit
covers that UTC day's run sequence, including its preceding workers/coordinators,
not only the final restart. No game sessions or coordinator processes were restarted.

## Measured usage

The native rollout traces support the reported order of magnitude: **23,519,502 fresh
tokens** over the 22 UTC hourly buckets containing activity. Peak buckets were
**1,638,570** and **1,639,474**; several others exceeded 1.2M. Fresh here follows the
dashboard: input minus cached input plus output. It is not total input or a dollar bill.

| Consumer | Fresh tokens | Share |
| --- | ---: | ---: |
| Terra stalker-opportunism closer | 12,430,619 | 52.9% |
| Terra integrated free-player | 4,811,992 | 20.5% |
| Three Sol coordinator contexts | 4,073,975 | 17.3% |
| Astra mutator + Astra coordinator context | 1,727,905 | 7.3% |
| Three Luna helpers | 475,011 | 2.0% |

The top two workers account for **73.3%**. Coordinator instruction trimming alone
cannot eliminate the main cost. Fresh tokens also do not prove wasted work: ordinary
gameplay and native proof genuinely require actions and observations.

## Findings and interventions

1. **Coordinator wait mechanics create unnecessary reasoning boundaries.** Three Sol
   contexts made **847 worker-wait calls** and **768 process-poll/wait calls**. Repeated
   commands requested `worker_library.py wait ... --timeout 55` through `exec_command`
   with `yield_time_ms: 30000`, then collected completion in another model turn.
   Requests following those categories account for **2,474,792 fresh tokens**. This
   is an association, not an estimate that all those tokens can be saved: it includes
   cached-prefix misses, output/reasoning, and useful reactions to actual changes.

   Applied a narrow coordinator-guidance fix: keep command launch and required
   `write_stdin` polling inside one `functions.exec`, emit the completed wait result,
   and bound the whole wait by the next task deadline and 60 seconds. This removes
   the need for a model decision at a shell yield. It does not suppress worker
   completion or authorize unattended waits beyond the deadline. Actual savings must
   be measured on the next run; this is guidance, not runtime enforcement.

2. **Sol repeatedly imports worker internals.** **161 raw worker-event reads** returned
   about **731,707 text characters**. Examples include tail/rg of complete JSONL
   events, sometimes explicitly truncated at 12,000 output tokens. Those files
   include tool output and agent messages, so a small line count is not a small read.
   Added guidance to use raw events when a concrete question remains after checking
   status/messages/result artifacts. No access prohibition or evidence cap was added.

3. **Workers spend heavily on fine-grained interaction and process checks.** The two
   Terra workers made **1,957 `play_cli.py` calls** and **721 process-status calls**.
   The latter includes repeated `ps`, child-process counts and build-progress checks.
   Their requests following process-status/poll categories account for approximately
   **1.58M fresh tokens**, again an association rather than recoverable savings.
   Best next experiment: a bounded local wait for a concrete process/log transition,
   returning only a change or deadline, with no model turn for unchanged polls.
   Do not batch gameplay actions blindly; preserve native observation/action validity.

4. **Repeated retrieval remains a secondary target.** The two workers have **1,138
   source/log-read calls** under the heuristic classifier. One worker underwent
   **40 `new_context` calls**, the other 15. Context reconstruction plausibly explains
   some repeated reads; it is not proof they are all redundant. The current harness
   already contains `gameplay_display.py` deltas and exact recoverable bounded output
   in `evidence_display.py`; adding another generic compact-output layer would
   duplicate existing functionality. Inspect the actual calls that bypass those
   routes before changing the gameplay interface.

## Telescope trial

One bounded live query asked where existing worker wait/status interfaces avoid
tailing event logs, with the hypothesis that raw logs were required. Candidate source:
`de-67-3/scripts/worker_library.py` only; **no private transcripts were transmitted**.
Jev selected the actual `wait`, `describe`, and CLI routes as counterevidence. Response
validated; no fallback. Usage: **3,537 input + 697 output tokens** (4,234 total).

This helped locate the implementation, but did not discover the usage totals; those
came from deterministic local analysis. Telescope is useful for targeted evidence
retrieval. Running it on every gameplay move, status poll, or known-symbol lookup
would add overhead. It remains off by default in workspace configuration.

## Method and limitations

- Read-only discovery from local `state_5.sqlite` threads matching the exact project
  directory suffix and updated on/after September 16; 14 matching session files,
  10 with usage that day. Session IDs and hourly totals are in the companion JSON.
- Stream JSONL `token_count` events. Difference cumulative fresh counters; on first
  observation/reset use `last_token_usage`, matching the dashboard's reset handling.
  Prior-day counters establish the baseline but do not count toward this day.
  This is an observed local-trace total, not a reconciliation against provider billing.
- Classify tool calls by command substrings, then associate the next positive usage
  delta with preceding tool categories. This cannot assign causal token cost to a
  specific tool or distinguish every useful read from redundant work.
- Count text output separately from image/encrypted content. Raw JSONL byte size,
  especially base64 screenshots, is **not** a model-token estimate.
- Existing native game evidence, acceptance quality, and completed outcomes were not
  rejudged. No conclusion that an individual worker's total consumption was wasted.
- Follow-up acceptance: compare fresh tokens per completed comparable outcome, wait
  model-turn count, evidence correctness, and elapsed time. A lower hourly burn from
  simply doing less useful work is not a win.

## Validation

The effective-role context test and seven named-worker integration tests pass.
The latter require modern Python: Apple's Python 3.9 failed two existing fixtures
using `Path.write_text(newline=...)`; rerunning with Homebrew Python 3.14 passed all
seven without a source workaround. Installed guidance preserves existing local
modifications. No game code, dashboard changes, or running coordinator was modified.
