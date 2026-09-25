# de67

de67 helps a Codex team discuss an idea, freeze a specification grounded in the code, and carry implementation through testing and repair. A GPT-6 Sol coordinator assigns GPT-6 Luna and Sol workers, while GPT-6 Astra handles independent review. The ledger and deadline clock preserve progress across handoffs.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

[![de67 dashboard showing a synthetic GPT-6 campaign and its radar plot](docs/assets/dashboard-overview.png)](integrations/dashboard/README.md)

*Screenshot of the dashboard running a synthetic campaign. The dashboard is optional.*

| Topic | Guide |
| --- | --- |
| Requirements, installation, upgrade, and verification | [Install de67](docs/install.md) |
| Phase commands and boundaries | [Skill router](SKILL.md) |
| Architecture, supervision, and durable artifacts | [How de67 works](docs/how-de67-works.md) |
| Optional dashboard and hosting | [Dashboard guide](integrations/dashboard/README.md) |
| Optional owner contact | [OpenClaw/Discord guide](integrations/openclaw_discord/README.md) |
| Experimental optional Jev retrieval | [Jev Telescope guide](integrations/jev_telescope/README.md) |
| Experimental optional Jev evidence advisories | [Jev Pit Crew guide](integrations/jev_pit_crew/README.md) |
| Problems and recovery | [Troubleshooting](docs/troubleshooting.md) |
| Release contents and promotion | [GPT-6 release notes](docs/releases/3.2.1.md) and [release promotion](RELEASE_PROMOTION.md) |

The core skill works without optional integrations. The Jev add-ons are separate experimental packages; installing them does not enable provider calls by default. Existing workspaces with a GPT-5.6 capability roster need successful GPT-6 probes before new Phase-3 work. Historical records remain evidence.

Built for [OpenAI Codex](https://openai.com/codex/). Josef Horvath directed the method, contributed the imagination round, and supplied the Cataclysm-AOL proving ground. OpenAI Codex implemented the skill and integrations. The [MSW kernel](references/msw-kernel.md) comes from [@aienginerd](https://x.com/aienginerd); [Jekudy's GrillMe](https://github.com/Jekudy/grillme-skill), [Absurd](https://github.com/earendil-works/absurd), [Slopo](https://github.com/rafal-qa/slopo), and SolAdvisor informed parts of the method. Licensed under [Apache 2.0](LICENSE).
