from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from coordinator_supervisor import (  # noqa: E402
    COORDINATOR_ROLE_PATH,
    KERNEL_PATH,
    PHASE3_ROOT,
    ROLE_ROOT,
    SupervisionEvent,
    SupervisorError,
    _supervisor_lock,
    build_parser,
    coordinator_prompt,
    read_clock,
    run_supervisor,
    wait_for_supervision_event,
    work_is_complete,
)
from deadline_harness import DeadlineHarness  # noqa: E402


FAKE_RUNNER = r'''from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--cwd", required=True)
arguments = parser.parse_args()
sys.path.insert(0, os.environ["FAKE_DE67_SCRIPTS"])
from deadline_harness import DeadlineHarness

generation_text = os.environ.get("DE67_COORDINATOR_RESTART_GENERATION")
generation = int(generation_text) if generation_text else None
event = {
    "pid": os.getpid(),
    "ppid": os.getppid(),
    "cwd": str(Path.cwd()),
    "workspace_argument": arguments.cwd,
    "generation": generation,
    "run_id": os.environ["DE67_COORDINATOR_RUN_ID"],
    "ack_argv": json.loads(os.environ["DE67_COORDINATOR_ACK_ARGV_JSON"])
    if generation is not None
    else None,
}
with Path(os.environ["FAKE_EVENTS"]).open("a", encoding="utf-8") as output:
    output.write(json.dumps(event) + "\n")

mode = os.environ["FAKE_MODE"]
with DeadlineHarness(os.environ["DE67_DEADLINE_STATE"]) as harness:
    if mode == "two-restarts":
        if generation is None:
            harness.request_coordinator_restart(
                os.environ["DE67_LINEAGE"], "fake first retirement"
            )
        else:
            harness.acknowledge_coordinator_restart(
                os.environ["DE67_LINEAGE"],
                generation,
                os.environ["DE67_COORDINATOR_RUN_ID"],
            )
            if generation == 1:
                harness.request_coordinator_restart(
                    os.environ["DE67_LINEAGE"], "fake second retirement"
                )
    elif mode == "restart-then-exit-nonzero":
        if generation is None:
            harness.request_coordinator_restart(
                os.environ["DE67_LINEAGE"], "valid baton before non-zero exit"
            )
            raise SystemExit(2)
        harness.acknowledge_coordinator_restart(
            os.environ["DE67_LINEAGE"],
            generation,
            os.environ["DE67_COORDINATOR_RUN_ID"],
        )
        root = Path(os.environ["DE67_WORKSPACE"]) / ".de67"
        (root / "DFS.md").write_text(
            "# DFS\n\nStatus: Frozen\n\n- [x] R-001 \N{EM DASH} Done\n",
            encoding="utf-8",
        )
        (root / "work-ledger.md").write_text(
            "# Work ledger\n\n## Active work\n",
            encoding="utf-8",
        )
    elif mode == "ack":
        harness.acknowledge_coordinator_restart(
            os.environ["DE67_LINEAGE"],
            generation,
            os.environ["DE67_COORDINATOR_RUN_ID"],
        )
    elif mode == "ack-from-json":
        completed = subprocess.run(
            json.loads(os.environ["DE67_COORDINATOR_ACK_ARGV_JSON"]),
            capture_output=True,
            text=True,
        )
        Path(os.environ["FAKE_EVENTS"] + ".ack").write_text(
            json.dumps(
                {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            ),
            encoding="utf-8",
        )
        completed.check_returncode()
    elif mode == "unacknowledged":
        pass
    elif mode == "complete-program":
        harness.complete_task(
            os.environ["DE67_LINEAGE"], "seed", "final proof"
        )
        root = Path(os.environ["DE67_WORKSPACE"]) / ".de67"
        (root / "DFS.md").write_text(
            "# DFS\n\nStatus: Frozen\n\n- [x] R-001 \N{EM DASH} Done\n",
            encoding="utf-8",
        )
        (root / "work-ledger.md").write_text(
            "# Work ledger\n\n## Active work\n",
            encoding="utf-8",
        )
    elif mode == "handover-then-complete":
        if generation is not None:
            harness.acknowledge_coordinator_restart(
                os.environ["DE67_LINEAGE"],
                generation,
                os.environ["DE67_COORDINATOR_RUN_ID"],
            )
            harness.complete_task(
                os.environ["DE67_LINEAGE"], "seed", "final proof"
            )
            root = Path(os.environ["DE67_WORKSPACE"]) / ".de67"
            (root / "DFS.md").write_text(
                "# DFS\n\nStatus: Frozen\n\n- [x] R-001 \N{EM DASH} Done\n",
                encoding="utf-8",
            )
            (root / "work-ledger.md").write_text(
                "# Work ledger\n\n## Active work\n",
                encoding="utf-8",
            )
    elif mode == "drain-then-no-refill":
        root = Path(os.environ["DE67_WORKSPACE"]) / ".de67"
        if generation is None:
            harness.complete_task(
                os.environ["DE67_LINEAGE"], "seed", "ledger item retired"
            )
            (root / "work-ledger.md").write_text(
                "# Work ledger\n\n## Active work\n",
                encoding="utf-8",
            )
        else:
            harness.acknowledge_coordinator_restart(
                os.environ["DE67_LINEAGE"],
                generation,
                os.environ["DE67_COORDINATOR_RUN_ID"],
            )
    elif mode == "fail-before-ack":
        raise SystemExit(7)
    else:
        raise AssertionError(f"unknown fake mode: {mode}")
'''


def restart_required(restart: dict[str, object]) -> bool:
    value = restart.get("required", restart.get("pending"))
    if not isinstance(value, bool):
        raise AssertionError("restart state lacks required/pending boolean")
    return value


class CoordinatorSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "deadlines.sqlite3"
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.run_root = self.root / "runs"
        self.events = self.root / "events.jsonl"
        self.fake_runner = self.root / "fake_runner.py"
        self.fake_runner.write_text(FAKE_RUNNER, encoding="utf-8")
        with DeadlineHarness(self.state_path) as harness:
            harness.start_task(
                "project", "seed", "R-000", 3600, now=time.time()
            )
        self.waiter = patch(
            "coordinator_supervisor.wait_for_supervision_event",
            return_value=None,
        )
        self.waiter.start()

    def tearDown(self) -> None:
        self.waiter.stop()
        self.temporary.cleanup()

    def test_clock_event_waits_once_and_requests_a_successor(self) -> None:
        base = time.time()
        with DeadlineHarness(self.state_path) as harness:
            deadline = harness._claim("project", "R-000")["deadline_at"]
        sleeps: list[float] = []

        event = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: base,
            sleep=sleeps.append,
        )

        self.assertIsInstance(event, SupervisionEvent)
        assert event is not None
        self.assertAlmostEqual(sleeps[0], float(deadline) - base, places=3)
        self.assertTrue(event.signature.startswith("gate:"))
        self.assertTrue(event.restart.required)
        self.assertEqual(event.restart.generation, 1)
        with DeadlineHarness(self.state_path) as harness:
            summary = harness.list_tasks(now=float(deadline))
        self.assertEqual(
            summary["pending_incident_reviews"][0]["kind"], "deadline_miss"
        )

    def test_pending_incident_requests_a_successor_without_sleeping(self) -> None:
        with DeadlineHarness(self.state_path) as harness:
            deadline = float(harness._claim("project", "R-000")["deadline_at"])
            harness.expire_claim("project", "R-000", now=deadline)
        sleeps: list[float] = []

        event = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: deadline,
            sleep=sleeps.append,
        )

        self.assertIsNotNone(event)
        self.assertEqual(sleeps, [])
        assert event is not None
        self.assertTrue(event.restart.required)
        self.assertTrue(event.signature.startswith("gate:"))

    def test_unchanged_incident_does_not_create_a_second_successor(self) -> None:
        with DeadlineHarness(self.state_path) as harness:
            deadline = float(harness._claim("project", "R-000")["deadline_at"])
            harness.expire_claim("project", "R-000", now=deadline)
        first = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: deadline,
            sleep=lambda _seconds: None,
        )
        assert first is not None and first.restart.generation is not None
        with DeadlineHarness(self.state_path) as harness:
            harness.claim_coordinator_restart(
                "project", first.restart.generation, "successor-1", now=deadline
            )
            harness.acknowledge_coordinator_restart(
                "project", first.restart.generation, "successor-1", now=deadline
            )

        with self.assertRaisesRegex(SupervisorError, "without resolving"):
            wait_for_supervision_event(
                self.state_path,
                "project",
                now=lambda: deadline,
                sleep=lambda _seconds: None,
                handled_signatures={first.signature},
            )

        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertEqual(restart["generation"], 1)
        self.assertFalse(restart["pending"])

    def test_resolved_deadline_does_not_rearm_a_successor(self) -> None:
        with DeadlineHarness(self.state_path) as harness:
            deadline = float(harness._claim("project", "R-000")["deadline_at"])
            harness.expire_claim("project", "R-000", now=deadline)
            harness.connection.execute(
                """
                UPDATE incidents SET reviewed_at = ?
                WHERE lineage_id = 'project' AND task_id = 'seed'
                  AND kind = 'deadline_miss'
                """,
                (deadline,),
            )
            harness.connection.executemany(
                """
                INSERT INTO deadline_mutation_components (
                    lineage_id, claim_id, component, resolved_at, evidence
                ) VALUES ('project', 'R-000', ?, ?, ?)
                """,
                (
                    ("micro", deadline, "micro guarded"),
                    ("macro", deadline, "macro guarded"),
                ),
            )
            harness.connection.commit()

        sleeps: list[float] = []
        event = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: deadline,
            sleep=sleeps.append,
        )

        self.assertIsNone(event)
        self.assertEqual(sleeps, [])
        with DeadlineHarness(self.state_path) as harness:
            self.assertIsNone(
                harness.coordinator_restart_status("project")[
                    "coordinator_restart"
                ]
            )

    def environment(self, mode: str) -> dict[str, str]:
        return {
            "FAKE_DE67_SCRIPTS": str(SCRIPTS),
            "FAKE_EVENTS": str(self.events),
            "FAKE_MODE": mode,
        }

    def runner_command(self) -> list[str]:
        return [sys.executable, str(self.fake_runner)]

    def write_work_documents(self, *, red: bool = False, active: bool = False) -> None:
        state_root = self.workspace / ".de67"
        state_root.mkdir(exist_ok=True)
        claim = "- [ ] \N{LARGE RED CIRCLE} R-001 \N{EM DASH} Open\n" if red else "- [x] R-001 \N{EM DASH} Done\n"
        item = "- [ ] R-001 \N{EM DASH} Current route\n" if active else ""
        (state_root / "DFS.md").write_text(
            "# DFS\n\nStatus: Frozen\n\n" + claim,
            encoding="utf-8",
        )
        (state_root / "work-ledger.md").write_text(
            "# Work ledger\n\n## Active work\n\n" + item,
            encoding="utf-8",
        )

    def request_restart(self) -> int:
        with DeadlineHarness(self.state_path) as harness:
            return harness.request_coordinator_restart(
                "project", "test restart"
            )["coordinator_restart"]["generation"]

    def statuses(self) -> dict[str, str]:
        return {
            path.parent.name: path.read_text(encoding="utf-8").strip()
            for path in self.run_root.glob("*/status.txt")
        }

    def read_events(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.events.read_text(encoding="utf-8").splitlines()
        ]

    def test_supervisor_prompt_routes_only_the_coordinator_role(self) -> None:
        prompt = coordinator_prompt(
            self.workspace.resolve(),
            self.state_path.resolve(),
            "project",
            "prompt-test-run",
            None,
        )

        self.assertIn(str(KERNEL_PATH), prompt)
        self.assertIn(str(COORDINATOR_ROLE_PATH), prompt)
        self.assertNotIn(str(PHASE3_ROOT / "SKILL.md"), prompt)
        self.assertNotIn("Read the installed DE-67-3 skill", prompt)
        self.assertNotIn("Run DE-67-3", prompt)
        self.assertIn("Do not read the phase router", prompt)
        self.assertIn("extract its guarded claim-bound DFS slices", prompt)
        self.assertIn("do not preload the whole DFS", prompt)
        self.assertIn("Canonical mutable method guidance is only under", prompt)
        self.assertIn("Never read, create, or mutate workspace-local copies", prompt)
        for role_path in ROLE_ROOT.glob("*.md"):
            if role_path != COORDINATOR_ROLE_PATH:
                self.assertNotIn(str(role_path), prompt)

    def test_cli_defaults_coordinator_to_sol_low_without_changing_runner_args(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--state", "state.sqlite3",
                "--lineage", "project",
                "--workspace", "workspace",
                "--run-root", "runs",
                "--runner", "runner", "--runner-owned-option",
            ]
        )

        self.assertEqual(arguments.coordinator_model, "gpt-5.6-sol")
        self.assertEqual(arguments.coordinator_reasoning_effort, "low")
        self.assertEqual(arguments.runner, ["runner", "--runner-owned-option"])

    def test_external_parent_continues_two_restart_generations_once_each(self) -> None:
        run_ids = iter(("initial-run", "generation-1-run", "generation-2-run"))

        with patch("coordinator_supervisor.read_clock", wraps=read_clock) as clock_reads:
            result = run_supervisor(
                self.state_path,
                "project",
                self.workspace,
                self.runner_command(),
                self.run_root,
                extra_env=self.environment("two-restarts"),
                run_id_factory=lambda _generation: next(run_ids),
            )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual([event["generation"] for event in events], [None, 1, 2])
        self.assertEqual(
            [event["run_id"] for event in events],
            ["initial-run", "generation-1-run", "generation-2-run"],
        )
        self.assertTrue(all(event["ppid"] == os.getpid() for event in events))
        self.assertTrue(
            all(event["cwd"] == str(self.workspace.resolve()) for event in events)
        )
        self.assertEqual(clock_reads.call_count, 4)
        initial_prompt = (self.run_root / "initial-run" / "prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("DE67_DEADLINE_STATE", initial_prompt)
        self.assertIn("DE67_LINEAGE", initial_prompt)

        with DeadlineHarness(self.state_path) as harness:
            restart = harness.list_tasks()["coordinator_restart"]
        self.assertEqual(restart["generation"], 2)
        self.assertFalse(restart_required(restart))
        self.assertEqual(restart["run_id"], "generation-2-run")
        self.assertEqual(
            self.statuses(),
            {
                "initial-run": "DONE",
                "generation-1-run": "DONE",
                "generation-2-run": "DONE",
            },
        )
        self.assertNotIn("RUNNING", self.statuses().values())

    def test_valid_baton_continues_after_any_child_exit_code(self) -> None:
        self.write_work_documents(red=True, active=True)
        run_ids = iter(("retiring-run", "successor-run"))

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("restart-then-exit-nonzero"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            [event["run_id"] for event in self.read_events()],
            ["retiring-run", "successor-run"],
        )
        self.assertEqual(
            self.statuses(),
            {"retiring-run": "FAILED", "successor-run": "DONE"},
        )

    def test_fresh_workspace_initializes_clock_before_first_coordinator(self) -> None:
        self.state_path.unlink()
        run_ids = iter(
            ("fresh-initial", "fresh-generation-1", "fresh-generation-2")
        )

        result = run_supervisor(
            self.state_path,
            "fresh-project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("two-restarts"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        with DeadlineHarness(self.state_path) as harness:
            summary = harness.list_tasks()
        self.assertEqual(summary["lineage_id"], "fresh-project")
        self.assertFalse(restart_required(summary["coordinator_restart"]))

    def test_all_green_empty_work_returns_before_runner(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
        )

        self.assertEqual(result, 0)
        self.assertFalse(self.events.exists())
        self.assertFalse(self.run_root.exists())

    def test_green_documents_cannot_hide_an_open_named_closure_gap(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "strategy known", now=time.time())
            harness.transition_claim_to_closure(
                "project",
                "R-000",
                "seed",
                "Prove the product outcome.",
                "Run the owner route.",
                gaps=[("G-001", "Owner-route proof remains.", "Run owner route.")],
                now=time.time(),
            )

        self.assertFalse(work_is_complete(self.workspace, self.state_path, "project"))

    def test_final_wave_exits_without_manufacturing_a_successor(self) -> None:
        self.write_work_documents(red=True, active=True)

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("complete-program"),
            run_id_factory=lambda _generation: "final-wave-run",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 1)
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNone(restart)

    def test_empty_ledger_with_red_dfs_still_launches(self) -> None:
        self.write_work_documents(red=True)
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
            run_id_factory=lambda _generation: "red-work-run",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 1)

    def test_drained_ledger_launches_one_replenishment_coordinator(self) -> None:
        self.write_work_documents(red=True, active=True)

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("drain-then-no-refill"),
            run_id_factory=lambda generation: (
                "draining-run" if generation is None else "replenishment-run"
            ),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["generation"])
        self.assertEqual(events[1]["generation"], 1)
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNotNone(restart)
        self.assertFalse(restart_required(restart))

    def test_active_ledger_restarts_immediately_without_a_deadline_event(self) -> None:
        self.write_work_documents(active=True)
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("handover-then-complete"),
            run_id_factory=lambda generation: (
                "active-ledger-initial" if generation is None else "active-ledger-successor"
            ),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["generation"])
        self.assertEqual(events[1]["generation"], 1)
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNotNone(restart)
        self.assertFalse(restart_required(restart))

    def test_active_clock_prevents_completion(self) -> None:
        self.write_work_documents()

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
            run_id_factory=lambda _generation: "active-clock-run",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 1)

    def test_reopened_unaccepted_claim_prevents_green_dfs_completion(self) -> None:
        self.write_work_documents()
        base = time.time()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "explored", now=base)
            harness.transition_claim_to_closure(
                "project",
                "R-000",
                "seed",
                "The owner route returns the finished outcome.",
                "Run the owner route and inspect its artifact.",
                "Only closure remains.",
                now=base + 1,
            )
            harness.start_task(
                "project", "closure", "R-000", 3600,
                phase="closure", now=base + 2
            )
            harness.complete_task(
                "project", "closure", "closure proved", now=base + 3
            )
            harness.accept_claim(
                "project", "R-000", "closure", "accepted proof", now=base + 4
            )
            harness.start_task(
                "project", "closure-check", "R-000", 3600,
                phase="closure", now=base + 5
            )
            harness.report_worker_finding(
                "project",
                "closure-check",
                "unexpected",
                "The owner route returns the finished outcome premise is false.",
                now=base + 6,
            )
            harness.reopen_claim_exploration(
                "project",
                "R-000",
                "closure-check",
                "The owner route returns the finished outcome",
                now=base + 7,
            )
            harness.start_task(
                "project", "reexplore", "R-000", 3600, now=base + 8
            )
            harness.complete_task(
                "project", "reexplore", "replacement strategy proved",
                now=base + 9
            )

        self.assertFalse(work_is_complete(self.workspace, self.state_path, "project"))
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
            run_id_factory=lambda _generation: "reopened-claim-run",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 1)

    def test_pending_restart_prevents_completion(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())
            harness.request_coordinator_restart("project", "guarded mutation")

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("ack"),
            run_id_factory=lambda _generation: "pending-restart-run",
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["generation"], 1)

    def test_pending_incident_prevents_completion(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "late green", now=time.time() + 7200)

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
            run_id_factory=lambda _generation: "incident-run",
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 1)

    def test_pending_integrity_mutation_prevents_completion(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())
            summary = harness.list_tasks()
        summary["tasks"] = [
            {"task_id": "seed", "claim_id": "R-000", "state": "completed"}
        ]
        summary["pending_incident_reviews"] = []
        summary["pending_integrity_mutations"] = [
            {
                "task_id": "proof-breach",
                "claim_id": "R-000",
                "pending_components": ["micro", "macro"],
            }
        ]

        with patch.object(DeadlineHarness, "list_tasks", return_value=summary):
            self.assertFalse(
                work_is_complete(self.workspace, self.state_path, "project")
            )

    def test_final_completion_supersedes_random_improvement_due(self) -> None:
        self.write_work_documents()
        with DeadlineHarness(self.state_path) as harness:
            harness.connection.execute(
                """
                UPDATE random_mutation_cycles
                SET interval_windows = 10, due_after_terminal_windows = 10
                WHERE lineage_id = 'project' AND cycle_number = 1
                """
            )
            harness.connection.commit()
            harness.complete_task("project", "seed", "green", now=time.time())
            for number in range(2, 11):
                task_id = f"terminal-{number}"
                dispatched_at = time.time()
                harness.start_task(
                    "project",
                    task_id,
                    f"R-{number:03d}",
                    3600,
                    now=dispatched_at,
                )
                result = harness.complete_task(
                    "project", task_id, "green", now=dispatched_at + 1
                )
        self.assertTrue(result["random_mutation"]["due"])

        supervised = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
        )

        self.assertEqual(supervised, 0)
        self.assertFalse(self.events.exists())

    def test_acknowledgement_argv_preserves_hostile_valid_values(self) -> None:
        hostile_root = self.root / "state and runs [literal]"
        state = hostile_root / "deadline state.sqlite3"
        workspace = self.root / "workspace & code [literal]"
        workspace.mkdir()
        run_root = hostile_root / "coordinator runs"
        lineage = "project & branch [literal]"
        with DeadlineHarness(state) as harness:
            generation = harness.request_coordinator_restart(
                lineage, "path quoting proof"
            )["coordinator_restart"]["generation"]

        result = run_supervisor(
            state,
            lineage,
            workspace,
            self.runner_command(),
            run_root,
            extra_env=self.environment("ack-from-json"),
            run_id_factory=lambda _generation: "hostile-values-run",
        )

        self.assertEqual(
            result,
            0,
            Path(str(self.events) + ".ack").read_text(encoding="utf-8"),
        )
        event = self.read_events()[0]
        self.assertEqual(
            event["ack_argv"],
            [
                sys.executable,
                str((SCRIPTS / "deadline_harness.py").resolve()),
                "ack-restart",
                "--state",
                str(state.resolve()),
                "--lineage",
                lineage,
                "--generation",
                str(generation),
                "--run-id",
                "hostile-values-run",
            ],
        )

    def test_unacknowledged_successor_is_not_retried_and_stays_pending(self) -> None:
        generation = self.request_restart()

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("unacknowledged"),
            run_id_factory=lambda _generation: "unacknowledged-run",
        )

        self.assertEqual(result, 1)
        events = self.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["generation"], generation)
        self.assertEqual(events[0]["ppid"], os.getpid())
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.list_tasks()["coordinator_restart"]
        self.assertTrue(restart_required(restart))
        self.assertEqual(restart["generation"], generation)
        self.assertIsNone(restart["run_id"])
        self.assertEqual(restart["expected_run_id"], "unacknowledged-run")
        self.assertEqual(self.statuses(), {"unacknowledged-run": "FAILED"})
        self.assertNotIn("RUNNING", self.statuses().values())

    def test_failed_successor_is_not_retried_and_stays_pending(self) -> None:
        generation = self.request_restart()

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("fail-before-ack"),
            run_id_factory=lambda _generation: "failed-run",
        )

        self.assertEqual(result, 7)
        events = self.read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["generation"], generation)
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.list_tasks()["coordinator_restart"]
        self.assertTrue(restart_required(restart))
        self.assertEqual(restart["generation"], generation)
        self.assertEqual(restart["expected_run_id"], "failed-run")
        self.assertEqual(self.statuses(), {"failed-run": "FAILED"})
        self.assertEqual(
            (self.run_root / "failed-run" / "exit_code.txt")
            .read_text(encoding="utf-8")
            .strip(),
            "7",
        )
        self.assertNotIn("RUNNING", self.statuses().values())

    def test_second_supervisor_is_rejected_before_launch(self) -> None:
        lock_state = self.state_path.resolve()
        with _supervisor_lock(lock_state):
            with self.assertRaisesRegex(SupervisorError, "already owns"):
                run_supervisor(
                    self.state_path,
                    "project",
                    self.workspace,
                    self.runner_command(),
                    self.run_root,
                    extra_env=self.environment("two-restarts"),
                )

        self.assertFalse(self.events.exists())
        self.assertFalse(self.run_root.exists())


if __name__ == "__main__":
    unittest.main()
