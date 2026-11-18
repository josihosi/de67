from contextlib import closing
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from test_worker_library import WorkerFixture
import worker_library as library


class HandoffHistoryTests(WorkerFixture, unittest.TestCase):
    def prepare_history(self):
        self.worker(model="gpt-6.2-sol", effort="high")
        self.assign(); self.dispatcher.process_pending()
        old = self.returned(); self.settle()
        with closing(library._connect(self.workspace, write=True)) as db, db:
            row = dict(db.execute("SELECT * FROM requests WHERE id=?", (old["request_id"],)).fetchone())
            row.update(id="old-uncertain", kind="message", status="uncertain", error="steer receipt timeout")
            db.execute("INSERT INTO requests (" + ",".join(row) + ") VALUES (" + ",".join("?" for _ in row) + ")", tuple(row.values()))
        Path(self.binding["socket"]).unlink()
        self.binding = self.bind("sol-a", "run-b", "supervisor-b")
        self.dispatcher = library.WorkerDispatcher(self.workspace, self.rpc, self.binding)
        self.assign(task_id="task-b"); self.dispatcher.process_pending()
        current = self.returned()
        return old, current

    def change(self):
        return library.describe(self.workspace, "pilot", model="gpt-6.1-terra", effort="low", environment=self.env)

    def test_obsolete_uncertainty_preserved_across_same_assignment_resume(self):
        old, current = self.prepare_history()
        before = dict(self.harness.connection.execute("SELECT * FROM tasks WHERE task_id='task-b'").fetchone())
        with closing(library._connect(self.workspace)) as db:
            historical = dict(db.execute("SELECT * FROM requests WHERE id='old-uncertain'").fetchone())
        self.change()
        library.message(self.workspace, "pilot", "Continue with original player and save", environment=self.env)
        self.dispatcher.process_pending()
        now = library.describe(self.workspace, "pilot")["assignment"]
        self.assertEqual(now["id"], current["id"])
        self.assertEqual(now["worker_id"], current["worker_id"])
        self.assertEqual(before, dict(self.harness.connection.execute("SELECT * FROM tasks WHERE task_id='task-b'").fetchone()))
        resumed = [p for m,p in self.rpc.calls if m == "thread/resume"][-1]
        self.assertEqual(resumed["threadId"], current["worker_id"])
        self.assertEqual(resumed["model"], "gpt-6.1-terra")
        self.assertEqual(resumed["config"]["model_reasoning_effort"], "low")
        self.assertEqual([p for m,p in self.rpc.calls if m == "turn/start"][-1]["effort"], "low")
        with closing(library._connect(self.workspace)) as db:
            self.assertEqual(historical, dict(db.execute("SELECT * FROM requests WHERE id='old-uncertain'").fetchone()))

    def test_current_unsettled_requests_refuse(self):
        self.prepare_history()
        for status in ("pending", "submitting", "uncertain"):
            with self.subTest(status=status):
                with closing(library._connect(self.workspace, write=True)) as db, db:
                    db.execute("UPDATE requests SET status=? WHERE id!='old-uncertain' AND assignment_id=(SELECT id FROM assignments ORDER BY created_at DESC LIMIT 1)", (status,))
                with self.assertRaisesRegex(library.WorkerLibraryError, "Settle pending"):
                    self.change()

    def test_old_live_transport_refuses(self):
        old, current = self.prepare_history()
        old_binding = {"run_id": "run-a"}
        with patch.object(library, "_old_server_present", side_effect=lambda b: b["run_id"] == old_binding["run_id"]):
            with self.assertRaisesRegex(library.WorkerLibraryError, "Settle pending"):
                self.change()

    def test_history_must_be_returned_older_and_not_queued(self):
        old, current = self.prepare_history()
        changes = [
            ("UPDATE requests SET status='pending' WHERE id='old-uncertain'", "UPDATE requests SET status='uncertain' WHERE id='old-uncertain'"),
            ("UPDATE requests SET status='submitting' WHERE id='old-uncertain'", "UPDATE requests SET status='uncertain' WHERE id='old-uncertain'"),
            ("UPDATE assignments SET status='running' WHERE id=?", "UPDATE assignments SET status='returned' WHERE id=?"),
            ("UPDATE requests SET created_at=9999999999 WHERE id='old-uncertain'", "UPDATE requests SET created_at=0 WHERE id='old-uncertain'"),
        ]
        for change, restore in changes:
            with self.subTest(change=change):
                with closing(library._connect(self.workspace, write=True)) as db, db:
                    db.execute(change, (old["id"],) if "?" in change else ())
                with self.assertRaisesRegex(library.WorkerLibraryError, "Settle pending"):
                    self.change()
                with closing(library._connect(self.workspace, write=True)) as db, db:
                    db.execute(restore, (old["id"],) if "?" in restore else ())


if __name__ == "__main__":
    unittest.main()
