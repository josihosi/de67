# Owner input to running DE67 agents

This optional relay sends Discord messages into DE67's existing native agent context:

- Plain messages go to the active mutation reviewer.
- A leading `coordinator:` routes that message to the active coordinator.
- Input starts with `User Message:`. No importance keyword is needed.
- With `persistent_mutator` enabled, the first plain owner message starts Astra's
  mutator session. Later conversations and supervisor reviews resume that same native
  thread. A process lock prevents two mutator invocations from using it concurrently.
- Coordinator messages wait for the next normal DE67 launch when Sol is inactive.
- Intentional DE67 resets remain fresh launches. Only the supervisor's explicit
  `DE67_COORDINATOR_RESUME_SESSION` requests a continuation.

Native workers stay under their coordinator. Codex rejects external App Server input
to native multi-agent children; owner input is limited to coordinator and mutator.
Sol replies to workers using native `send_message` or `followup_task`. Workers without
native outbound messaging use `de-67-3/scripts/agent_mailbox.py`, whose command is
included in their task brief. Concurrent messages have separate durable records and
the recipient's adapter serializes delivery into its active turn. Agent messages are
explicitly distinguished from owner input. All roles retain their configured
models, effort, full-access sandbox, skills and computer-use capabilities.

## Runtime

The transport uses a runner-owned Unix socket on macOS or Linux. Windows keeps the
default CLI transport; portable logic can be developed and tested there.

Install `de-67-3/scripts/app-server-requirements.txt` in the interpreter that will run
the adapter. Add these fields to the target workspace's existing
`.de67/state/workspace.json`:

```json
{
  "agent_transport": "app-server",
  "agent_transport_python": "/absolute/path/to/venv/bin/python",
  "persistent_mutator": true
}
```

Use the normal `supervisor_service.py stop/start --workspace PATH` lifecycle to apply
the change. It owns clock reconciliation and restart state. Do not delete the clock,
roster, run artifacts, or pending owner corrections. `agent_transport: "cli"` restores
the original transport on the next normal launch.

Each active role publishes `.de67/state/coordinator-input.json` or `mutator-input.json`.
These are temporary connection bindings; they are removed when that runner exits.
The mutator's durable identity is `.de67/state/mutator-session.json`; preserve it across
restarts. Astra uses experimental context management. Conversations may run alongside
delivery, while applying mutations still requires the existing exclusive review lifecycle.
The dashboard reads the native mutator binding and persistent session state.
The adapter preserves the runner's task handoff, event audit, role prompt refresh, and
context-index recording. App Server diagnostics remain in the run's `app-server.log`.

## Discord cutover

Keep configuration outside the repository. Example fields:

```json
{
  "workspace": "/absolute/target/workspace",
  "stateDir": "/absolute/private/relay-state",
  "ownerId": "DISCORD_OWNER_ID",
  "channelId": "DISCORD_CHANNEL_ID",
  "guildId": "DISCORD_GUILD_ID",
  "openclawConfig": "/absolute/path/to/openclaw.json",
  "codexHome": "/absolute/path/to/.codex",
  "whisper": "/absolute/path/to/whisper"
}
```

The relay reads the existing Discord bot token from the OpenClaw configuration; do not
copy the token into this configuration or logs. Exclude this channel from ordinary
OpenClaw routing before starting the relay. Startup requires its configured channel's
`enabled` value to be `false`. Stop any previous direct relay for the same channel.

At cutover, create `stateDir/state.json` with `{"cursor": "LAST_EXISTING_MESSAGE_ID"}`.
This cursor is deliberate: old Discord messages must not be replayed. Preserve this
file and the `jobs` directory across later restarts. Run the following with the adapter's
interpreter under the host's existing service manager:

```text
python integrations/direct_input/de67_agent_relay.py --config /absolute/private/config.json
```

Only messages from the configured owner are accepted; bots and webhooks are excluded.
Images are delivered as native image input. Other files are local file references.
Audio attachments use the configured Whisper executable (`turbo`, CPU); a text caption
can supply the `coordinator:` prefix.

The relay forwards the first acknowledgment and the final answer, suppressing intervening
routine commentary. When both arrive together, only the final answer is sent. Uncertain
delivery is reported and never automatically resent; persisted native message receipts
can recover the result. A confirmed delivery without a final answer is distinguished
from an unconfirmed delivery. Receipt recovery reads only the original turn and never
feeds historical transcripts into a new agent.

## Validation

```text
python -X utf8 -m unittest discover -s de-67-3/tests -p "test_codex*"
python -X utf8 -m unittest discover -s integrations/direct_input
```

Native integration proof must additionally launch isolated runner-owned contexts, route
owner envelopes through this relay, observe the matching native user-message receipts
and final answers, and verify runner/socket cleanup. Unit fixtures alone do not establish
that the installed Codex runtime accepts input or exposes computer-use permissions.
