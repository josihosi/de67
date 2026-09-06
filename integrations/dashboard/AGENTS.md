# Dashboard integration guidance

- This package is optional and passive. Never add it to core de67 startup or coordinator rituals.
- Treat the configured workspace as read-only. Tests must prove source files and SQLite bytes do not
  change after refresh.
- Escape all workspace-derived text. Do not enable raw Markdown HTML, remote assets, workspace-supplied scripts, state
  editing, coordinator restart actions, or OpenClaw controls.
- A source failure must degrade only its own panel. Preserve the last good panel in memory and make
  staleness visible.
- Bind to loopback by default. LAN exposure is an explicit owner choice.

- The bundled `live_refresh.js` may fetch same-origin dashboard snapshots and update display DOM.
  Keep CSP restricted to same-origin scripts/connections; never execute workspace-derived markup.
