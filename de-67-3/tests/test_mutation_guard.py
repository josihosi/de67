from __future__ import annotations

import io
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


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
SKILL_TEXT = (ROOT / "SKILL.md").read_text(encoding="utf-8")


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
        dfs_text = self.expansion_dfs(new_claim="")
        (self.baseline / guard.DFS_FILE).write_text(dfs_text, encoding="utf-8")
        (self.candidate / guard.DFS_FILE).write_text(dfs_text, encoding="utf-8")
        self.empty_ledger = self.root / guard.MUTATION_LEDGER
        self.empty_ledger.write_text(
            guard.read_markdown(
                guard.CANONICAL_GUIDELINES_ROOT / guard.MUTATION_LEDGER
            ),
            encoding="utf-8",
        )

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
                "Begin fresh by reading",
                "Begin independently by reading",
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

    def test_incident_mutations_reject_whitespace_only_ledger_consumption(self) -> None:
        task_path = self.candidate / guard.TASK_GUIDELINES
        task_path.write_text(
            TASK_GUIDANCE.replace("Read the exact", "Read  the exact"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(guard.GuardError, "whitespace-only"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=False
            )

        orchestrator_path = self.candidate / guard.ORCHESTRATOR_GUIDELINES
        orchestrator_path.write_text(
            ORCHESTRATOR_GUIDANCE.replace("Begin fresh", "Begin  fresh"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(guard.GuardError, "whitespace-only"):
            guard.validate_guideline_mutation(
                self.baseline, self.candidate, broader_mutation=True
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
                harness.diagnose_incident(
                    "project",
                    task,
                    "deadline_miss",
                    f"miss {number}",
                    f"Independent diagnosis for miss {number}.",
                    now=3,
                )
            harness.start_task("project", "breach", "R-004", 10, now=0)
            harness.record_integrity_breach(
                "project", "breach", "fabricated evidence", now=1
            )
            harness.diagnose_incident(
                "project",
                "breach",
                "integrity_breach",
                "integrity breach",
                "Independent diagnosis of fabricated evidence.",
                now=2,
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
                    "--ledger-candidate",
                    str(self.empty_ledger),
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

    def test_guidelines_cli_rejects_an_undiagnosed_incident(self) -> None:
        state = self.root / "undiagnosed.sqlite"
        with deadline.DeadlineHarness(state) as harness:
            harness.start_task("project", "miss", "R-001", 1, now=0)
            harness.expire_task("project", "miss", now=2)
        self.mutate_task()

        result, output = self.run_guidelines_cli(
            state, "miss", "deadline_miss"
        )

        self.assertEqual(result, 1)
        self.assertIn("independent short and long diagnosis", output)

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

    @staticmethod
    def expansion_dfs(*, new_claim: str = "- [ ] 🔴 R-003 — New prerequisite\n") -> str:
        return (
            "# DFS\n\n"
            "## Functional contract\n\n"
            "The existing behavior remains the contract.\n\n"
            "## Project language and terminology\n\n"
            "Use the project's existing names.\n\n"
            "## Mechanistic design\n\n"
            "The coordinator may add source-grounded mechanics here.\n\n"
            "## Stable work claims\n\n"
            "- [x] R-000 — Accepted frontier\n"
            "- [ ] 🔴 R-001 — Worker found a blocker\n"
            "- [ ] 🔴 R-002 — Existing next work\n"
            + new_claim
        )

    def expansion_files(self, candidate_text: str | None = None) -> tuple[Path, Path]:
        before = self.root / "expansion-before.md"
        candidate = self.root / "expansion-candidate.md"
        before.write_text(self.expansion_dfs(new_claim=""), encoding="utf-8")
        candidate.write_text(
            self.expansion_dfs() if candidate_text is None else candidate_text,
            encoding="utf-8",
        )
        return before, candidate

    def finding_state(
        self,
        name: str,
        *,
        kind: str = "blocker",
        claim: str = "R-001",
        report: bool = True,
    ) -> Path:
        state = self.root / f"finding-{name}.sqlite"
        with deadline.DeadlineHarness(state) as harness:
            harness.start_task("project", "worker-task", claim, 10, now=0)
            if report:
                harness.report_worker_finding(
                    "project",
                    "worker-task",
                    kind,
                    "The production owner has an unmodelled competing writer.",
                    now=1,
                )
        return state

    def run_expand_cli(
        self,
        state: Path,
        *,
        lineage: str = "project",
        task: str = "worker-task",
        candidate_text: str | None = None,
    ) -> tuple[int, str]:
        before, candidate = self.expansion_files(candidate_text)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = guard.main(
                [
                    "expand-dfs",
                    "--before",
                    str(before),
                    "--candidate",
                    str(candidate),
                    "--state",
                    str(state),
                    "--lineage",
                    lineage,
                    "--task",
                    task,
                    "--ledger-candidate",
                    str(self.empty_ledger),
                ]
            )
        return result, stdout.getvalue() + stderr.getvalue()

    def test_expand_dfs_cli_accepts_exact_blocker_and_unexpected_findings(self) -> None:
        for kind in ("blocker", "unexpected"):
            with self.subTest(kind=kind):
                state = self.finding_state(kind, kind=kind)
                result, output = self.run_expand_cli(state)
                self.assertEqual(result, 0, output)
                self.assertIn(f"ok: {kind} finding expanded R-001", output)
                self.assertIn("added R-003", output)

    def test_expand_dfs_cli_rejects_missing_or_mismatched_finding(self) -> None:
        missing = self.finding_state("missing", report=False)
        result, output = self.run_expand_cli(missing)
        self.assertEqual(result, 1)
        self.assertIn("Missing stored worker finding", output)

        stored = self.finding_state("stored")
        result, output = self.run_expand_cli(stored, task="other-task")
        self.assertEqual(result, 1)
        self.assertIn("Missing stored worker finding", output)

        wrong_claim = self.finding_state("wrong-claim", claim="R-999")
        result, output = self.run_expand_cli(wrong_claim)
        self.assertEqual(result, 1)
        self.assertIn("not exactly one still-red DFS claim", output)

    def test_expand_dfs_preserves_protected_sections_exactly(self) -> None:
        before, candidate = self.expansion_files(
            self.expansion_dfs().replace(
                "The existing behavior remains the contract.",
                "The behavior is now broader.",
            )
        )
        with self.assertRaisesRegex(guard.GuardError, "Functional contract"):
            guard.validate_dfs_expansion(before, candidate, "R-001")

        before, candidate = self.expansion_files(
            self.expansion_dfs().replace(
                "Use the project's existing names.",
                "Introduce a new project vocabulary.",
            )
        )
        with self.assertRaisesRegex(guard.GuardError, "Project language"):
            guard.validate_dfs_expansion(before, candidate, "R-001")

    def test_expand_dfs_cannot_rewrite_or_delete_nonprotected_prose(self) -> None:
        baseline = self.expansion_dfs()
        candidates = (
            baseline.replace(
                "The coordinator may add source-grounded mechanics here.",
                "A different owner now controls the transition.",
            ),
            baseline.replace(
                "The coordinator may add source-grounded mechanics here.\n", ""
            ),
        )
        for candidate_text in candidates:
            with self.subTest(candidate=candidate_text):
                before, candidate = self.expansion_files(candidate_text)
                with self.assertRaisesRegex(
                    guard.GuardError, "cannot delete or rewrite"
                ):
                    guard.validate_dfs_expansion(before, candidate, "R-001")

    def test_expand_dfs_requires_a_unique_new_unchecked_red_claim(self) -> None:
        before, candidate = self.expansion_files(self.expansion_dfs(new_claim=""))
        with self.assertRaisesRegex(guard.GuardError, "at least one new red claim"):
            guard.validate_dfs_expansion(before, candidate, "R-001")

        before, candidate = self.expansion_files(
            self.expansion_dfs(new_claim="- [x] R-003 — Prematurely accepted\n")
        )
        with self.assertRaisesRegex(guard.GuardError, "unchecked and red"):
            guard.validate_dfs_expansion(before, candidate, "R-001")

        before, candidate = self.expansion_files(
            self.expansion_dfs(new_claim="- [ ] 🔴 R-001 — Duplicate id\n")
        )
        with self.assertRaisesRegex(guard.GuardError, "duplicate stable claim id"):
            guard.validate_dfs_expansion(before, candidate, "R-001")

    def test_expand_dfs_rejects_existing_claim_deletion_rewrite_closure_or_reorder(self) -> None:
        baseline = self.expansion_dfs()
        mutations = {
            "delete": baseline.replace("- [ ] 🔴 R-002 — Existing next work\n", ""),
            "rewrite": baseline.replace(
                "R-002 — Existing next work", "R-002 — Renamed work"
            ),
            "close": baseline.replace(
                "- [ ] 🔴 R-001 — Worker found a blocker",
                "- [x] R-001 — Worker found a blocker",
            ),
            "reopen accepted frontier": baseline.replace(
                "- [x] R-000 — Accepted frontier",
                "- [ ] 🔴 R-000 — Accepted frontier",
            ),
            "reorder": baseline.replace(
                "- [ ] 🔴 R-001 — Worker found a blocker\n"
                "- [ ] 🔴 R-002 — Existing next work\n",
                "- [ ] 🔴 R-002 — Existing next work\n"
                "- [ ] 🔴 R-001 — Worker found a blocker\n",
            ),
        }
        for name, candidate_text in mutations.items():
            with self.subTest(name=name):
                before, candidate = self.expansion_files(candidate_text)
                with self.assertRaises(guard.GuardError):
                    guard.validate_dfs_expansion(before, candidate, "R-001")

    def test_expand_dfs_never_authorizes_completed_task_or_claim(self) -> None:
        state = self.finding_state("completed")
        connection = sqlite3.connect(state)
        try:
            connection.execute(
                """
                UPDATE tasks
                SET completed_at = 2, completion_evidence = 'tampered completion'
                WHERE lineage_id = 'project' AND task_id = 'worker-task'
                """
            )
            connection.commit()
        finally:
            connection.close()
        result, output = self.run_expand_cli(state)
        self.assertEqual(result, 1)
        self.assertIn("completed task cannot authorize DFS expansion", output)

        closed = self.expansion_dfs().replace(
            "- [ ] 🔴 R-001 — Worker found a blocker",
            "- [x] R-001 — Worker found a blocker",
        )
        state = self.finding_state("claim-closure")
        result, output = self.run_expand_cli(state, candidate_text=closed)
        self.assertEqual(result, 1)
        self.assertIn("cannot delete or rewrite", output)

    def random_review_state(self, lane_index: int) -> tuple[Path, int]:
        state = self.root / f"random-{lane_index}.sqlite"
        with patch.object(
            deadline.secrets, "randbelow", side_effect=[0, lane_index]
        ), deadline.DeadlineHarness(state) as harness:
            for number in range(1, 11):
                task = f"terminal-{number}"
                harness.start_task("project", task, f"R-{number:03d}", 10, now=0)
                harness.complete_task("project", task, "green", now=1)
            cycle = harness.list_tasks(now=2)["random_mutation"]["cycle_number"]
        return state, cycle

    def run_random_review_cli(
        self,
        state: Path,
        cycle: int,
        *,
        ledger: Path | None = None,
    ) -> tuple[int, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = guard.main(
                [
                    "random-review",
                    "--baseline",
                    str(self.baseline),
                    "--candidate",
                    str(self.candidate),
                    "--state",
                    str(state),
                    "--lineage",
                    "project",
                    "--cycle",
                    str(cycle),
                    "--ledger-candidate",
                    str(self.empty_ledger if ledger is None else ledger),
                ]
            )
        return result, stdout.getvalue() + stderr.getvalue()

    def test_random_review_applies_exactly_the_selected_guideline_lane(self) -> None:
        state, cycle = self.random_review_state(0)
        self.mutate_task()
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 0, output)
        self.assertIn(guard.TASK_GUIDELINES, output)

        self.setUp_candidate_again()
        state, cycle = self.random_review_state(1)
        self.mutate_orchestrator()
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 0, output)
        self.assertIn(guard.ORCHESTRATOR_GUIDELINES, output)

    def setUp_candidate_again(self) -> None:
        self.write_guidelines(self.candidate, TASK_GUIDANCE, ORCHESTRATOR_GUIDANCE)
        (self.candidate / guard.DFS_FILE).write_text(
            self.expansion_dfs(new_claim=""), encoding="utf-8"
        )

    def test_random_review_rejects_wrong_lane_and_whitespace_only_change(self) -> None:
        state, cycle = self.random_review_state(1)
        self.mutate_task()
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 1)
        self.assertIn("selected orchestrator-guidelines.md", output)

        self.setUp_candidate_again()
        state, cycle = self.random_review_state(0)
        path = self.candidate / guard.TASK_GUIDELINES
        path.write_text(
            TASK_GUIDANCE.replace("Read the exact", "Read  the exact"),
            encoding="utf-8",
        )
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 1)
        self.assertIn("whitespace-only", output)

    def test_random_dfs_review_accepts_safe_expansion_or_exact_guarded_noop(self) -> None:
        state, cycle = self.random_review_state(2)
        (self.candidate / guard.DFS_FILE).write_text(
            self.expansion_dfs(), encoding="utf-8"
        )
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 0, output)
        self.assertIn("changed DFS.md", output)

        self.setUp_candidate_again()
        state, cycle = self.random_review_state(2)
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 0, output)
        self.assertIn("guarded DFS no-op", output)

    def test_random_dfs_review_preserves_frozen_contract(self) -> None:
        state, cycle = self.random_review_state(2)
        candidate = self.expansion_dfs().replace(
            "The existing behavior remains the contract.",
            "The behavior is now broader.",
        )
        (self.candidate / guard.DFS_FILE).write_text(candidate, encoding="utf-8")
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 1)
        self.assertIn("Functional contract", output)

    def test_successful_random_mutation_requires_empty_scratch_ledger(self) -> None:
        state, cycle = self.random_review_state(0)
        self.mutate_task()
        uncleared = self.root / "uncleared.md"
        uncleared.write_text("# pending suggestion\n", encoding="utf-8")
        result, output = self.run_random_review_cli(
            state, cycle, ledger=uncleared
        )
        self.assertEqual(result, 1)
        self.assertIn("reset mutation-suggestions.md", output)

    def test_random_review_requires_due_unresolved_stored_cycle(self) -> None:
        state = self.root / "not-due.sqlite"
        with patch.object(
            deadline.secrets, "randbelow", side_effect=[0, 0]
        ), deadline.DeadlineHarness(state) as harness:
            harness.start_task("project", "running", "R-001", 100, now=0)
            cycle = harness.list_tasks(now=1)["random_mutation"]["cycle_number"]
        self.mutate_task()
        result, output = self.run_random_review_cli(state, cycle)
        self.assertEqual(result, 1)
        self.assertIn("not due", output)

    def test_documented_random_commands_use_the_tested_cli_surface(self) -> None:
        command_lines = [
            line
            for line in SKILL_TEXT.splitlines()
            if "mutation_guard.py random-review" in line
            or "deadline_harness.py resolve-random-mutation" in line
        ]
        self.assertEqual(len(command_lines), 2)
        self.assertNotIn("--disposition", "\n".join(command_lines))
        self.assertIn("--ledger-candidate", command_lines[0])
        self.assertIn("--evidence", command_lines[1])

    def test_documented_integrity_route_requires_exact_diagnosis(self) -> None:
        self.assertIn("`--kind integrity_breach`", SKILL_TEXT)
        self.assertIn("using `--kind integrity_breach`", SKILL_TEXT)


if __name__ == "__main__":
    unittest.main()
