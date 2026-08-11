from __future__ import annotations

import io
import json
import sqlite3
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
        self.assertNotIn("incidents", summary)
        self.assertEqual(summary["recent_failure_verdicts"], [])
        self.assertEqual(len(summary["pending_incident_reviews"]), 1)
        self.assertEqual(
            summary["pending_incident_reviews"][0]["kind"], "deadline_miss"
        )
        self.assertEqual(
            summary["pending_incident_reviews"][0]["task_id"], "late"
        )
        self.assertEqual(tasks["late"]["state"], "deadline_missed")
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

    def test_list_omits_accepted_tasks_but_keeps_nonaccepted_current_work(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 0]):
            self.harness.start_task("project", "accepted", "R-001", 100, now=0)
        self.harness.complete_task("project", "accepted", "green detail", now=1)

        self.harness.start_task("project", "late-accepted", "R-002", 10, now=0)
        self.harness.complete_task(
            "project", "late-accepted", "late green detail", now=11
        )

        self.harness.start_task("project", "breached", "R-003", 100, now=0)
        self.harness.complete_task("project", "breached", "later invalidated", now=1)
        self.harness.record_integrity_breach(
            "project", "breached", "fabricated long reason", now=2
        )

        self.harness.start_task("project", "finding", "R-004", 100, now=0)
        self.harness.report_worker_finding(
            "project",
            "finding",
            "blocker",
            "long dependency evidence",
            short_verdict="dependency absent",
            now=3,
        )
        self.harness.start_task("project", "running", "R-005", 100, now=0)

        with patch.object(
            self.harness, "_status", wraps=self.harness._status
        ) as status:
            summary = self.harness.list_tasks(now=4)
        listed = {task["task_id"]: task for task in summary["tasks"]}

        self.assertEqual(set(listed), {"breached", "finding", "running"})
        self.assertEqual(
            {call.args[1] for call in status.call_args_list},
            {"breached", "finding", "running"},
        )
        self.assertEqual(listed["breached"]["state"], "integrity_breach")
        self.assertEqual(listed["finding"]["state"], "worker_finding")
        self.assertEqual(listed["running"]["state"], "running")
        for task in listed.values():
            self.assertNotIn("completion_evidence", task)
            self.assertNotIn("incidents", task)
            self.assertNotIn("worker_finding", task)
            self.assertNotIn("integrity_reason", task)

        pending = summary["pending_incident_reviews"]
        self.assertEqual(
            {review["task_id"] for review in pending},
            {"late-accepted", "breached"},
        )
        self.assertEqual(
            [verdict["task_id"] for verdict in summary["recent_failure_verdicts"]],
            ["finding"],
        )
        verdicts = pending + summary["recent_failure_verdicts"]
        for verdict in verdicts:
            self.assertNotIn("evidence", verdict)
            self.assertNotIn("reason", verdict)
            self.assertNotIn("long_detail", verdict)

    def test_list_keeps_only_ten_recent_short_failure_verdicts(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 0]):
            for number in range(1, 13):
                task_id = f"W-{number:03d}"
                if number % 2:
                    self.harness.start_task(
                        "project", task_id, f"R-{number:03d}", 1, now=0
                    )
                    self.harness.expire_task("project", task_id, now=number)
                    self.harness.diagnose_incident(
                        "project",
                        task_id,
                        "deadline_miss",
                        f"short {number}",
                        f"long incident diagnosis {number}",
                        now=100 + number,
                    )
                else:
                    self.harness.start_task(
                        "project", task_id, f"R-{number:03d}", 100, now=0
                    )
                    self.harness.report_worker_finding(
                        "project",
                        task_id,
                        "unexpected",
                        f"long worker evidence {number}",
                        short_verdict=f"short {number}",
                        now=number,
                    )

        summary = self.harness.list_tasks(now=20)
        verdicts = summary["recent_failure_verdicts"]

        self.assertEqual(summary["pending_incident_reviews"], [])
        self.assertEqual(len(verdicts), 10)
        self.assertEqual(
            [verdict["task_id"] for verdict in verdicts],
            [f"W-{number:03d}" for number in range(12, 2, -1)],
        )
        self.assertEqual(
            [verdict["short_verdict"] for verdict in verdicts],
            [f"short {number}" for number in range(12, 2, -1)],
        )
        for verdict in verdicts:
            self.assertNotIn("evidence", verdict)
            self.assertNotIn("reason", verdict)
            self.assertNotIn("long_detail", verdict)

        incident_status = self.harness.status_task("project", "W-011", now=20)
        self.assertEqual(
            incident_status["incidents"][0]["long_detail"],
            "long incident diagnosis 11",
        )
        finding_status = self.harness.status_task("project", "W-012", now=20)
        self.assertEqual(
            finding_status["worker_finding"]["evidence"],
            "long worker evidence 12",
        )

    def test_list_omits_completed_task_with_prior_finding_but_keeps_verdict(self) -> None:
        self.harness.start_task("project", "task", "R-001", 100, now=0)
        self.harness.report_worker_finding(
            "project",
            "task",
            "unexpected",
            "Long finding evidence retained for exact diagnostics.",
            short_verdict="owner contradicted",
            now=1,
        )
        self.harness.connection.execute(
            """
            UPDATE tasks
            SET completed_at = 2, completion_evidence = 'accepted after finding review'
            WHERE lineage_id = 'project' AND task_id = 'task'
            """
        )
        self.harness.connection.commit()

        summary = self.harness.list_tasks(now=3)

        self.assertEqual(summary["tasks"], [])
        self.assertEqual(summary["pending_incident_reviews"], [])
        self.assertEqual(
            summary["recent_failure_verdicts"],
            [
                {
                    "task_id": "task",
                    "claim_id": "R-001",
                    "kind": "unexpected",
                    "recorded_at": 1,
                    "short_verdict": "owner contradicted",
                }
            ],
        )

    def test_list_keeps_only_current_route_for_an_unresolved_claim(self) -> None:
        for number in (1, 2):
            task_id = f"attempt-{number}"
            self.harness.start_task(
                "project", task_id, "R-001", 100, now=number
            )
            self.harness.report_worker_finding(
                "project",
                task_id,
                "unexpected",
                f"Long evidence for attempt {number}.",
                short_verdict=f"route {number} failed",
                now=number + 0.25,
            )

        summary = self.harness.list_tasks(now=3)
        self.assertEqual(
            [task["task_id"] for task in summary["tasks"]], ["attempt-2"]
        )
        self.assertEqual(
            [item["task_id"] for item in summary["recent_failure_verdicts"]],
            ["attempt-2", "attempt-1"],
        )

        self.harness.start_task("project", "attempt-3", "R-001", 100, now=4)
        summary = self.harness.list_tasks(now=5)
        self.assertEqual(
            [task["task_id"] for task in summary["tasks"]], ["attempt-3"]
        )

        self.harness.complete_task(
            "project", "attempt-3", "The DFS claim is now proven.", now=6
        )
        self.assertEqual(self.harness.list_tasks(now=7)["tasks"], [])

    def test_list_supersedes_prior_deadline_miss_for_the_same_claim(self) -> None:
        for number in (1, 2):
            task_id = f"miss-{number}"
            self.harness.start_task("project", task_id, "R-001", 1, now=number)
            self.harness.expire_task("project", task_id, now=number + 1)
            self.harness.diagnose_incident(
                "project",
                task_id,
                "deadline_miss",
                f"route {number} late",
                f"Long diagnosis for route {number}.",
                now=number + 1.25,
            )

        summary = self.harness.list_tasks(now=4)
        self.assertEqual(
            [task["task_id"] for task in summary["tasks"]], ["miss-2"]
        )
        self.assertEqual(summary["pending_incident_reviews"], [])
        self.assertEqual(
            [item["task_id"] for item in summary["recent_failure_verdicts"]],
            ["miss-2", "miss-1"],
        )

    def test_seven_due_breaches_cannot_crowd_out_pending_incident_reviews(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 0]):
            for number in range(1, 8):
                task_id = f"W-{number:03d}"
                self.harness.start_task(
                    "project", task_id, f"R-{number:03d}", 1, now=0
                )
                self.harness.record_integrity_breach(
                    "project", task_id, f"long breach reason {number}", now=2
                )

        summary = self.harness.list_tasks(now=3)
        pending = summary["pending_incident_reviews"]

        self.assertEqual(len(pending), 14)
        self.assertEqual(
            {
                (review["task_id"], review["kind"])
                for review in pending
            },
            {
                (f"W-{number:03d}", kind)
                for number in range(1, 8)
                for kind in ("deadline_miss", "integrity_breach")
            },
        )
        self.assertEqual(summary["recent_failure_verdicts"], [])

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

    def test_incident_diagnosis_is_persisted_immutable_and_cli_visible(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)
        self.harness.expire_task("project", "task", now=111)
        self.assertTrue(
            self.harness.status_task("project", "task", now=111)["incidents"][0][
                "independent_review_required"
            ]
        )

        first = self.harness.diagnose_incident(
            "project",
            "task",
            "deadline_miss",
            "test overdefined",
            "The intended proof required behavior outside the DFS claim.",
            now=112,
        )
        repeated = self.harness.diagnose_incident(
            "project",
            "task",
            "deadline_miss",
            "test overdefined",
            "The intended proof required behavior outside the DFS claim.",
            now=113,
        )

        self.assertTrue(first["recorded"])
        self.assertFalse(repeated["recorded"])
        self.assertEqual(first["incident"]["short_verdict"], "test overdefined")
        self.assertEqual(first["incident"]["reviewed_at"], 112)
        self.assertFalse(first["incident"]["independent_review_required"])
        with self.assertRaisesRegex(DeadlineError, "immutable"):
            self.harness.diagnose_incident(
                "project",
                "task",
                "deadline_miss",
                "different verdict",
                "Different diagnosis",
                now=114,
            )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main(
                    [
                        "status",
                        "--state",
                        str(self.state_path),
                        "--lineage",
                        "project",
                        "--task",
                        "task",
                    ]
                ),
                0,
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["incidents"][0]["short_verdict"], "test overdefined")
        self.assertEqual(
            payload["incidents"][0]["long_detail"],
            "The intended proof required behavior outside the DFS claim.",
        )

    def test_documented_diagnose_cli_records_exact_incident_review(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)
        self.harness.expire_task("project", "task", now=111)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main(
                    [
                        "diagnose",
                        "--state",
                        str(self.state_path),
                        "--lineage",
                        "project",
                        "--task",
                        "task",
                        "--kind",
                        "deadline_miss",
                        "--short-verdict",
                        "estimate unsound",
                        "--diagnosis",
                        "Measured setup time contradicted the estimate premise.",
                    ]
                ),
                0,
            )
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["recorded"])
        self.assertEqual(payload["incident"]["short_verdict"], "estimate unsound")
        self.assertEqual(
            payload["incident"]["long_detail"],
            "Measured setup time contradicted the estimate premise.",
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

    def test_on_time_worker_finding_stops_timer_without_accepting_task(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        reported = self.harness.report_worker_finding(
            "project", "task", "blocker", "missing production dependency", now=109
        )
        later = self.harness.status_task("project", "task", now=500)

        self.assertTrue(reported["finding"]["recorded"])
        self.assertIsNone(reported["deadline_incident"])
        self.assertEqual(reported["status"]["state"], "worker_finding")
        self.assertFalse(reported["status"]["completion_accepted"])
        self.assertFalse(reported["status"]["deadline_missed"])
        self.assertEqual(later["state"], "worker_finding")
        self.assertEqual(later["cumulative_miss_units"], 0)
        self.assertEqual(later["worker_finding"]["kind"], "blocker")
        self.assertEqual(
            later["worker_finding"]["evidence"], "missing production dependency"
        )
        with self.assertRaises(DeadlineError):
            self.harness.complete_task("project", "task", "green test", now=501)

    def test_late_worker_finding_preserves_exactly_one_deadline_miss(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        reported = self.harness.report_worker_finding(
            "project", "task", "unexpected", "runtime contradicts DFS", now=110
        )
        repeated_expiry = self.harness.expire_task("project", "task", now=500)

        self.assertTrue(reported["deadline_incident"]["recorded"])
        self.assertEqual(reported["deadline_incident"]["units"], 1)
        self.assertEqual(reported["status"]["state"], "worker_finding")
        self.assertTrue(reported["status"]["deadline_missed"])
        self.assertFalse(repeated_expiry["incident"]["recorded"])
        self.assertEqual(repeated_expiry["status"]["cumulative_miss_units"], 1)

    def test_late_worker_finding_verdict_precedes_same_time_deadline_miss(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        self.harness.report_worker_finding(
            "project",
            "task",
            "unexpected",
            "The production owner returned a contradictory long result.",
            short_verdict="owner contradicted",
            now=110,
        )
        summary = self.harness.list_tasks(now=110)

        self.assertEqual(summary["tasks"][0]["state"], "worker_finding")
        self.assertEqual(
            summary["tasks"][0]["current_short_verdict"], "owner contradicted"
        )
        self.assertEqual(
            summary["recent_failure_verdicts"][0]["short_verdict"],
            "owner contradicted",
        )
        self.assertEqual(
            summary["pending_incident_reviews"],
            [
                {
                    "task_id": "task",
                    "claim_id": "R-1",
                    "kind": "deadline_miss",
                    "recorded_at": 110,
                }
            ],
        )

    def test_worker_finding_is_validated_immutable_and_terminal(self) -> None:
        self.harness.start_task("project", "task", "R-1", 10, now=100)

        for kind, evidence in (("unknown", "evidence"), ("blocker", "   ")):
            with self.subTest(kind=kind, evidence=repr(evidence)):
                with self.assertRaises(DeadlineError):
                    self.harness.report_worker_finding(
                        "project", "task", kind, evidence, now=101
                    )

        first = self.harness.report_worker_finding(
            "project",
            "task",
            "unexpected",
            "observed result",
            short_verdict="production owner contradicted",
            now=102,
        )
        repeated = self.harness.report_worker_finding(
            "project", "task", "unexpected", "observed result", now=500
        )

        self.assertTrue(first["finding"]["recorded"])
        self.assertEqual(
            first["finding"]["short_verdict"], "production owner contradicted"
        )
        self.assertFalse(repeated["finding"]["recorded"])
        self.assertEqual(
            repeated["finding"]["short_verdict"], "production owner contradicted"
        )
        self.assertEqual(repeated["finding"]["reported_at"], 102)
        self.assertEqual(repeated["status"]["cumulative_miss_units"], 0)
        for kind, evidence in (
            ("blocker", "observed result"),
            ("unexpected", "different evidence"),
        ):
            with self.subTest(kind=kind, evidence=evidence):
                with self.assertRaisesRegex(DeadlineError, "immutable"):
                    self.harness.report_worker_finding(
                        "project", "task", kind, evidence, now=501
                    )
        with self.assertRaisesRegex(DeadlineError, "immutable"):
            self.harness.report_worker_finding(
                "project",
                "task",
                "unexpected",
                "observed result",
                short_verdict="different short verdict",
                now=501,
            )

    def test_completed_or_breached_task_rejects_worker_finding(self) -> None:
        self.harness.start_task("project", "completed", "R-1", 10, now=100)
        self.harness.complete_task("project", "completed", "green test", now=101)
        with self.assertRaises(DeadlineError):
            self.harness.report_worker_finding(
                "project", "completed", "blocker", "too late", now=102
            )

        self.harness.start_task("project", "breached", "R-2", 10, now=100)
        self.harness.record_integrity_breach(
            "project", "breached", "fabricated output", now=101
        )
        with self.assertRaises(DeadlineError):
            self.harness.report_worker_finding(
                "project", "breached", "unexpected", "too late", now=102
            )

    def test_cli_finding_and_list_expose_terminal_finding(self) -> None:
        state_path = Path(self.temporary.name) / "finding-cli.sqlite"
        with DeadlineHarness(state_path) as harness:
            harness.start_task("project", "task", "R-1", 100)
        finding_output = io.StringIO()
        with redirect_stdout(finding_output):
            self.assertEqual(
                main(
                    [
                        "finding",
                        "--state",
                        str(state_path),
                        "--lineage",
                        "project",
                        "--task",
                        "task",
                        "--kind",
                        "blocker",
                        "--short-verdict",
                        "dependency absent",
                        "--evidence",
                        "dependency is absent",
                    ]
                ),
                0,
            )
        finding_payload = json.loads(finding_output.getvalue())

        list_output = io.StringIO()
        with redirect_stdout(list_output):
            self.assertEqual(main(["list", "--state", str(state_path)]), 0)
        listed = json.loads(list_output.getvalue())
        listed_task = listed["tasks"][0]

        self.assertEqual(finding_payload["finding"]["kind"], "blocker")
        self.assertEqual(listed_task["state"], "worker_finding")
        self.assertNotIn("worker_finding", listed_task)
        self.assertEqual(listed_task["current_short_verdict"], "dependency absent")
        self.assertEqual(
            listed["recent_failure_verdicts"][0]["short_verdict"],
            "dependency absent",
        )
        self.assertNotIn("evidence", listed["recent_failure_verdicts"][0])

    def test_restart_request_persists_and_blocks_only_new_task_ids(self) -> None:
        initial = self.harness.start_task(
            "project", "existing", "R-001", 100, now=0
        )
        self.assertIsNone(initial["coordinator_restart"])

        first = self.harness.request_coordinator_restart(
            "project", "guarded guideline mutation", now=1
        )
        repeated = self.harness.request_coordinator_restart(
            "project", "later request coalesces into the pending baton", now=2
        )

        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(first["coordinator_restart"]["generation"], 1)
        self.assertTrue(repeated["coordinator_restart"]["pending"])
        self.assertEqual(
            repeated["coordinator_restart"]["reason"],
            "guarded guideline mutation",
        )
        resumed = self.harness.start_task(
            "project", "existing", "R-001", 100, now=3
        )
        self.assertFalse(resumed["created"])
        self.assertTrue(resumed["coordinator_restart"]["pending"])
        with self.assertRaisesRegex(DeadlineError, "restart generation 1 is pending"):
            self.harness.start_task("project", "new", "R-002", 100, now=3)

        self.harness.close()
        self.harness = DeadlineHarness(self.state_path)
        persisted = self.harness.list_tasks(now=3)["coordinator_restart"]
        self.assertEqual(persisted["generation"], 1)
        self.assertTrue(persisted["pending"])

        with self.assertRaisesRegex(DeadlineError, "claimed by its supervisor"):
            self.harness.acknowledge_coordinator_restart(
                "project", 1, "retiring-coordinator", now=4
            )
        claimed = self.harness.claim_coordinator_restart(
            "project", 1, "run-fresh-1", now=4
        )
        repeated_claim = self.harness.claim_coordinator_restart(
            "project", 1, "run-fresh-1", now=5
        )
        self.assertTrue(claimed["recorded"])
        self.assertFalse(repeated_claim["recorded"])
        with self.assertRaisesRegex(DeadlineError, "different run"):
            self.harness.claim_coordinator_restart(
                "project", 1, "wrong-run", now=5
            )
        with self.assertRaisesRegex(DeadlineError, "does not match"):
            self.harness.release_coordinator_restart_claim(
                "project", 1, "wrong-run"
            )

        acknowledged = self.harness.acknowledge_coordinator_restart(
            "project", 1, "run-fresh-1", now=4
        )
        repeated_ack = self.harness.acknowledge_coordinator_restart(
            "project", 1, "run-fresh-1", now=5
        )
        self.assertTrue(acknowledged["recorded"])
        self.assertFalse(repeated_ack["recorded"])
        self.assertEqual(
            repeated_ack["coordinator_restart"]["acknowledged_at"], 4
        )
        with self.assertRaisesRegex(DeadlineError, "claimed run"):
            self.harness.acknowledge_coordinator_restart(
                "project", 1, "different-run", now=6
            )
        with self.assertRaisesRegex(DeadlineError, "cannot be released"):
            self.harness.release_coordinator_restart_claim(
                "project", 1, "run-fresh-1"
            )

        started = self.harness.start_task("project", "new", "R-002", 100, now=6)
        self.assertTrue(started["created"])
        self.assertFalse(started["coordinator_restart"]["pending"])

        next_request = self.harness.request_coordinator_restart(
            "project", "next guarded mutation", now=7
        )
        self.assertTrue(next_request["created"])
        self.assertEqual(next_request["coordinator_restart"]["generation"], 2)
        generations = self.harness.connection.execute(
            """
            SELECT generation FROM coordinator_restart_requests
            ORDER BY generation
            """
        ).fetchall()
        self.assertEqual([row["generation"] for row in generations], [1, 2])

    def test_restart_request_and_acknowledgement_cli(self) -> None:
        state_path = Path(self.temporary.name) / "restart-cli.sqlite"
        with DeadlineHarness(state_path) as harness:
            harness.start_task("project", "existing", "R-001", 100, now=0)

        request_output = io.StringIO()
        with redirect_stdout(request_output):
            self.assertEqual(
                main(
                    [
                        "request-restart",
                        "--state",
                        str(state_path),
                        "--lineage",
                        "project",
                        "--reason",
                        "guarded DFS expansion",
                    ]
                ),
                0,
            )
        requested = json.loads(request_output.getvalue())
        self.assertTrue(requested["created"])
        self.assertTrue(requested["coordinator_restart"]["pending"])

        with DeadlineHarness(state_path) as harness:
            harness.claim_coordinator_restart("project", 1, "dead-run-cli")
        release_output = io.StringIO()
        with redirect_stdout(release_output):
            self.assertEqual(
                main(
                    [
                        "release-restart-claim",
                        "--state",
                        str(state_path),
                        "--lineage",
                        "project",
                        "--generation",
                        "1",
                        "--run-id",
                        "dead-run-cli",
                    ]
                ),
                0,
            )
        self.assertTrue(json.loads(release_output.getvalue())["released"])
        with DeadlineHarness(state_path) as harness:
            harness.claim_coordinator_restart("project", 1, "run-cli-1")

        ack_output = io.StringIO()
        with redirect_stdout(ack_output):
            self.assertEqual(
                main(
                    [
                        "ack-restart",
                        "--state",
                        str(state_path),
                        "--lineage",
                        "project",
                        "--generation",
                        "1",
                        "--run-id",
                        "run-cli-1",
                    ]
                ),
                0,
            )
        acknowledged = json.loads(ack_output.getvalue())
        self.assertTrue(acknowledged["recorded"])
        self.assertFalse(acknowledged["coordinator_restart"]["pending"])
        self.assertEqual(acknowledged["coordinator_restart"]["run_id"], "run-cli-1")

    @staticmethod
    def complete_windows(
        harness: DeadlineHarness,
        count: int,
        *,
        first: int = 1,
    ) -> None:
        for number in range(first, first + count):
            task = f"window-{number}"
            harness.start_task("project", task, f"R-{number:03d}", 10, now=0)
            harness.complete_task("project", task, "green", now=1)

    def test_random_interval_includes_ten_and_thirty_boundaries(self) -> None:
        self.harness.close()
        for offset, boundary in ((0, 10), (20, 30)):
            with self.subTest(boundary=boundary):
                state = Path(self.temporary.name) / f"boundary-{boundary}.sqlite"
                with patch(
                    "deadline_harness.secrets.randbelow", side_effect=[offset, 0]
                ), DeadlineHarness(state) as harness:
                    self.complete_windows(harness, boundary - 1)
                    before = harness.list_tasks(now=2)["random_mutation"]
                    self.assertFalse(before["due"])
                    task = f"window-{boundary}"
                    harness.start_task(
                        "project", task, f"R-{boundary:03d}", 10, now=0
                    )
                    running = harness.status_task("project", task, now=1)
                    self.assertFalse(running["random_mutation"]["due"])
                    terminal = harness.complete_task(
                        "project", task, "green", now=2
                    )
                    self.assertTrue(terminal["random_mutation"]["due"])
                    self.assertEqual(
                        terminal["random_mutation"]["interval_windows"], boundary
                    )
        self.harness = DeadlineHarness(self.state_path)

    def test_random_schedule_persists_across_restart_without_redraw(self) -> None:
        with patch(
            "deadline_harness.secrets.randbelow", side_effect=[4, 1]
        ) as draw:
            self.complete_windows(self.harness, 7)
            self.assertEqual(draw.call_count, 2)
        self.harness.close()
        with patch(
            "deadline_harness.secrets.randbelow",
            side_effect=AssertionError("persisted schedule must not redraw"),
        ):
            self.harness = DeadlineHarness(self.state_path)
            self.complete_windows(self.harness, 7, first=8)
            schedule = self.harness.list_tasks(now=2)["random_mutation"]

        self.assertEqual(schedule["interval_windows"], 14)
        self.assertEqual(schedule["selected_lane"], "orchestrator-guidelines.md")
        self.assertEqual(schedule["completed_terminal_windows"], 14)
        self.assertTrue(schedule["due"])

    def test_random_lane_draw_is_persisted_and_not_cli_controlled(self) -> None:
        self.harness.close()
        for lane_index, lane in enumerate(
            (
                "test-and-task-guidelines.md",
                "orchestrator-guidelines.md",
                "DFS.md",
            )
        ):
            with self.subTest(lane=lane):
                state = Path(self.temporary.name) / f"lane-{lane_index}.sqlite"
                with patch(
                    "deadline_harness.secrets.randbelow",
                    side_effect=[0, lane_index],
                ), DeadlineHarness(state) as harness:
                    started = harness.start_task(
                        "project", "task", "R-001", 10, now=0
                    )
                    self.assertEqual(
                        started["random_mutation"]["selected_lane"], lane
                    )
                    self.assertEqual(
                        started["random_mutation"]["due_after_terminal_windows"],
                        10,
                    )
        self.harness = DeadlineHarness(self.state_path)

    def test_each_terminal_route_counts_once_and_late_followups_do_not(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 0]):
            self.complete_windows(self.harness, 6)

            self.harness.start_task("project", "finding", "R-007", 10, now=0)
            self.harness.report_worker_finding(
                "project", "finding", "blocker", "direct evidence", now=1
            )

            self.harness.start_task("project", "miss", "R-008", 10, now=0)
            self.harness.expire_task("project", "miss", now=11)
            self.harness.complete_task("project", "miss", "late green", now=12)

            self.harness.start_task("project", "breach", "R-009", 10, now=0)
            self.harness.record_integrity_breach(
                "project", "breach", "fabricated evidence", now=1
            )

            self.harness.start_task("project", "completion", "R-010", 10, now=0)
            result = self.harness.complete_task(
                "project", "completion", "green", now=1
            )
            repeated = self.harness.complete_task(
                "project", "completion", "different text", now=2
            )

        self.assertEqual(result["random_mutation"]["completed_terminal_windows"], 10)
        self.assertTrue(result["random_mutation"]["due"])
        self.assertEqual(repeated["random_mutation"]["completed_terminal_windows"], 10)
        self.assertEqual(
            self.harness.list_tasks(now=20)["random_mutation"]["completed_terminal_windows"],
            10,
        )

    def test_due_review_blocks_new_dispatch_until_exactly_once_resolution(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 2]):
            self.complete_windows(self.harness, 10)
        schedule = self.harness.list_tasks(now=2)["random_mutation"]
        self.assertTrue(schedule["due"])
        self.harness.close()
        self.harness = DeadlineHarness(self.state_path)
        with self.assertRaisesRegex(DeadlineError, "resolve it before dispatching"):
            self.harness.start_task("project", "blocked", "R-011", 10, now=2)

        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 1]) as draw:
            first = self.harness.resolve_random_mutation(
                "project",
                schedule["cycle_number"],
                "guard accepted exact DFS no-op; ledger review retained",
            )
            repeated = self.harness.resolve_random_mutation(
                "project",
                schedule["cycle_number"],
                "guard accepted exact DFS no-op; ledger review retained",
            )
        self.assertTrue(first["recorded"])
        self.assertFalse(repeated["recorded"])
        self.assertTrue(first["coordinator_restart"]["pending"])
        self.assertEqual(first["coordinator_restart"]["generation"], 1)
        self.assertEqual(
            repeated["coordinator_restart"]["generation"],
            first["coordinator_restart"]["generation"],
        )
        restart_count = self.harness.connection.execute(
            "SELECT COUNT(*) AS total FROM coordinator_restart_requests"
        ).fetchone()["total"]
        self.assertEqual(restart_count, 1)
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(first["random_mutation"]["interval_windows"], 30)
        self.assertFalse(first["random_mutation"]["due"])
        with self.assertRaisesRegex(DeadlineError, "restart generation 1 is pending"):
            self.harness.start_task("project", "unblocked", "R-011", 10, now=5)
        self.harness.claim_coordinator_restart(
            "project", 1, "run-after-random-noop"
        )
        self.harness.acknowledge_coordinator_restart(
            "project", 1, "run-after-random-noop"
        )
        started = self.harness.start_task(
            "project", "unblocked", "R-011", 10, now=5
        )
        self.assertTrue(started["created"])

    def test_documented_random_resolution_cli_flags_execute(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 1]):
            self.complete_windows(self.harness, 10)
        cycle = self.harness.list_tasks(now=2)["random_mutation"]["cycle_number"]
        output = io.StringIO()
        with patch(
            "deadline_harness.secrets.randbelow", side_effect=[0, 0]
        ), redirect_stdout(output):
            self.assertEqual(
                main(
                    [
                        "resolve-random-mutation",
                        "--state",
                        str(self.state_path),
                        "--lineage",
                        "project",
                        "--cycle",
                        str(cycle),
                        "--evidence",
                        "guard passed and target was applied",
                    ]
                ),
                0,
            )
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["recorded"])
        self.assertEqual(payload["cycle_number"], cycle)

    def test_running_status_and_list_never_trigger_random_review(self) -> None:
        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 1]):
            self.complete_windows(self.harness, 9)
            running = self.harness.start_task(
                "project", "tenth", "R-010", 100, now=0
            )
            status = self.harness.status_task("project", "tenth", now=50)
            listed = self.harness.list_tasks(now=50)

        self.assertFalse(running["random_mutation"]["due"])
        self.assertFalse(status["random_mutation"]["due"])
        self.assertFalse(listed["random_mutation"]["due"])
        self.assertEqual(listed["random_mutation"]["completed_terminal_windows"], 9)

    @staticmethod
    def strip_random_cadence(state: Path) -> None:
        connection = sqlite3.connect(state)
        try:
            connection.execute("DROP TABLE random_mutation_cycles")
            connection.execute("DROP TABLE coordinator_restart_requests")
            connection.execute("ALTER TABLE tasks DROP COLUMN terminal_at")
            connection.commit()
        finally:
            connection.close()

    def test_legacy_database_backfills_compact_and_long_failure_forms(self) -> None:
        self.harness.close()
        legacy = Path(self.temporary.name) / "legacy-compact-history.sqlite"
        connection = sqlite3.connect(legacy)
        try:
            connection.executescript(
                """
                CREATE TABLE tasks (
                    lineage_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL,
                    estimate_seconds REAL NOT NULL,
                    started_at REAL NOT NULL,
                    deadline_at REAL NOT NULL,
                    completed_at REAL,
                    completion_evidence TEXT,
                    integrity_breached_at REAL,
                    integrity_reason TEXT,
                    PRIMARY KEY (lineage_id, task_id)
                );
                CREATE TABLE incidents (
                    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lineage_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    reason TEXT,
                    units INTEGER NOT NULL,
                    cumulative_before INTEGER NOT NULL,
                    cumulative_after INTEGER NOT NULL,
                    cadence_threshold INTEGER,
                    UNIQUE (lineage_id, task_id, kind)
                );
                CREATE TABLE worker_findings (
                    lineage_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    reported_at REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    PRIMARY KEY (lineage_id, task_id)
                );
                CREATE TABLE lineage_binding (
                    singleton INTEGER PRIMARY KEY,
                    lineage_id TEXT NOT NULL
                );
                """
            )
            connection.executemany(
                """
                INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ("project", "legacy-miss", "R-001", 10, 0, 10, None, None, None, None),
                    (
                        "project",
                        "legacy-finding",
                        "R-002",
                        10,
                        0,
                        10,
                        None,
                        None,
                        None,
                        None,
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO incidents (
                    lineage_id, task_id, kind, recorded_at, reason, units,
                    cumulative_before, cumulative_after, cadence_threshold
                ) VALUES ('project', 'legacy-miss', 'deadline_miss', 11, NULL, 1, 0, 1, NULL)
                """
            )
            connection.execute(
                """
                INSERT INTO worker_findings
                VALUES ('project', 'legacy-finding', 'blocker', 5, 'legacy long evidence')
                """
            )
            connection.execute(
                "INSERT INTO lineage_binding VALUES (1, 'project')"
            )
            connection.commit()
        finally:
            connection.close()

        with patch(
            "deadline_harness.secrets.randbelow", side_effect=[20, 0]
        ), DeadlineHarness(legacy) as migrated:
            summary = migrated.list_tasks(now=6)
            self.assertEqual(
                [item["short_verdict"] for item in summary["recent_failure_verdicts"]],
                ["blocker"],
            )
            self.assertEqual(
                summary["pending_incident_reviews"],
                [
                    {
                        "task_id": "legacy-miss",
                        "claim_id": "R-001",
                        "kind": "deadline_miss",
                        "recorded_at": 11,
                    }
                ],
            )
            miss = migrated.status_task("project", "legacy-miss", now=6)
            self.assertEqual(
                miss["incidents"][0]["long_detail"],
                "The immutable deadline passed without an on-time terminal result.",
            )
            finding = migrated.status_task("project", "legacy-finding", now=6)
            self.assertEqual(
                finding["worker_finding"]["evidence"], "legacy long evidence"
            )
            diagnosed = migrated.diagnose_incident(
                "project",
                "legacy-miss",
                "deadline_miss",
                "tooling unchecked",
                "The required tool had not been probed before dispatch.",
                now=12,
            )
            self.assertTrue(diagnosed["recorded"])
            incident_columns = {
                row["name"]
                for row in migrated.connection.execute(
                    "PRAGMA table_info(incidents)"
                ).fetchall()
            }
            finding_columns = {
                row["name"]
                for row in migrated.connection.execute(
                    "PRAGMA table_info(worker_findings)"
                ).fetchall()
            }
            self.assertTrue(
                {"short_verdict", "long_detail", "reviewed_at"}
                <= incident_columns
            )
            self.assertIn("short_verdict", finding_columns)
        self.harness = DeadlineHarness(self.state_path)

    def test_legacy_terminal_history_seeds_the_first_random_cycle(self) -> None:
        self.harness.close()
        legacy = Path(self.temporary.name) / "legacy-history.sqlite"
        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 0]), DeadlineHarness(
            legacy
        ) as harness:
            for number in range(1, 12):
                task = f"window-{number}"
                harness.start_task(
                    "project", task, f"R-{number:03d}", 100, now=0
                )
                harness.complete_task("project", task, "green", now=number)
            harness.start_task("project", "window-12", "R-012", 100, now=0)
            harness.report_worker_finding(
                "project", "window-12", "blocker", "legacy finding", now=12
            )
            harness.start_task("project", "window-13", "R-013", 100, now=0)
            harness.expire_task("project", "window-13", now=101)
            harness.start_task("project", "window-14", "R-014", 100, now=0)
            harness.record_integrity_breach(
                "project", "window-14", "legacy breach", now=14
            )
        self.strip_random_cadence(legacy)

        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 1]), DeadlineHarness(
            legacy
        ) as migrated:
            schedule = migrated.list_tasks(now=2)["random_mutation"]
            self.assertEqual(schedule["completed_terminal_windows"], 14)
            self.assertEqual(schedule["due_after_terminal_windows"], 10)
            self.assertEqual(schedule["due_task_id"], "window-10")
            self.assertTrue(schedule["due"])
            with self.assertRaisesRegex(DeadlineError, "resolve it before dispatching"):
                migrated.start_task("project", "blocked", "R-015", 10, now=3)
        self.harness = DeadlineHarness(self.state_path)

    def test_first_post_upgrade_terminal_window_is_not_skipped(self) -> None:
        self.harness.close()
        legacy = Path(self.temporary.name) / "legacy-running.sqlite"
        with patch("deadline_harness.secrets.randbelow", side_effect=[20, 0]), DeadlineHarness(
            legacy
        ) as harness:
            harness.start_task("project", "running", "R-001", 100, now=0)
        self.strip_random_cadence(legacy)

        with patch("deadline_harness.secrets.randbelow", side_effect=[0, 2]), DeadlineHarness(
            legacy
        ) as migrated:
            result = migrated.complete_task(
                "project", "running", "post-upgrade green", now=1
            )
            self.assertEqual(
                result["random_mutation"]["completed_terminal_windows"], 1
            )
            self.assertEqual(result["random_mutation"]["due_after_terminal_windows"], 10)
        self.harness = DeadlineHarness(self.state_path)


if __name__ == "__main__":
    unittest.main()
