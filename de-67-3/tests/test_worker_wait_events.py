import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import worker_library as library
from agent_mailbox import enqueue, pending

class WaitEventsTest(unittest.TestCase):
    def test_mail_wakes_live_wait_without_consuming_or_replaying(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            message = enqueue(workspace, "coordinator", "worker", "decision ready")
            with patch.object(library, "describe", return_value={"status": "running"}), patch.object(library.time, "sleep") as sleep:
                result = library.wait(workspace, "pilot", 60)
            self.assertEqual(result["wake_reason"], "coordinator_message")
            self.assertEqual(pending(workspace, "coordinator")[0][1]["id"], message["id"])
            sleep.assert_not_called()

    def test_returned_uncertain_and_deadline_zero_do_not_spin(self):
        with tempfile.TemporaryDirectory() as root:
            for status in ("returned", "uncertain", "running", "pending"):
                with patch.object(library, "describe", return_value={"status": status}), patch.object(library.time, "sleep") as sleep:
                    self.assertEqual(library.wait(Path(root), "pilot", 0)["status"], status)
                    sleep.assert_not_called()

    def test_delivered_mail_does_not_cause_unchanged_wake(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            from agent_mailbox import mailbox, write_json
            message = enqueue(workspace, "coordinator", "worker", "already delivered")
            message["state"] = "delivered"
            write_json(mailbox(workspace, "coordinator") / (message["id"] + ".json"), message)
            with patch.object(library, "describe", side_effect=[{"status": "running"}, {"status": "returned"}]), patch.object(library.time, "sleep") as sleep:
                self.assertEqual(library.wait(workspace, "pilot", 1)["status"], "returned")
                sleep.assert_called_once()
