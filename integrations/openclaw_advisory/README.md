# Task-bound OpenClaw advisory adapter

This optional adapter gives an active DE67 coordinator a bounded, read-only consultation path to
the configured Astra Mutator conversation. It is separate from `direct_input`, the owner-authorized
Discord relay, and never writes the owner mailbox or DE67 ledgers.

The host-owned config must contain `workspace`, `openclaw`, `agent`, `session_key`,
`recipient_role`, and `role_source`; `role_source_sha256` may pin the host guidance digest. The
packet supplied by Sol contains `lineage_id`, `task_id`, `assignment_revision`,
`sender_run_id`, `sender_session_id`, `sender_supervisor_id`, the concise state/decision fields,
and retained evidence references. SQLite is authoritative for the lineage, active task claim,
coordinator run, and supervisor owner. The assignment hash is recomputed from the current ledger,
so stale or rebound packets fail closed.

Each canonical packet gets one stable SHA-256 request identity. Requests are written under
`.de67/state/advisory-consultations/` and indexed by
`.de67/state/advisory-consultations.json`. An exclusive state lock serializes mixed writers;
`submitting`/`uncertain` requests are never resent automatically. A caller may explicitly retry an
`unavailable` endpoint. The exact Gateway JSON payload and reply identity are retained, and replies
that are missing, failed, or equal to the request are not accepted. The command is always an
argument array and deliberately omits `--deliver`.

The module is library-first. For a one-shot packet file:

```text
python advisory_consult.py --config /private/host/advisory.json --packet /private/request.json
```

The CLI returns a JSON result and exits zero for an unavailable optional route so the coordinator
can retain the continuation. Add `--retry-unavailable` only after inspecting an unavailable result;
`submitting`/`uncertain` requests remain fenced against replay. Isolated coverage is in `test_advisory_consult.py`; it proves wrong
sender/workspace/revision, duplicate and mixed-writer retries, unavailable endpoint retention,
echo rejection, no `--deliver`, and no owner-mailbox mutation.
