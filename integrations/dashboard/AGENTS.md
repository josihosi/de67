# Dashboard integration guidance

- This package is optional and passive. Never add it to core DE67 startup or coordinator rituals.
- Treat the configured workspace as read-only. Tests must prove source files and SQLite bytes do not
  change after refresh.
- Escape all workspace-derived text. Do not enable raw Markdown HTML, remote assets, scripts, state
  editing, coordinator restart actions, or OpenClaw controls.
- A source failure must degrade only its own panel. Preserve the last good panel in memory and make
  staleness visible.
- Bind to loopback by default. LAN exposure is an explicit owner choice.
