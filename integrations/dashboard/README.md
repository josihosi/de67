# DE67 dashboard

This optional package serves a small, read-only view of one DE67 workspace. It reads
`.de67/DFS.md`, `.de67/work-ledger.md`, the deadline SQLite database, and supervisor process state.
It does not import DE67 core, write workspace state, or require OpenClaw.

Run on loopback:

```sh
python3 integrations/dashboard/de67_dashboard.py --workspace /path/to/project
```

Open `http://127.0.0.1:8767`. Add `--refresh-seconds 5` for browser-driven live refresh. The
default is manual refresh, so an idle browser causes no filesystem or database reads.

Home-network exposure is explicit:

```sh
python3 integrations/dashboard/de67_dashboard.py \
  --workspace /path/to/project --bind 0.0.0.0 --port 8767 --refresh-seconds 5
```

Direct LAN binding has no authentication or TLS. Prefer loopback behind an authenticated Tailscale
or HTTPS proxy when the workspace contents are sensitive.

The dashboard uses only Python's standard library. It keeps the last good Markdown and clock panel
in memory when a source becomes unavailable. A missing workspace, locked database, malformed text,
unknown schema, failed process probe, or dashboard crash cannot stop or mutate DE67.

Run focused tests:

```sh
python3 -m unittest integrations/dashboard/test_de67_dashboard.py
```
