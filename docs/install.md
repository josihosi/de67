# Install de67

These instructions are for Codex setting up de67 for its user. The core skill is independent of
the optional dashboard and Discord packages. Use the matching version of each installed package.

## Requirements and platform scope

de67 is built on OpenAI Codex, including its App Server thread, turn, tool, and event interfaces.
An authenticated Codex installation and access to the configured models are required. A generic
LLM endpoint is not a substitute. See the [Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).

| Capability | Requirements |
| --- | --- |
| Planning, specification, shared scripts and CLI transport | Python 3.10+, Git for project work, authenticated Codex CLI |
| Persistent named workers and live owner input | macOS or Linux, Codex App Server with Unix-socket support, `websockets>=15,<16` |
| Bundled detached Phase 3 service | macOS and `tmux`; the current service launcher is macOS-only |
| Native Windows | CLI transport and shared logic; the Unix App Server route is not implemented |

The configured roles are Astra high for specification, Sol low for coordination, Luna/Terra for
workers, and Astra medium for mutation review. Phase 2 probes the needed model/effort combinations
and records actual availability. Named workers run with full filesystem access; install and run
this workflow only in the user's intended execution environment.

## Install the core

1. Download `de67-3.0.0-core.zip` and `SHA256SUMS` from the
   [v3.0.0 release](https://github.com/josihosi/de67/releases/tag/v3.0.0). Verify its SHA-256 before
   extraction (`Get-FileHash` on PowerShell or `shasum -a 256` on macOS).
2. Inspect the user's existing skill installation and changes. Extract the archive's `de67/`
   directory into the configured user skills directory. Keep its complete structure; do not
   install only `SKILL.md`. An upgrade should preserve the previous installation until the new
   one is verified. Do not replace a skill used by an active run.
3. Verify the actual execution environment with `codex --version`, `codex app-server --help`,
   `python --version`, and `git --version`. On Unix, use `python3` if that is the supported
   interpreter. The shell's first Python may be too old even when a newer one is installed.
4. For the App Server route, create or use a Python virtual environment outside the skill and
   install `de-67-3/scripts/app-server-requirements.txt` with that interpreter. On macOS also
   verify `tmux -V`. Run the bundled tests below with the same interpreter.
5. Start a fresh Codex task in the target project and invoke one phase at a time. Read the
   [router](../SKILL.md), then only the selected phase. Installing the skill does not start work.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

Phase 2 creates the project configuration, records worker capabilities, and configures the project's
existing upstream for checkpoint pushes. Inspect that target before setup: setup can push already
committed work. The skill repository and the product repository are different repositories.

For persistent workers, merge these fields into the project's existing `.de67/state/workspace.json`
before its first Phase 3 launch, preserving its clock, lineage, and push configuration:

```json
{
  "agent_transport": "app-server",
  "agent_transport_python": "/absolute/path/to/venv/bin/python"
}
```

The documented service command on macOS is
`python de-67-3/scripts/supervisor_service.py start --workspace /absolute/project` from the skill
directory. Use the same script's `status` and `stop` commands. Linux supports the Unix transport,
but this release does not ship a Linux service manager; foreground supervisor execution is an
attended route, not equivalent detached-service support.

## Verify and upgrade

From the installed skill, run:

```text
python -X utf8 -m unittest discover -s tests
python -X utf8 -m unittest discover -s de-67-3/tests
```

Also verify a real disposable Codex turn in the intended runtime before starting a long run.
Tests of fixtures alone do not establish account access, model availability, or native tool access.

For an existing run, first inspect its exact workspace and follow the
[supervisor lifecycle](../de-67-3/references/external-supervisor.md). Preserve its specification,
ledgers, database, worker registry, and mutator conversation. An explicit service start normalizes
old execution ownership; it is not a harmless reload. Do not delete state to make an upgrade pass.
Legacy `DFS.md` is supported. A migrated `FS.md` requires its hash-bound `DFS.md` compatibility
pointer; do not edit the pointer as a second specification.

Optional packages: [dashboard](../integrations/dashboard/README.md) and
[Discord](../integrations/openclaw_discord/SETUP.md). Diagnose failures with
[troubleshooting](troubleshooting.md).
