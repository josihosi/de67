# Jev Pit Crew

Pit Crew is an optional, normally packaged evidence-advisory path. It reads the existing
`worker_library.py` audit JSONL only after that audit record is durable, builds compact
active-task candidates, and can send one fixed-format advisory to the existing coordinator
mailbox. It cannot assign or interrupt workers, change a task/claim/receipt, approve work,
rewrite a specification, or mark anything complete.

This slice is provider-free. It has no HTTP client, does not read credentials, and does not
start a daemon. The normal worker-library boundary supplies no selector or transport, so
installing or enabling it cannot make a provider request. An explicit caller may use
`pit_crew.run(..., selector=...)` for a controlled local stub or a separately
owner-authorized future adapter; that callable is admitted through the existing
credential-free `integrations/jev_telescope/provider_guard.py` boundary.
The Pit Crew archive includes that guard from the same core revision; the full Telescope
adapter remains optional.

## Configuration

Merge an optional object into the target workspace's `.de67/state/workspace.json`. Off is
the default: it creates no Pit Crew state, performs no provider/selector activity, and emits
no notice. A malformed, absent, broken, or unfunded optional route is ignored by
`worker_library.py`; ordinary worker audit and coordinator behavior continue unchanged.

```json
{
  "jev_pit_crew": {
    "mode": "off",
    "state_path": "/target-workspace/.de67/state/owner-chosen-pit-crew.sqlite3",
    "max_scan_bytes": "owner-chosen-positive-integer",
    "max_candidates": "owner-chosen-positive-integer",
    "max_admissions": "owner-chosen-non-negative-integer",
    "cooldown_seconds": "owner-chosen-non-negative-number",
    "selection_timeout_seconds": "owner-chosen-positive-number",
    "provider_guard": { "mode": "off" }
  }
}
```

`state_path` must resolve inside the target workspace's `.de67/state/`, not the installed
package. Shadow/on require every Pit Crew bound and a matching, fully owner-configured Provider
Guard as described in [Jev Telescope's guide](../jev_telescope/README.md#durable-provider-admission-guard).
Pit Crew supplies no paid-mode defaults and does not convert HTTP, rate-limit, auth, or local
errors into a funding claim.

`shadow` records a validated local selection and usage but does not enqueue. `on` enqueues
only after exact candidate/relationship validation and a second task/evidence freshness check.
A selector may choose the complete candidate relationship or `none`; it does not need to
supply a generated explanation. The ordinary hook has no selector, so a configured
`shadow`/`on` workspace remains provider-free until an explicit caller supplies one.

## Owner operations

To deactivate, set `jev_pit_crew.mode` to `off`. That path opens no Pit Crew state, invokes
no selector, and emits no new notice; leave any prior durable state available for audit instead
of deleting it while a delivery could be uncertain. To activate `shadow` or `on`, explicitly
choose every Pit Crew and matching Provider Guard bound shown above, including the local state
owners, byte/candidate/admission limits, cooldown, timeout, and Guard call/request/concurrency/
retry limits. There is no automatic transport or paid-mode default.

Pit Crew has no funding classifier or top-up action. Current Jev Telescope Guard behavior does
not treat authentication, 429, 529, timeout, or a local error as funds exhaustion. If a future,
authoritative provider contract enables a persisted `disabled_funds` latch and the owner has
replenished the same Guard scope, the owner—not Pit Crew—must explicitly reset it on the owning
host:

```python
from provider_guard import ProviderGuard

ProviderGuard(owner_guard_config).reset_funds_latch(owner_confirmed=True)
```

The Guard's documented auth reset is likewise explicit after credentials are corrected:
`ProviderGuard(owner_guard_config).reset_auth_latch(owner_confirmed=True)`. Neither reset is a
reason to replay an uncertain advisory or to make a live request; the next admission must be a
fresh, separately authorized call.

## Evidence and delivery rules

- Inputs are final worker evidence in the durable worker-library JSONL stream. Per-source byte
  cursors avoid transcript rereads. Replacement/truncation resets the cursor generation;
  individual line hashes and exact byte handles make stale evidence fail closed.
- Candidates have stable identities and contain the active task objective, an assumption or
  related active task where applicable, and the original event handle. The only relationship
  classes are `relevant_new_evidence`, `duplicated_investigation`, and
  `challenged_assumption`.
- Explicit independent verification is suppressed. Hard or long work is never interpreted as a
  stuck-worker signal; there is no stuck relationship class.
- Delivery deduplicates by original evidence event + recipient + task + relationship and
  applies the configured cooldown. The recipient is always `coordinator`.
- A durable `prepared` emission is reconciled against the real mailbox by its stable Pit Crew
  sender identity. If a prior process may have enqueued but no mailbox record can be found, it
  becomes `uncertain`; it is not blindly resent.

The fixed message names a *possible* relationship and original evidence handle, explicitly
preserves coordinator authority, and never replaces the worker's own update/final-result carrier.

## Controlled comparison and validation

The checked-in [evaluation fixture](evaluation.json) keeps independent labels apart from
controlled-stub choices. The evaluator creates temporary active task state and durable
worker-event JSONL, then drives the real Pit Crew selector seam through the local guard in
`shadow` mode. It intentionally retains one missed duplicate and one irrelevant notice, so
the outcome is mixed rather than promoted as a usefulness win. It reports useful/irrelevant/
missed relationships, induced follow-up effort, local stub calls/tokens/latency, candidate
relationships, and the observed zero-mailbox shadow outcome:

```sh
python3 integrations/jev_pit_crew/evaluate.py
python3 -m unittest discover -s integrations/jev_pit_crew -p 'test_*.py'
```

The tests cover the three relationship classes, none, explicit independent verification, long
work, unknown/stale identities, restart/source replacement, deduplication/cooldown,
concurrent/uncertain mailbox delivery, off/shadow/on, guard failures, and absent/broken/copied
package isolation. They use temporary SQLite owners and injected local stubs only; no credential,
provider request, installation, or promotion is involved.
