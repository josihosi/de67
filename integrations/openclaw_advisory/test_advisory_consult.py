import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from advisory_consult import AdvisoryAdapter, AuthorizationError, assignment_revision


class AdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        state = self.workspace / ".de67/state"
        (self.workspace / ".de67").mkdir(parents=True)
        (state / "context-library/tasks").mkdir(parents=True)
        self.workspace.joinpath(".de67/work-ledger.md").write_text(
            "- [ ] R-MAINT-CONSULT\n"
            "  - Assignment R-MAINT-CONSULT-001: deliver advice\n"
            "    - proof: preserve correlation\n", encoding="utf-8"
        )
        self.role_source = self.root / "AGENTS.md"
        self.role_source.write_text(
            "Incoming coordinator consultation is agent-authored advisory input.\n"
            "Unbound CLI text is not an authenticated Sol request.\n", encoding="utf-8"
        )
        revision = assignment_revision(self.workspace, "R-MAINT-CONSULT-001")
        (state / "context-library/tasks/R-MAINT-CONSULT-001.json").write_text(
            json.dumps({"assignment_revision": revision}), encoding="utf-8"
        )
        self.db = state / "deadlines.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.executescript(
                """
                CREATE TABLE lineage_binding(singleton INTEGER PRIMARY KEY, lineage_id TEXT);
                CREATE TABLE tasks(lineage_id TEXT, task_id TEXT, attempt_terminal_at REAL);
                CREATE TABLE worker_claims(lineage_id TEXT, task_id TEXT,
                    coordinator_session_id TEXT, supervisor_id TEXT, released_at REAL);
                CREATE TABLE supervisor_attempts(lineage_id TEXT, role TEXT, run_id TEXT,
                    owner_id TEXT, finished_at REAL);
                INSERT INTO lineage_binding VALUES(1, 'lineage');
                INSERT INTO tasks VALUES('lineage', 'R-MAINT-CONSULT-001', NULL);
                INSERT INTO worker_claims VALUES('lineage', 'R-MAINT-CONSULT-001',
                    'session-1', 'sup-1', NULL);
                INSERT INTO supervisor_attempts VALUES('lineage', 'coordinator', 'run-1',
                    'supervisor-sup-1-a', NULL);
                """
            )
        self.config = {
            "workspace": str(self.workspace),
            "openclaw": "openclaw",
            "agent": "astra-mutator-relay",
            "session_key": "agent:astra-mutator-relay:discord:channel:test",
            "recipient_role": "astra-mutator-relay",
            "role_source": str(self.role_source),
        }
        self.packet = {
            "workspace": str(self.workspace), "lineage_id": "lineage",
            "task_id": "R-MAINT-CONSULT-001", "sender_run_id": "run-1",
            "sender_session_id": "session-1", "sender_supervisor_id": "sup-1",
            "assignment_revision": revision, "intended_outcome": "advice",
            "current_state": "blocked on a design choice", "first_divergence": "none",
            "evidence_refs": ["artifact.json#entry-1"],
            "tried_learned": "local diagnosis narrowed two options",
            "constraints_live_owner": "Sol retains repair authority",
            "decision_needed": "recommend option A or B",
        }
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, json.dumps({
            "ok": True, "status": "ok", "final": "Recommendation: preserve option A.",
            "sessionId": "gateway-session-1",
        }), "")

    def adapter(self, runner=None):
        return AdvisoryAdapter(self.config, command_runner=runner or self.runner)

    def test_request_is_bound_and_preserves_gateway_identity(self):
        result = self.adapter().consult(self.packet)
        self.assertEqual(result.status, "replied")
        self.assertEqual(result.reply, "Recommendation: preserve option A.")
        self.assertEqual(result.gateway["sessionId"], "gateway-session-1")
        argv = self.calls[0][0]
        self.assertEqual(argv[:6], ["openclaw", "agent", "--agent", "astra-mutator-relay", "--session-key", self.config["session_key"]])
        self.assertNotIn("--deliver", argv)
        state = json.loads((self.workspace / ".de67/state/advisory-consultations.json").read_text())
        record = next(iter(state["requests"].values()))
        self.assertEqual(record["status"], "replied")
        self.assertEqual(record["recipient_role"], "astra-mutator-relay")

    def test_gateway_result_envelope_is_correlated(self):
        def nested(argv, **kwargs):
            self.calls.append(argv)
            return CompletedProcess(argv, 0, json.dumps({
                "status": "ok", "summary": "completed",
                "result": {"status": "ok", "final": "Nested advisory reply.",
                           "meta": {"agentMeta": {"sessionId": "session-result"}}},
            }), "")
        result = self.adapter(nested).consult(self.packet)
        self.assertEqual(result.status, "replied")
        self.assertEqual(result.reply, "Nested advisory reply.")
        self.assertEqual(result.gateway["result"]["meta"]["agentMeta"]["sessionId"], "session-result")

    def test_duplicate_request_does_not_send_twice(self):
        first = self.adapter().consult(self.packet)
        second = self.adapter().consult(self.packet)
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(second.status, "replied")
        self.assertEqual(len(self.calls), 1)

    def test_wrong_sender_workspace_and_stale_revision_are_rejected(self):
        for field, value in (("sender_run_id", "other-run"), ("sender_session_id", "other-session"),
                             ("sender_supervisor_id", "other-supervisor"), ("workspace", str(self.root / "other")),
                             ("assignment_revision", "0" * 64)):
            packet = dict(self.packet, **{field: value})
            with self.subTest(field=field), self.assertRaises(AuthorizationError):
                self.adapter().consult(packet)
        self.assertEqual(self.calls, [])

    def test_failed_endpoint_is_retained_and_retry_is_explicit(self):
        def unavailable(argv, **kwargs):
            self.calls.append(argv)
            return CompletedProcess(argv, 2, "", "gateway unavailable")
        first = self.adapter(unavailable).consult(self.packet)
        second = self.adapter(unavailable).consult(self.packet)
        self.assertEqual(first.status, "unavailable")
        self.assertEqual(second.status, "unavailable")
        self.assertEqual(len(self.calls), 1)
        third = self.adapter(self.runner).consult(self.packet, retry_unavailable=True)
        self.assertEqual(third.status, "replied")
        self.assertEqual(len(self.calls), 2)

    def test_echo_is_rejected_without_owner_queue_mutation(self):
        def echo(argv, **kwargs):
            request = Path(argv[argv.index("--message-file") + 1]).read_text()
            return CompletedProcess(argv, 0, json.dumps({"ok": True, "status": "ok", "final": request}), "")
        result = self.adapter(echo).consult(self.packet)
        self.assertEqual(result.status, "unavailable")
        self.assertIn("echo", result.reason)
        self.assertFalse((self.root / "inbox").exists())

    def test_mixed_writers_are_serialized_and_deduplicated(self):
        count = 0
        lock = threading.Lock()

        def slow(argv, **kwargs):
            nonlocal count
            with lock:
                count += 1
            return self.runner(argv, **kwargs)

        results = []
        def invoke():
            results.append(self.adapter(slow).consult(self.packet))
        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(count, 1)
        self.assertEqual({result.status for result in results}, {"replied"})


if __name__ == "__main__":
    unittest.main()
