# de67

de67 helps you plan an idea, turn it into a frozen specification grounded in your code, and
orchestrate implementation, testing, and repair. It runs on OpenAI Codex; persistent workers and
live steering use the Codex App Server.

```text
de67 1   plan and discuss the idea
de67 2   inspect the code and freeze the specification
de67 3   orchestrate implementation, testing, and repair
```

[![The complete de67 dashboard showing agents, token use, and the current work's radar.](docs/assets/dashboard-overview.png)](docs/assets/dashboard-overview.png)

**Trust the agents. Give them the context to do good work.** Sol coordinates a team of persistent
Luna and Terra workers: choosing assignments, running independent work in parallel, following the
evidence, and changing course when an approach stops helping. Workers keep useful context between
assignments and retrieve more when they need it. A returned answer can start another conversation;
Sol decides whether the requested outcome is actually met.

When an agent goes wrong, look at what it was given: the brief, the tools, the missing information,
the inherited assumptions. Refine that input and remove contradictory or unnecessary instructions.
Adding another rule, test, or ledger entry needs a reason tied to the outcome. Tests establish what
works; durable records preserve evidence and ownership across handoffs. Strategy and problem-solving
remain agent decisions.

The workflow can improve itself, too. At scheduled reviews, after deadline or integrity incidents,
or on your request, active worker turns finish and Astra reviews the approach. It can revise the
method within the workflow's contracts, then hand the accumulated work to a fresh Sol coordinator.
The intended outcome stays the reference point while the route to it can change.

- **[Install and upgrade](docs/install.md)** — requirements, platform support, and setup for Codex.
- **[How it works](docs/how-de67-works.md)** — phases, durable state, workers, and mutation review.
- **[Persistent workers](docs/worker-library.md)** — reuse, context, ownership, and evidence.
- **[Optional dashboard and hosting](integrations/dashboard/README.md)** — install, run, and expose the read-only view.
- **[Optional Discord connection](integrations/openclaw_discord/SETUP.md)** — prerequisites and agent-led installation.
- **[Troubleshooting](docs/troubleshooting.md)** — diagnose the actual failing layer.
- **[Skill router](SKILL.md)** — entrypoints for agents, including release packaging and alignment audit.
- **[v3.0.0 release notes](docs/releases/3.0.0.md)** — changes, compatibility, and package contents.
- **[Credits](docs/credits.md)** · **[Apache 2.0 license](LICENSE)**
