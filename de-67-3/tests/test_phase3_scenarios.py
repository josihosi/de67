from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from deadline_harness import DeadlineError, DeadlineHarness  # noqa: E402
from policy_kernel import decide, load_policy_bytes, workspace_facts  # noqa: E402


class Phase3ScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        self.state = self.workspace / ".de67" / "state" / "deadlines.sqlite3"
        self.policy = load_policy_bytes(
            (ROOT / "assets" / "environment" / "phase3-policy.d67").read_bytes()
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def decision(self, now: float):
        facts = workspace_facts(self.workspace, self.state, "project", now=now)
        return facts, decide(self.policy, facts)

    def test_expired_claim_routes_to_review_without_cadence_restart(self) -> None:
        with DeadlineHarness(self.state) as harness:
            harness.start_task("project", "late", "R-001", 10, now=0)
            expired = harness.expire_task("project", "late", now=11)

            self.assertTrue(expired["incident"]["recorded"])
            facts, routed = self.decision(11)
            self.assertIn("deadline_incident", facts)
            self.assertEqual(routed.action, "review_deadline_incident")
            self.assertIn(
                "cadence_is_observation_not_restart_authority",
                routed.obligations,
            )

            harness.diagnose_claim_deadline(
                "project",
                "R-001",
                "The full route exceeded its clock.",
                "No acceptance was recorded before the immutable deadline.",
                now=12,
            )
            harness.resolve_deadline_mutation(
                "project", "R-001", "micro", "Use the recovered route.", now=13
            )
            resolved = harness.resolve_deadline_mutation(
                "project",
                "R-001",
                "macro",
                "The method remains correct.",
                no_change_required=True,
                now=14,
            )

            self.assertEqual(resolved["pending_components"], [])
            self.assertTrue(resolved["coordinator_restart"]["pending"])
            self.assertIn(
                "successor must set a fresh clock without inheritance",
                resolved["coordinator_restart"]["reason"],
            )

    def test_attempt_that_cannot_fit_waits_for_real_claim_expiry(self) -> None:
        with DeadlineHarness(self.state) as harness:
            harness.start_task("project", "first", "R-002", 100, now=0)
            harness.complete_task("project", "first", "Useful partial work.", now=20)

            with self.assertRaisesRegex(
                DeadlineError,
                "Attempt estimate exceeds the remaining claim deadline",
            ):
                harness.start_task(
                    "project",
                    "cannot-fit",
                    "R-002",
                    100,
                    attempt_estimate_seconds=80,
                    now=30,
                )

            self.assertIsNone(
                harness.connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = 'cannot-fit'"
                ).fetchone()
            )
            facts_before, routed_before = self.decision(30)
            self.assertNotIn("deadline_incident", facts_before)
            self.assertEqual(routed_before.action, "receive_worker_result")

            expired = harness.expire_task("project", "first", now=101)
            self.assertTrue(expired["incident"]["recorded"])
            facts_after, routed_after = self.decision(101)
            self.assertIn("deadline_incident", facts_after)
            self.assertEqual(routed_after.action, "review_deadline_incident")

    def test_worker_twenty_three_runs_stored_mutation_once_then_restarts(self) -> None:
        with patch(
            "deadline_harness.secrets.randbelow", side_effect=[3, 1, 7, 0]
        ), DeadlineHarness(self.state) as harness:
            for number in range(1, 24):
                task_id = f"window-{number:02d}"
                harness.start_task(
                    "project", task_id, f"R-{number:03d}", 100, now=0
                )
                terminal = harness.complete_task(
                    "project", task_id, "Terminal worker result.", now=1
                )

            mutation = terminal["random_mutation"]
            self.assertTrue(mutation["due"])
            self.assertEqual(mutation["completed_terminal_windows"], 23)
            self.assertEqual(mutation["interval_windows"], 23)
            self.assertEqual(
                mutation["selected_lane"], "orchestrator-guidelines.md"
            )
            facts, routed = self.decision(2)
            self.assertIn("random_mutation_due", facts)
            self.assertEqual(routed.action, "review_scheduled_mutation")
            self.assertIn("use_stored_lane", routed.obligations)

            first = harness.resolve_random_mutation(
                "project", mutation["cycle_number"], "Guarded stored-lane review."
            )
            repeated = harness.resolve_random_mutation(
                "project", mutation["cycle_number"], "Guarded stored-lane review."
            )
            self.assertTrue(first["recorded"])
            self.assertFalse(repeated["recorded"])
            self.assertEqual(first["coordinator_restart"]["generation"], 1)
            self.assertEqual(
                repeated["coordinator_restart"]["generation"], 1
            )
            restart_count = harness.connection.execute(
                "SELECT COUNT(*) AS total FROM coordinator_restart_requests"
            ).fetchone()["total"]
            self.assertEqual(restart_count, 1)

            harness.claim_coordinator_restart("project", 1, "mutation-successor")
            harness.acknowledge_coordinator_restart(
                "project", 1, "mutation-successor"
            )
            continued = harness.start_task(
                "project", "window-24", "R-024", 100, now=3
            )
            self.assertTrue(continued["created"])


if __name__ == "__main__":
    unittest.main()
