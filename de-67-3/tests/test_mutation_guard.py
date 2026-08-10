from __future__ import annotations

import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "mutation_guard.py"
SPEC = importlib.util.spec_from_file_location("de67_phase3_mutation_guard", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

DEADLINE_MODULE_PATH = ROOT / "scripts" / "deadline_harness.py"
DEADLINE_SPEC = importlib.util.spec_from_file_location(
    "de67_phase3_deadline_harness", DEADLINE_MODULE_PATH
)
assert DEADLINE_SPEC is not None and DEADLINE_SPEC.loader is not None
deadline = importlib.util.module_from_spec(DEADLINE_SPEC)
DEADLINE_SPEC.loader.exec_module(deadline)


TASK_GUIDANCE = guard.read_markdown(
    guard.CANONICAL_GUIDELINES_ROOT / guard.TASK_GUIDELINES
)
ORCHESTRATOR_GUIDANCE = guard.read_markdown(
    guard.CANONICAL_GUIDELINES_ROOT / guard.ORCHESTRATOR_GUIDELINES
)


class MutationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.baseline = self.root / "baseline"
        self.candidate = self.root / "candidate"
        self.baseline.mkdir()
        self.candidate.mkdir()
        self.write_guidelines(self.baseline, TASK_GUIDANCE, ORCHESTRATOR_GUIDANCE)
        self.write_guidelines(self.candidate, TASK_GUIDANCE, ORCHESTRATOR_GUIDANCE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write_guidelines(root: Path, task_text: str, orchestrator_text: str) -> None:
        (root / guard.TASK_GUIDELINES).write_text(task_text, encoding="utf-8")
        (root / guard.ORCHESTRATOR_GUIDELINES).write_text(
            orchestrator_text, encoding="utf-8"
        )

    def mutate_task(self) -> None:
        path = self.candidate / guard.TASK_GUIDELINES
        path.write_text(
            TASK_GUIDANCE.replace(
                "Read the exact working tree, affected DFS claim, current owner path, relevant tests,",
                "Read the exact working tree and state owners before preparing the affected DFS claim,",
            ),
            encoding="utf-8",
        )

    def mutate_orchestrator(self) -> None:
        path = self.candidate / guard.ORCHESTRATOR_GUIDELINES
        path.write_text(
            ORCHESTRATOR_GUIDANCE.replace(
                "Begin fresh from the DFS, both guidance documents, both ledgers, timer status, repository identity,",
                "Begin independently from the DFS, both guidance documents, both ledgers, timer status, and repository identity,",
            ),
            encoding="utf-8",
        )

    def test_frozen_heading_change_is_rejected(self) -> None:
        path = self.candidate / guard.TASK_GUIDELINES
        path.write_text(
            TASK_GUIDANCE.replace("## Task preparation", "## Prepare work"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(guard.GuardError, "canonical template"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=False
            )

    def test_shared_corrupt_heading_is_rejected(self) -> None:
        corrupt = TASK_GUIDANCE.replace("## Task preparation", "## Prepare work")
        baseline_corrupt = corrupt
        candidate_corrupt = corrupt.replace(
            "Read the exact working tree, affected DFS claim, current owner path, relevant tests,",
            "Read the exact working tree and state owners before preparing the affected DFS claim,",
        )
        (self.baseline / guard.TASK_GUIDELINES).write_text(
            baseline_corrupt, encoding="utf-8"
        )
        (self.candidate / guard.TASK_GUIDELINES).write_text(
            candidate_corrupt, encoding="utf-8"
        )
        with self.assertRaisesRegex(guard.GuardError, "baseline headings"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=False
            )

    def test_ordinary_miss_changes_only_task_guidance(self) -> None:
        self.mutate_task()
        changed = guard.validate_guideline_mutation(
            self.baseline, self.candidate, broader_mutation=False
        )
        self.assertEqual(changed, (guard.TASK_GUIDELINES,))

        self.mutate_orchestrator()
        with self.assertRaisesRegex(guard.GuardError, "ordinary miss"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=False
            )

    def test_broader_mutation_requires_both_guidelines(self) -> None:
        self.mutate_task()
        with self.assertRaisesRegex(guard.GuardError, "must change both"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=True
            )

        self.mutate_orchestrator()
        changed = guard.validate_guideline_mutation(
            self.baseline,
            self.candidate,
            broader_mutation=True,
        )
        self.assertEqual(set(changed), set(guard.GUIDELINE_FILES))

    def incident_state(self) -> Path:
        state = self.root / "incidents.sqlite"
        with deadline.DeadlineHarness(state) as harness:
            for number in range(1, 4):
                task = f"miss-{number}"
                harness.start_task(
                    "project", task, f"R-{number:03d}", 1, now=0
                )
                harness.expire_task("project", task, now=2)
            harness.start_task("project", "breach", "R-004", 10, now=0)
            harness.record_integrity_breach(
                "project", "breach", "fabricated evidence", now=1
            )
        return state

    def run_guidelines_cli(
        self, state: Path, task: str, incident_kind: str
    ) -> tuple[int, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = guard.main(
                [
                    "guidelines",
                    "--baseline",
                    str(self.baseline),
                    "--candidate",
                    str(self.candidate),
                    "--state",
                    str(state),
                    "--lineage",
                    "project",
                    "--task",
                    task,
                    "--incident-kind",
                    incident_kind,
                ]
            )
        return result, stdout.getvalue() + stderr.getvalue()

    def test_guidelines_cli_derives_second_and_third_miss_scope(self) -> None:
        state = self.incident_state()
        self.mutate_task()

        result, output = self.run_guidelines_cli(state, "miss-2", "deadline_miss")
        self.assertEqual(result, 0, output)
        self.assertIn(guard.TASK_GUIDELINES, output)

        result, output = self.run_guidelines_cli(state, "miss-3", "deadline_miss")
        self.assertEqual(result, 1)
        self.assertIn("must change both", output)

        self.mutate_orchestrator()
        result, output = self.run_guidelines_cli(state, "miss-3", "deadline_miss")
        self.assertEqual(result, 0, output)
        self.assertIn(guard.ORCHESTRATOR_GUIDELINES, output)

    def test_guidelines_cli_derives_integrity_scope(self) -> None:
        state = self.incident_state()
        self.mutate_task()
        self.mutate_orchestrator()

        result, output = self.run_guidelines_cli(
            state, "breach", "integrity_breach"
        )
        self.assertEqual(result, 0, output)
        self.assertIn(guard.ORCHESTRATOR_GUIDELINES, output)

    def test_guidelines_cli_rejects_missing_or_mismatched_incident(self) -> None:
        state = self.incident_state()
        self.mutate_task()

        result, output = self.run_guidelines_cli(
            state, "missing", "deadline_miss"
        )
        self.assertEqual(result, 1)
        self.assertIn("Missing stored deadline_miss incident", output)

        result, output = self.run_guidelines_cli(
            state, "miss-2", "integrity_breach"
        )
        self.assertEqual(result, 1)
        self.assertIn("Missing stored integrity_breach incident", output)

    def write_dfs(self, text: str) -> Path:
        path = self.root / "DFS.md"
        path.write_text(text, encoding="utf-8")
        return path

    def write_ledger(self, text: str) -> Path:
        path = self.root / "work-ledger.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_work_ledger_accepts_ten_and_rejects_eleven_active_items(self) -> None:
        dfs = self.write_dfs(
            "# DFS\n\n"
            + "".join(f"- [ ] 🔴 R-{number:03d} — Work {number}\n" for number in range(1, 12))
        )
        ten = self.write_ledger(
            "# Work ledger\n\n## Active work\n\n"
            + "".join(f"- [ ] R-{number:03d} — Work {number}\n" for number in range(1, 11))
            + "  - [ ] R-999 — Nested worker prose is not another work item\n"
        )
        self.assertEqual(len(guard.validate_work_ledger(ten, dfs)), 10)

        eleven = self.write_ledger(
            "# Work ledger\n\n## Active work\n\n"
            + "".join(f"- [ ] R-{number:03d} — Work {number}\n" for number in range(1, 12))
        )
        with self.assertRaisesRegex(guard.GuardError, "maximum is 10"):
            guard.validate_work_ledger(eleven, dfs)

    def test_work_ledger_rejects_missing_and_non_red_claims(self) -> None:
        dfs = self.write_dfs(
            "# DFS\n\n"
            "- [ ] 🔴 R-001 — Still open\n"
            "- [x] R-002 — Already accepted\n"
        )
        missing = self.write_ledger(
            "# Work ledger\n\n## Active work\n\n- [ ] R-404 — Missing\n"
        )
        with self.assertRaisesRegex(guard.GuardError, "still-red"):
            guard.validate_work_ledger(missing, dfs)

        non_red = self.write_ledger(
            "# Work ledger\n\n## Active work\n\n- [ ] R-002 — Already accepted\n"
        )
        with self.assertRaisesRegex(guard.GuardError, "still-red"):
            guard.validate_work_ledger(non_red, dfs)

    def test_exact_red_syntax_matches_an_active_item(self) -> None:
        dfs = self.write_dfs(
            "# DFS\n\n- [ ] 🔴 R-001 — Missing production behavior\n"
        )
        ledger = self.write_ledger(
            "# Work ledger\n\n## Active work\n\n"
            "- [ ] R-001 — Implement the red claim\n"
        )
        items = guard.validate_work_ledger(ledger, dfs)
        self.assertEqual(items, ("R-001 — Implement the red claim",))

    def test_exact_selected_marker_removal_is_accepted(self) -> None:
        before = self.root / "before.md"
        after = self.root / "after.md"
        before.write_text(
            "# DFS\n\n- [ ] 🔴 R-001 — First\n- [ ] 🔴 R-002 — Second\n",
            encoding="utf-8",
        )
        after.write_text(
            "# DFS\n\n- [x] R-001 — First\n- [ ] 🔴 R-002 — Second\n",
            encoding="utf-8",
        )
        completed = guard.validate_dfs_completion(before, after, "R-001 — First")
        self.assertEqual(completed, "R-001 — First")

    def test_dfs_completion_rejects_collateral_edit(self) -> None:
        before = self.root / "before.md"
        after = self.root / "after.md"
        before.write_text(
            "# DFS\n\n- [ ] 🔴 R-001 — First\n- [ ] 🔴 R-002 — Second\n",
            encoding="utf-8",
        )
        after.write_text(
            "# DFS revised\n\n- [x] R-001 — First\n- [ ] 🔴 R-002 — Second\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(guard.GuardError, "must only change"):
            guard.validate_dfs_completion(before, after, "R-001")

    def completion_files(self) -> tuple[Path, Path]:
        before = self.root / "state-before.md"
        after = self.root / "state-after.md"
        before.write_text("# DFS\n\n- [ ] 🔴 R-001 — First\n", encoding="utf-8")
        after.write_text("# DFS\n\n- [x] R-001 — First\n", encoding="utf-8")
        return before, after

    def deadline_state(
        self,
        name: str,
        *,
        lineage: str = "project",
        task: str = "task",
        claim: str = "R-001",
        accepted: bool = True,
        breached: bool = False,
    ) -> Path:
        state = self.root / f"{name}.sqlite"
        with deadline.DeadlineHarness(state) as harness:
            harness.start_task(lineage, task, claim, 10, now=0)
            if accepted:
                harness.complete_task(
                    lineage, task, "coordinator accepted the real test", now=1
                )
            if breached:
                harness.record_integrity_breach(
                    lineage, task, "completion evidence was fabricated", now=2
                )
        return state

    def run_complete_cli(
        self,
        state: Path,
        *,
        lineage: str = "project",
        task: str = "task",
        claim: str = "R-001",
    ) -> tuple[int, str]:
        before, after = self.completion_files()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = guard.main(
                [
                    "complete-dfs",
                    "--before",
                    str(before),
                    "--after",
                    str(after),
                    "--claim",
                    claim,
                    "--state",
                    str(state),
                    "--lineage",
                    lineage,
                    "--task",
                    task,
                ]
            )
        return result, stdout.getvalue() + stderr.getvalue()

    def test_complete_dfs_cli_accepts_matching_accepted_task(self) -> None:
        state = self.deadline_state("accepted")
        result, output = self.run_complete_cli(state)
        self.assertEqual(result, 0, output)
        self.assertIn("ok: completed R-001 — First", output)

    def test_complete_dfs_cli_rejects_unknown_and_unaccepted_tasks(self) -> None:
        accepted = self.deadline_state("known", task="known")
        result, output = self.run_complete_cli(accepted, task="unknown")
        self.assertEqual(result, 1)
        self.assertIn("Unknown deadline task", output)

        pending = self.deadline_state("pending", task="pending", accepted=False)
        result, output = self.run_complete_cli(pending, task="pending")
        self.assertEqual(result, 1)
        self.assertIn("has not been accepted", output)

    def test_complete_dfs_cli_rejects_mismatch_and_integrity_breach(self) -> None:
        mismatched = self.deadline_state("mismatch", claim="R-002")
        result, output = self.run_complete_cli(mismatched)
        self.assertEqual(result, 1)
        self.assertIn("does not match selected claim", output)

        breached = self.deadline_state("breached", breached=True)
        result, output = self.run_complete_cli(breached)
        self.assertEqual(result, 1)
        self.assertIn("integrity breach", output)


if __name__ == "__main__":
    unittest.main()
