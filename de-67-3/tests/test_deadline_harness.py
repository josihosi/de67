from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from deadline_harness import DeadlineError, DeadlineHarness, main  # noqa: E402


class DeadlineHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary.name) / "state.sqlite"
        self.harness = DeadlineHarness(self.state_path)

    def tearDown(self) -> None:
        self.harness.close()
        self.temporary.cleanup()

    def test_repeated_start_preserves_identity_clock_and_estimate(self) -> None:
        first = self.harness.start_task("project", "task", "R-1", 10, now=100)
        self.harness.close()
        self.harness = DeadlineHarness(self.state_path)
        repeated = self.harness.start_task("project", "task", "R-1", 10, now=500)

        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["claim_id"], "R-1")
        self.assertEqual(repeated["estimate_seconds"], 10)
        self.assertEqual(repeated["started_at"], 100)
        self.assertEqual(repeated["deadline_at"], 110)
        with self.assertRaises(DeadlineError):
            self.harness.start_task("project", "task", "R-2", 10, now=500)
        with self.assertRaises(DeadlineError):
            self.harness.start_task("project", "task", "R-1", 11, now=500)

    def test_deadline_miss_is_recorded_once(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        first = self.harness.expire_task("project", "task", now=111)
        repeated = self.harness.expire_task("project", "task", now=200)

        self.assertTrue(first["incident"]["recorded"])
        self.assertEqual(first["incident"]["units"], 1)
        self.assertTrue(first["incident"]["independent_review_required"])
        self.assertFalse(repeated["incident"]["recorded"])
        self.assertEqual(repeated["status"]["cumulative_miss_units"], 1)

    def test_late_completion_is_accepted_without_erasing_miss(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        completed = self.harness.complete_task("project", "task", "test output", now=111)
        later = self.harness.status_task("project", "task", now=500)

        self.assertTrue(completed["completion_accepted"])
        self.assertEqual(completed["state"], "accepted")
        self.assertTrue(completed["deadline_missed"])
        self.assertEqual(later["cumulative_miss_units"], 1)
        self.assertTrue(later["deadline_missed"])

    def test_parallel_task_ids_have_independent_clocks(self) -> None:
        self.harness.start_task("project", "short", "R-1", 10, now=100)
        self.harness.start_task("project", "long", "R-2", 30, now=100)

        short = self.harness.status_task("project", "short", now=111)
        long = self.harness.status_task("project", "long", now=111)
        completed = self.harness.complete_task("project", "long", "green test", now=120)

        self.assertTrue(short["deadline_missed"])
        self.assertEqual(long["state"], "running")
        self.assertFalse(long["deadline_missed"])
        self.assertTrue(completed["completion_accepted"])
        self.assertFalse(completed["deadline_missed"])

    def test_cumulative_misses_report_three_and_six_cadence(self) -> None:
        incidents = []
        for number in range(1, 7):
            task_id = f"task-{number}"
            self.harness.start_task("project", task_id, f"R-{number}", 1, now=0)
            incidents.append(
                self.harness.expire_task("project", task_id, now=2)["incident"]
            )

        self.assertFalse(incidents[1]["cadence_crossed"])
        self.assertTrue(incidents[2]["cadence_crossed"])
        self.assertEqual(incidents[2]["cadence_threshold"], 3)
        self.assertFalse(incidents[4]["cadence_crossed"])
        self.assertTrue(incidents[5]["cadence_crossed"])
        self.assertEqual(incidents[5]["cadence_threshold"], 6)
        self.assertEqual(incidents[5]["cumulative_after"], 6)

    def test_state_database_rejects_lineage_reset_but_allows_new_tasks(self) -> None:
        self.harness.start_task("alpha", "task", "R-A", 10, now=100)
        self.harness.start_task("alpha", "retry", "R-A", 20, now=101)
        self.harness.close()
        self.harness = DeadlineHarness(self.state_path)

        with self.assertRaises(DeadlineError):
            self.harness.start_task("beta", "task", "R-B", 30, now=102)

        original = self.harness.status_task("alpha", "task", now=102)
        retry = self.harness.status_task("alpha", "retry", now=102)
        self.assertEqual(original["claim_id"], "R-A")
        self.assertEqual(retry["claim_id"], "R-A")
        self.assertEqual(retry["deadline_at"], 121)

    def test_list_reconciles_multiple_tasks_and_miss_summary(self) -> None:
        self.harness.start_task("project", "late", "R-1", 10, now=100)
        self.harness.start_task("project", "active", "R-2", 30, now=100)

        summary = self.harness.list_tasks(now=111)
        tasks = {task["task_id"]: task for task in summary["tasks"]}

        self.assertEqual(summary["lineage_id"], "project")
        self.assertEqual(summary["cumulative_miss_units"], 1)
        self.assertEqual(len(summary["incidents"]), 1)
        self.assertEqual(summary["incidents"][0]["kind"], "deadline_miss")
        self.assertTrue(summary["incidents"][0]["independent_review_required"])
        self.assertTrue(tasks["late"]["deadline_missed"])
        self.assertEqual(tasks["active"]["state"], "running")

    def test_list_requires_binding_and_cli_needs_no_task_identity(self) -> None:
        unbound_path = Path(self.temporary.name) / "unbound.sqlite"
        with DeadlineHarness(unbound_path) as unbound:
            with self.assertRaises(DeadlineError):
                unbound.list_tasks(now=100)

        cli_path = Path(self.temporary.name) / "list-cli.sqlite"
        with DeadlineHarness(cli_path) as harness:
            harness.start_task("project", "task", "R-1", 100)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["list", "--state", str(cli_path)]), 0)
        payload = json.loads(output.getvalue())

        self.assertEqual(payload["lineage_id"], "project")
        self.assertEqual([task["task_id"] for task in payload["tasks"]], ["task"])

    def test_due_integrity_breach_records_miss_before_three_breach_units(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        result = self.harness.record_integrity_breach(
            "project", "task", "fabricated result", now=111
        )

        miss = result["deadline_incident"]
        breach = result["incident"]
        self.assertTrue(miss["recorded"])
        self.assertEqual(miss["cumulative_before"], 0)
        self.assertEqual(miss["cumulative_after"], 1)
        self.assertEqual(breach["cumulative_before"], 1)
        self.assertEqual(breach["cumulative_after"], 4)
        self.assertEqual(breach["cadence_threshold"], 3)
        self.assertEqual(result["status"]["cumulative_miss_units"], 4)
        self.assertEqual(
            [incident["kind"] for incident in result["status"]["incidents"]],
            ["deadline_miss", "integrity_breach"],
        )

    def test_cli_start_uses_documented_flags_and_spawns_only_once(self) -> None:
        state_path = Path(self.temporary.name) / "cli.sqlite"
        arguments = [
            "start",
            "--state",
            str(state_path),
            "--lineage",
            "project",
            "--task",
            "task",
            "--claim",
            "R-1",
            "--estimate-seconds",
            "100",
        ]

        with patch("deadline_harness.spawn_watcher") as spawn, redirect_stdout(io.StringIO()):
            self.assertEqual(main(arguments), 0)
            self.assertEqual(main(arguments), 0)

        spawn.assert_called_once_with(str(state_path), "project", "task")

    def test_integrity_breach_adds_three_once_and_invalidates_completion(self) -> None:
        self.harness.start_task("project", "first", "R-1", 100, now=0)
        self.harness.complete_task("project", "first", "initial evidence", now=1)

        first = self.harness.record_integrity_breach(
            "project", "first", "fabricated result", now=2
        )
        repeated = self.harness.record_integrity_breach(
            "project", "first", "new wording", now=3
        )

        self.assertTrue(first["incident"]["recorded"])
        self.assertEqual(first["incident"]["units"], 3)
        self.assertTrue(first["incident"]["cadence_crossed"])
        self.assertEqual(first["incident"]["cadence_threshold"], 3)
        self.assertFalse(first["status"]["completion_accepted"])
        self.assertFalse(repeated["incident"]["recorded"])
        self.assertEqual(repeated["status"]["cumulative_miss_units"], 3)
        self.assertEqual(repeated["status"]["integrity_reason"], "fabricated result")

        self.harness.start_task("project", "second", "R-2", 100, now=0)
        second = self.harness.record_integrity_breach(
            "project", "second", "hidden reset", now=4
        )
        self.assertEqual(second["incident"]["cadence_threshold"], 6)
        self.assertEqual(second["incident"]["cumulative_after"], 6)

        with self.assertRaises(DeadlineError):
            self.harness.complete_task(
                "project", "first", "replacement evidence", now=5
            )

    def test_completion_rejects_empty_evidence(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        for evidence in ("", "   "):
            with self.subTest(evidence=repr(evidence)):
                with self.assertRaises(DeadlineError):
                    self.harness.complete_task("project", "task", evidence, now=101)

        self.assertFalse(
            self.harness.status_task("project", "task", now=101)["completion_accepted"]
        )


if __name__ == "__main__":
    unittest.main()
