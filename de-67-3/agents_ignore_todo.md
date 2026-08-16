# Frozen agent backlog — ignore during DE-67 runs

This is a human maintenance note with no DE-67 runtime authority. Routers, coordinators, workers,
reviewers, and watchers must not read, execute, summarize, mutate, or copy it into project `.de67/`
state. Only the repository owner or an agent directly tasked with maintaining this note may change it.

## Pending

- Add a low-maintenance, read-only DE67 dashboard for the repository owner.

  Purpose and boundary:

  - Host a small home-network website on the machine that owns the long-lived DE67 workspaces.
  - Show the authoritative `.de67/DFS.md`, active and blocked `.de67/work-ledger.md` items, and a
    compact projection of SQLite clock, deadline-generation, restart, supervisor, and optional
    sidecar state.
  - Do not use a coordinator, worker, observer, or language-model call to render or refresh it.
  - Do not edit DE67 state from the site, create a second source of truth, add required ledger
    fields, add coordinator rituals, or make dashboard health a DE67 blocker.
  - Keep public hosting, remote code execution, a large frontend framework, and automatic user
    deployment outside the first version.

  Recommended architecture:

  - Use a standalone read-only process that reads the DFS and ledger directly and queries SQLite
    through a strictly read-only connection and transaction.
  - Build an immutable in-memory projection and atomically swap it only after a refresh attempt has
    produced a usable result. Keep the last good projection for each source independently.
  - Do not require an on-disk generated snapshot in the first version. A persisted cache may be
    considered later, but it must stay explicitly disposable and non-authoritative.
  - Serve small server-rendered HTML. A manual-refresh page should have effectively zero idle work;
    optional browser refresh may be configured explicitly without becoming DE67 policy.
  - Run under process supervision independent of the DE67 supervisor. Removing, breaking, or
    restarting the dashboard must have no effect on DE67.

  Source and rendering rules:

  - Read each Markdown file as one byte snapshot. Decode tolerantly, record source identity and
    observation time, and detect when the file changes during observation.
  - Render headings, paragraphs, lists, checkboxes, code fences, and basic tables conservatively.
    Unknown or incomplete Markdown falls back to escaped text; never pass raw source HTML through.
  - Escape every value from Markdown, SQLite, paths, findings, restart reasons, and error messages.
    Use a content-security policy that disallows scripts, frames, remote assets, and inline event
    handlers.
  - Query SQLite with read-only mode, `PRAGMA query_only`, and one consistent read transaction. Do
    not instantiate the operational deadline harness merely to render state because its open path
    may initialize or migrate schema.
  - Present the immutable original claim clock, appended deadline generations, active task clock,
    restart generation, and supervisor/process observation as different facts. Do not flatten them
    into one ambiguous deadline.
  - Show each panel's observed time, source hash or identity, freshness, and partial/stale/error
    state. Markdown and SQLite cannot share one transaction, so the page must not imply perfect
    simultaneity.

  Failure behavior:

  - A malformed or partially written DFS or ledger leaves its last good panel visible with a clear
    stale/error notice while other panels continue updating.
  - A locked, missing, replaced, newer-schema, or temporarily unavailable database leaves the last
    good clock panel visible and never waits behind or writes to the operational owner.
  - A missing workspace produces a healthy unavailable page. If no last-good view exists after a
    service restart, show an empty unavailable state rather than failing the service.
  - Refresh requests share one refresh operation instead of multiplying filesystem and database
    reads during active churn.
  - Display exceptions, service crashes, restart loops, and complete dashboard absence never stop,
    restart, mutate, or block DE67.

  Home-network access:

  - Bind to loopback by default. Home-network exposure is an explicit owner configuration.
  - Prefer an authenticated home-network or Tailscale HTTPS endpoint in front of the loopback
    service. Direct unauthenticated LAN binding exposes specifications, paths, findings, and blocker
    text to every device on that network and should not be the default.
  - Keep authentication and TLS concerns outside the DE67 runtime and outside the authoritative
    workspace state.

  Smallest honest vertical slice:

  - One standard-library service, one configured workspace, and one server-rendered overview.
  - DFS status and claim navigation; active and blocked ledger items; current task and deadline
    generation; compact restart/supervisor state; per-source freshness and errors.
  - Immutable in-memory last-good projection, loopback-only initial service, no workspace writes,
    and no OpenClaw dependency.
  - Focused controls for partial files, invalid UTF-8, incomplete Markdown, unknown fields, HTML and
    script payloads, source changes during reads, SQLite locks, missing/replaced/newer databases,
    parser exceptions, workspace disappearance, service restart, and concurrent refreshes.
  - Prove that dashboard reads do not initialize, migrate, or modify SQLite and that DE67 continues
    when the dashboard is absent or repeatedly broken.

  Packaging direction:

  - Develop and validate the dashboard in `de67-lab`, then promote it deliberately into release
    `de67` as an optional integration.
  - The dashboard and OpenClaw adapter may share a top-level `integrations/` home and packaging
    conventions, but they remain separate install units and processes. The dashboard is passive;
    the OpenClaw adapter receives external owner authority and therefore has a different trust and
    failure boundary.
- Add an owner-contact route for blockers that require a material user decision. Preserve unattended
  progress on other unblocked work, and do not treat ordinary worker findings as reasons to contact
  the owner.
