from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
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
    return {
        "kind": "coordinator_review",
        "window_failures": [
            {"deadline_id": f"lineage/run-{number}/window", "deadline_missed": True}
            for number in range(3)
        ],
    }


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


class MutationGuardTests(unittest.TestCase):
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

    def seal_success(
        self, *, skill_root: Path, install_root: Path, elapsed_seconds: int, tokens: int
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
                    "intended_task": "work",
                    "pass_test": "test",
                    "worker_profile": "terra-high",
                    "estimate_seconds": 20,
                    "depends_on": [],
                }
            ]
        }
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
            payload={"tokens": tokens},
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

    def test_equal_operations_choose_smaller_skill(self) -> None:
        baseline = benchmark(misses=0, elapsed=100, tokens=1000, size=5000)
        candidate = benchmark(misses=0, elapsed=100, tokens=1000, size=4900)
        result = guard.compare_benchmark(baseline, candidate, POLICY["quality_predicates"])
        self.assertTrue(result["promotable"])

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
                            "intended_task": "work",
                            "pass_test": "test",
                            "worker_profile": "terra-high",
                            "estimate_seconds": 10,
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

    def test_coordinator_evidence_comes_from_three_sealed_misses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            ledger = {
                "tasks": [
                    {
                        "id": "T",
                        "intended_task": "work",
                        "pass_test": "test",
                        "worker_profile": "terra-high",
                        "estimate_seconds": 1,
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
            evidence = guard.evidence_from_harness(
                db_path=db,
                lineage_id="L",
                run_id="R2",
                window_id="W",
                scope="coordinator",
                event_hash=None,
                policy=POLICY,
            )
            self.assertEqual(len(evidence["window_failures"]), 3)


if __name__ == "__main__":
    unittest.main()
