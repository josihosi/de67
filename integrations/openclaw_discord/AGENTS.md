# Agent integration instructions

Install this adapter only when the owner explicitly enables OpenClaw/Discord blocker contact.
Do not make OpenClaw a DE67 prerequisite and do not copy this package into phase instructions.

Before enabling it:

1. Verify Python 3.10 or newer and the exact `openclaw` executable on the target machine.
2. Verify OpenClaw's Discord account and the dedicated channel without printing credentials.
3. Obtain the exact channel ID and owner user ID from the owner or authenticated configuration.
4. Prefer reply-reference enforcement. Use `--allow-unthreaded-owner-answer` only after inspecting
   actual OpenClaw read output and only with a dedicated DE67 channel.
5. Add the adapter command through `--blocker-adapter-command-json`; do not edit core DE67 imports,
   requirements, or Python path.

Verification must prove:

- no adapter configured: active and blocked-only DE67 behavior remains normal;
- missing executable, nonzero exit, invalid JSON, and malformed state: core exits safely without a
  coordinator restart or DE67 failure;
- active ledger work: no OpenClaw command runs;
- genuine blocked-only ledger: one notification is sent for one blocker digest;
- wrong owner, empty answer, old message, and wrong reply reference are ignored;
- authenticated bound owner answer is durable and returned once;
- unrelated ledger edits do not duplicate the notification, while a materially changed blocker
  receives a new digest;
- adapter removal after configuration does not stop ordinary DE67 work.

For a live verification, use a disposable workspace and test channel when available. Never turn an
active product ledger into a fake blocker. If observing a real blocked workspace, do not answer or
restart it unless the owner separately authorizes that exact decision.
