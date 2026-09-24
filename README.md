# de67

> Don't let your vibe coding project turn 67. Stop aura farming and start building. You need to **de67**.

de67 helps a Codex team discuss an idea, freeze a specification grounded in the code, and carry implementation through testing and repair. A GPT-6 Sol coordinator assigns GPT-6 Luna and Sol workers; GPT-6 Astra handles independent review. The ledger and deadline clock keep evidence and progress across handoffs.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

[![Synthetic de67 dashboard demo with active GPT-6 Sol, Luna, and Astra workers, campaign fuel, and trajectory radar.](docs/assets/dashboard-overview.png)](integrations/dashboard/README.md)

*Synthetic demo of the release candidate dashboard. The dashboard and its narrator are optional.*

Install the complete repository as a Codex skill folder named `de67`. You need the OpenAI Codex CLI and Python 3.10 or newer; Git is needed for repository work. Phase 2 must probe the target runtime for GPT-6 Luna and Sol model/effort pairs before Phase 3 starts. Existing workspaces with a GPT-5.6 roster must be reconfigured with successful GPT-6 probes; prior session records remain historical evidence.

**[See the complete lifecycle and diagrams →](docs/how-de67-works.md)**

## Structure, not a prison

The **supervisor** owns process lifetime. The **coordinator** owns the trajectory.
**Workers** investigate, implement, test, and repair. The clock and ledger preserve what happened
without spending model tokens while nothing is happening.

Independent work can run in parallel. Ordinary failures return to the coordinator as work to
understand and resolve. Accepted progress stays in durable state when an agent is replaced.

When mutation review is due, new dispatch pauses and active workers can finish. A fresh,
independent reviewer examines the method at a quiet junction. Guarded changes and receipts
preserve the handoff, then a fresh coordinator resumes from the ledger.

The machinery gives agents durable structure and leaves semantic judgment with the agents.

## Steer Phase 3 while it runs

Autonomous does not mean unsteerable. Add plain-English guidance to
`.de67/mutation-suggestions.md` at any time:

```text
- Owner-authorized [trigger]: Review this at the next safe worker-quiet junction.
- Owner-authorized [defer]: Keep this for the next regularly due mutation review.
```

**Trigger** makes review due without killing work in flight. **Defer** keeps ordinary delivery
moving and supplies the suggestion to the next scheduled review. Both let you name the outcome
you want the reviewer to address.

The independent reviewer reads the complete ledger, applies owner-authorized changes through the
guarded review route, and returns control to a fresh coordinator.

**[See mutation steering and the review lifecycle →](docs/how-de67-works.md#mutation-without-losing-the-work)**

## Watch it work

The optional dashboard provides a read-only view of the live FS, work ledger, deadline clock,
coordinator, workers, mutation state, and recent evidence. It cannot control or stop delivery.

Run the dashboard from this checkout:

```sh
python3 integrations/dashboard/de67_dashboard.py --workspace /path/to/project
```

Open `http://127.0.0.1:8767`. The visible tab updates in place every 30 seconds. The dashboard uses Python's standard
library; the optional narrator makes model calls only when configured.

- **[Dashboard guide](integrations/dashboard/README.md):** setup, trajectory sidecar, optional
  narrator, session sources, and network exposure.
- **[OpenClaw owner contact](integrations/openclaw_discord/README.md):** a separate, optional route
  for one human answer when no executable route remains.
- **[Pit Crew evidence advisories](integrations/jev_pit_crew/README.md):** optional, provider-free,
  coordinator-only evidence relationship notices.

## Go deeper

| Looking for… | Start here |
| --- | --- |
| Installation, requirements, and routing | [Skill router](SKILL.md) |
| The complete delivery and mutation lifecycle | [How de67 works](docs/how-de67-works.md) |
| Discussion and the WEC | [de67 1](de-67-1/SKILL.md) |
| Repository inspection and frozen FS | [de67 2](de-67-2/SKILL.md) |
| Autonomous delivery and mutation | [de67 3](de-67-3/SKILL.md) |
| A manual review of workflow friction | [Alignment audit](alignment-audit/SKILL.md) |
| Minimal-work reasoning | [MSW kernel](references/msw-kernel.md) |
| Clear, auditable artifacts | [Writing guideline](references/controlled-english.md) |
| Live progress website | [Dashboard](integrations/dashboard/README.md) |
| Optional owner contact | [OpenClaw adapter](integrations/openclaw_discord/README.md) |
| Optional evidence advisories | [Jev Pit Crew](integrations/jev_pit_crew/README.md) |
| Moving tested lab work into a release | [Release promotion](RELEASE_PROMOTION.md) |

The dashboard, narrator, owner contact, and evidence integrations install separately from the core method. This `de67-lab` tree is a release candidate for testing; publication to the `de67` repository and a release tag require a separate review.

Built for [OpenAI Codex](https://openai.com/codex/). Josef Horvath directed the method, contributed the imagination round, and supplied the Cataclysm-AOL proving ground. OpenAI Codex implemented the skill and integrations. [OpenClaw](https://docs.openclaw.ai/) and [Tailscale](https://tailscale.com/) are optional services. The [MSW kernel](references/msw-kernel.md) comes from [@aienginerd](https://x.com/aienginerd); [Jekudy's GrillMe](https://github.com/Jekudy/grillme-skill), [Absurd](https://github.com/earendil-works/absurd), [Slopo](https://github.com/rafal-qa/slopo), and SolAdvisor informed parts of the method. Licensed under [Apache 2.0](LICENSE).
