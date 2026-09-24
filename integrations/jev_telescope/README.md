# Jev Telescope

Experimental optional add-on for one-shot retrieval by Sol and workers. Install its separate
archive only on request. Python 3.10+ and `rg` are required;
the HTTP adapter uses the Python standard library. No daemon, embedding index, model
SDK, or orchestration changes. Off is the default and does not change existing briefs.

The pipeline is ignore-aware `rg` file discovery → bounded lexical candidate pool →
TypeSafe typed choices → hash-verified local excerpts. It can also reuse the existing
`work_context.py` receipts index, reading original deadline checkpoint rows as evidence.
It does not edit code/specifications, assign work, approve findings, or settle tasks.

## Configuration and invocation

Merge the following optional object into the target workspace's existing
`.de67/state/workspace.json`. Preserve its other settings. Changing to `shadow` or `on`
explicitly permits sending the query, hypothesis, and allowed candidate excerpts to
TypeSafe. Start with narrow source roots you are authorized to read and transmit.

```json
{
  "jev_telescope": {
    "mode": "off",
    "paths": ["src", "tests", "doc/findings"],
    "excludes": ["src/private/**"],
    "receipt_index": false,
    "model": "jev-latest",
    "max_candidates": 12,
    "max_files": 300,
    "max_file_bytes": 524288,
    "max_scan_bytes": 4194304,
    "candidate_bytes": 1600,
    "input_bytes": 48000,
    "evidence_bytes": 8000,
    "max_calls": 1,
    "elapsed_seconds": 15,
    "context_lines": 4,
    "cache_seconds": 3600,
    "provider_guard": {
      "mode": "off"
    }
  }
}
```

Use paths that exist in your workspace. `paths: []` reads no source files.
`receipt_index: true` additionally permits the existing
`.de67/state/work-context.sqlite3` index and its authoritative checkpoint sources
inside this workspace; custom path exclusions still apply. No index is built or
refreshed by Telescope. Oversized receipt rows are omitted with truncation reported.
Approved context-library source artifacts can be included through `paths`; normal
`context_library.py put/prepare` remains available to the caller for reuse of a packet.

```sh
python3 /path/to/de67/integrations/jev_telescope/telescope.py \
  --workspace /path/to/project \
  --query 'NPC accepts an order but never executes it; find implementation and tests' \
  --hypothesis 'The order was never stored' \
  --term pending_order --term execute_order
```

Terms are literal case-insensitive substrings, not regular expressions. Without
`--term`, query words seed lexical retrieval. Repeat `--path` to narrow configured
roots. It cannot expand source access. Output is JSON on stdout; evidence handles
identify the path, SHA-256 and inclusive one-based lines, or the exact receipt key.
An agent can open the named source and compare its hash before using the location.

Off returns the deterministic baseline without provider calls, cache reads, telemetry,
or added role instructions. Shadow evaluates Jev but returns the same baseline items;
its metadata-only comparison is saved locally. On uses valid Jev choices. Explicit
`irrelevant` choices permit abstention even when lexical matches exist. Hypotheses get
an independent counterevidence question; selected counterevidence has first access to
the evidence budget, even if the separate relevance choice was irrelevant.

Configured shadow/on modes advertise this CLI through the existing shared guidance
builder for Sol and workers. Nothing runs automatically. The optional integration
folder must accompany the de67 installation. Existing running role contexts pick up
the discovery hint on their next normal prompt generation, not by forced restart.

## Durable provider admission guard

`provider_guard.py` is credential-free and has no HTTP client. It is the shared
admission boundary used by Telescope before the bounded transport callable runs, and
can be used by another optional integration without enabling Telescope. `off` makes
no provider dispatch and does not open its SQLite owner. For a Telescope `shadow` or
`on` request, `provider_guard.mode` must be the same mode; a missing, off, or mismatched
guard returns deterministic baseline evidence with `provider_guard_mode_mismatch`.

Enabled mode has no made-up product defaults. The owner supplies every paid-mode bound
and an absolute state location outside the installed package and any disposable agent
context. This is a schema, not a values-to-copy example:

```json
{
  "provider_guard": {
    "mode": "on-or-shadow-to-match-jev_telescope",
    "scope_id": "owner-chosen-nonsecret-funding-scope",
    "state_path": "/owner-controlled/state/provider-guard.sqlite3",
    "max_calls": "owner-chosen-non-negative-integer",
    "max_request_bytes": "owner-chosen-positive-integer",
    "max_in_flight": "owner-chosen-positive-integer",
    "timeout_seconds": "owner-chosen-positive-number",
    "max_retries": "owner-chosen-non-negative-integer",
    "retry_backoff_seconds": "owner-chosen-non-negative-number",
    "max_total_tokens": "optional-owner-chosen-non-negative-integer",
    "per_request_token_ceiling": "required-when-max_total_tokens-is-set"
  }
}
```

The JSON above intentionally uses strings in place of limits: choose real values for
an authorized deployment, and do not treat the illustration as a recommended budget.
`timeout_seconds` and `retry_backoff_seconds` must be finite numbers. The enabled
configuration rejects state paths under the installed package, the active OS temporary
or runtime roots (`tempfile`, `TMP*`, and `XDG_RUNTIME_DIR`), the active Codex home,
or `DE67_RUNNER_ACTIVE_DIR`. This is an executable exclusion for known disposable
agent contexts. It cannot establish the retention policy of an arbitrary filesystem,
so the owner must still record and retain the selected external path as deployment
evidence rather than treating a passing path check as a distributed-durability claim.
`max_calls` counts durable reservations that remain exposed to provider usage. A local
deadline that expires before transport cancels its reservation without counting a
provider attempt; every actual retry is a new reservation. Timeouts after transport
starts remain recorded as unknown-provider-usage attempts. Reservations blocked by a
committed latch or epoch change remain auditable but are excluded from future exposure
totals. Capacity occupied only by still-reserved work rejects another reservation but
does not permanently latch the scope; a terminal local budget starts only once the
configured exposure is actually in flight or settled, except for an explicit zero
capacity. A queued admission rechecks its own reservation against current exposed token
charge immediately before transport, so another response's observed overage cannot
push it through the configured total. The optional token bound
uses `per_request_token_ceiling` as a local reservation before dispatch, not as a
provider-side output cap. If a structurally valid response reports more combined
input/output tokens than that reservation, its durable local charge increases before
the total-token latch is evaluated. A token value that cannot fit SQLite's signed
integer storage is recorded as unknown with the maximum representable local charge,
then returns fallback rather than stranding an in-flight admission. This integration
does not send a provider-side token-limit field and cannot prevent an already-run
response from exceeding its local reservation; it also does not invent a
billing/currency conversion.

SQLite records scope-bound reservations, in-flight work, safe outcomes, retries, and
latches in the one owner-selected file. Admission is a `BEGIN IMMEDIATE` transaction;
the queued caller must recheck immediately before dispatch, so a committed latch stops
it without an independent permission to send. Already in-flight requests can still
finish and incur provider usage; the configured in-flight limit is the bounded exposure,
not a promise of zero overrun. If the configured owner cannot be opened or locked,
Telescope returns its ordinary deterministic baseline with a safe guard-state fallback;
it does not bypass the guard. A terminal local-budget transition yields one durable
`shutdown_notice` result for callers to observe; a `status()` read reports it when
that read itself reaches the terminal local budget. This module does not enqueue a Pit
Crew or coordinator notice.

An in-flight admission never expires automatically: a slow live transport can still
incur usage after a local timeout. Only after verifying that every in-flight caller for
the scope has stopped may an owner explicitly release those local concurrency slots:

```python
ProviderGuard(owner_config).recover_abandoned_in_flight(owner_confirmed=True)
```

Recovery records those attempts as unknown and retains their call/token reservations;
it never retries, refunds, or infers a provider outcome. A late completion is rejected
as no longer in-flight, so recovery cannot create a new retry. It is an
owner-confirmed single-host recovery action, not a distributed liveness check.

If a process dies after `reserve()` but before `start()`, the owner can instead cancel
the pre-transport capacity after confirming every such caller has stopped:

```python
ProviderGuard(owner_config).cancel_abandoned_reservations(owner_confirmed=True)
```

Those rows remain a durable cancelled audit record and do not count as provider exposure.

Each reservation is bound in SQLite to the scope's current state epoch. Every durable
state transition advances that epoch. `start()` accepts only a still-reserved admission
from the current epoch, so a queued or retry admission from before a funds/budget/auth/
transient transition cannot revive merely because a later owner reset returns the scope
to `ready`. Legacy reservations that predate the epoch record are conservatively
invalidated; an owner reset permits only a fresh, newly reserved request.

Effective state is separate from mode:

- `ready` admits within the explicit owner bounds.
- `disabled_budget` is a durable local call/token latch; normal Telescope behavior is
  deterministic baseline fallback.
- `auth_error` is a distinct non-retrying 401/403 state. After credentials are corrected,
  only an explicit owner-confirmed `reset_auth_latch()` may reopen it.
- `transient_open` represents 429, 529, or timeout. It reopens only after the
  configured backoff and, when supplied, no sooner than the provider's advertised
  retry wait. A retry that would reach the caller's deadline is not dispatched; the
  transient latch remains durable, and later work must re-enter normal admission.
  An overlapping 401/403 upgrades it to `auth_error`; a later overlapping 429/529 can
  extend, but never shorten, its `retry_not_before` time.
- `disabled_funds` is intentionally unavailable in this revision. It is retained for
  durable compatibility and explicit owner reset, but no current provider response
  enters it.

The public TypeSafe HTTP table currently documents 401 authentication, 422 validation,
429 rate limiting, and 529 temporary overload; it says to back off for 429/529. A
numeric retry-after value is treated as the provider's minimum requested wait, never
as a maximum that local configuration may shorten. The
Python exception reference exposes status, body, headers, and the
`x-typesafe-request-id`, including a distinct 429 rate-limit exception. Neither source
documents exhausted credits, expired prepaid balance, a funding code, or a balance
endpoint. Therefore 429 is never interpreted as unavailable funds. The child boundary
keeps only sanitized status, structured code, request ID, and numeric retry-after data;
it never logs or persists raw error bodies, credentials, or request bodies.

When a later authoritative provider contract permits a real funding latch, only an
explicit owner action after replenishment may clear it:

```python
from provider_guard import ProviderGuard

ProviderGuard(owner_config).reset_funds_latch(owner_confirmed=True)
```

After correcting a provider credential, the equivalent explicit auth recovery is:

```python
ProviderGuard(owner_config).reset_auth_latch(owner_confirmed=True)
```

There is no timed reset, paid probe, automatic purchase, credential borrowing, or
automatic funds/auth reset. A local SQLite file coordinates processes that
share the file on its configured owning host; it is not a distributed cross-machine
lock. Remote paid dispatch remains unavailable through this guard unless existing
authenticated coordination routes every request to that owning host. Do not add a
distributed service merely to hide that limit.

## Retained playtest evidence

`harness_adapter.py` selects exact rows from an existing `play_cli evidence`
snapshot. First use the harness's run/request/actor filters and `--select` to retain
a compact candidate pool. Add both `.userdata/openclaw_harness/evidence-display`
and the original log directories to the configured `paths`; every source must be
inside the workspace and allowed. Then invoke:

```sh
python3 /path/to/de67/integrations/jev_telescope/harness_adapter.py \
  --workspace /path/to/project --snapshot SNAPSHOT_SHA256 \
  --query 'Which events explain the rejected movement?' \
  --hypothesis 'The movement request was accepted'
```

The adapter verifies the retained snapshot and original record byte spans before
selection and again before returning evidence. Handles preserve the snapshot row,
source path, offset, length and SHA-256. Appending a log keeps old records valid;
changed or deleted records are omitted. Original bindings and statuses remain in
the exact JSON row. Historical records never become fresh gameplay proof.

Off/shadow/on, counterevidence, caching and provider failure behavior are shared
with Telescope. Oversized rows are omitted visibly, so narrow the harness projection
or explicitly increase `candidate_bytes`. Selection covers only the bounded submitted
pool; it is not an exhaustive search. This command does not drive the game or run
automatically. Token savings need an end-to-end playtest comparison.

## Credentials, limits and failures

Set `TYPESAFE_API_KEY` in the environment of the process invoking Telescope. A key in
`~/.zshrc` is available to interactive zsh, but not automatically to a desktop service.
Do not put it in workspace configuration or command arguments. Endpoint is fixed to
`https://api.typesafe.ai/v1/systemone`; redirects are refused.

Limits are adjustable working parameters, not product acceptance thresholds. Byte
limits are UTF-8 bytes, not token/cost claims. `input_bytes` covers the complete provider
request; `evidence_bytes` covers exact excerpt text (JSON/provenance overhead is extra).
`max_calls` is per Telescope invocation: zero disables uncached calls. The durable
guard's independently configured call budget counts actual transport attempts, including
configured bounded retries. Provider work runs in a short-lived subprocess, terminated
at its remaining wall-time budget, including slow HTTP bodies. Local source verification
and process cleanup can add small overhead.

Timeout, credentials, HTTP/provider errors, invalid/partial answers, and exhausted
provider budgets return baseline evidence with `fallback` populated. Valid abstention
has `abstained: true` and no fallback. Empty local retrieval is `no_candidates: true`,
not a claim about relevance. Changed/deleted/now-excluded sources are omitted and
reported as stale; rerun search. Never silently attach old line references to new text.

Retrieval reports matched and submitted counts, exclusions, scan bytes and truncation.
It is bounded: lexical retrieval can miss synonyms, callers, or important evidence
outside the chosen roots. Explicit terms, narrower roots, or larger limits can expand
the search. No omitted item is claimed nonexistent. Overlapping excerpts are not
repeated; whole excerpts that do not fit the remaining evidence budget are reported
as omitted. Long lines are skipped, not rewritten into fake evidence.

Git ignores, path exclusions, link rejection and secret filename/content patterns are
applied before transmission. Patterns are a backstop, not a guarantee that arbitrary
allowed files contain no secrets; scope roots accordingly. Historical records retain
their original text and receipt timestamp/status where available; filesystem mtime is
an observation, not proof of the original finding's age. Historical content is never
promoted to fresh behavioral proof. Source and provider content are untrusted data.

Selection caches live in `.de67/state/jev-telescope/cache`, keyed by query, hypothesis,
candidate content/working-tree hashes, model, endpoint, question schema and adapter
version. They expire after `cache_seconds`; zero disables them. Cache contains typed
answers and usage, not excerpts. A cache lookup still requires an explicit matching
provider-guard mode and a `ready` guard state, so an off, mismatched, or latched guard
returns baseline rather than cached provider-derived output. Model aliases may change
within a TTL; use a pinned model or disable caching for reproducible provider
comparisons. Comparison files under
`comparisons/` contain IDs, categories, timing, usage and failure codes, never source
text, questions or credentials. Delete that directory when its experiment is over.

## Validation and evaluation

```sh
python3 -m unittest discover -s integrations/jev_telescope -p 'test_*.py'
python3 integrations/jev_telescope/evaluate.py --output /tmp/telescope-baseline.json
# Requires explicit matching `on` provider_guard owner configuration before it can
# send four bounded de67 source/test pools (otherwise it records local fallback):
python3 integrations/jev_telescope/evaluate.py --live --output /tmp/telescope-live.json
```

Tests use a deterministic provider stub and never require credentials or network.
`test_provider_guard.py` uses a real temporary SQLite state owner, concurrent local
callers, a copied module file, and stub transport only; it does not make a TypeSafe
request. It proves the off path, durable local budget/auth/transient distinctions,
retry re-admission and provider retry-wait/deadline handling, latch recheck, reset
semantics, overlapping in-flight auth/retry handling, safe child error projection,
terminal-notice observation, actual-usage token latching, explicit abandoned-slot
recovery, unrepresentable-usage fallback and aggregate saturation, cache
guard-state/mode enforcement, blocked-queue budget release, queued-token recheck, and
ordinary Telescope fallback. No test proves a real provider-funds classification
because the official contract does not provide one.
`evaluation.json` supplies real de67 questions, important source anchors, an irrelevant
pool, and misleading hypotheses. Baseline and Jev use exactly the same pool and excerpt
budget. Each report records pool hashes/locations, coverage of labeled excerpts,
missed important/counterevidence IDs, abstention, latency, token usage and fallback
frequency. Missing anchors fail the evaluation command so source drift is visible.
Anchor labels are deliberately small and inspectable; unlabeled excerpts may still be
useful. Coverage is conditional on retrieved candidates, not whole-repository recall.

Typed choices and probability validation prove the interface, not selection quality.
No ranking score is presented as a calibrated probability. Shorter packets alone do
not establish efficiency: the current evaluation does not measure full agent task
quality, recovery searches, or total agent usage. See VALIDATION.md for observed results.

Official adapter references: [HTTP API](https://docs.typesafe.ai/api.md),
[Python exceptions](https://docs.typesafe.ai/sdk/python/api/exceptions.md),
[Choice](https://docs.typesafe.ai/primitives/choice),
[State](https://docs.typesafe.ai/concepts/state), and
[reranking cookbook](https://docs.typesafe.ai/cookbooks/rerank_typesafe).
