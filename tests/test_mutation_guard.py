from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import deadline_harness as harness
from scripts import mutation_guard as guard


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "contracts" / "mutation-policy.json").read_text(encoding="utf-8"))


def specification(root: Path) -> Path:
    path = root / "FS.md"
    if not path.exists():
        path.write_text("# Frozen functional specification\n", encoding="utf-8")
    return path


def worker_evidence(
    *, permit_event_hash: str | None = None, receipt: Path | None = None, artifact: Path | None = None
) -> dict:
    evidence = {
        "kind": "worker_failure",
        "slot_id": "T",
        "worker_profile": "terra-high",
        "worker_identity": "worker-1/terra-high",
        "deadline_id": "lineage/run/window/T01",
        "status": "deadline_missed",
        "work_performed": True,
        "test_state": "failed",
        "test_completed": True,
        "test_result": "failed",
        "receipt_sha256": "a" * 64,
        "artifact_hashes": {"artifacts/T01.json": "b" * 64},
    }
    if permit_event_hash is not None and receipt is not None and artifact is not None:
        evidence.update(
            {
                "permit_event_hash": permit_event_hash,
                "receipt_path": str(receipt),
                "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                "artifact_hashes": {
                    str(artifact): harness.digest_bytes(artifact.read_bytes())
                },
            }
        )
    return evidence


def coordinator_evidence() -> dict:
    event_hashes = [f"{number + 1:064x}" for number in range(3)]
    return {
        "kind": "coordinator_review",
        "window_failures": [
            {
                "deadline_id": (
                    "lineage/run/window/T01" if number == 0 else f"lineage/run-{number}/window"
                ),
                "deadline_missed": True,
                "event_hash": event_hashes[number],
            }
            for number in range(3)
        ],
        "fresh_review": {
            "reviewer_identity": "fresh-reviewer/sol-xhigh",
            "reviewer_profile": "sol-xhigh",
            "fresh": True,
            "review_event_hash": "f" * 64,
            "reviewed_parent_skill_hash": "c" * 64,
            "reviewed_failure_event_hashes": event_hashes,
        },
    }


def proof_policy_evidence() -> dict:
    evidence = coordinator_evidence()
    evidence["proof_plan_failures"] = [
        {
            "deadline_id": failure["deadline_id"],
            "failure_owner": "proof_plan",
            "causal_fingerprint": f"{number + 11:064x}",
            "assessment_event_hash": f"{number + 21:064x}",
        }
        for number, failure in enumerate(evidence["window_failures"])
    ]
    return evidence


def intent(*changed_keys: str) -> dict:
    return {
        "kind": "efficiency_mutation",
        "target_failure_id": "lineage/run/window/T01",
        "observed_bottleneck": "The worker repeated an unchanged route",
        "changed_policy_keys": sorted(changed_keys),
        "expected_reduction": "repeated_work",
        "quality_contract_unchanged": True,
    }


def benchmark(*, misses: int, elapsed: int, tokens: int, size: int, quality: bool = True) -> dict:
    return {
        "provenance": {
            "producer": "de67-deadline-harness/0.1.0",
            "lineage_id": "L",
            "run_id": "R",
            "window_id": "W",
            "definition_hash": "1" * 64,
            "fs_hash": "5" * 64,
            "comparison_epoch": "2" * 64,
            "skill_hash": "3" * 64,
            "event_chain_hash": "4" * 64,
        },
        "quality": {
            "worker_executed": quality,
            "test_completed": quality,
            "acceptance_passed": quality,
            "evidence_valid": quality,
        },
        "deadline": {"misses": misses, "elapsed_seconds": elapsed},
        "usage": {"tokens": tokens},
        "skill": {"bytes": size},
        "target_failure_resolved": quality,
        "new_failure_ids": [],
    }


def product_frontier() -> dict:
    return {
        "repository": "product/example",
        "commit": "a" * 40,
        "tree": "b" * 40,
    }


def run_git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def benchmark_binding(skill_root: Path) -> dict:
    identity = guard.git_identity(skill_root)
    return {
        "git": {
            "worktree": identity["worktree"],
            "branch": identity["branch"],
            "commit": identity["commit"],
            "tree": identity["tree"],
        },
        "product_frontier": product_frontier(),
        "mutation": {
            "target_failure_id": "lineage/run/window/T01",
            "changed_policy_keys": ["policy/orchestration.json.ready_order"],
            "expected_reduction": "repeated_work",
        },
    }


class MutationGuardTests(unittest.TestCase):
    def test_three_adjacent_distinct_proof_plan_misses_allow_p2(self) -> None:
        self.set_policy(
            "policy/proof.json", "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        result = guard.validate_mutation(
            base=self.base, candidate=self.candidate, scope="coordinator",
            evidence=proof_policy_evidence(),
            intent=intent("policy/proof.json.conformance_route"), policy=POLICY,
        )
        self.assertEqual(result["changed_paths"], ["policy/proof.json"])

    def test_successful_windows_do_not_reset_cumulative_p2_failures(self) -> None:
        self.set_policy(
            "policy/proof.json", "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        evidence = proof_policy_evidence()
        evidence["successful_window_ids"] = ["lineage/success-1", "lineage/success-2"]
        result = guard.validate_mutation(
            base=self.base, candidate=self.candidate, scope="coordinator",
            evidence=evidence, intent=intent("policy/proof.json.conformance_route"),
            policy=POLICY,
        )
        self.assertEqual(result["changed_paths"], ["policy/proof.json"])

    def test_duplicate_proof_fingerprints_do_not_qualify_p2(self) -> None:
        self.set_policy(
            "policy/proof.json", "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        evidence = proof_policy_evidence()
        evidence["proof_plan_failures"][2]["causal_fingerprint"] = (
            evidence["proof_plan_failures"][1]["causal_fingerprint"]
        )
        with self.assertRaisesRegex(guard.GuardError, "Duplicate"):
            guard.validate_mutation(
                base=self.base, candidate=self.candidate, scope="coordinator",
                evidence=evidence, intent=intent("policy/proof.json.conformance_route"),
                policy=POLICY,
            )

    def test_product_or_harness_failures_cannot_qualify_or_be_relabelled(self) -> None:
        self.set_policy(
            "policy/proof.json", "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        for owner in ("product", "harness"):
            evidence = proof_policy_evidence()
            evidence["proof_plan_failures"][1]["failure_owner"] = owner
            with self.assertRaisesRegex(guard.GuardError, "Product and harness"):
                guard.validate_mutation(
                    base=self.base, candidate=self.candidate, scope="coordinator",
                    evidence=evidence, intent=intent("policy/proof.json.conformance_route"),
                    policy=POLICY,
                )

    def test_worker_scope_remains_p1_only(self) -> None:
        self.set_policy(
            "policy/proof.json", "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base, candidate=self.candidate, scope="worker",
                evidence=worker_evidence(), intent=intent("policy/proof.json.conformance_route"),
                policy=POLICY,
            )

    def test_same_core_and_frontier_compare_across_different_proof_plans(self) -> None:
        baseline = benchmark(misses=1, elapsed=120, tokens=1000, size=5000)
        candidate = benchmark(misses=0, elapsed=90, tokens=900, size=5100)
        frontier = product_frontier()
        for result, plan_hash in ((baseline, "6" * 64), (candidate, "7" * 64)):
            result["provenance"]["semantic_condition_manifest_hash"] = "8" * 64
            result["provenance"]["proof_plan_hash"] = plan_hash
            result["provenance"]["product_frontier"] = frontier
        compared = guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])
        self.assertTrue(compared["promotable"])

        changed_frontier = json.loads(json.dumps(candidate))
        changed_frontier["provenance"]["product_frontier"]["commit"] = "c" * 40
        with self.assertRaisesRegex(guard.GuardError, "product frontier"):
            guard.compare_benchmark(baseline, changed_frontier, POLICY["quality_predicates"])

        changed_core = json.loads(json.dumps(candidate))
        changed_core["provenance"]["fs_hash"] = "9" * 64
        with self.assertRaisesRegex(guard.GuardError, "fs_hash"):
            guard.compare_benchmark(baseline, changed_core, POLICY["quality_predicates"])

    def test_p2_validated_comparison_requires_and_accepts_proof_window_provenance(self) -> None:
        _, candidate, baseline, result, validation = self.p2_validated_benchmarks()
        self.assertEqual(
            validation["mutation"]["parent_conformance_route"],
            "minimal_authoritative_conformance",
        )
        self.assertEqual(
            validation["mutation"]["candidate_conformance_route"],
            "authoritative_owner_then_live_conformance",
        )
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "promotable")

    def test_p2_validated_comparison_rejects_inert_or_mismatched_route(self) -> None:
        _, candidate, baseline, result, validation = self.p2_validated_benchmarks()
        result["provenance"]["conformance_route"] = (
            "minimal_authoritative_conformance"
        )
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "rejected")
        self.assertIn("did not execute the conformance route", comparison["error"])

    def test_p2_validated_comparison_rejects_generic_nonproof_benchmark(self) -> None:
        _, candidate, baseline, result, validation = self.p2_validated_benchmarks(
            include_proof_provenance=False
        )
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "rejected")
        self.assertIn("P2 benchmark requires proof-window provenance", comparison["error"])

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary.name)
        self.fs_root = specification(temporary_root)
        self.base = temporary_root / "base"
        self.candidate = temporary_root / "candidate"
        ignore = shutil.ignore_patterns(".git", ".skill-init", "__pycache__", ".pytest_cache")
        shutil.copytree(ROOT, self.base, ignore=ignore)
        shutil.copytree(ROOT, self.candidate, ignore=ignore)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def set_policy(self, relative: str, key: str, value: object) -> None:
        path = self.candidate / relative
        policy = json.loads(path.read_text(encoding="utf-8"))
        policy[key] = value
        path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")

    def git_pair(
        self,
        relative: str = "policy/orchestration.json",
        key: str = "ready_order",
        value: object = "fs_order",
    ) -> tuple[Path, Path]:
        admin = Path(self.temporary.name) / "git-admin"
        parent = Path(self.temporary.name) / "git-parent"
        candidate = Path(self.temporary.name) / "git-candidate"
        ignore = shutil.ignore_patterns(".git", ".skill-init", "__pycache__", ".pytest_cache")
        shutil.copytree(ROOT, admin, ignore=ignore)
        run_git(admin, "init", "-b", "main")
        run_git(admin, "config", "user.name", "Mutation Guard Test")
        run_git(admin, "config", "user.email", "mutation-guard@example.invalid")
        run_git(admin, "add", ".")
        run_git(admin, "commit", "-m", "accepted parent")
        run_git(admin, "switch", "--detach")
        run_git(admin, "worktree", "add", str(parent), "main")
        run_git(parent, "worktree", "add", "-b", "candidate", str(candidate), "main")
        policy_path = candidate / relative
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy[key] = value
        policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        run_git(candidate, "add", relative)
        run_git(candidate, "commit", "-m", "candidate mutation")
        return parent, candidate

    def secure_benchmarks(self, parent: Path, candidate: Path) -> tuple[dict, dict]:
        baseline = benchmark(misses=1, elapsed=120, tokens=1000, size=5000)
        result = benchmark(misses=0, elapsed=90, tokens=900, size=5100)
        for plan_number, (benchmark_result, skill_root) in enumerate(
            ((baseline, parent), (result, candidate)), start=6
        ):
            identity = guard.git_identity(skill_root)
            benchmark_result["provenance"]["skill_hash"] = identity["skill_hash"]
            benchmark_result["provenance"]["effective_plan_hash"] = (
                f"{plan_number:x}" * 64
            )
            benchmark_result["provenance"]["git"] = {
                "worktree": identity["worktree"],
                "branch": identity["branch"],
                "commit": identity["commit"],
                "tree": identity["tree"],
            }
            benchmark_result["provenance"]["product_frontier"] = product_frontier()
        result["mutation"] = {
            "target_failure_id": "lineage/run/window/T01",
            "changed_policy_keys": ["policy/orchestration.json.ready_order"],
            "expected_reduction": "repeated_work",
            "observed_reductions": ["repeated_work"],
        }
        return baseline, result

    def p2_validated_benchmarks(
        self, *, include_proof_provenance: bool = True
    ) -> tuple[Path, Path, dict, dict, dict]:
        parent, candidate = self.git_pair(
            "policy/proof.json",
            "conformance_route",
            "authoritative_owner_then_live_conformance",
        )
        baseline, result = self.secure_benchmarks(parent, candidate)
        if include_proof_provenance:
            for benchmark_result, plan_hash, route in (
                (baseline, "6" * 64, "minimal_authoritative_conformance"),
                (result, "7" * 64, "authoritative_owner_then_live_conformance"),
            ):
                benchmark_result["provenance"]["semantic_condition_manifest_hash"] = "8" * 64
                benchmark_result["provenance"]["proof_plan_hash"] = plan_hash
                benchmark_result["provenance"]["conformance_route"] = route
        p2_intent = intent("policy/proof.json.conformance_route")
        result["mutation"] = {
            "target_failure_id": p2_intent["target_failure_id"],
            "changed_policy_keys": p2_intent["changed_policy_keys"],
            "expected_reduction": p2_intent["expected_reduction"],
            "observed_reductions": [p2_intent["expected_reduction"]],
        }
        evidence = proof_policy_evidence()
        evidence["fresh_review"]["reviewed_parent_skill_hash"] = guard.git_identity(parent)[
            "skill_hash"
        ]
        validation = guard.create_validation_receipt(
            base=parent,
            candidate=candidate,
            accepted_ref="main",
            scope="coordinator",
            evidence=evidence,
            intent=p2_intent,
            policy=POLICY,
            product_frontier=product_frontier(),
            baseline_benchmark=baseline,
        )
        return parent, candidate, baseline, result, validation

    def validation_receipt(self, parent: Path, candidate: Path, baseline: dict) -> dict:
        return guard.create_validation_receipt(
            base=parent,
            candidate=candidate,
            accepted_ref="main",
            scope="worker",
            evidence=worker_evidence(),
            intent=intent("policy/orchestration.json.ready_order"),
            policy=POLICY,
            product_frontier=product_frontier(),
            baseline_benchmark=baseline,
        )

    def seal_success(
        self,
        *,
        skill_root: Path,
        install_root: Path,
        elapsed_seconds: int,
        tokens: int,
        benchmark_binding: dict | None = None,
    ) -> dict:
        started = datetime(2026, 8, 9, tzinfo=timezone.utc)
        install_root.mkdir(parents=True, exist_ok=True)
        receipt = install_root / "receipt.json"
        artifact = install_root / "artifact.json"
        receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
        artifact.write_text('{"proof":"production-route"}\n', encoding="utf-8")
        ledger = {
            "tasks": [
                {
                    "id": "T",
                    "claim_id": "claim-T",
                    "intended_task": "work",
                    "owner": "unit-test fixture",
                    "preconditions": ["fixture files exist"],
                    "authoritative_route": "sealed harness event",
                    "pass_test": "test",
                    "evidence_requirements": {"artifact": "production-route proof"},
                    "worker_profile": "terra-high",
                    "estimate_seconds": 20,
                    "estimate_provenance": "fixed unit-test scenario",
                    "depends_on": [],
                }
            ]
        }
        if benchmark_binding is not None:
            ledger["benchmark_binding"] = benchmark_binding
        db = install_root / "state.sqlite3"
        harness.open_window(
            db_path=db,
            install_root=install_root,
            source_script=skill_root / "scripts" / "deadline_harness.py",
            lineage_id="L",
            run_id="R",
            window_id="W",
            fs_root=self.fs_root,
            ledger=ledger,
            now=started,
            start_watcher=False,
        )
        permit = harness.permit_dispatch(
            db_path=db,
            install_root=install_root,
            lineage_id="L",
            run_id="R",
            window_id="W",
            slot_id="T",
            worker_profile="terra-high",
            now=started,
        )
        completed_payload = {"tokens": tokens}
        if benchmark_binding is not None:
            completed_payload["mutation"] = {
                **benchmark_binding["mutation"],
                "observed_reductions": [
                    benchmark_binding["mutation"]["expected_reduction"]
                ],
            }
        harness.record_event(
            db_path=db,
            install_root=install_root,
            lineage_id="L",
            run_id="R",
            window_id="W",
            kind="task_accepted",
            payload={
                "slot_id": "T",
                "worker_profile": "terra-high",
                "permit_event_hash": permit["permit_event_hash"],
                "worker_identity": "worker/terra-high",
                "test_completed": True,
                "test_result": "passed",
                "receipt_path": str(receipt),
                "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                "artifact_hashes": {
                    str(artifact): harness.digest_bytes(artifact.read_bytes())
                },
            },
            now=started.replace(second=elapsed_seconds - 1),
        )
        harness.record_event(
            db_path=db,
            install_root=install_root,
            lineage_id="L",
            run_id="R",
            window_id="W",
            kind="completed",
            payload=completed_payload,
            now=started.replace(second=elapsed_seconds),
        )
        return guard.benchmark_from_harness(
            install_root=install_root,
            lineage_id="L",
            run_id="R",
            window_id="W",
            expected_skill_root=skill_root,
        )

    def test_worker_failure_can_change_only_orchestration(self) -> None:
        self.set_policy("policy/orchestration.json", "ready_order", "fs_order")
        result = guard.validate_mutation(
            base=self.base,
            candidate=self.candidate,
            scope="worker",
            evidence=worker_evidence(),
            intent=intent("policy/orchestration.json.ready_order"),
            policy=POLICY,
        )
        self.assertEqual(result["changed_paths"], ["policy/orchestration.json"])

    def test_worker_failure_cannot_change_execution(self) -> None:
        self.set_policy("policy/execution.json", "live_route", "final_integration_only")
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="worker",
                evidence=worker_evidence(),
                intent=intent("policy/execution.json.live_route"),
                policy=POLICY,
            )

    def test_three_windows_allow_broad_policy_but_not_kernel(self) -> None:
        self.set_policy("policy/orchestration.json", "ready_order", "fs_order")
        self.set_policy("policy/execution.json", "live_route", "final_integration_only")
        result = guard.validate_mutation(
            base=self.base,
            candidate=self.candidate,
            scope="coordinator",
            evidence=coordinator_evidence(),
            intent=intent(
                "policy/execution.json.live_route",
                "policy/orchestration.json.ready_order",
            ),
            policy=POLICY,
        )
        self.assertEqual(
            result["changed_paths"],
            ["policy/execution.json", "policy/orchestration.json"],
        )
        kernel = self.candidate / "references" / "kernel.md"
        kernel.write_text(kernel.read_text(encoding="utf-8") + "\nmutation\n", encoding="utf-8")
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="coordinator",
                evidence=coordinator_evidence(),
                intent=intent(
                    "policy/execution.json.live_route",
                    "policy/orchestration.json.ready_order",
                ),
                policy=POLICY,
            )

    def test_coordinator_scope_requires_three_distinct_windows(self) -> None:
        self.set_policy("policy/execution.json", "live_route", "final_integration_only")
        evidence = coordinator_evidence()
        evidence["window_failures"][2] = evidence["window_failures"][1]
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="coordinator",
                evidence=evidence,
                intent=intent("policy/execution.json.live_route"),
                policy=POLICY,
            )

    def test_mutable_policy_rejects_unknown_prose_or_values(self) -> None:
        self.set_policy("policy/orchestration.json", "coordinator_may_test", True)
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="worker",
                evidence=worker_evidence(),
                intent=intent("policy/orchestration.json.coordinator_may_test"),
                policy=POLICY,
            )

        shutil.rmtree(self.candidate)
        shutil.copytree(self.base, self.candidate)
        self.set_policy("policy/orchestration.json", "ready_order", "ignore_tests")
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="worker",
                evidence=worker_evidence(),
                intent=intent("policy/orchestration.json.ready_order"),
                policy=POLICY,
            )

    def test_candidate_must_keep_quality_and_improve_stored_baseline(self) -> None:
        baseline = benchmark(misses=1, elapsed=120, tokens=1000, size=5000)
        candidate = benchmark(misses=0, elapsed=90, tokens=900, size=5100)
        result = guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])
        self.assertTrue(result["promotable"])

        bad_quality = benchmark(misses=0, elapsed=10, tokens=10, size=10, quality=False)
        with self.assertRaises(guard.GuardError):
            guard.compare_benchmark(baseline, bad_quality, POLICY["quality_predicates"])

        slower = benchmark(misses=1, elapsed=121, tokens=800, size=4000)
        with self.assertRaises(guard.GuardError):
            guard.compare_benchmark(baseline, slower, POLICY["quality_predicates"])

        different_fs = json.loads(json.dumps(candidate))
        different_fs["provenance"]["fs_hash"] = "6" * 64
        with self.assertRaises(guard.GuardError):
            guard.compare_benchmark(baseline, different_fs, POLICY["quality_predicates"])

    def test_comparison_derives_both_receipts_from_sealed_harness_state(self) -> None:
        baseline_install = Path(self.temporary.name) / "baseline-state"
        candidate_install = Path(self.temporary.name) / "candidate-state"
        baseline = self.seal_success(
            skill_root=self.base,
            install_root=baseline_install,
            elapsed_seconds=10,
            tokens=100,
        )
        self.set_policy("policy/orchestration.json", "ready_order", "fs_order")
        candidate = self.seal_success(
            skill_root=self.candidate,
            install_root=candidate_install,
            elapsed_seconds=8,
            tokens=90,
        )
        result = guard.compare_benchmark(
            baseline, candidate, POLICY["quality_predicates"]
        )
        self.assertTrue(result["promotable"])
        self.assertEqual(result["baseline_fitness"][:2], (0.0, 10.0))
        self.assertEqual(result["candidate_fitness"][:2], (0.0, 8.0))

    def test_exact_git_benchmarks_share_definition_and_compare_end_to_end(self) -> None:
        parent, candidate = self.git_pair()
        baseline_install = Path(self.temporary.name) / "git-baseline-state"
        candidate_install = Path(self.temporary.name) / "git-candidate-state"
        baseline = self.seal_success(
            skill_root=parent,
            install_root=baseline_install,
            elapsed_seconds=10,
            tokens=100,
            benchmark_binding=benchmark_binding(parent),
        )
        result = self.seal_success(
            skill_root=candidate,
            install_root=candidate_install,
            elapsed_seconds=8,
            tokens=90,
            benchmark_binding=benchmark_binding(candidate),
        )
        self.assertEqual(
            baseline["provenance"]["definition_hash"],
            result["provenance"]["definition_hash"],
        )
        self.assertNotEqual(
            baseline["provenance"]["effective_plan_hash"],
            result["provenance"]["effective_plan_hash"],
        )
        validation = self.validation_receipt(parent, candidate, baseline)
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "promotable")

        wrong_plan = json.loads(json.dumps(baseline))
        wrong_plan["provenance"]["effective_plan_hash"] = "0" * 64
        rejected = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=wrong_plan,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(rejected["decision"], "rejected")
        self.assertIn("exact validated parent benchmark", rejected["error"])

    def test_equal_operations_cannot_win_by_shortening_skill_only(self) -> None:
        baseline = benchmark(misses=0, elapsed=100, tokens=1000, size=5000)
        candidate = benchmark(misses=0, elapsed=100, tokens=1000, size=4900)
        with self.assertRaises(guard.GuardError):
            guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])

    def test_unavailable_usage_is_omitted_symmetrically(self) -> None:
        baseline = benchmark(misses=0, elapsed=100, tokens=1000, size=5000)
        candidate = benchmark(misses=0, elapsed=99, tokens=900, size=5100)
        baseline["usage"]["tokens"] = None
        candidate["usage"]["tokens"] = None
        result = guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])
        self.assertEqual(
            result["dimensions"],
            ["deadline_misses", "elapsed_seconds", "skill_bytes"],
        )

        candidate["usage"]["tokens"] = 900
        with self.assertRaises(guard.GuardError):
            guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])

    def test_gitless_candidate_cannot_receive_validation_receipt(self) -> None:
        baseline = benchmark(misses=1, elapsed=120, tokens=1000, size=5000)
        with self.assertRaises(guard.GuardError):
            self.validation_receipt(self.base, self.candidate, baseline)

    def test_mutation_benchmarks_require_exact_git_and_product_frontier(self) -> None:
        parent, candidate = self.git_pair()
        baseline, result = self.secure_benchmarks(parent, candidate)

        for missing, message in (
            ("git", "Git provenance"),
            ("product_frontier", "product frontier provenance"),
            ("effective_plan_hash", "effective_plan_hash provenance"),
        ):
            incomplete = json.loads(json.dumps(baseline))
            incomplete["provenance"].pop(missing)
            with self.assertRaisesRegex(guard.GuardError, message):
                self.validation_receipt(parent, candidate, incomplete)

        validation = self.validation_receipt(parent, candidate, baseline)
        for missing, message in (
            ("git", "Git provenance"),
            ("product_frontier", "product frontier provenance"),
            ("effective_plan_hash", "effective_plan_hash provenance"),
        ):
            incomplete = json.loads(json.dumps(result))
            incomplete["provenance"].pop(missing)
            comparison = guard.compare_validated_candidate(
                validation_receipt=validation,
                baseline=baseline,
                candidate=incomplete,
                candidate_root=candidate,
                predicates=POLICY["quality_predicates"],
            )
            self.assertEqual(comparison["decision"], "rejected")
            self.assertIn(message, comparison["error"])

        wrong_git = json.loads(json.dumps(result))
        wrong_git["provenance"]["git"]["commit"] = "0" * 40
        wrong_frontier = json.loads(json.dumps(result))
        wrong_frontier["provenance"]["product_frontier"]["commit"] = "0" * 40
        for wrong, message in (
            (wrong_git, "Git provenance differs"),
            (wrong_frontier, "product frontier differs"),
        ):
            comparison = guard.compare_validated_candidate(
                validation_receipt=validation,
                baseline=baseline,
                candidate=wrong,
                candidate_root=candidate,
                predicates=POLICY["quality_predicates"],
            )
            self.assertEqual(comparison["decision"], "rejected")
            self.assertIn(message, comparison["error"])

    def test_dirty_or_nonroot_candidate_path_is_rejected(self) -> None:
        parent, candidate = self.git_pair()
        baseline, _ = self.secure_benchmarks(parent, candidate)
        with self.assertRaisesRegex(guard.GuardError, "exact root"):
            self.validation_receipt(parent, candidate / "policy", baseline)
        (candidate / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(guard.GuardError, "clean"):
            self.validation_receipt(parent, candidate, baseline)

    def test_mutation_target_must_be_in_sealed_failure_evidence(self) -> None:
        self.set_policy("policy/orchestration.json", "ready_order", "fs_order")
        unrelated = intent("policy/orchestration.json.ready_order")
        unrelated["target_failure_id"] = "another/claim"
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="worker",
                evidence=worker_evidence(),
                intent=unrelated,
                policy=POLICY,
            )

    def test_coordinator_cannot_bypass_fresh_review(self) -> None:
        self.set_policy("policy/execution.json", "live_route", "final_integration_only")
        evidence = coordinator_evidence()
        evidence.pop("fresh_review")
        with self.assertRaises(guard.GuardError):
            guard.validate_mutation(
                base=self.base,
                candidate=self.candidate,
                scope="coordinator",
                evidence=evidence,
                intent=intent("policy/execution.json.live_route"),
                policy=POLICY,
            )

    def test_validate_candidate_a_then_compare_candidate_b_is_rejected(self) -> None:
        parent, candidate_a = self.git_pair()
        baseline, result_a = self.secure_benchmarks(parent, candidate_a)
        validation = self.validation_receipt(parent, candidate_a, baseline)
        candidate_b = Path(self.temporary.name) / "git-candidate-b"
        run_git(parent, "worktree", "add", "-b", "candidate-b", str(candidate_b), "main")
        policy_path = candidate_b / "policy" / "orchestration.json"
        policy_value = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_value["parallelism"] = "conservative_disjoint"
        policy_path.write_text(json.dumps(policy_value, indent=2) + "\n", encoding="utf-8")
        run_git(candidate_b, "add", "policy/orchestration.json")
        run_git(candidate_b, "commit", "-m", "different candidate")
        result_a["provenance"]["skill_hash"] = guard.digest_json(guard.file_map(candidate_b))
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result_a,
            candidate_root=candidate_b,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "rejected")
        self.assertIn("exact validated Git candidate", comparison["error"])
        tampered = json.loads(json.dumps(validation))
        tampered["candidate"]["commit"] = "0" * 40
        with self.assertRaisesRegex(guard.GuardError, "changed after"):
            guard.compare_validated_candidate(
                validation_receipt=tampered,
                baseline=baseline,
                candidate=result_a,
                candidate_root=candidate_a,
                predicates=POLICY["quality_predicates"],
            )

    def test_main_movement_makes_validated_candidate_stale(self) -> None:
        parent, candidate = self.git_pair()
        baseline, result = self.secure_benchmarks(parent, candidate)
        validation = self.validation_receipt(parent, candidate, baseline)
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "promotable")
        marker = parent / "accepted-frontier.txt"
        marker.write_text("advanced\n", encoding="utf-8")
        run_git(parent, "add", "accepted-frontier.txt")
        run_git(parent, "commit", "-m", "advance accepted main")
        with self.assertRaisesRegex(guard.GuardError, "stale"):
            guard.create_promotion_plan(
                validation_receipt=validation,
                comparison_receipt=comparison,
                accepted_root=parent,
                candidate_root=candidate,
            )

    def test_rejected_candidate_cannot_be_parent_of_next_candidate(self) -> None:
        parent, rejected = self.git_pair()
        baseline, result = self.secure_benchmarks(parent, rejected)
        validation = self.validation_receipt(parent, rejected, baseline)
        result["deadline"] = dict(baseline["deadline"])
        result["usage"] = dict(baseline["usage"])
        result["skill"]["bytes"] = baseline["skill"]["bytes"] - 1
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=rejected,
            predicates=POLICY["quality_predicates"],
        )
        self.assertEqual(comparison["decision"], "rejected")

        descendant = Path(self.temporary.name) / "rejected-descendant"
        run_git(parent, "worktree", "add", "-b", "descendant", str(descendant), "candidate")
        policy_path = descendant / "policy" / "orchestration.json"
        policy_value = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_value["parallelism"] = "conservative_disjoint"
        policy_path.write_text(json.dumps(policy_value, indent=2) + "\n", encoding="utf-8")
        run_git(descendant, "add", "policy/orchestration.json")
        run_git(descendant, "commit", "-m", "descendant of rejected candidate")
        descendant_baseline, _ = self.secure_benchmarks(parent, descendant)
        with self.assertRaisesRegex(guard.GuardError, "directly"):
            self.validation_receipt(parent, descendant, descendant_baseline)

    def test_non_fast_forward_candidate_has_no_promotion_plan(self) -> None:
        parent, candidate = self.git_pair()
        baseline, result = self.secure_benchmarks(parent, candidate)
        validation = self.validation_receipt(parent, candidate, baseline)
        comparison = guard.compare_validated_candidate(
            validation_receipt=validation,
            baseline=baseline,
            candidate=result,
            candidate_root=candidate,
            predicates=POLICY["quality_predicates"],
        )
        unrelated = Path(self.temporary.name) / "unrelated-candidate"
        run_git(parent, "worktree", "add", "--detach", str(unrelated), "main")
        run_git(unrelated, "switch", "--orphan", "unrelated")
        run_git(unrelated, "commit", "--allow-empty", "-m", "unrelated candidate")
        forged_validation = dict(validation)
        forged_validation["candidate"] = guard.git_identity(unrelated)
        forged_validation = guard.seal_receipt(forged_validation)
        forged_comparison = dict(comparison)
        forged_comparison["validation_receipt_hash"] = forged_validation["receipt_hash"]
        forged_comparison["candidate_commit"] = forged_validation["candidate"]["commit"]
        forged_comparison = guard.seal_receipt(forged_comparison)
        with self.assertRaisesRegex(guard.GuardError, "fast-forward"):
            guard.create_promotion_plan(
                validation_receipt=forged_validation,
                comparison_receipt=forged_comparison,
                accepted_root=parent,
                candidate_root=unrelated,
            )

    def test_worker_evidence_is_resolved_from_sealed_harness_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=ROOT / "scripts" / "deadline_harness.py",
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={
                    "tasks": [
                        {
                            "id": "T",
                            "claim_id": "claim-T",
                            "intended_task": "work",
                            "owner": "unit-test fixture",
                            "preconditions": ["fixture files exist"],
                            "authoritative_route": "sealed harness event",
                            "pass_test": "test",
                            "evidence_requirements": {"artifact": "failed test proof"},
                            "worker_profile": "terra-high",
                            "estimate_seconds": 10,
                            "estimate_provenance": "fixed unit-test scenario",
                            "depends_on": [],
                        }
                    ]
                },
                now=started,
                start_watcher=False,
            )
            receipt = root / "failure-receipt.json"
            artifact = root / "failure-artifact.json"
            receipt.write_text('{"status":"failed"}\n', encoding="utf-8")
            artifact.write_text('{"test":"failed"}\n', encoding="utf-8")
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started,
            )
            recorded = harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_failed",
                payload=worker_evidence(
                    permit_event_hash=permit["permit_event_hash"],
                    receipt=receipt,
                    artifact=artifact,
                ),
                now=started,
            )
            event_hash = recorded["event_hash"]
            evidence = guard.evidence_from_harness(
                db_path=db,
                lineage_id="L",
                run_id="R",
                window_id="W",
                scope="worker",
                event_hash=event_hash,
                policy=POLICY,
            )
            self.assertEqual(evidence["worker_identity"], "worker-1/terra-high")

    def test_three_sealed_misses_without_fresh_review_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            ledger = {
                "tasks": [
                    {
                        "id": "T",
                        "claim_id": "claim-T",
                        "intended_task": "work",
                        "owner": "unit-test fixture",
                        "preconditions": ["fixture files exist"],
                        "authoritative_route": "sealed harness event",
                        "pass_test": "test",
                        "evidence_requirements": {"artifact": "deadline proof"},
                        "worker_profile": "terra-high",
                        "estimate_seconds": 1,
                        "estimate_provenance": "fixed unit-test scenario",
                        "depends_on": [],
                    }
                ]
            }
            for number in range(3):
                run_id = f"R{number}"
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=ROOT / "scripts" / "deadline_harness.py",
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    fs_root=specification(root),
                    ledger=ledger,
                    now=started,
                    start_watcher=False,
                )
                connection = harness.connect(db)
                harness.expire_window(
                    connection=connection,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    now=started.replace(second=2),
                )
                connection.close()
            with self.assertRaisesRegex(guard.GuardError, "fresh|review"):
                guard.evidence_from_harness(
                    db_path=db,
                    lineage_id="L",
                    run_id="R2",
                    window_id="W",
                    scope="coordinator",
                    event_hash=None,
                    policy=POLICY,
                )
            connection = harness.connect(db)
            state = harness.lineage_review_state(connection, "L")
            parent_skill_hash = harness.get_window(connection, "L", "R2", "W")["skill_hash"]
            connection.close()
            review_receipt = root / "review.json"
            review_receipt.write_text('{"review":"fresh"}\n', encoding="utf-8")
            recorded = harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R2",
                window_id="W",
                kind="coordinator_review_completed",
                payload={
                    "reviewer_identity": "fresh-sol/reviewer",
                    "reviewer_profile": "sol-xhigh",
                    "fresh": True,
                    "reviewed_parent_skill_hash": parent_skill_hash,
                    "reviewed_failure_event_hashes": state["miss_event_hashes"],
                    "receipt_path": str(review_receipt),
                    "receipt_sha256": harness.digest_bytes(review_receipt.read_bytes()),
                },
                now=started.replace(second=3),
            )
            evidence = guard.evidence_from_harness(
                db_path=db,
                lineage_id="L",
                run_id="R2",
                window_id="W",
                scope="coordinator",
                event_hash=recorded["event_hash"],
                policy=POLICY,
            )
            guard.validate_coordinator_evidence(
                evidence, POLICY["coordinator_review_threshold"]
            )

            first_batch = {
                failure["event_hash"] for failure in evidence["window_failures"]
            }
            review_bytes = review_receipt.read_bytes()
            review_receipt.write_text('{"review":"tampered"}\n', encoding="utf-8")
            connection = harness.connect(db)
            tampered_state = harness.lineage_review_state(connection, "L")
            connection.close()
            self.assertEqual(tampered_state["unreviewed_miss_count"], 3)
            self.assertTrue(tampered_state["review_required"])
            with self.assertRaisesRegex(guard.GuardError, "valid sealed review receipt"):
                guard.evidence_from_harness(
                    db_path=db,
                    lineage_id="L",
                    run_id="R2",
                    window_id="W",
                    scope="coordinator",
                    event_hash=recorded["event_hash"],
                    policy=POLICY,
                )
            review_receipt.write_bytes(review_bytes)

            for number in range(3, 6):
                run_id = f"R{number}"
                window_started = started.replace(second=number * 10)
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=ROOT / "scripts" / "deadline_harness.py",
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    fs_root=specification(root),
                    ledger=ledger,
                    now=window_started,
                    start_watcher=False,
                )
                connection = harness.connect(db)
                harness.expire_window(
                    connection=connection,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    now=window_started + timedelta(seconds=2),
                )
                connection.close()

            connection = harness.connect(db)
            state = harness.lineage_review_state(connection, "L")
            parent_skill_hash = harness.get_window(connection, "L", "R5", "W")["skill_hash"]
            connection.close()
            self.assertEqual(state["miss_count"], 6)
            self.assertEqual(state["unreviewed_miss_count"], 3)
            second_batch = set(state["miss_event_hashes"])
            self.assertTrue(first_batch.isdisjoint(second_batch))

            second_receipt = root / "review-2.json"
            second_receipt.write_text('{"review":"fresh second batch"}\n', encoding="utf-8")
            second_review = harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R5",
                window_id="W",
                kind="coordinator_review_completed",
                payload={
                    "reviewer_identity": "fresh-sol/reviewer-2",
                    "reviewer_profile": "sol-xhigh",
                    "fresh": True,
                    "reviewed_parent_skill_hash": parent_skill_hash,
                    "reviewed_failure_event_hashes": state["miss_event_hashes"],
                    "receipt_path": str(second_receipt),
                    "receipt_sha256": harness.digest_bytes(second_receipt.read_bytes()),
                },
                now=started.replace(second=53),
            )
            evidence = guard.evidence_from_harness(
                db_path=db,
                lineage_id="L",
                run_id="R5",
                window_id="W",
                scope="coordinator",
                event_hash=second_review["event_hash"],
                policy=POLICY,
            )
            self.assertEqual(
                {failure["event_hash"] for failure in evidence["window_failures"]},
                second_batch,
            )
            self.assertTrue(
                first_batch.isdisjoint(
                    failure["event_hash"] for failure in evidence["window_failures"]
                )
            )


if __name__ == "__main__":
    unittest.main()
