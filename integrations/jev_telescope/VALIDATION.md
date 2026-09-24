# Initial validation — 2026-09-18

Implementation and checks ran on macOS using Python 3 and ripgrep. No Windows/Linux
runtime was available for this pass; implementation uses portable standard-library
APIs and the existing `rg` executable contract.

- `python3 -m unittest discover -s integrations/jev_telescope -p 'test_*.py'`:
  19 deterministic tests passed, without credentials or network. Includes a real
  short-lived process timeout/cleanup test and HTTP request/response contract tests.
- `python3 -m unittest discover -s de-67-3/tests -p 'test_*context.py'`:
  12 existing context tests passed; disabled integration preserves existing prompts.
- `python3 integrations/jev_telescope/evaluate.py --output /tmp/telescope-baseline.json`:
  all four real-repository cases retrieved their declared important anchors.
- Live paired evaluation: four requests, same candidate pools and 4,800-byte excerpt
  budget per arm, no retries, no fallbacks. Model requested: `jev-latest`.

| Case | Baseline / Jev labeled coverage | Baseline / Jev returned items | Jev selection + verification |
| --- | --- | --- | --- |
| Worker unloading and reuse | 100% / 100% | 6 / 6 | 1.066 s |
| Owner bootstrap on resume | 100% / 100% | 4 / 4 | 0.983 s |
| Misleading WEC hypothesis | 100% / 100% | 2 / 2 | 1.011 s |
| Irrelevant symbol-codec pool | not applicable | 7 / 0 | 0.972 s |

No labeled important or counterevidence excerpt was missed. Jev correctly abstained
on the irrelevant-only pool; baseline did not. Other cases produced the same evidence
size as baseline. Baseline retrieval/verification took approximately 18–32 ms per case;
that local retrieval cost also applies before Jev selection. Provider usage totaled
11,546 input tokens and 2,350 output tokens. Detailed candidate locations/hashes and
usage are in `evaluation-results.json`; no credentials or source excerpts are stored there.

The labels identify a small set of important excerpts, not an exhaustive relevance
annotation. Unlabeled results may still be useful. This sample establishes a working
adapter and one successful abstention example, not calibrated quality or an efficiency
win. Full agent task quality, subsequent recovery searches, total agent tokens/cost,
and end-to-end elapsed time remain unmeasured. Stubbed tests prove behavior under the
stub, not Jev's selection quality. External transmission remains off by default.

## Provider-guard candidate validation — 2026-09-20

This candidate added `provider_guard.py` without sending a provider request or
changing an installed skill. The current public TypeSafe API/error references were
read without credentials: 429 is documented as rate limiting and 529 as temporary
overload; the Python reference documents status/body/headers/request ID and a distinct
429 exception. Neither documents exhausted credit, prepaid expiry, a funding code, or
a balance endpoint. The candidate consequently leaves `disabled_funds` unsupported
and does not map 429 (or any stub label) to funding exhaustion.

- `python3 -m unittest discover -s integrations/jev_telescope -p 'test_*.py'`:
  64 deterministic tests passed with local Python 3.9.6, no credentials, no network, and
  no live provider request. The focused guard cases use a real temporary SQLite
  owner and stub transport at the actual Telescope adapter boundary.
- Focused assertions cover off/no dispatch; distinct budget, auth, 429, 529,
  timeout, malformed, and undocumented-funds cases; retry re-admission; an advertised
  retry wait that is not shortened and is not retried past the caller deadline;
  retry-admission denial preserving the original provider failure and actual call count
  through Telescope; queued latch recheck; restart and copied-package persistence;
  overlapping in-flight auth failures upgrading transient state and longer retry waits
  extending it; concurrent single shutdown notice across spawned local processes;
  status-read terminal-notice preservation through Telescope; unavailable-owner,
  mismatched-guard, mismatched-guard-cache, and latched-guard-cache fallbacks;
  observed token usage that raises its local reservation and latches total budget; an
  owner-confirmed abandoned-slot recovery that preserves the unknown attempt's charge;
  late completion after recovery retaining the actual attempted-call accounting;
  unrepresentable token usage settling as a charged unknown attempt with Telescope
  baseline fallback; retry-admission storage failure retaining the prior call count;
  overflow-safe aggregate token latching after a prior charged request; expiry while
  local admission waits or just before transport cancelling without a provider call;
  latch-blocked queued work excluded from future exposure budget while retained in the
  durable audit trail; reserved-only capacity rejecting new work without terminally
  latching the scope; and explicit owner-confirmed auth reset after corrected credentials;
  queued start rechecking token capacity after another observed response; and explicit
  owner-confirmed cancellation of abandoned pre-start reservations;
  pre-latch admission epoch invalidation across simulated funds reset; finite-bound and
  known-disposable-path rejection; safe status/code/request-ID child projection; and
  explicit-only funds reset.
- The SQLite check proves one local-host owner file serializes concurrent processes.
  It does not prove a distributed lock or authorize cross-machine paid dispatch.

The validation ceiling is source behavior under deterministic stubs and the cited
public contract. It does not prove provider billing, funds exhaustion semantics, a
paid request, a real balance, or cross-machine coordination.
