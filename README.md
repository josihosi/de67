# de67

> Don't let your vibe coding project turn 67. Stop aura farming and start building. You need to **de67**.

de67 is a **skill**, an **autonomous delivery loop**, and—where reality gets sharp—just enough
**harness** to cover the whole software-building stack.

It turns an idea into a code-grounded specification, gives implementation to agents, keeps proof
attached to progress, and repairs its working method when evidence says the method—not the
product—is failing.

Built natively for [OpenAI Codex](https://openai.com/codex/). The method could be adapted to other
frontier models, and possibly strong local models, when their agent runtime provides equivalent
tools, subagents, durable state, and reasoning control. Those ports are not shipped today.

## Use de67

Install or link this complete repository as a folder named `de67` in your Codex skills directory.
Keep the router, phase folders, scripts, references, assets, integrations, and agent metadata
together.

Then invoke one phase at a time from your project:

```text
de67 1   discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   build and prove it autonomously
```

Each phase ends with a durable artifact. You decide when to begin the next phase.

## Three phases

- **[de67 1 — Discuss](de-67-1/SKILL.md)**
  Focused questions preserve the requested experience, language, and owner choices in `WEC.md`.
  Phase 1 does not design or implement the solution.

- **[de67 2 — Specify](de-67-2/SKILL.md)**
  A fresh specification owner inspects the actual repository and turns the WEC into a frozen,
  code-grounded `.de67/DFS.md`.

- **[de67 3 — Deliver](de-67-3/SKILL.md)**
  Coordinators and workers autonomously implement the frozen DFS, test production routes, preserve
  evidence, and continue until the requested outcome is proved.

**[See the complete de67 lifecycle and diagrams →](docs/how-de67-works.md)**

## Structure, not a prison

The coordinator owns the trajectory. Workers implement, investigate, test, and repair. A
deterministic clock and SQLite ledger preserve deadlines, attempts, evidence, and handovers without
spending model tokens while nothing is happening.

The machinery gives capable agents durable structure. It does not try to replace their judgment with
a maze of administrative rules.

Accepted progress survives worker or coordinator replacement. Ordinary failures remain ordinary
work. Independent mutation review changes the delivery method only when evidence or a scheduled
review justifies it.

## Steer Phase 3 while it runs

Autonomous does not mean unsteerable. Add plain-English guidance to
`.de67/mutation-suggestions.md` at any time:

```text
- Owner-authorized [trigger]: Review this at the next safe worker-quiet junction.
- Owner-authorized [defer]: Keep this for the next regularly due mutation review.
```

A **trigger** is the forcing mode: it makes mutation review due without killing work already in
flight. A **defer** is the non-forcing mode: ordinary delivery continues, and the next scheduled
review must consume the suggestion. The independent reviewer reads the complete ledger, applies
the owner-authorized outcome through guarded changes, and then returns control to a fresh
coordinator. This is the main steering wheel for Phase 3.

**[See mutation steering and the review lifecycle →](docs/how-de67-works.md#mutation-without-losing-the-work)**

## Watch it work

Phase 3 includes an optional passive website showing the live DFS, ledger, clock, workers,
coordinator, mutation state, and recent evidence. The dashboard cannot control or stop delivery.

[![de67 dashboard overview](integrations/dashboard/dashboard.png)](integrations/dashboard/README.md)

- **[Host the dashboard](integrations/dashboard/README.md)** locally or through authenticated
  [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve).
- **[Contact the owner through OpenClaw](integrations/openclaw_discord/README.md)** when no
  executable route remains and one human answer is genuinely required.

## Go deeper

| Topic | Read |
| --- | --- |
| Complete lifecycle and diagrams | [How de67 works](docs/how-de67-works.md) |
| Installation and skill routing | [Skill router](SKILL.md) |
| Discussion and the WEC | [de67 1](de-67-1/SKILL.md) |
| Repository inspection and frozen DFS | [de67 2](de-67-2/SKILL.md) |
| Autonomous delivery and mutation | [de67 3](de-67-3/SKILL.md) |
| Steering a live Phase 3 run | [Mutation review](docs/how-de67-works.md#mutation-without-losing-the-work) |
| Minimal-work reasoning | [MSW kernel](references/msw-kernel.md) |
| Writing clear, auditable artifacts | [Writing guideline](references/controlled-english.md) |
| Live progress website | [Dashboard](integrations/dashboard/README.md) |
| Optional owner contact | [OpenClaw adapter](integrations/openclaw_discord/README.md) |
| Moving lab work into a release | [Release promotion](RELEASE_PROMOTION.md) |

## Lab and release

Use a writable fork or private `de67-lab` to observe and evolve the method against real work.
Accepted mutations become reviewable Git history there.

Promote stable changes deliberately into the public release. Never overwrite the release repository
with a lab worktree. See [release promotion](RELEASE_PROMOTION.md).

## Credits

- Josef Horvath directed the product and method, contributed the imagination round, and supplied
  the live Cataclysm-AOL proving ground.
- OpenAI Codex implemented and integrated the current skill, loop, harness, dashboard, integrations,
  and failure controls.
- [OpenClaw](https://docs.openclaw.ai/) provides the optional owner-contact route.
- [Tailscale](https://tailscale.com/) provides the tested private-network and HTTPS route.
- The [MSW kernel](references/msw-kernel.md) comes from
  [@aienginerd](https://x.com/aienginerd).
- Phase 1's question-driven flow was inspired by
  [Jekudy's GrillMe](https://github.com/Jekudy/grillme-skill).
- [Absurd](https://github.com/earendil-works/absurd) by Earendil Works influenced de67's
  database-owned durable workflow state and inspectable agent-loop design. de67's implementation is
  independent and contains no Absurd code.
- The trajectory sidecar was inspired by [Slopo](https://github.com/rafal-qa/slopo). Its
  implementation is independent and contains no Slopo code.
- SolAdvisor influenced the advisory approach to agent reasoning and review.

Licensed under the [Apache License 2.0](LICENSE).
