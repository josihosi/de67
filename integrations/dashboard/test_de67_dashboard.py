import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("de67_dashboard.py")
SPEC = importlib.util.spec_from_file_location("de67_dashboard", MODULE_PATH)
dashboard_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(dashboard_module)


class DashboardTests(unittest.TestCase):
    def test_native_persistent_mutator_activity_replaces_legacy_source(self) -> None:
        state = self.workspace / '.de67/state'
        state.mkdir(parents=True, exist_ok=True)
        config_path = state / 'workspace.json'
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
        config['persistent_mutator'] = True
        config_path.write_text(json.dumps(config))
        self.assertEqual(dashboard_module.native_mutator_state(self.workspace, 30),
                         {'glowing': False, 'status': 'idle'})
        session = {'thread_id': 'astra', 'state': 'active', 'mode': 'conversation'}
        (state / 'mutator-session.json').write_text(json.dumps(session))
        (state / 'mutator-input.json').write_text(json.dumps({
            'thread_id': 'astra', 'workspace': str(self.workspace.resolve()), 'state': 'active',
            'runner_pid': 123, 'server_pid': 456}))
        with patch.object(dashboard_module.os, 'kill'):
            self.assertEqual(dashboard_module.native_mutator_state(self.workspace, 30),
                             {'glowing': True, 'status': 'conversation'})
        with patch.object(dashboard_module.os, 'kill', side_effect=ProcessLookupError):
            self.assertEqual(dashboard_module.native_mutator_state(self.workspace, 30),
                             {'glowing': False, 'status': 'idle'})

    def test_mutator_message_lights_galaxy_until_reply(self) -> None:
        database = self.workspace / "openclaw-agent.sqlite"
        connection = sqlite3.connect(database)
        connection.executescript("""
            CREATE TABLE session_nodes (current_session_id TEXT, archived_at INTEGER);
            CREATE TABLE session_windows (session_id TEXT, status TEXT, ended_at INTEGER);
            CREATE TABLE session_pending_inputs (session_id TEXT, state TEXT, consumed_event_id TEXT);
            INSERT INTO session_nodes VALUES ('live', NULL), ('archived', 1);
            INSERT INTO session_windows VALUES ('live', 'running', NULL), ('archived', 'running', NULL), ('old', 'running', NULL);
        """)
        connection.close()

        def change(sql):
            connection = sqlite3.connect(database)
            connection.executescript(sql)
            connection.close()

        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions,
                                               mutator_activity_db=database)
        before = database.read_bytes()
        self.assertIn('class="galaxy on"', dashboard.render("overview").decode())
        self.assertEqual(before, database.read_bytes())
        change("UPDATE session_windows SET status='done', ended_at=100000 WHERE session_id='live'")
        with patch.object(dashboard_module.time, "time", return_value=101):
            self.assertEqual(dashboard_module.openclaw_mutator_state(database, 30),
                             {"glowing": True, "status": "replied"})
        with patch.object(dashboard_module.time, "time", return_value=131):
            self.assertIn('class="galaxy off"', dashboard.render("overview").decode())
        change("INSERT INTO session_pending_inputs VALUES ('live', 'queued', NULL)")
        self.assertEqual(dashboard_module.openclaw_mutator_state(database, 30),
                         {"glowing": True, "status": "queued"})
        change("UPDATE session_pending_inputs SET consumed_event_id='consumed'")
        for status in ("failed", "killed", "timeout"):
            change(f"UPDATE session_windows SET status='{status}' WHERE session_id='live'")
            self.assertIn('class="galaxy off"', dashboard.render("overview").decode())
        database.unlink()
        self.assertIn('class="galaxy off"', dashboard.render("overview").decode())
        self.assertEqual(dashboard.snapshot()["mutator_activity"]["status"], "unavailable")

    def test_coordinator_activity_tracks_wait_and_resume(self) -> None:
        trace = self.sessions / "activity.jsonl"
        records = []

        def append(record_type, **payload):
            records.append({"type": record_type, "payload": payload})
            trace.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")

        append("event_msg", type="task_started")
        self.assertEqual(dashboard_module._session_activity(trace), "working")
        append("response_item", type="function_call", name="wait_agent", call_id="wait-1")
        append("event_msg", type="token_count")
        append("response_item", type="agent_message")
        append("response_item", type="agent_message", content="incoming " * 70000)
        self.assertEqual(dashboard_module._session_activity(trace), "waiting")
        append("response_item", type="function_call_output", call_id="wait-1", output="agent finished")
        self.assertEqual(dashboard_module._session_activity(trace), "working")
        append("response_item", type="custom_tool_call", name="exec", input="do work")
        self.assertEqual(dashboard_module._session_activity(trace), "working")
        append("event_msg", type="task_complete")
        self.assertEqual(dashboard_module._session_activity(trace), "waiting")
        with trace.open("a", encoding="utf-8") as stream:
            stream.write('\n{"type":')
        self.assertEqual(dashboard_module._session_activity(trace), "waiting")

        index = self.sessions.parent / "state_5.sqlite"
        with sqlite3.connect(index) as connection:
            connection.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
            connection.execute("INSERT INTO threads VALUES (?, ?)", ("live", str(trace)))
        connection.close()
        with patch.object(dashboard_module, "_active_coordinator_id", return_value="live"):
            self.assertEqual(dashboard_module.coordinator_activity(self.workspace, self.sessions), "waiting")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.sessions = self.workspace / "sessions"
        self.sessions.mkdir()
        state = self.workspace / ".de67/state"
        state.mkdir(parents=True)
        (state / "workspace.json").write_text(json.dumps({
            "version": 1,
            "clock": {"state": str(state / "deadlines.sqlite3"), "lineage": "lineage"},
        }), encoding="utf-8")
        (self.workspace / ".de67/DFS.md").write_text(
            "# DFS\n\nStatus: Frozen\n\n<script>alert(1)</script>\n\n"
            "- [ ] R-009 — active work\n"
            "- [ ] R-010 — waiting on an event\n"
            "- [ ] 🔴 R-011 — upcoming work\n"
            "- [x] R-012 — accepted work\n",
            encoding="utf-8",
        )
        (self.workspace / ".de67/work-ledger.md").write_text(
            "# Ledger\n\n## Active work\n\n- [ ] R-009 — useful work\n\n"
            "## Waiting work\n\n- [ ] R-010 — waiting work\n\n## Blocked work\n",
            encoding="utf-8",
        )
        connection = sqlite3.connect(state / "deadlines.sqlite3")
        connection.executescript("""
            CREATE TABLE tasks (task_id TEXT, claim_id TEXT, started_at REAL, deadline_at REAL,
              closure_gap_id TEXT, closure_gap_revision INTEGER);
            INSERT INTO tasks VALUES ('R009-M1','R-009',1,9999999999,'G-002',41);
            CREATE TABLE claim_deadline_generations (generation INTEGER, deadline_at REAL);
            INSERT INTO claim_deadline_generations VALUES (11,9999999999);
            CREATE TABLE coordinator_restart_requests (generation INTEGER);
            INSERT INTO coordinator_restart_requests VALUES (12);
            CREATE TABLE incidents (kind TEXT);
            INSERT INTO incidents VALUES ('deadline_miss');
            CREATE TABLE worker_findings (
              task_id TEXT, reported_at REAL, short_verdict TEXT, evidence TEXT
            );
            INSERT INTO worker_findings VALUES ('R009-M0',1,'escaped <finding>','details');
            CREATE TABLE deadline_mutation_components (component TEXT);
            INSERT INTO deadline_mutation_components VALUES ('micro'), ('macro');
            CREATE TABLE integrity_mutation_components (component TEXT);
            INSERT INTO integrity_mutation_components VALUES ('micro'), ('macro');
            CREATE TABLE random_mutation_cycles (
              cycle_number INTEGER, interval_windows INTEGER, due_after_terminal_windows INTEGER,
              resolution_evidence TEXT,
              ordinary_resolution_evidence TEXT, universal_resolution_evidence TEXT
            );
            INSERT INTO random_mutation_cycles VALUES
              (1,1,1,'done',NULL,NULL), (2,2,2,NULL,NULL,NULL);
        """)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()


    def test_token_trace_reads_only_complete_appends_and_handles_truncation(self) -> None:
        from datetime import datetime, timezone
        trace = self.sessions / "fuel.jsonl"
        def event(total):
            return json.dumps({"type": "event_msg", "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {"type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": total, "cached_input_tokens": 10, "output_tokens": 5},
                    "last_token_usage": {"input_tokens": 20, "cached_input_tokens": 10, "output_tokens": 5}}}}).encode() + b"\n"
        trace.write_bytes(event(100))
        self.assertEqual(dashboard_module._trace_fuel(trace)["fresh"], 95)
        pending = event(150)
        with trace.open("ab") as stream:
            stream.write(pending[:-1])
        self.assertEqual(dashboard_module._trace_fuel(trace)["fresh"], 95)
        with trace.open("ab") as stream:
            stream.write(b"\n")
        usage = dashboard_module._trace_fuel(trace)
        self.assertEqual(usage["fresh"], 145)
        self.assertEqual(usage["observed"], 65)
        self.assertTrue(usage["partial"])
        self.assertEqual([value for _, value in usage["points"]], [15, 50])
        self.assertEqual(dashboard_module._trace_fuel(trace)["points"], usage["points"])
        with trace.open("ab") as stream:
            stream.write(event(30))
        self.assertEqual(dashboard_module._trace_fuel(trace)["observed"], 80)
        trace.write_bytes(event(30))
        self.assertEqual(dashboard_module._trace_fuel(trace)["fresh"], 25)
        self.assertEqual([n for _, n in dashboard_module._trace_fuel(trace)["points"]], [15])

    def test_campaign_fuel_is_scoped_deduplicated_and_read_only(self) -> None:
        from datetime import datetime, timezone
        clock = self.workspace / ".de67/state/deadlines.sqlite3"
        with sqlite3.connect(clock) as connection:
            connection.executescript("CREATE TABLE supervisor_attempts(role TEXT, run_id TEXT, lineage_id TEXT);")
            connection.executemany("INSERT INTO supervisor_attempts VALUES (?,?,?)", [
                ("coordinator", "run1", "lineage"), ("coordinator", "run1", "lineage"),
                ("mutation-reviewer", "run2", "lineage"), ("coordinator", "other", "unrelated")])
        connection.close()
        for run, session in (("run1", "coord"), ("run2", "review")):
            folder = self.workspace / ".de67/state/coordinator-runs" / run
            folder.mkdir(parents=True)
            (folder / "session_id.txt").write_text(session)
        index = self.sessions.parent / "state_5.sqlite"
        with sqlite3.connect(index) as connection:
            connection.executescript("CREATE TABLE threads(id TEXT, rollout_path TEXT); CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT);")
            for session, total in (("coord",100), ("worker",200), ("nested",300), ("review",400), ("unrelated",999)):
                path = self.sessions / (session + ".jsonl")
                path.write_text(json.dumps({"type":"turn_context", "payload":{"model":"gpt-5.6-luna" if session == "nested" else "gpt-5.6-terra"}}) + "\n" + json.dumps({"type":"event_msg", "timestamp":datetime.now(timezone.utc).isoformat(),
                    "payload":{"type":"token_count", "info":{"total_token_usage":{
                    "input_tokens":total,"cached_input_tokens":10,"output_tokens":5},
                    "last_token_usage":{"input_tokens":total,"cached_input_tokens":10,"output_tokens":5}}}}) + "\n")
                connection.execute("INSERT INTO threads VALUES (?,?)", (session,str(path)))
            connection.executemany("INSERT INTO thread_spawn_edges VALUES (?,?)", [("coord","worker"),("worker","nested")])
        connection.close()
        paths = [p for p in self.workspace.rglob("*") if p.is_file()]
        before = [p.read_bytes() for p in paths]
        fuel = dashboard_module.fuel_state(self.workspace, self.sessions)
        self.assertEqual(fuel["totals"], {"coordinator":95,"terra":195,"luna":295,"astra":395,"other":0})
        self.assertEqual(sum(fuel["bins"]), sum(fuel["totals"].values()))
        for role in fuel["totals"]:
            self.assertEqual(sum(fuel["series"][role]), fuel["totals"][role])
        self.assertFalse(fuel["partial"])
        self.assertEqual(fuel["sessions"], 4)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        (self.sessions / "nested.jsonl").unlink()
        self.assertTrue(dashboard_module.fuel_state(self.workspace, self.sessions)["partial"])

    def test_fuel_labels_and_dynamic_axis(self) -> None:
        for peak, label in ((0,"1"),(1800,"2k"),(9000000,"10m")):
            page = dashboard_module.render_fuel({"available":True,"totals":{"coordinator":1,"terra":2,"luna":4,"astra":3,"other":0},
                "bins":[peak] + [0]*23,"series":{role:[peak if role == "terra" else 0]+[0]*23 for role in ("astra","coordinator","terra","luna","other")},"partial":True})
            self.assertIn('aria-label="coordinator: 1 fresh tokens"', page)
            self.assertIn('aria-label="worker Terra: 2 fresh tokens"', page)
            self.assertIn('aria-label="worker Luna: 4 fresh tokens"', page)
            self.assertEqual(page.count('class="fuel-series"'), 4)
            self.assertLess(page.index("<svg"), page.index('class="fuel-total"'))
            self.assertIn('aria-label="mutator: 3 fresh tokens"', page)
            self.assertLess(page.index('</svg>'), page.index('class="fuel-legend"'))
            self.assertLess(page.index('class="fuel-legend"'), page.index('class="fuel-bars"'))
            self.assertIn('left:100.00%">5</span>', page)
            self.assertIn("role totals · log scale", page)
            self.assertIn("campaign · partial", page)
            self.assertIn("0 to " + label + " tokens per hour", page)
            self.assertIn("last 24h", page)

    def test_role_dot_axis_crops_unused_range_and_keeps_role_order(self) -> None:
        import re
        roles = ("astra", "coordinator", "terra", "luna")
        for values in ((13000000, 12000000, 102000000, 5000000), (10, 10, 10, 10), (0, 0, 0, 0)):
            page = dashboard_module.render_fuel({"available": True,
                "totals": dict(zip(roles, values)), "bins": [0] * 24,
                "series": {role: [0] * 24 for role in roles}, "partial": False})
            plot = page.split('class="fuel-bars"', 1)[1]
            labels = re.findall(r'aria-label="([^":]+):', plot)
            self.assertEqual(labels, ["mutator", "coordinator", "worker Terra", "worker Luna"])
            positions = [float(value) for value in re.findall(r'<em style="left:([0-9.]+)%', plot)]
            self.assertEqual(len(positions), sum(value > 0 for value in values))
            self.assertTrue(all(0 <= value <= 100 for value in positions))
            self.assertIn('data-role="astra" style="color:#fff0d6"', page)
            if values[0] == 13000000:
                self.assertIn('left:0.00%">5m</span>', plot)
                self.assertIn('left:100.00%">200m</span>', plot)
            if not any(values):
                self.assertNotIn('class="fuel-bar-axis"', plot)

    def test_refresh_interval_and_local_script_are_explicit(self) -> None:
        for interval in (0, 30, 900):
            page = dashboard_module.Dashboard(self.workspace, refresh_seconds=interval,
                sessions_root=self.sessions).render("overview").decode()
            self.assertIn(f'data-refresh-seconds="{interval}"', page)
            self.assertIn('<script src="/live_refresh.js" defer></script>', page)
            self.assertIn('id="dashboard-content"', page)
            self.assertNotIn('http-equiv="refresh"', page)
            self.assertIn("Manual refresh" if not interval else f"Live · every {interval}s", page)

    def test_projection_is_read_only_and_escapes_workspace_html(self) -> None:
        paths = [self.workspace / ".de67/DFS.md", self.workspace / ".de67/work-ledger.md",
                 self.workspace / ".de67/state/deadlines.sqlite3"]
        before = [path.read_bytes() for path in paths]
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("dfs").decode()
        self.assertIn("<title>de67</title>", page)
        self.assertIn('aria-label="de67 · supervisor', page)
        self.assertNotIn("DE67", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_random_count_excludes_restart_cleanup_and_other_lineages(self):
        connection = sqlite3.connect(self.workspace / ".de67/state/deadlines.sqlite3")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            ALTER TABLE tasks ADD COLUMN lineage_id TEXT;
            ALTER TABLE tasks ADD COLUMN attempt_terminal_at REAL;
            ALTER TABLE tasks ADD COLUMN attempt_terminal_kind TEXT;
            ALTER TABLE tasks ADD COLUMN abandonment_reason TEXT;
            ALTER TABLE random_mutation_cycles ADD COLUMN lineage_id TEXT;
            UPDATE random_mutation_cycles SET lineage_id='current';
            UPDATE tasks SET lineage_id='current', attempt_terminal_at=1, attempt_terminal_kind='completed';
            INSERT INTO tasks (lineage_id,attempt_terminal_at,attempt_terminal_kind) VALUES ('current',2,'restart_normalized'),('other',3,'completed');
            INSERT INTO tasks (lineage_id,attempt_terminal_at,attempt_terminal_kind,abandonment_reason) VALUES ('current',4,'abandoned','external_supervisor_restart_normalization');
        """)
        _, _, cycle = dashboard_module._completed_mutation_counts(connection)
        self.assertEqual(cycle["terminal_windows"], 1)
        self.assertEqual(cycle["remaining_windows"], 1)
        connection.close()

    def test_overview_uses_real_ledger_and_clock_state(self) -> None:
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("overview").decode()
        self.assertIn("R009-M1", page)
        self.assertIn("gap G-002 r41", page)
        self.assertIn("deadline generation 11", page)
        self.assertIn("restart 12", page)
        self.assertIn("useful work", page)
        self.assertIn("<h2>Up next</h2>", page)
        self.assertIn("R-011", page)
        self.assertIn("upcoming work", page)
        self.assertNotIn("R-012 — accepted work", page)
        self.assertIn("<h2>Waiting on event</h2>", page)
        self.assertIn("waiting work", page)
        self.assertIn("<small>mutations</small><strong>3</strong>", page)
        self.assertIn('aria-label="Astra mutator: idle"', page)
        self.assertNotIn("<small>Random mutations</small>", page)
        self.assertIn("due in 2 results", page)
        self.assertIn('class="cosmos-workers"', page)
        self.assertIn("unavailable", page)
        self.assertIn("Latest finding", page)
        self.assertIn("R009-M0", page)
        self.assertIn("escaped &lt;finding&gt;", page)
        self.assertNotIn("escaped <finding>", page)

    def test_fratbro_card_is_opt_in_and_directly_below_trajectory(self) -> None:
        cache = self.workspace / "dashboard-cache/fratbro.json"
        cache.parent.mkdir()
        cache.write_text(json.dumps({"summary": (
            "The worker is testing whether real smoke escapes a building. The wall blocked it, "
            "which is useful progress; next it will clean the save and rerun."
        )}), encoding="utf-8")
        sidecar = self.workspace / "sidecar.py"
        sidecar.write_text("# fixture\n", encoding="utf-8")
        report = {"claim": "R-009", "gaps": [{"gap_id": "G-002", "status": "open"}]}

        with patch.object(dashboard_module, "read_sidecar", return_value=report):
            page = dashboard_module.Dashboard(
                self.workspace, sessions_root=self.sessions,
                sidecar_script=sidecar, fratbro_cache=cache,
            ).render("overview").decode()

        self.assertLess(page.index("Trajectory sidecar"), page.index("BRIEFING"))
        self.assertLess(page.index("BRIEFING"), page.index("Latest finding"))
        self.assertIn("The worker is testing whether real smoke escapes a building.", page)
        self.assertNotIn("Fratbro status <em>stale</em>", page)
        self.assertNotIn("Fratbro status", dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions
        ).render("overview").decode())

    def test_unchanged_fratbro_input_does_not_spawn_luna_again(self) -> None:
        script = self.workspace / "fratbro_narrator.py"
        script.write_text("# fixture\n", encoding="utf-8")
        cache = self.workspace / "fratbro.json"
        dashboard = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions,
            fratbro_script=script, fratbro_cache=cache,
        )
        ledger = {"identity": {"hash": "ledger"}}
        clock = {"data": {"task": {"task_id": "R-009"}}}
        process = type("Process", (), {"poll": lambda self: None})()

        with (patch.object(dashboard_module, "_active_worker_claims",
                           return_value={"worker": "coordinator"}),
              patch.object(dashboard_module.subprocess, "Popen", return_value=process) as spawn):
            dashboard._fratbro_source(ledger, clock)
            dashboard._fratbro_source(ledger, clock)
            dashboard._fratbro_source({"identity": {"hash": "changed"}}, clock)

        self.assertEqual(spawn.call_count, 1)

    def test_fratbro_fires_again_when_worker_finishes(self) -> None:
        script = self.workspace / "fratbro_narrator.py"
        script.write_text("# fixture\n", encoding="utf-8")
        cache = self.workspace / "fratbro.json"
        dashboard = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions,
            fratbro_script=script, fratbro_cache=cache,
        )
        process = type("Process", (), {"poll": lambda self: 0})()
        active_clock = {"data": {"latest_task": {"task_id": "R-009"}}}
        terminal_clock = {"data": {"latest_task": {
            "task_id": "R-009", "completed_at": 42,
        }}}

        with (patch.object(dashboard_module, "_active_worker_claims",
                           side_effect=[{"worker": "coordinator"}, {}]),
              patch.object(dashboard_module.subprocess, "Popen", return_value=process) as spawn):
            dashboard._fratbro_source({}, active_clock)
            dashboard._fratbro_source({}, terminal_clock)

        self.assertEqual(spawn.call_count, 2)

    def test_overview_falls_back_to_ledger_for_non_string_clock_claim(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE tasks SET claim_id = ?", (sqlite3.Binary(b"R-011"),)
        )
        connection.commit()
        connection.close()

        page = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions
        ).render("overview").decode()

        self.assertIn("<h2>Up next</h2>", page)
        self.assertIn("R-011", page)
        self.assertIn("upcoming work", page)

    def test_upcoming_dfs_work_excludes_active_waiting_blocked_and_accepted_claims(self) -> None:
        ledger = dashboard_module.parse_ledger(
            "## Active work\n- [ ] R-002 — active depends on R-light.response\n"
            "## Waiting work\n- [ ] R-003 — waiting\n"
            "## Blocked work\n- Blocked: R-004 — blocked\n"
        )
        dfs = (
            "# DFS\n\nStatus: Refrozen\n\n"
            "- [ ] 🔴 R-002 — active\n"
            "- [ ] 🔴 R-003 — waiting\n"
            "- [ ] 🔴 R-004 — blocked\n"
            "- [ ] 🔴 R-light.response — first upcoming claim references R-002\n"
            "- [x] R-006 — accepted\n"
            "  - [ ] 🔴 R-nested — nested implementation detail\n"
            "~~~markdown\n"
            "- [ ] 🔴 R-example — fenced example\n"
            "``` does not close a tilde fence\n"
            "~~~\n"
            "````markdown\n"
            "```\n"
            "- [ ] 🔴 R-short-fence — still inside four backticks\n"
            "````\n"
        )

        upcoming = dashboard_module.upcoming_dfs_work(dfs, ledger, "R-002")

        self.assertEqual(
            upcoming,
            "- [ ] 🔴 R-light.response — first upcoming claim references R-002",
        )

    def test_upcoming_dfs_work_accepts_workspace_setup_frozen_status_forms(self) -> None:
        ledger = dashboard_module.parse_ledger("## Active work\n- [ ] R-002 — active\n")
        for status in (
            "Status: Frozen against inspected source baseline",
            "Status: Refrozen against inspected source baseline",
            "- Status: `Frozen` against inspected source baseline",
        ):
            with self.subTest(status=status):
                upcoming = dashboard_module.upcoming_dfs_work(
                    f"# DFS\n\n{status}\n\n- [ ] 🔴 R-next_1 — upcoming\n",
                    ledger,
                    "R-002",
                )
                self.assertEqual(upcoming, "- [ ] 🔴 R-next_1 — upcoming")

    def test_draft_dfs_does_not_project_upcoming_work(self) -> None:
        ledger = dashboard_module.parse_ledger("## Active work\n- [ ] R-002 — active\n")

        upcoming = dashboard_module.upcoming_dfs_work(
            "# DFS\n\nStatus: Draft\n\n"
            "~~~markdown\nStatus: Frozen\n~~~\n"
            "## Freeze record\n\nStatus: Refrozen\n\n"
            "- [ ] 🔴 R-003 — not authoritative\n",
            ledger,
            "R-002",
        )

        self.assertEqual(upcoming, "")

    def test_upcoming_claim_identity_is_case_sensitive_and_ignores_ledger_fences(self) -> None:
        ledger = dashboard_module.parse_ledger(
            "## Active work\n- [ ] R-foo — active\n"
            "~~~markdown\n- [ ] R-fenced — example only\n~~~\n"
        )
        dfs = (
            "# DFS\n\nStatus: Frozen\n\n"
            "- [ ] 🔴 R-FOO — distinct uppercase claim\n"
            "- [ ] 🔴 R-fenced — not owned by the ledger example\n"
        )

        upcoming = dashboard_module.upcoming_dfs_work(dfs, ledger, "R-foo")

        self.assertIn("R-FOO — distinct uppercase claim", upcoming)
        self.assertIn("R-fenced — not owned by the ledger example", upcoming)

    def test_deadline_matches_active_claim_when_generations_are_equal(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("DROP TABLE claim_deadline_generations")
        connection.execute("ALTER TABLE tasks ADD COLUMN lineage_id TEXT")
        connection.execute("ALTER TABLE tasks ADD COLUMN deadline_generation INTEGER")
        connection.execute(
            "UPDATE tasks SET lineage_id = 'lineage', deadline_generation = 1"
        )
        connection.executescript("""
            CREATE TABLE claim_deadline_generations (
              lineage_id TEXT, claim_id TEXT, generation INTEGER, deadline_at REAL
            );
            INSERT INTO claim_deadline_generations VALUES
              ('lineage','R-009',1,9999999999),
              ('lineage','R-001',1,1);
        """)
        connection.commit()
        connection.close()

        clock = dashboard_module.read_clock(database)
        self.assertEqual(clock["task"]["claim_id"], "R-009")
        self.assertEqual(clock["deadline"]["claim_id"], "R-009")
        self.assertEqual(clock["deadline"]["deadline_at"], 9999999999)

    def test_deadline_without_active_worker_uses_newest_unretired_claim_clock(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE claim_deadline_generations (
              lineage_id TEXT, claim_id TEXT, generation INTEGER,
              started_at REAL, deadline_at REAL, retired_at REAL
            );
            INSERT INTO claim_deadline_generations VALUES
              ('lineage','R-008',1,200,9999999999,300),
              ('lineage','R-009',1,100,8888888888,NULL);
        """)

        deadline = dashboard_module._active_deadline(connection, None)

        self.assertEqual(deadline["claim_id"], "R-009")
        self.assertEqual(deadline["deadline_at"], 8888888888)
        connection.close()

    def test_overview_uses_alternate_configured_clock_for_clock_and_sidecar(self) -> None:
        alternate = self.workspace / ".de67/state/alternate.sqlite3"
        connection = sqlite3.connect(alternate)
        connection.executescript("""
            CREATE TABLE tasks (task_id TEXT, claim_id TEXT, started_at REAL,
              deadline_at REAL, closure_gap_id TEXT, closure_gap_revision INTEGER);
            INSERT INTO tasks VALUES ('R002-M001','R-002',2,9999999999,NULL,NULL);
        """)
        connection.commit()
        connection.close()
        config = self.workspace / ".de67/state/workspace.json"
        config.write_text(json.dumps({
            "version": 1,
            "clock": {"state": ".de67/state/alternate.sqlite3", "lineage": "lineage"},
        }), encoding="utf-8")
        script = self.workspace / "trajectory_sidecar.py"
        script.write_text("# test sidecar\n", encoding="utf-8")

        with patch.object(dashboard_module, "read_sidecar", return_value={"gaps": []}) as run:
            page = dashboard_module.Dashboard(
                self.workspace, sessions_root=self.sessions, sidecar_script=script
            ).render("overview").decode()

        self.assertIn("R002-M001", page)
        self.assertNotIn("R009-M1", page)
        self.assertEqual(run.call_args.args[2], alternate.resolve())

    def test_mutation_review_lamp_tracks_incomplete_clock_components(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.executescript("""
            CREATE TABLE claim_deadline_generation_incidents (
              lineage_id TEXT, claim_id TEXT, generation INTEGER, recorded_at REAL,
              reviewed_at REAL
            );
            CREATE TABLE deadline_generation_mutation_components (
              lineage_id TEXT, claim_id TEXT, generation INTEGER, component TEXT
            );
            INSERT INTO claim_deadline_generation_incidents
              VALUES ('lineage','R-009',12,100,NULL);
            INSERT INTO deadline_generation_mutation_components
              VALUES ('lineage','R-009',12,'micro');
        """)
        connection.commit()
        connection.close()

        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions)
        running = dashboard.render("overview").decode()
        self.assertIn('aria-label="Astra mutator: reviewing"', running)

        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE claim_deadline_generation_incidents SET reviewed_at = 101"
        )
        connection.commit()
        connection.close()
        reviewed = dashboard.render("overview").decode()
        self.assertIn('aria-label="Astra mutator: idle"', reviewed)

        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE claim_deadline_generation_incidents SET reviewed_at = NULL"
        )
        connection.execute(
            "INSERT INTO deadline_generation_mutation_components VALUES (?,?,?,?)",
            ("lineage", "R-009", 12, "macro"),
        )
        connection.commit()
        connection.close()
        off = dashboard.render("overview").decode()
        self.assertIn('aria-label="Astra mutator: idle"', off)

    def test_terminal_attempt_is_not_shown_as_running_work(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("ALTER TABLE tasks ADD COLUMN attempt_terminal_at REAL")
        connection.execute("UPDATE tasks SET attempt_terminal_at=2")
        connection.commit()
        connection.close()
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("overview").decode()
        self.assertNotIn("R009-M1", page)
        self.assertIn('<strong>work: R-009</strong>', page)

    def test_invalid_utf8_is_visible_without_raw_failure(self) -> None:
        (self.workspace / ".de67/DFS.md").write_bytes(b"# DFS\n\xff")
        state = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).snapshot()
        self.assertTrue(state["dfs"]["identity"]["invalid_utf8"])
        self.assertIn("�", state["dfs"]["html"])

    def test_missing_sources_return_healthy_unavailable_page(self) -> None:
        empty = Path(self.temporary.name) / "gone"
        page = dashboard_module.Dashboard(empty, sessions_root=self.sessions).render("overview").decode()
        self.assertIn("Work in focus", page)
        self.assertIn("SQLite", page)
        self.assertIn("workspace.json", page)

    def test_last_good_panel_survives_source_disappearance(self) -> None:
        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions)
        first = dashboard.snapshot()
        (self.workspace / ".de67/DFS.md").unlink()
        second = dashboard.snapshot()
        self.assertFalse(first["dfs"]["stale"])
        self.assertTrue(second["dfs"]["stale"])
        self.assertIn("<h1>DFS</h1>", second["dfs"]["html"])

    def test_last_good_clock_survives_malformed_workspace_configuration(self) -> None:
        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions)
        first = dashboard.snapshot()["clock"]
        (self.workspace / ".de67/state/workspace.json").write_text(
            "{malformed", encoding="utf-8"
        )
        second = dashboard.snapshot()["clock"]
        self.assertFalse(first["stale"])
        self.assertTrue(second["stale"])
        self.assertEqual(second["data"]["task"]["task_id"], "R009-M1")

    def test_exclusive_sqlite_lock_does_not_wait_or_write(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        before = database.read_bytes()
        writer = sqlite3.connect(database)
        writer.execute("BEGIN EXCLUSIVE")
        try:
            state = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).snapshot()
            self.assertIsNotNone(state["clock"]["error"])
        finally:
            writer.rollback()
            writer.close()
        self.assertEqual(before, database.read_bytes())

    def test_incomplete_fence_and_unknown_markdown_are_escaped(self) -> None:
        rendered = dashboard_module.render_markdown("# One\n\n```\n<img src=x onerror=bad>")
        self.assertIn("&lt;img src=x onerror=bad&gt;", rendered)
        self.assertNotIn("<img", rendered)

    def test_de67_control_markers_are_hidden_without_enabling_raw_html(self) -> None:
        rendered = dashboard_module.render_markdown(
            "<!-- DE67:DELIVERY-STATUS:BEGIN claim=R-ONE -->\n"
            "- [x] R-ONE — accepted\n"
            "<!-- DE67:DELIVERY-STATUS:END -->\n"
            "<!-- ordinary comment -->\n"
        )

        self.assertNotIn("DE67:DELIVERY-STATUS", rendered)
        self.assertIn("☑ R-ONE — accepted", rendered)
        self.assertIn("&lt;!-- ordinary comment --&gt;", rendered)

    def test_ledger_continuations_stay_inside_one_decorative_rail(self) -> None:
        rendered = dashboard_module.render_ledger_section(
            "- [ ] R-009 — useful work\n"
            "  - Phase: Closure.\n"
            "  - Current route: first line\n"
            "    continues here.\n"
        )
        self.assertEqual(rendered.count('class="ledger-item"'), 1)
        self.assertIn('class="ledger-title">R-009 — useful work', rendered)
        self.assertIn("continues here", rendered)
        self.assertNotIn("☐", rendered)

    def test_ledger_accepts_projection_heading_and_preserves_nested_claim_text(self) -> None:
        ledger = (
            "# Active Phase-3 projection\n\n"
            "## R-001 — immutable evidence class and gate authority\n\n"
            "- Claim: preserve every evidence class.\n"
            "- Current route: R001-M002.\n"
        )
        parsed = dashboard_module.parse_ledger(ledger)
        rendered = dashboard_module.render_ledger_section(parsed["active"])

        self.assertEqual(parsed["claim"], "R-001")
        self.assertIn("## R-001", parsed["active"])
        self.assertIn("preserve every evidence class", parsed["active"])
        self.assertIn("<h2>R-001 — immutable evidence class and gate authority</h2>", rendered)
        self.assertIn("Current route: R001-M002.", rendered)

    def test_ledger_without_section_template_is_shown_as_active_text(self) -> None:
        parsed = dashboard_module.parse_ledger("Coordinator note without special headings.\n")

        self.assertEqual(parsed["active"], "Coordinator note without special headings.")
        self.assertEqual(parsed["waiting"], "")
        self.assertEqual(parsed["blocked"], "")

    def test_ledger_claim_accepts_the_authoritative_nonnumeric_id_grammar(self) -> None:
        parsed = dashboard_module.parse_ledger(
            "# Active Phase-3 projection\n\n## R-light.response — active claim\n"
        )

        self.assertEqual(parsed["claim"], "R-light.response")

    def test_completed_section_cannot_become_active_projection_focus(self) -> None:
        parsed = dashboard_module.parse_ledger(
            "# Active Phase-3 projection\n\n"
            "## Completed cockpit foundation\n\n"
            "### R-010 — completed\n\n- [x] Done.\n\n"
            "## Active cockpit items\n\n"
            "### R-012 — active\n\n- [ ] Current route.\n"
        )

        self.assertEqual(parsed["claim"], "R-012")
        self.assertNotIn("R-010", parsed["active"])

    def test_between_workers_focuses_latest_durable_task_not_ledger_order(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("ALTER TABLE tasks ADD COLUMN attempt_terminal_at REAL")
        connection.execute("UPDATE tasks SET attempt_terminal_at = 2")
        connection.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?)",
            ("R008-M1", "R-008", 3, 9999999999, "G-008", 1, 4),
        )
        connection.commit()
        connection.close()
        (self.workspace / ".de67/work-ledger.md").write_text(
            "# Active Phase-3 projection\n\n"
            "## Completed work\n\n### R-010 — completed\n\n"
            "## Active work\n\n### R-012 — queued\n",
            encoding="utf-8",
        )

        page = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions
        ).render("overview").decode()

        self.assertIn("<strong>work: R-008</strong>", page)
        self.assertNotIn("<strong>work: R-010</strong>", page)

    def test_sidecar_is_cached_by_clock_state_and_rendered_without_artifacts(self) -> None:
        script = self.workspace / "trajectory_sidecar.py"
        script.write_text("# test sidecar\n", encoding="utf-8")
        report = {
            "claim": "R-009",
            "closure_sequence": 2,
            "latest_task": "R009-M1",
            "latest_task_gap": "G-002",
            "latest_task_result": "active",
            "gaps": [
                {"gap_id": "G-001", "revision": 1, "summary": "proved route",
                 "status": "proved", "attempts": 1,
                 "implementation_relation": 0.25, "test_relation": 0.75},
                {"gap_id": "G-002", "revision": 41, "summary": "<active route>",
                 "status": "open", "attempts": 3,
                 "implementation_relation": 0.8, "test_relation": 0.4},
            ],
            "churn_vector": {
                "product_owner": {"direction": "product-surface-present",
                                  "evidence": ["one changed product path"]},
            },
            "attention": [
                {"key": "target", "label": "Assigned gap", "source": "R009-M1",
                 "points": [
                     {"gap_id": "G-001", "raw_relation": 0, "relative_pull": 0},
                     {"gap_id": "G-002", "raw_relation": 1, "relative_pull": 1},
                 ]},
                {"key": "code", "label": "Workspace code", "source": "Current <diff>",
                 "points": [
                     {"gap_id": "G-001", "raw_relation": .25, "relative_pull": .3125},
                     {"gap_id": "G-002", "raw_relation": .8, "relative_pull": 1},
                 ]},
                {"key": "test", "label": "Workspace tests", "source": "Current diff",
                 "points": [
                     {"gap_id": "G-001", "raw_relation": .75, "relative_pull": 1},
                     {"gap_id": "G-002", "raw_relation": .4, "relative_pull": .533},
                 ]},
            ],
        }
        before = set(self.workspace.rglob("*"))
        with patch.object(dashboard_module, "read_sidecar", return_value=report) as run:
            dashboard = dashboard_module.Dashboard(
                self.workspace, sessions_root=self.sessions, sidecar_script=script
            )
            first = dashboard.render("overview").decode()
            second = dashboard.render("overview").decode()
        self.assertEqual(run.call_count, 1)
        self.assertIn("Trajectory sidecar", first)
        self.assertIn("G-002 r41", first)
        self.assertNotIn("What the boxes mean", first)
        self.assertEqual(first.count('class="gap-explanation '), 2)
        self.assertEqual(first.count('class="gap-state"'), 2)
        self.assertIn("active · 3 attempts", first)
        self.assertNotIn("code 0.80 · test 0.40", first)
        self.assertNotIn('class="product-vector"', first)
        self.assertNotIn('class="test-vector"', first)
        self.assertNotIn("product surface present", first)
        self.assertIn("Attention spider", first)
        self.assertIn("Relative pull · not completion", first)
        self.assertIn('class="attention-series attention-code"', first)
        self.assertIn("Current &lt;diff&gt;", first)
        self.assertIn("Each line is scaled to its own strongest gap", first)
        self.assertIn('class="attention-claim"', first)
        self.assertEqual(first.count('class="trajectory-node '), 2)
        self.assertIn("&lt;active route&gt;", first)
        self.assertLess(first.index("cosmos-workers"), first.index("Trajectory sidecar"))
        self.assertLess(first.index("Trajectory sidecar"), first.index("Latest finding"))
        self.assertEqual(first.split("<body>")[0], second.split("<body>")[0])
        self.assertEqual(before, set(self.workspace.rglob("*")))

    def test_trajectory_tolerates_different_gap_shapes_and_missing_fields(self) -> None:
        single = dashboard_module.render_trajectory({
            "claim": "R-ONE", "latest_task": None, "gaps": [
                {"gap_id": "G-ONLY", "revision": 1, "status": "open",
                 "summary": "single gap", "implementation_relation": "invalid"},
                "unstructured gap text",
            ], "churn_vector": "optional non-mapping value",
        })
        self.assertIn("G-ONLY r1", single)
        self.assertIn("No active attempt", single)
        self.assertIn("unstructured gap text", single)
        self.assertIn("Waiting for attention data", single)
        self.assertEqual(single.count('class="trajectory-node '), 2)

        many = dashboard_module.render_trajectory({
            "claim": "R-MANY", "gaps": [
                {"gap_id": f"G-{index:03d}", "revision": index, "status": "open",
                 "summary": "gap", "implementation_relation": 2,
                 "test_relation": -1}
                for index in range(1, 15)
            ],
        })
        self.assertEqual(many.count('class="trajectory-node open"'), 14)
        self.assertIn('viewBox="0 0 794 794"', many)

        empty = dashboard_module.render_trajectory({"claim": "R-EXPLORE", "gaps": []})
        self.assertIn("No closure trajectory", empty)

    def test_trajectory_uses_literal_subtasks_as_axes_and_keeps_gap_cards(self) -> None:
        rendered = dashboard_module.render_trajectory({
            "claim": "R-008",
            "latest_task": "R008-M3",
            "latest_task_result": "active",
            "subtasks": [
                {"subtask_id": "setup", "status": "done", "summary": "Fixture setup"},
                {"subtask_id": "signal", "status": "active", "summary": "Signal causation"},
                {"subtask_id": "bandits", "status": "open", "summary": "Bandit lifecycle"},
                {"subtask_id": "camp", "status": "finding", "summary": "Camp interaction"},
            ],
            "gaps": [
                {"gap_id": "G-001", "revision": 2, "status": "open",
                 "summary": "Acceptance proof", "attempts": 3},
            ],
            "attention": [],
        })

        self.assertIn("Subtask attention", rendered)
        self.assertIn("Attention distribution across ledger subtasks", rendered)
        self.assertEqual(rendered.count('class="trajectory-node '), 4)
        self.assertIn(">signal</text>", rendered)
        self.assertNotIn("signal r?", rendered)
        self.assertIn("G-001 r2", rendered)
        self.assertEqual(rendered.count('class="gap-explanation '), 1)

    def test_exploration_without_closure_gaps_is_a_healthy_empty_sidecar(self) -> None:
        script = self.workspace / "trajectory_sidecar.py"
        script.write_text("# test sidecar\n", encoding="utf-8")
        dashboard = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions, sidecar_script=script
        )
        with patch.object(
            dashboard_module, "read_sidecar",
            side_effect=RuntimeError("error: No closure gaps found for lineage/R-009"),
        ) as run:
            first = dashboard.snapshot()["sidecar"]
            second = dashboard.snapshot()["sidecar"]
        self.assertIsNone(first["error"])
        self.assertEqual(first["data"]["gaps"], [])
        self.assertEqual(second, first)
        self.assertEqual(run.call_count, 1)

    def test_active_workers_are_counted_by_model_and_effort(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort, complete=False):
            path = day / name
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            ]
            if complete:
                items.append({"type": "event_msg", "payload": {"type": "task_complete"}})
            path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")

        write_session("rollout-2026-08-18T08-00-00-root.jsonl", "root", None,
                      "gpt-5.6-sol", "low")
        write_session("rollout-2026-08-18T08-01-00-luna.jsonl", "luna", "root",
                      "gpt-5.6-luna", "medium")
        write_session("rollout-2026-08-18T08-02-00-terra.jsonl", "terra", "root",
                      "gpt-5.6-terra", "high", complete=True)
        write_session("rollout-2026-08-18T08-03-00-sol.jsonl", "sol", "root",
                      "gpt-5.6-sol", "low")

        page = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions
        ).render("overview").decode()
        self.assertIn('class="cosmos-workers"', page)
        self.assertIn('aria-label="Luna: low: 0, medium: 1, high: 0, max: 0"', page)
        self.assertIn("<strong>Terra</strong>", page)
        self.assertNotIn("<strong>Sol</strong>", page)
        self.assertNotIn("Unavailable", page)

    def test_nested_luna_helpers_count_as_active_workers(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort, complete=False):
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            ]
            if complete:
                items.append({"type": "event_msg", "payload": {"type": "task_complete"}})
            (day / name).write_text(
                "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
            )

        write_session("rollout-root.jsonl", "root", None, "gpt-5.6-sol", "low")
        write_session("rollout-terra.jsonl", "terra", "root", "gpt-5.6-terra", "high")
        write_session("rollout-helper-a.jsonl", "helper-a", "terra", "gpt-5.6-luna", "low")
        write_session("rollout-helper-b.jsonl", "helper-b", "terra", "gpt-5.6-luna", "max")
        write_session(
            "rollout-finished-helper.jsonl", "helper-old", "terra",
            "gpt-5.6-luna", "medium", complete=True,
        )

        workers = dashboard_module.worker_state(self.workspace, self.sessions)

        self.assertEqual(workers["counts"]["terra"]["high"], 1)
        self.assertEqual(workers["counts"]["luna"]["low"], 1)
        self.assertEqual(workers["counts"]["luna"]["max"], 1)
        self.assertEqual(workers["counts"]["luna"]["medium"], 0)

    def test_interrupted_nested_luna_helpers_are_not_active_workers(self) -> None:
        day = self.sessions / "2026/09/02"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort, events):
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-09-02T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
            ] + [{"type": "event_msg", "payload": {"type": event}}
                 for event in events]
            (day / name).write_text(
                "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
            )

        write_session("rollout-root.jsonl", "root", None,
                      "gpt-5.6-sol", "low", ["task_started"])
        write_session("rollout-terra.jsonl", "terra", "root",
                      "gpt-5.6-terra", "high", ["task_started"])
        write_session("rollout-interrupted-a.jsonl", "helper-a", "terra",
                      "gpt-5.6-luna", "low", ["task_started", "turn_aborted"])
        write_session("rollout-interrupted-b.jsonl", "helper-b", "terra",
                      "gpt-5.6-luna", "max", ["task_started", "turn_aborted"])

        workers = dashboard_module.worker_state(self.workspace, self.sessions)

        self.assertEqual(workers["counts"]["terra"]["high"], 1)
        self.assertEqual(workers["counts"]["luna"]["low"], 0)
        self.assertEqual(workers["counts"]["luna"]["max"], 0)

    def test_interrupted_worker_can_be_reactivated(self) -> None:
        session = self.sessions / "rollout-worker.jsonl"
        session.write_text("".join(json.dumps(item) + "\n" for item in (
            {"type": "event_msg", "payload": {"type": "task_started"}},
            {"type": "event_msg", "payload": {"type": "turn_aborted"}},
            {"type": "event_msg", "payload": {"type": "task_started"}},
        )), encoding="utf-8")

        self.assertFalse(dashboard_module._session_complete(session))

    def test_durable_claims_hide_released_primaries_without_completion_markers(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort):
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            ]
            (day / name).write_text(
                "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
            )

        write_session("rollout-root.jsonl", "root", None, "gpt-5.6-sol", "low")
        write_session("rollout-live.jsonl", "live", "root", "gpt-5.6-terra", "medium")
        write_session("rollout-owner-lost.jsonl", "owner-lost", "root",
                      "gpt-5.6-terra", "medium")
        write_session("rollout-returned.jsonl", "returned", "root",
                      "gpt-5.6-terra", "medium")
        write_session("rollout-helper.jsonl", "helper", "live", "gpt-5.6-luna", "low")
        write_session("rollout-stale-helper.jsonl", "stale-helper", "owner-lost",
                      "gpt-5.6-luna", "low")

        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.executescript("""
            ALTER TABLE tasks RENAME TO legacy_tasks;
            CREATE TABLE tasks (
              lineage_id TEXT, task_id TEXT, started_at REAL,
              attempt_terminal_at REAL, abandoned_at REAL
            );
            CREATE TABLE worker_claims (
              lineage_id TEXT, task_id TEXT, worker_id TEXT,
              coordinator_session_id TEXT, released_at REAL
            );
            INSERT INTO tasks VALUES
              ('lineage','live-task',1,NULL,NULL),
              ('lineage','lost-task',2,3,3),
              ('lineage','returned-task',4,5,5);
            INSERT INTO worker_claims VALUES
              ('lineage','live-task','live','root',NULL),
              ('lineage','lost-task','owner-lost','root',3),
              ('lineage','returned-task','returned','root',5);
        """)
        connection.commit()
        connection.close()

        workers = dashboard_module.worker_state(self.workspace, self.sessions)

        self.assertEqual(workers["counts"]["terra"]["medium"], 1)
        self.assertEqual(workers["counts"]["luna"]["low"], 1)

    def test_worker_header_survives_large_metadata_before_turn_context(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort, noise=0):
            path = day / name
            items = [{"type": "session_meta", "payload": {
                "id": session_id, "parent_thread_id": parent,
                "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
            }}]
            items.extend(
                {"type": "response_item", "payload": {"text": "x" * 32768}}
                for _ in range(noise)
            )
            items.extend([
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            ])
            path.write_text(
                "".join(json.dumps(item) + "\n" for item in items), encoding="utf-8"
            )

        write_session("rollout-root.jsonl", "root", None, "gpt-5.6-sol", "low")
        write_session(
            "rollout-worker.jsonl", "worker", "root", "gpt-5.6-luna", "high", noise=20
        )

        workers = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertEqual(workers["counts"]["luna"]["high"], 1)

    def test_active_runner_selects_coordinator_and_reactivated_worker(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort, events):
            path = day / name
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
            ] + [{"type": "event_msg", "payload": {"type": event}} for event in events]
            path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")

        write_session("rollout-root.jsonl", "coordinator", None,
                      "gpt-5.6-terra", "low", ["task_started"])
        write_session("rollout-worker.jsonl", "worker", "coordinator",
                      "gpt-5.6-luna", "high",
                      ["task_started", "task_complete", "task_started"])
        write_session("rollout-unrelated.jsonl", "unrelated", None,
                      "gpt-5.6-sol", "low", ["task_started"])

        runner = self.workspace / ".de67/state/runner-runs/live"
        runner.mkdir(parents=True)
        (runner / "status.json").write_text(
            json.dumps({"status": "running"}), encoding="utf-8"
        )
        (runner / "events.jsonl").write_text(json.dumps({
            "type": "item.started",
            "item": {"type": "collab_tool_call", "sender_thread_id": "coordinator"},
        }) + "\n", encoding="utf-8")

        workers = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertTrue(workers["available"])
        self.assertEqual(workers["counts"]["luna"]["high"], 1)

        with (day / "rollout-worker.jsonl").open("a", encoding="utf-8") as session:
            session.write(json.dumps({
                "type": "event_msg", "payload": {"type": "task_complete"}
            }) + "\n")
        completed = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertEqual(completed["counts"]["luna"]["high"], 0)

    def test_historical_incomplete_worker_is_not_inherited_by_current_coordinator(self) -> None:
        day = self.sessions / "2026/08/18"
        day.mkdir(parents=True)

        def write_session(name, session_id, parent, model, effort):
            path = day / name
            items = [
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": parent,
                    "cwd": str(self.workspace), "timestamp": "2026-08-18T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {"model": model, "effort": effort}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            ]
            path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")

        write_session("rollout-old-root.jsonl", "old-coordinator", None,
                      "gpt-5.6-terra", "low")
        write_session("rollout-worker.jsonl", "worker", "old-coordinator",
                      "gpt-5.6-luna", "medium")
        write_session("rollout-current-root.jsonl", "current-coordinator", None,
                      "gpt-5.6-terra", "low")

        old_runner = self.workspace / ".de67/state/coordinator-runs/old"
        current_runner = self.workspace / ".de67/state/coordinator-runs/current"
        old_runner.mkdir(parents=True)
        current_runner.mkdir(parents=True)
        (old_runner / "session_id.txt").write_text("old-coordinator\n", encoding="ascii")
        (old_runner / "status.txt").write_text("DONE\n", encoding="ascii")
        (current_runner / "session_id.txt").write_text("current-coordinator\n", encoding="ascii")
        (current_runner / "status.txt").write_text("RUNNING\n", encoding="ascii")
        stale_runner = self.workspace / ".de67/state/old-coordinator-runs/stale"
        stale_runner.mkdir(parents=True)
        (stale_runner / "session_id.txt").write_text("old-coordinator\n", encoding="ascii")
        (stale_runner / "status.txt").write_text("RUNNING\n", encoding="ascii")
        (self.workspace / ".de67/state/coordinator-supervisor.pid").write_text(
            "123\n", encoding="ascii"
        )

        command = type("Completed", (), {
            "stdout": (f"123 python coordinator_supervisor.py --workspace {self.workspace} "
                       f"--run-root {current_runner.parent}")
        })()
        with patch.object(dashboard_module.subprocess, "run", return_value=command):
            workers = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertTrue(workers["available"])
        self.assertEqual(workers["counts"]["luna"]["medium"], 0)

    def test_dead_running_marker_does_not_make_coordinator_ambiguous(self) -> None:
        day = self.sessions / "2026/08/24"
        day.mkdir(parents=True)
        for name, session_id in (("rollout-stale.jsonl", "stale-coordinator"),
                                 ("rollout-current.jsonl", "current-coordinator")):
            (day / name).write_text("".join(json.dumps(item) + "\n" for item in (
                {"type": "session_meta", "payload": {
                    "id": session_id, "parent_thread_id": None,
                    "cwd": str(self.workspace), "timestamp": "2026-08-24T08:00:00Z",
                }},
                {"type": "turn_context", "payload": {
                    "model": "gpt-5.6-sol", "effort": "low",
                }},
                {"type": "event_msg", "payload": {"type": "task_started"}},
            )), encoding="utf-8")

        runs = self.workspace / ".de67/state/coordinator-runs"
        stale = runs / "stale"
        current = runs / "current"
        stale.mkdir(parents=True)
        current.mkdir(parents=True)
        for path, session_id, pid in ((stale, "stale-coordinator", "111"),
                                      (current, "current-coordinator", "222")):
            (path / "session_id.txt").write_text(session_id + "\n", encoding="ascii")
            (path / "status.txt").write_text("RUNNING\n", encoding="ascii")
            (path / "pid.txt").write_text(pid + "\n", encoding="ascii")

        command = type("Completed", (), {
            "stdout": (f"123 python coordinator_supervisor.py --workspace {self.workspace} "
                       f"--run-root {runs}")
        })()
        with patch.object(dashboard_module.subprocess, "run", return_value=command), \
                patch.object(dashboard_module, "_recorded_run_pid_is_alive",
                             side_effect=lambda path: path.parent == current):
            workers = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertTrue(workers["available"])

    def test_stale_pid_file_falls_back_to_workspace_process(self) -> None:
        (self.workspace / ".de67/state/coordinator-supervisor.pid").write_text(
            "999999999", encoding="ascii"
        )
        process_output = type("Result", (), {"stdout": (
            f" 42 1 python coordinator_supervisor.py --workspace {self.workspace}\n"
            " 43 42 codex-remote-run --cwd project\n"
        )})()
        with patch.object(dashboard_module.subprocess, "run", return_value=process_output):
            state = dashboard_module.process_state(self.workspace)
        self.assertEqual(state["pid"], 42)
        self.assertEqual(state["supervisor"], "running")
        self.assertEqual(state["coordinator"], "running")

    def test_process_discovery_accepts_equivalent_workspace_symlink(self) -> None:
        alias = self.workspace.parent / f"{self.workspace.name}-alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        (self.workspace / ".de67/state/coordinator-supervisor.pid").write_text(
            "999999999", encoding="ascii"
        )
        process_output = type("Result", (), {"stdout": (
            f" 42 1 python coordinator_supervisor.py --workspace {alias}\n"
            " 43 42 python codex_runner.py\n"
        )})()
        with patch.object(dashboard_module.subprocess, "run", return_value=process_output):
            state = dashboard_module.process_state(self.workspace.resolve())

        self.assertEqual(state["supervisor"], "running")
        self.assertEqual(state["coordinator"], "running")

    def test_process_state_separates_mutation_reviewer_from_coordinator(self) -> None:
        runs = self.workspace / ".de67/state/coordinator-runs"
        reviewer = runs / "mutation-owner-review"
        reviewer.mkdir(parents=True)
        (reviewer / "status.txt").write_text("RUNNING\n", encoding="ascii")
        (reviewer / "pid.txt").write_text("43\n", encoding="ascii")
        (self.workspace / ".de67/state/coordinator-supervisor.pid").write_text(
            "42\n", encoding="ascii"
        )
        process_output = type("Result", (), {"stdout": (
            f" 42 1 python coordinator_supervisor.py --workspace {self.workspace}\n"
            " 43 42 python codex_runner.py\n"
        )})()
        with patch.object(dashboard_module.os, "kill"), \
                patch.object(dashboard_module.subprocess, "run", return_value=process_output):
            state = dashboard_module.process_state(self.workspace)

        self.assertEqual(state["role"], "mutation-reviewer")
        self.assertEqual(state["coordinator"], "running")


if __name__ == "__main__":
    unittest.main()

class IndexedWorkerTests(unittest.TestCase):
    def test_no_workers_does_not_scan_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(dashboard_module, "_active_worker_claims", return_value={}),                  patch.object(Path, "glob", side_effect=AssertionError("history scan")):
                result = dashboard_module.worker_state(root, root / "sessions")
            self.assertTrue(result["available"])
            self.assertTrue(all(value == 0 for row in result["counts"].values()
                                for value in row.values()))

    def test_active_worker_uses_index_without_history_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            connection = sqlite3.connect(root / "state_5.sqlite")
            connection.executescript(
                "CREATE TABLE threads(id TEXT, rollout_path TEXT);"
                "CREATE TABLE thread_spawn_edges(parent_thread_id TEXT, child_thread_id TEXT);"
            )
            connection.execute("INSERT INTO threads VALUES (?, ?)", ("owner", str(root / "owner.jsonl")))
            connection.commit()
            connection.close()
            with patch.object(dashboard_module, "_active_worker_claims", return_value={"worker": "owner"}),                  patch.object(dashboard_module, "_active_coordinator_id", return_value="owner"),                  patch.object(dashboard_module, "_session_header", return_value={"id": "owner", "cwd": str(root)}),                  patch.object(Path, "glob", side_effect=AssertionError("history scan")):
                result = dashboard_module.worker_state(root, root / "sessions")
            self.assertTrue(result["available"])

class OverviewDesignTests(unittest.TestCase):
    def test_digest_preserves_wrapped_heading_and_moves_completed_work_to_record(self):
        result = dashboard_module.render_work_digest(
            "- [ ] R-001 — Repair saving\n  across a restart. More detail.\n  - Evidence: exact receipt\n"
            "- [x] R-002 — Prior work\n  - Long history\n")
        self.assertIn("Repair saving across a restart.", result)
        self.assertNotIn("More detail", result)
        self.assertNotIn("Long history", result)
        self.assertIn("1 completed items", result)
        self.assertIn('href="/ledger"', result)

    def test_structured_briefing_escapes_fields_and_omits_empty_obstacle(self):
        result = dashboard_module.render_fratbro_status({"summary": {
            "headline": "Save <confirmation>", "changed": "A rejected action is visible.",
            "next": "Test the native exit.", "snag": ""}})
        self.assertIn("Save &lt;confirmation&gt;", result)
        self.assertIn("What changed", result)
        self.assertIn("Next", result)
        self.assertNotIn("Obstacle", result)

class WorkerScaleTests(unittest.TestCase):
    def test_dots_do_not_overlap_at_each_supported_count(self):
        import math
        for count in range(13):
            points = dashboard_module.worker_dot_positions(count)
            self.assertEqual(len(points), count)
            for i, left in enumerate(points):
                for right in points[i+1:]:
                    self.assertGreater(math.dist(left, right), 10.34)

    def test_overflow_is_explicit_and_total_remains_exact(self):
        result = dashboard_module.render_worker_scale("terra", {"max": 15})
        self.assertEqual(result.count('class="worker-dot"'), 12)
        self.assertIn("+3", result)
        self.assertIn("<b>15</b> active", result)
        self.assertIn("max: 15", result)
