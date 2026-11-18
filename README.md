# de67

de67 helps a Codex team plan an idea, inspect the code and freeze the intended work in a specification, then orchestrate implementation, testing, and repair. A work ledger and deadline clock preserve progress and evidence across handoffs. GPT-6.2 Sol coordinates and GPT-6.2 Astra reviews mutations.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

[![de67 dashboard demo showing the worker roster and trajectory radar](docs/assets/dashboard-overview.png)](integrations/dashboard/README.md)

*The dashboard renders synthetic campaign data.*

| Topic | Guide |
| --- | --- |
| Requirements, installation, upgrade, and verification | [Install de67](docs/install.md) |
| Phase commands and boundaries | [Skill router](SKILL.md) |
| Architecture, supervision, and durable artifacts | [How de67 works](docs/how-de67-works.md) |
| Optional dashboard and hosting | [Dashboard guide](integrations/dashboard/README.md) |
| Optional owner contact and direct input | [OpenClaw/Discord guide](integrations/openclaw_discord/SETUP.md) |
| Experimental optional Jev retrieval | [Jev Telescope guide](integrations/jev_telescope/README.md) |
| Experimental optional Jev evidence advisories | [Jev Pit Crew guide](integrations/jev_pit_crew/README.md) |
| Problems and recovery | [Troubleshooting](docs/troubleshooting.md) |
| Release details | [GPT-6.2 release notes](docs/releases/3.5.0.md) and [release promotion](RELEASE_PROMOTION.md) |
| Introduction | [Illustrated explainer](docs/assets/de67-explainer.mp4?raw=true) |

The core skill works without optional integrations. Install matching add-on archives only for the capabilities you want; the Jev packages remain experimental and disabled by default.

Built for [OpenAI Codex](https://openai.com/codex/). Josef Horvath directed the method, contributed the imagination round, and supplied the Cataclysm-AOL proving ground. OpenAI Codex implemented the skill and integrations. The [MSW kernel](references/msw-kernel.md) comes from [@aienginerd](https://x.com/aienginerd); [Jekudy's GrillMe](https://github.com/Jekudy/grillme-skill), [Absurd](https://github.com/earendil-works/absurd), [Slopo](https://github.com/rafal-qa/slopo), and SolAdvisor informed parts of the method. Licensed under [Apache 2.0](LICENSE).
