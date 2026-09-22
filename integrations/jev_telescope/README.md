# Jev Telescope

Optional, one-shot retrieval for Sol and workers. Python 3.10+ and `rg` are required;
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
    "cache_seconds": 3600
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

### Route exact evidence before semantic selection

Known identity, failure, status, and rejection questions are retrieval questions, not semantic
selection. Run the accepted harness route first, using exact identities and an explicit projection:

```sh
python3 tools/openclaw_harness/play_cli.py --session SESSION evidence \
  --run-id RUN --process-instance PROCESS --request-id REQUEST \
  --actor-id ACTOR --event rejection \
  --select event,run_id,process_instance,request_id,actor_id,actor_name,\
payload.payload.accepted,payload.payload.rejection_reason,payload.payload.outcome
```

This route makes zero provider calls. Keep source handles and inspect original record bytes; the
returned event, status, or rejection is evidence to inspect, not an accepted finding. For a
genuinely competing explanation, use `harness_adapter.search` with the already-filtered snapshot,
the bounded relevant pool, and the competing hypothesis. Its typed Choice questions preserve
independent counterevidence, reject unknown IDs, allow explicit irrelevant/abstain, and fall back
to deterministic retrieval when the provider fails. Exact retrieval is also available as
`harness_adapter.exact(workspace, snapshot, filters, selectors=...)`; it accepts only the
published identity/event filters and always reports `provider_calls: 0`.

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

Before provider submission, the adapter scans within the configured row/byte/time
budget, ranks deterministic query-relevant rows, removes only exact-equivalent
records while retaining their handles, and then applies the final candidate-pool
limit. Retrieval reports scan truncation separately from final-pool truncation,
plus exclusion and duplicate reasons; omitted rows may still be relevant. Use the
returned exact handles or `exact(...)` for expansion and source revalidation.

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
`max_calls` is per invocation: zero disables uncached calls; this version makes at most
one call even if configured higher. No automatic retries. Provider work runs in a
short-lived subprocess, terminated at its remaining wall-time budget, including slow
HTTP bodies. Local source verification and process cleanup can add small overhead.

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
answers and usage, not excerpts. Model aliases may change within a TTL; use a pinned
model or disable caching for reproducible provider comparisons. Comparison files under
`comparisons/` contain IDs, categories, timing, usage and failure codes, never source
text, questions or credentials. Delete that directory when its experiment is over.

## Validation and evaluation

```sh
python3 -m unittest discover -s integrations/jev_telescope -p 'test_*.py'
python3 integrations/jev_telescope/evaluate.py --output /tmp/telescope-baseline.json
# Explicitly sends four bounded de67 source/test pools, at most four API calls:
python3 integrations/jev_telescope/evaluate.py --live --output /tmp/telescope-live.json
```

Tests use a deterministic provider stub and never require credentials or network.
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

Official adapter references: [HTTP API](https://docs.typesafe.ai/api),
[Choice](https://docs.typesafe.ai/primitives/choice),
[State](https://docs.typesafe.ai/concepts/state), and
[reranking cookbook](https://docs.typesafe.ai/cookbooks/rerank_typesafe).
