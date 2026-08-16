# Optional OpenClaw Discord blocker adapter

This package connects one genuine DE67 blocked-only ledger to one authenticated owner answer in a
dedicated Discord channel through the OpenClaw CLI. It is optional. Core DE67 does not import this
package and works normally when OpenClaw is absent, unconfigured, broken, or removed.

The adapter runs only after the DE67 supervisor has audited the blocked-only ledger and confirmed
that no task or mutation gate is live. It sends no ordinary findings, progress updates, or active
work. A validated owner answer is stored atomically under the workspace's `.de67/state/` directory
and returned through the generic blocker-adapter JSON protocol. The coordinator, not this adapter,
decides how that owner authority changes the ledger.

## Requirements

- Python 3.10 or newer; the adapter uses only the standard library.
- A working `openclaw` CLI with a configured Discord account.
- A dedicated Discord channel for this DE67 owner-contact route.
- The numeric Discord channel ID and the only accepted owner's numeric Discord user ID.

No OpenClaw Python package is imported and no machine-specific install path is assumed. Pass the
actual OpenClaw executable with `--openclaw` when it is not available as `openclaw` on `PATH`.
The service environment must also resolve OpenClaw's own runtime dependencies. Test a real message
command under that exact service user and `PATH`; an absolute OpenClaw path does not make a missing
`node` or other launcher dependency available.

## Configure the supervisor

Pass one JSON argument array to the core supervisor. The supervisor appends `wait`, `--workspace`,
and `--lineage` without invoking a shell.

```text
--blocker-adapter-command-json ["python3","/absolute/path/to/openclaw_discord_blocker.py","--channel-id","123","--owner-id","456","--poll-seconds","2"]
```

The JSON array is one command-line value in the service definition. Use the platform's normal
quoting or structured process configuration; do not build a shell command from untrusted values.

By default, an answer must be an authenticated Discord reply whose reference identifies the
notification message. Some OpenClaw channel adapters omit reply-reference metadata. Only for a
dedicated channel where every later owner message is intentionally a DE67 answer, add:

```text
--allow-unthreaded-owner-answer
```

That weaker mode still requires the configured owner ID and a message received after the blocker
notification. Do not use it in a general chat channel.

## Failure behavior

- Missing OpenClaw, command failure, malformed JSON, an unreadable ledger, malformed adapter state,
  and channel failure make only this optional contact route unavailable.
- The core supervisor reports the adapter error and remains safely quiescent with exit code zero.
- Active DE67 work never invokes the adapter.
- The adapter never edits the DFS, ledger, clock database, or coordinator restart state.
- A changed blocker gets a new digest. Unrelated ledger formatting or active-section edits do not
  create another blocker identity.
- On first use, a matching pending or answered record from the former `discord-blockers.json`
  location is copied into the generic adapter state without modifying the legacy file.

See `AGENTS.md` for the installation and verification contract an integrating agent must follow.
