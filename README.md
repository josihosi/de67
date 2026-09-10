# de67

de67 helps you plan an idea, turn it into a frozen specification grounded in your code, and
orchestrate implementation, testing, and repair. It runs on OpenAI Codex; persistent workers and
live steering use the Codex App Server.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

[![The de67 dashboard showing agents, token use, and the current work's radar.](docs/assets/dashboard-overview.png)](integrations/dashboard/README.md)

- **[Install and upgrade](docs/install.md)** — requirements, platform support, and setup for Codex.
- **[How it works](docs/how-de67-works.md)** — phases, durable state, workers, and mutation review.
- **[Persistent workers](docs/worker-library.md)** — reuse, context, ownership, and evidence.
- **[Optional dashboard and hosting](integrations/dashboard/README.md)** — install, run, and expose the read-only view.
- **[Optional Discord connection](integrations/openclaw_discord/SETUP.md)** — prerequisites and agent-led installation.
- **[Troubleshooting](docs/troubleshooting.md)** — diagnose the actual failing layer.
- **[Skill router](SKILL.md)** — entrypoints for agents, including release packaging and alignment audit.
- **[v3.0.0 release notes](docs/releases/3.0.0.md)** — changes, compatibility, and package contents.
- **[Credits](docs/credits.md)** · **[Apache 2.0 license](LICENSE)**
