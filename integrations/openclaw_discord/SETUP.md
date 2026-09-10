# Install the optional Discord package

For Codex installing this integration for an interested user: explain the requirements below,
obtain the user's channel/account choices, then perform the authorized setup and verification.
The package is optional; no Discord account is needed for core de67.

Download `de67-3.0.0-discord.zip` from the [v3.0.0 release](https://github.com/josihosi/de67/releases/tag/v3.0.0),
verify its entry in `SHA256SUMS`, and merge its `de67/` directory into the **3.0.0 core** installation.
The archive contains these distinct routes; enable only the one the user wants:

| Route | Purpose and setup |
| --- | --- |
| Direct owner conversation | Send owner messages, images, files, or voice into the native mutator; prefix `coordinator:` to address Sol. Follow [direct input](../direct_input/README.md). |
| Blocked-only notification | Ask the owner a question only when no executable route remains. Follow [blocker adapter](README.md) and its [agent contract](AGENTS.md). |
| Task-bound consultation | Optional coordinator consultation with a configured OpenClaw agent, without posing as owner input. Follow [advisory adapter](../openclaw_advisory/README.md). |

## What the user needs

- A Discord account, a dedicated channel, and a bot/account configured in OpenClaw with access to
  read that channel and send messages. For the direct relay, incoming message content must be
  available to the bot. Obtain exact channel, guild, and permitted owner IDs from authenticated
  configuration or the user; never invent them.
- A working OpenClaw installation and its private configuration. Use the existing bot credentials;
  do not put tokens in this skill, Git, screenshots, or terminal output.
- For direct input: macOS/Linux, the core App Server transport and its Python requirements.
  Voice transcription additionally needs the configured Whisper executable and its model;
  text/image use does not require Whisper.
- The advisory adapter also requires macOS/Linux for its Unix state lock.

Codex can install dependencies, write the nonsecret relay configuration to a private location,
configure the chosen host service, and verify delivery. User-only login, bot provisioning, and
channel permission choices need the user's participation when not already available.

## Verify and remove

Run the selected package's bundled tests first. Then use the dedicated test channel or a disposable
workspace for one authorized message and verify both the native receipt and returned answer.
For direct input, exclude the channel from normal OpenClaw routing, initialize the explicit message
cursor, and ensure only one relay owns it. For blocked-only mode, do not fabricate a blocker in a
live product. Test wrong-owner rejection and an unavailable adapter as well as successful delivery.

Removal means stopping the exact optional relay/service and removing its configuration from future
launches. Preserve its cursor and pending receipt state if it may be reinstalled; uncertain messages
must not be replayed. The package's code directories can then be removed without removing core de67.
Do not stop the product supervisor simply to remove an inactive optional add-on.
