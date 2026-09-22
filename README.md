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

| Need | Guide |
| --- | --- |
| Install or upgrade | [Installation](docs/install.md) |
| Route phases and verify models | [Skill router](SKILL.md) |
| Discuss the idea | [de67 1](de-67-1/SKILL.md) |
| Inspect code and freeze the FS | [de67 2](de-67-2/SKILL.md) |
| Deliver and verify the FS | [de67 3](de-67-3/SKILL.md) |
| Understand the supervisor, clock, and handoffs | [How de67 works](docs/how-de67-works.md) |
| Watch progress and configure optional hosting | [Dashboard](integrations/dashboard/README.md) |
| Enable optional owner contact | [OpenClaw/Discord](integrations/openclaw_discord/README.md) |
| Inspect optional playtest evidence | [Jev Telescope](integrations/jev_telescope/README.md) |
| Enable optional evidence advisories | [Jev Pit Crew](integrations/jev_pit_crew/README.md) |
| Diagnose setup and workflow friction | [Alignment audit](alignment-audit/SKILL.md) and [MSW kernel](references/msw-kernel.md) |
| Prepare a release | [Release promotion](RELEASE_PROMOTION.md) |

The dashboard, narrator, owner contact, and evidence integrations install separately from the core method. This `de67-lab` tree is a release candidate for testing; publication to the `de67` repository and a release tag require a separate review.

Built for [OpenAI Codex](https://openai.com/codex/). Josef Horvath directed the method, contributed the imagination round, and supplied the Cataclysm-AOL proving ground. OpenAI Codex implemented the skill and integrations. [OpenClaw](https://docs.openclaw.ai/) and [Tailscale](https://tailscale.com/) are optional services. The [MSW kernel](references/msw-kernel.md) comes from [@aienginerd](https://x.com/aienginerd); [Jekudy's GrillMe](https://github.com/Jekudy/grillme-skill), [Absurd](https://github.com/earendil-works/absurd), [Slopo](https://github.com/rafal-qa/slopo), and SolAdvisor informed parts of the method. Licensed under [Apache 2.0](LICENSE).
