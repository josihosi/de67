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
    SupervisionEvent,
    SupervisorError,
    _supervisor_lock,
    build_parser,
    coordinator_prompt,
    blocked_ledger_audit_reason,
    ledger_has_only_blocked_work,
    main,
    read_clock,
    run_supervisor,
    wait_for_supervision_event,
    work_is_complete,
)
from blocker_adapter import BlockerReply  # noqa: E402
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
    "role": os.environ.get("DE67_PROCESS_ROLE"),
    "model": os.environ.get("DE67_COORDINATOR_MODEL"),
    "effort": os.environ.get("DE67_COORDINATOR_REASONING_EFFORT"),
    "ack_argv": json.loads(os.environ["DE67_COORDINATOR_ACK_ARGV_JSON"])
    if generation is not None
    else None,
    "policy_argv": json.loads(os.environ["DE67_POLICY_DECIDE_ARGV_JSON"]),
    "policy_guard_argv": json.loads(os.environ["DE67_POLICY_GUARD_ARGV_JSON"]),
    "resume_session": os.environ.get("DE67_COORDINATOR_RESUME_SESSION"),
}
with Path(os.environ["FAKE_EVENTS"]).open("a", encoding="utf-8") as output:
    output.write(json.dumps(event) + "\n")
event_count = len(Path(os.environ["FAKE_EVENTS"]).read_text(encoding="utf-8").splitlines())
mode = os.environ["FAKE_MODE"]
if not (mode == "crash-without-session-then-complete" and event_count == 1):
    Path(os.environ["DE67_COORDINATOR_SESSION_FILE"]).write_text(
        os.environ.get("DE67_COORDINATOR_RESUME_SESSION", "fake-session") + "\n",
        encoding="utf-8",
    )

with DeadlineHarness(os.environ["DE67_DEADLINE_STATE"]) as harness:
    if mode in {"mutation-lifecycle", "mutation-after-coordinator", "deadline-mutation-lifecycle"}:
        if os.environ.get("DE67_PROCESS_ROLE") == "mutation-reviewer":
            suggestions = Path(os.environ["DE67_WORKSPACE"]) / ".de67" / "mutation-suggestions.md"
            if not suggestions.is_file():
                raise AssertionError("mutation reviewer must receive the suggestion ledger")
            if mode in {"mutation-lifecycle", "mutation-after-coordinator"}:
                cycle = harness.list_tasks()["random_mutation"]
                harness.resolve_random_mutation(
                    os.environ["DE67_LINEAGE"],
                    cycle["cycle_number"],
                    "reviewed the complete suggestion ledger; no change required",
                )
            else:
                incident = harness.list_tasks()["pending_incident_reviews"][0]
                harness.diagnose_claim_deadline(
                    os.environ["DE67_LINEAGE"],
                    incident["claim_id"],
                    incident["task_id"],
                    "The deadline expired before the worker returned.",
                )
                harness.resolve_deadline_mutation(
                    os.environ["DE67_LINEAGE"], incident["claim_id"],
                    "micro", "Recover with a fresh whole-item clock."
                )
                harness.resolve_deadline_mutation(
                    os.environ["DE67_LINEAGE"], incident["claim_id"],
                    "macro", "Keep the existing general deadline guidance."
                )
        else:
            if mode == "mutation-after-coordinator" and generation is None:
                harness.complete_task(
                    os.environ["DE67_LINEAGE"], "seed", "trigger mutation boundary"
                )
                raise SystemExit(0)
            if generation is None:
                raise AssertionError("post-mutation coordinator must be a fresh generation")
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
    elif mode == "two-restarts":
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
        if event_count > 1:
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
        if event_count == 1:
            harness.complete_task(
                os.environ["DE67_LINEAGE"], "seed", "ledger item retired"
            )
            (root / "work-ledger.md").write_text(
                "# Work ledger\n\n## Active work\n",
                encoding="utf-8",
            )
        else:
            if generation is not None:
                harness.acknowledge_coordinator_restart(
                    os.environ["DE67_LINEAGE"],
                    generation,
                    os.environ["DE67_COORDINATOR_RUN_ID"],
                )
            (root / "DFS.md").write_text(
                "# DFS\n\nStatus: Frozen\n\n- [x] R-001 \N{EM DASH} Done\n",
                encoding="utf-8",
            )
            (root / "work-ledger.md").write_text(
                "# Work ledger\n\n## Active work\n",
                encoding="utf-8",
            )
    elif mode == "crash-then-complete":
        if event_count == 1:
            raise SystemExit(9)
        if generation is not None:
            raise AssertionError("resumable crash must keep the same coordinator generation")
        harness.complete_task(
            os.environ["DE67_LINEAGE"], "seed", "successor proof"
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
    elif mode == "crash-without-session-then-complete":
        if event_count == 1:
            raise SystemExit(9)
        if generation is not None:
            raise AssertionError("crash recovery must not manufacture a mutation generation")
        harness.complete_task(
            os.environ["DE67_LINEAGE"], "seed", "successor proof"
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
    elif mode == "confirm-blocked":
        if generation is None:
            raise AssertionError("blocked audit must be a restart generation")
        harness.acknowledge_coordinator_restart(
            os.environ["DE67_LINEAGE"],
            generation,
            os.environ["DE67_COORDINATOR_RUN_ID"],
        )
        harness.report_worker_finding(
            os.environ["DE67_LINEAGE"],
            "seed",
            "blocker",
            "Fresh coordinator confirmed the exact owner choice remains unavailable.",
            short_verdict="owner choice is still required",
        )
    elif mode == "blocked-reply-complete":
        if generation is None:
            raise AssertionError("blocked reply route must use a restart generation")
        harness.acknowledge_coordinator_restart(
            os.environ["DE67_LINEAGE"],
            generation,
            os.environ["DE67_COORDINATOR_RUN_ID"],
        )
        if generation == 2:
            root = Path(os.environ["DE67_WORKSPACE"]) / ".de67"
            (root / "DFS.md").write_text(
                "# DFS\n\nStatus: Frozen\n\n- [x] R-001 \N{EM DASH} Done\n",
                encoding="utf-8",
            )
            (root / "work-ledger.md").write_text(
                "# Work ledger\n\n## Active work\n",
                encoding="utf-8",
            )
    elif mode == "matrix-recover":
        if generation is not None:
            harness.acknowledge_coordinator_restart(
                os.environ["DE67_LINEAGE"],
                generation,
                os.environ["DE67_COORDINATOR_RUN_ID"],
            )
        event_count = len(Path(os.environ["FAKE_EVENTS"]).read_text(encoding="utf-8").splitlines())
        if event_count == 1:
            raise SystemExit(int(os.environ["FAKE_FIRST_EXIT"]))
        harness.complete_task(
            os.environ["DE67_LINEAGE"], "seed", "matrix recovery proof"
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

    def test_clock_event_waits_once_and_signals_mutation_without_restart(self) -> None:
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
        self.assertIsNone(event.restart)
        with DeadlineHarness(self.state_path) as harness:
            summary = harness.list_tasks(now=float(deadline))
        self.assertEqual(
            summary["pending_incident_reviews"][0]["kind"], "deadline_miss"
        )

    def test_pending_incident_signals_mutation_without_sleeping(self) -> None:
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
        self.assertIsNone(event.restart)
        self.assertTrue(event.signature.startswith("gate:"))

    def test_unchanged_incident_does_not_manufacture_restarts(self) -> None:
        with DeadlineHarness(self.state_path) as harness:
            deadline = float(harness._claim("project", "R-000")["deadline_at"])
            harness.expire_claim("project", "R-000", now=deadline)
        first = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: deadline,
            sleep=lambda _seconds: None,
        )
        assert first is not None
        self.assertIsNone(first.restart)

        second = wait_for_supervision_event(
            self.state_path,
            "project",
            now=lambda: deadline,
            sleep=lambda _seconds: None,
        )

        assert second is not None
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNone(restart)
        self.assertIsNone(second.restart)

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
        (state_root / "mutation-suggestions.md").write_text(
            "# Mutation suggestions\n\n## Pending suggestions\n\n- Review this.\n",
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

    def test_supervisor_prompt_routes_only_compiled_workspace_policy(self) -> None:
        prompt = coordinator_prompt(
            self.workspace.resolve(),
            self.state_path.resolve(),
            "project",
            "prompt-test-run",
            None,
        )

        self.assertIn("Do not read packaged DE-67", prompt)
        self.assertIn(".de67/phase3-policy.d67", prompt)
        self.assertIn("DE67_POLICY_DECIDE_ARGV_JSON", prompt)
        self.assertIn("machine-canonical", prompt)
        self.assertIn("Never review, apply, or resolve a mutation", prompt)
        self.assertIn("exit immediately", prompt)
        self.assertNotIn("promote both candidate source", prompt)
        self.assertIn("legacy differential fixtures", prompt)
        self.assertIn("Write every owner-facing text field rendered on the hosted dashboard in simple English", prompt)
        self.assertIn("ledger items, latest findings, waiting work", prompt)
        self.assertIn("explain what happened and why it matters", prompt)
        self.assertIn("state what remains or happens next", prompt)
        self.assertIn("exposes a contradiction or a missing causal step", prompt)
        self.assertIn("Internal machine state and DFS detail", prompt)
        self.assertNotIn("Read .de67/orchestrator-guidelines.md", prompt)
        self.assertNotIn("test-and-task-guidelines.md", prompt)

    def test_supervisor_exports_exact_compiled_policy_decision_command(self) -> None:
        self.write_work_documents(red=True, active=True)
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("complete-program"),
            run_id_factory=lambda _generation: "policy-command",
        )

        self.assertEqual(result, 0)
        command = self.read_events()[0]["policy_argv"]
        self.assertEqual(command[2], "decide")
        self.assertEqual(
            command[3:5],
            ["--policy", str((self.workspace / ".de67" / "phase3-policy.d67").resolve())],
        )
        self.assertIn("--workspace", command)
        self.assertIn("--state", command)
        guard = self.read_events()[0]["policy_guard_argv"]
        self.assertEqual(guard[2], "guard")
        self.assertTrue(any(str(item).endswith("phase3-policy.candidate.json") for item in guard))
        self.assertTrue(any(str(item).endswith("phase3-policy.candidate.d67") for item in guard))

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

    def test_due_mutation_exclusively_runs_high_reviewer_then_fresh_low_coordinator(self) -> None:
        self.write_work_documents(red=True, active=True)
        with DeadlineHarness(self.state_path) as harness:
            harness.connection.execute(
                """
                UPDATE random_mutation_cycles
                SET interval_windows = 10, due_after_terminal_windows = 10,
                    selected_lane = 'orchestrator-guidelines.md'
                WHERE lineage_id = 'project' AND cycle_number = 1
                """
            )
            harness.connection.commit()
            harness.complete_task("project", "seed", "terminal one")
            for number in range(2, 11):
                task_id = f"terminal-{number}"
                harness.start_task("project", task_id, "R-001", 3600)
                harness.complete_task("project", task_id, f"terminal {number}")

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env={
                **self.environment("mutation-lifecycle"),
                "DE67_COORDINATOR_MODEL": "gpt-5.6-sol",
                "DE67_COORDINATOR_REASONING_EFFORT": "low",
            },
            run_id_factory=lambda _generation: "fresh-low-coordinator",
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual([event["role"] for event in events], [
            "mutation-reviewer", "coordinator",
        ])
        self.assertEqual(
            [(event["model"], event["effort"]) for event in events],
            [("gpt-5.6-sol", "high"), ("gpt-5.6-sol", "low")],
        )
        reviewer_run = next(
            path for path in self.run_root.iterdir() if path.name.startswith("mutation-")
        )
        reviewer_prompt = (reviewer_run / "prompt.txt").read_text(encoding="utf-8")
        self.assertIn("mutation-suggestions.md completely", reviewer_prompt)
        self.assertIn("Disposition every pending suggestion explicitly", reviewer_prompt)
        self.assertIn("supervisor alone starts the fresh coordinator", reviewer_prompt)

    def test_mutation_becoming_due_retires_coordinator_before_reviewer(self) -> None:
        self.write_work_documents(red=True, active=True)
        with DeadlineHarness(self.state_path) as harness:
            harness.connection.execute(
                """
                UPDATE random_mutation_cycles
                SET interval_windows = 10, due_after_terminal_windows = 10,
                    selected_lane = 'test-and-task-guidelines.md'
                WHERE lineage_id = 'project' AND cycle_number = 1
                """
            )
            harness.connection.commit()
            for number in range(2, 11):
                task_id = f"terminal-{number}"
                harness.start_task("project", task_id, "R-001", 3600)
                harness.complete_task("project", task_id, f"terminal {number}")

        run_ids = iter(("retiring-low-coordinator", "fresh-low-coordinator"))
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env={
                **self.environment("mutation-after-coordinator"),
                "DE67_COORDINATOR_MODEL": "gpt-5.6-sol",
                "DE67_COORDINATOR_REASONING_EFFORT": "low",
            },
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(
            [(event["role"], event["effort"]) for event in events],
            [("coordinator", "low"), ("mutation-reviewer", "high"),
             ("coordinator", "low")],
        )
        self.assertEqual([event["generation"] for event in events], [None, None, 1])

    def test_optional_adapter_argument_stays_outside_runner_arguments(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--state", "state.sqlite3",
                "--lineage", "project",
                "--workspace", "workspace",
                "--run-root", "runs",
                "--blocker-adapter-command-json", "not-json",
                "--runner", "runner",
            ]
        )

        self.assertEqual(arguments.blocker_adapter_command_json, "not-json")
        self.assertEqual(arguments.runner, ["runner"])

    def test_invalid_optional_adapter_is_disabled_without_failing_core_main(self) -> None:
        arguments = [
            "--state", "state.sqlite3",
            "--lineage", "project",
            "--workspace", "workspace",
            "--run-root", "runs",
            "--blocker-adapter-command-json", "not-json",
            "--runner", "runner",
        ]
        with patch("coordinator_supervisor.run_supervisor", return_value=0) as run:
            result = main(arguments)

        self.assertEqual(result, 0)
        self.assertIsNone(run.call_args.kwargs["blocker_waiter"])

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
        self.assertIn("DE67_POLICY_DECIDE_ARGV_JSON", initial_prompt)
        self.assertIn("preserve every emitted obligation", initial_prompt)
        self.assertNotIn("Before spawning each worker", initial_prompt)

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

    def test_blocked_only_ledger_is_audited_once_then_stops(self) -> None:
        self.write_work_documents(red=True)
        ledger = self.workspace / ".de67" / "work-ledger.md"
        ledger.write_text(
            "# Work ledger\n\n## Active work\n\n"
            "## Blocked work\n\n"
            "- Blocked: R-001 \N{EM DASH} Owner choice required\n",
            encoding="utf-8",
        )

        self.assertTrue(ledger_has_only_blocked_work(self.workspace))
        audit_reason = blocked_ledger_audit_reason(self.workspace)
        self.assertIsNotNone(audit_reason)
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("confirm-blocked"),
            run_id_factory=lambda _generation: "blocked-audit",
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            [event["generation"] for event in self.read_events()],
            [1],
        )
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertEqual(restart["reason"], audit_reason)
        self.assertFalse(restart_required(restart))
        with DeadlineHarness(self.state_path) as harness:
            tasks = harness.list_tasks()["tasks"]
        self.assertFalse(any(task["state"] == "running" for task in tasks))

        second_run_root = self.root / "second-runs"
        second_result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            second_run_root,
            extra_env=self.environment("unacknowledged"),
        )

        self.assertEqual(second_result, 0)
        self.assertFalse(second_run_root.exists())
        self.assertEqual(len(self.read_events()), 1)

    def test_authenticated_blocker_reply_starts_one_fresh_coordinator(self) -> None:
        self.write_work_documents(red=True)
        ledger = self.workspace / ".de67" / "work-ledger.md"
        ledger.write_text(
            "# Work ledger\n\n## Active work\n\n"
            "## Blocked work\n\n"
            "- Blocked: R-001 \N{EM DASH} Owner choice required\n",
            encoding="utf-8",
        )
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "prior proof")

        replies = [
            BlockerReply(
                "digest",
                "notice-1",
                "reply-1",
                "Use the clean recovery route.",
                "owner",
            )
        ]

        def wait_for_owner_reply(*, workspace: Path, lineage_id: str) -> BlockerReply | None:
            self.assertEqual(workspace, self.workspace.resolve())
            self.assertEqual(lineage_id, "project")
            return replies.pop(0) if replies else None

        run_ids = iter(["blocked-audit", "owner-reply"])
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("blocked-reply-complete"),
            run_id_factory=lambda _generation: next(run_ids),
            blocker_waiter=wait_for_owner_reply,
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            [event["generation"] for event in self.read_events()],
            [1, 2],
        )
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertEqual(
            restart["reason"], "owner replied through blocker adapter reply-1"
        )
        self.assertFalse(restart_required(restart))

    def test_recoverable_lifecycle_matrix_converges_after_child_exit(self) -> None:
        ledger_cases = {
            "active": "# Work ledger\n\n## Active work\n\n- [ ] R-001 \N{EM DASH} Work\n",
            "empty": "# Work ledger\n\n## Active work\n",
            "malformed": "# Work ledger\n\n## Active work\n\n- maybe R-001\n",
        }
        for ledger_name, ledger_text in ledger_cases.items():
            for first_exit in (0, 9):
                with self.subTest(ledger=ledger_name, first_exit=first_exit):
                    with tempfile.TemporaryDirectory() as case_directory:
                        case_root = Path(case_directory)
                        workspace = case_root / "workspace"
                        state_root = workspace / ".de67"
                        state_root.mkdir(parents=True)
                        state = case_root / "deadlines.sqlite3"
                        runs = case_root / "runs"
                        events = case_root / "events.jsonl"
                        (state_root / "DFS.md").write_text(
                            "# DFS\n\nStatus: Frozen\n\n- [ ] \N{LARGE RED CIRCLE} R-001 \N{EM DASH} Open\n",
                            encoding="utf-8",
                        )
                        (state_root / "work-ledger.md").write_text(
                            ledger_text,
                            encoding="utf-8",
                        )
                        with DeadlineHarness(state) as harness:
                            harness.start_task(
                                "project", "seed", "R-000", 3600, now=time.time()
                            )
                        run_ids = iter(("first", "recovery"))

                        result = run_supervisor(
                            state,
                            "project",
                            workspace,
                            self.runner_command(),
                            runs,
                            extra_env={
                                **self.environment("matrix-recover"),
                                "FAKE_EVENTS": str(events),
                                "FAKE_FIRST_EXIT": str(first_exit),
                            },
                            run_id_factory=lambda _generation: next(run_ids),
                        )

                        self.assertEqual(result, 0)
                        recorded = [
                            json.loads(line)
                            for line in events.read_text(encoding="utf-8").splitlines()
                        ]
                        self.assertEqual(len(recorded), 2)
                        self.assertIsNone(recorded[0]["generation"])
                        self.assertIsNone(recorded[1]["generation"])
                        self.assertEqual(recorded[1]["resume_session"], "fake-session")
                        self.assertEqual(
                            {
                                path.parent.name: path.read_text(encoding="utf-8").strip()
                                for path in runs.glob("*/status.txt")
                            },
                            {
                                "first": "DONE" if first_exit == 0 else "FAILED",
                                "recovery": "DONE",
                            },
                        )

    def test_active_item_outranks_blocked_items(self) -> None:
        self.write_work_documents(red=True, active=True)
        ledger = self.workspace / ".de67" / "work-ledger.md"
        with ledger.open("a", encoding="utf-8") as output:
            output.write(
                "\n## Blocked work\n\n"
                "- Blocked: R-002 \N{EM DASH} Different owner choice\n"
            )

        self.assertFalse(ledger_has_only_blocked_work(self.workspace))

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
        run_ids = iter(("red-work-run", "red-work-successor"))

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("handover-then-complete"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(self.read_events()), 2)

    def test_empty_replenishment_keeps_same_coordinator_session(self) -> None:
        self.write_work_documents(red=True, active=True)
        run_ids = iter(("draining-run", "empty-replenishment"))

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("drain-then-no-refill"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["generation"])
        self.assertIsNone(events[1]["generation"])
        self.assertEqual(events[1]["resume_session"], "fake-session")
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNone(restart)

    def test_crashed_cli_with_active_work_resumes_the_same_coordinator(self) -> None:
        self.write_work_documents(red=True, active=True)
        run_ids = iter(("crashed-run", "recovery-run"))

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("crash-then-complete"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            [event["run_id"] for event in self.read_events()],
            ["crashed-run", "recovery-run"],
        )
        events = self.read_events()
        self.assertIsNone(events[0]["generation"])
        self.assertIsNone(events[1]["generation"])
        self.assertEqual(events[1]["resume_session"], "fake-session")
        with DeadlineHarness(self.state_path) as harness:
            self.assertIsNone(
                harness.coordinator_restart_status("project")["coordinator_restart"]
            )
        self.assertEqual(
            self.statuses(),
            {"crashed-run": "FAILED", "recovery-run": "DONE"},
        )

    def test_nonresumable_crash_with_active_work_gets_a_fresh_coordinator(self) -> None:
        self.write_work_documents(red=True, active=True)
        run_ids = iter(("crashed-run", "recovery-run"))

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("crash-without-session-then-complete"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertIsNone(events[0]["generation"])
        self.assertIsNone(events[1]["generation"])
        self.assertIsNone(events[1]["resume_session"])
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNone(restart)

    def test_missing_runner_is_a_concrete_environment_blocker(self) -> None:
        self.write_work_documents(red=True, active=True)

        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            [str(self.root / "missing-runner")],
            self.run_root,
            run_id_factory=lambda _generation: "missing-runner",
        )

        self.assertEqual(result, 1)
        self.assertFalse(self.events.exists())
        self.assertEqual(self.statuses(), {"missing-runner": "FAILED"})

    def test_active_ledger_resumes_same_session_without_restart(self) -> None:
        self.write_work_documents(active=True)
        with DeadlineHarness(self.state_path) as harness:
            harness.complete_task("project", "seed", "green", now=time.time())

        run_ids = iter(("active-ledger-initial", "active-ledger-continuation"))
        result = run_supervisor(
            self.state_path,
            "project",
            self.workspace,
            self.runner_command(),
            self.run_root,
            extra_env=self.environment("handover-then-complete"),
            run_id_factory=lambda _generation: next(run_ids),
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["generation"])
        self.assertIsNone(events[1]["generation"])
        self.assertEqual(events[1]["resume_session"], "fake-session")
        with DeadlineHarness(self.state_path) as harness:
            restart = harness.coordinator_restart_status("project")[
                "coordinator_restart"
            ]
        self.assertIsNone(restart)
        continuation_prompt = (
            self.run_root / "active-ledger-continuation" / "prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertNotIn("orchestrator-guidelines.md", continuation_prompt)
        self.assertIn("findings are state events", continuation_prompt)
        self.assertIn("minimal action brief", continuation_prompt)

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
            extra_env=self.environment("deadline-mutation-lifecycle"),
            run_id_factory=lambda _generation: "incident-run",
        )

        self.assertEqual(result, 0)
        events = self.read_events()
        self.assertEqual(len(events), 2)
        self.assertEqual([event["role"] for event in events], [
            "mutation-reviewer", "coordinator",
        ])

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
