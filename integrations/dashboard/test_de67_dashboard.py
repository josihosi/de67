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
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.sessions = self.workspace / "sessions"
        self.sessions.mkdir()
        state = self.workspace / ".de67/state"
        state.mkdir(parents=True)
        (self.workspace / ".de67/DFS.md").write_text("# DFS\n\n<script>alert(1)</script>\n", encoding="utf-8")
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

    def test_projection_is_read_only_and_escapes_workspace_html(self) -> None:
        paths = [self.workspace / ".de67/DFS.md", self.workspace / ".de67/work-ledger.md",
                 self.workspace / ".de67/state/deadlines.sqlite3"]
        before = [path.read_bytes() for path in paths]
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("dfs").decode()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertEqual(before, [path.read_bytes() for path in paths])

    def test_overview_uses_real_ledger_and_clock_state(self) -> None:
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("overview").decode()
        self.assertIn("R009-M1", page)
        self.assertIn("gap G-002 r41", page)
        self.assertIn("deadline generation 11", page)
        self.assertIn("restart 12", page)
        self.assertIn("useful work", page)
        self.assertIn("<h2>Waiting work</h2>", page)
        self.assertIn("waiting work", page)
        self.assertIn("<small>Mutations</small><strong>3</strong>", page)
        self.assertIn('<small>Mutation review</small><strong>Off</strong>', page)
        self.assertNotIn("<small>Random mutations</small>", page)
        self.assertIn("Next random in 2 worker results", page)
        self.assertIn("<h2>Active workers</h2>", page)
        self.assertIn("Unavailable", page)
        self.assertIn("Latest finding", page)
        self.assertIn("R009-M0", page)
        self.assertIn("escaped &lt;finding&gt;", page)
        self.assertNotIn("escaped <finding>", page)

    def test_mutation_review_lamp_tracks_incomplete_clock_components(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.executescript("""
            CREATE TABLE claim_deadline_generation_incidents (
              lineage_id TEXT, claim_id TEXT, generation INTEGER, recorded_at REAL
            );
            CREATE TABLE deadline_generation_mutation_components (
              lineage_id TEXT, claim_id TEXT, generation INTEGER, component TEXT
            );
            INSERT INTO claim_deadline_generation_incidents
              VALUES ('lineage','R-009',12,100);
            INSERT INTO deadline_generation_mutation_components
              VALUES ('lineage','R-009',12,'micro');
        """)
        connection.commit()
        connection.close()

        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions)
        running = dashboard.render("overview").decode()
        self.assertIn('<span class="dot yellow"></span><small>Mutation review</small>'
                      '<strong>Running</strong>', running)

        connection = sqlite3.connect(database)
        connection.execute(
            "INSERT INTO deadline_generation_mutation_components VALUES (?,?,?,?)",
            ("lineage", "R-009", 12, "macro"),
        )
        connection.commit()
        connection.close()
        off = dashboard.render("overview").decode()
        self.assertIn('<span class="dot grey"></span><small>Mutation review</small>'
                      '<strong>Off</strong>', off)

    def test_terminal_attempt_is_not_shown_as_running_work(self) -> None:
        database = self.workspace / ".de67/state/deadlines.sqlite3"
        connection = sqlite3.connect(database)
        connection.execute("ALTER TABLE tasks ADD COLUMN attempt_terminal_at REAL")
        connection.execute("UPDATE tasks SET attempt_terminal_at=2")
        connection.commit()
        connection.close()
        page = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).render("overview").decode()
        self.assertNotIn("R009-M1", page)
        self.assertIn('dot yellow', page)

    def test_invalid_utf8_is_visible_without_raw_failure(self) -> None:
        (self.workspace / ".de67/DFS.md").write_bytes(b"# DFS\n\xff")
        state = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions).snapshot()
        self.assertTrue(state["dfs"]["identity"]["invalid_utf8"])
        self.assertIn("�", state["dfs"]["html"])

    def test_missing_sources_return_healthy_unavailable_page(self) -> None:
        empty = Path(self.temporary.name) / "gone"
        page = dashboard_module.Dashboard(empty, sessions_root=self.sessions).render("overview").decode()
        self.assertIn("Active work ledger", page)
        self.assertIn("SQLite", page)
        self.assertIn("unable to open database file", page)

    def test_last_good_panel_survives_source_disappearance(self) -> None:
        dashboard = dashboard_module.Dashboard(self.workspace, sessions_root=self.sessions)
        first = dashboard.snapshot()
        (self.workspace / ".de67/DFS.md").unlink()
        second = dashboard.snapshot()
        self.assertFalse(first["dfs"]["stale"])
        self.assertTrue(second["dfs"]["stale"])
        self.assertIn("<h1>DFS</h1>", second["dfs"]["html"])

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

        page = dashboard_module.Dashboard(
            self.workspace, sessions_root=self.sessions
        ).render("overview").decode()
        self.assertIn("<h2>Active workers</h2>", page)
        self.assertIn("<tr><th>Luna</th><td class=\"\">0</td><td class=\"active-count\">1</td>", page)
        self.assertIn("<tr><th>Terra</th><td class=\"\">0</td><td class=\"\">0</td><td class=\"\">0</td>", page)
        self.assertNotIn("Unavailable", page)

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

    def test_worker_inherited_from_previous_coordinator_stays_visible(self) -> None:
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
                      "gpt-5.6-luna", "high")
        write_session("rollout-current-root.jsonl", "current-coordinator", None,
                      "gpt-5.6-terra", "low")

        old_runner = self.workspace / ".de67/state/runner-runs/old"
        current_runner = self.workspace / ".de67/state/runner-runs/current"
        old_runner.mkdir(parents=True)
        current_runner.mkdir(parents=True)
        (old_runner / "events.jsonl").write_text(
            json.dumps({"type": "thread.started", "thread_id": "old-coordinator"}) + "\n",
            encoding="utf-8",
        )
        (old_runner / "status.json").write_text(
            json.dumps({"status": "done"}), encoding="utf-8"
        )
        (current_runner / "events.jsonl").write_text(
            json.dumps({"type": "thread.started", "thread_id": "current-coordinator"}) + "\n"
            + json.dumps({
                "type": "item.started",
                "item": {"type": "collab_tool_call", "sender_thread_id": "current-coordinator"},
            }) + "\n",
            encoding="utf-8",
        )
        (current_runner / "status.json").write_text(
            json.dumps({"status": "running"}), encoding="utf-8"
        )

        workers = dashboard_module.worker_state(self.workspace, self.sessions)
        self.assertTrue(workers["available"])
        self.assertEqual(workers["counts"]["luna"]["high"], 1)

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


if __name__ == "__main__":
    unittest.main()
