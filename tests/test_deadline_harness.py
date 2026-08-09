from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts import deadline_harness as harness


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "deadline_harness.py"


def task(task_id: str, seconds: int, depends_on: list[str] | None = None) -> dict:
    dependencies = depends_on or []
    return {
        "id": task_id,
        "claim_id": f"claim:{task_id}",
        "intended_task": f"Perform {task_id}",
        "pass_test": f"test {task_id}",
        "owner": f"owner:{task_id}",
        "worker_profile": "terra-high",
        "estimate_seconds": seconds,
        "estimate_provenance": {"source": "test fixture", "basis": task_id},
        "depends_on": dependencies,
        "preconditions": [f"accepted:{dependency}" for dependency in dependencies],
        "authoritative_route": "identity-bound test receipt",
        "evidence_requirements": ["receipt_sha256", "artifact_hashes"],
    }


def specification(root: Path) -> Path:
    path = root / "FS.md"
    if not path.exists():
        path.write_text("# Frozen functional specification\n", encoding="utf-8")
    return path


def accepted_payload(root: Path, slot_id: str, permit_hash: str) -> dict:
    receipt = root / f"{slot_id}-receipt.json"
    artifact = root / f"{slot_id}-artifact.json"
    receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
    artifact.write_text('{"proof":"real"}\n', encoding="utf-8")
    return {
        "slot_id": slot_id,
        "worker_profile": "terra-high",
        "permit_event_hash": permit_hash,
        "worker_identity": f"worker/{slot_id}",
        "test_completed": True,
        "test_result": "passed",
        "receipt_path": str(receipt),
        "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
        "artifact_hashes": {str(artifact): harness.digest_bytes(artifact.read_bytes())},
    }


class DeadlineHarnessTests(unittest.TestCase):
    def test_critical_path_uses_parallel_max_and_serial_sum(self) -> None:
        ledger = {
            "tasks": [task("A", 10), task("B", 20), task("C", 5, ["A"])],
            "reserve_seconds": 3,
            "reserve_provenance": {"source": "test fixture"},
        }
        timing = harness.validate_ledger(ledger)
        self.assertEqual(timing["critical_path_seconds"], 20)
        self.assertEqual(timing["duration_seconds"], 23)

    def test_ledger_ceiling_and_cycles_are_rejected(self) -> None:
        with self.assertRaises(harness.HarnessError):
            harness.validate_ledger({"tasks": [task(str(i), 1) for i in range(11)]})
        with self.assertRaises(harness.HarnessError):
            harness.validate_ledger({"tasks": [task("A", 1, ["B"]), task("B", 1, ["A"])]})

    def test_deployment_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            install_root = Path(temporary) / "install"
            target, changed = harness.ensure_installed(SOURCE, install_root)
            target_again, changed_again = harness.ensure_installed(SOURCE, install_root)
            self.assertTrue(changed)
            self.assertFalse(changed_again)
            self.assertEqual(target, target_again)
            self.assertEqual(target.read_bytes(), SOURCE.read_bytes())

            target.write_text("stale", encoding="utf-8")
            repaired_target, repaired = harness.ensure_installed(SOURCE, install_root)
            self.assertTrue(repaired)
            self.assertEqual(repaired_target.read_bytes(), SOURCE.read_bytes())

    def test_window_identity_and_deadline_cannot_reset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            ledger = {
                "tasks": [task("T01", 30)],
                "reserve_seconds": 5,
                "reserve_provenance": {"source": "test fixture"},
            }
            opened = harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger=ledger,
                now=started,
                start_watcher=False,
            )
            with self.assertRaises(harness.HarnessError):
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=SOURCE,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    fs_root=specification(root),
                    ledger=ledger,
                    now=started + timedelta(hours=1),
                    start_watcher=False,
                )

            revised = {"tasks": [task("T01", 300)]}
            revision = harness.revise_ledger(
                db_path=db,
                lineage_id="L",
                run_id="R",
                window_id="W",
                ledger=revised,
            )
            self.assertFalse(revision["deadline_changed"])
            self.assertEqual(revision["sealed_deadline_utc"], opened["deadline_utc"])

    def test_third_distinct_deadline_miss_requires_coordinator_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            results = []
            for number in range(1, 4):
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=SOURCE,
                    lineage_id="lineage",
                    run_id=f"run-{number}",
                    window_id="window",
                    fs_root=specification(root),
                    ledger={"tasks": [task("T", 1)]},
                    now=started,
                    start_watcher=False,
                )
                connection = harness.connect(db)
                result = harness.expire_window(
                    connection=connection,
                    install_root=install,
                    lineage_id="lineage",
                    run_id=f"run-{number}",
                    window_id="window",
                    now=started + timedelta(seconds=2),
                )
                connection.close()
                results.append(result)

            self.assertEqual([result["miss_count"] for result in results], [1, 2, 3])
            self.assertFalse(results[1]["coordinator_review_required"])
            self.assertTrue(results[2]["coordinator_review_required"])
            status = harness.status_window(
                db_path=db,
                install_root=install,
                lineage_id="lineage",
                run_id="run-3",
                window_id="window",
                now=started + timedelta(seconds=3),
            )
            self.assertTrue(status["chain_valid"])
            self.assertIn("coordinator_review_required", status["event_kinds"])

    def test_completion_before_deadline_prevents_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_accepted",
                payload=accepted_payload(root, "T", permit["permit_event_hash"]),
                now=started + timedelta(seconds=4),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={},
                now=started + timedelta(seconds=5),
            )
            connection = harness.connect(db)
            result = harness.expire_window(
                connection=connection,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                now=started + timedelta(seconds=20),
            )
            connection.close()
            self.assertTrue(result["completed"])
            self.assertFalse(result["expired"])

    def test_dispatch_permit_expires_with_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(seconds=5),
            )
            self.assertTrue(permit["permitted"])
            with self.assertRaises(harness.HarnessError):
                harness.permit_dispatch(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    slot_id="T-retry",
                    worker_profile="terra-high",
                    now=started + timedelta(seconds=11),
                )

    def test_terminal_receipt_must_match_and_consume_dispatch_permit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(seconds=1),
            )
            receipt = root / "receipt.json"
            artifact = root / "artifact.json"
            receipt.write_text("{}\n", encoding="utf-8")
            artifact.write_text("{}\n", encoding="utf-8")
            payload = {
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
            }
            mismatched = dict(payload, worker_profile="sol-high")
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="task_accepted",
                    payload=mismatched,
                    now=started + timedelta(seconds=2),
                )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_accepted",
                payload=payload,
                now=started + timedelta(seconds=2),
            )
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="task_accepted",
                    payload=payload,
                    now=started + timedelta(seconds=3),
                )

    def test_lineage_rejects_changed_frozen_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copied_skill = root / "skill"
            shutil_ignore = shutil.ignore_patterns(
                ".git", ".skill-init", "__pycache__", ".pytest_cache"
            )
            shutil.copytree(ROOT, copied_skill, ignore=shutil_ignore)
            source = copied_skill / "scripts" / "deadline_harness.py"
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=source,
                lineage_id="L",
                run_id="R1",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            kernel = copied_skill / "references" / "kernel.md"
            kernel.write_text(kernel.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
            with self.assertRaises(harness.HarnessError):
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=source,
                    lineage_id="L",
                    run_id="R2",
                    window_id="W",
                    fs_root=specification(root),
                    ledger={"tasks": [task("T", 10)]},
                    now=started,
                    start_watcher=False,
                )

    def test_benchmark_rejects_a_changed_functional_specification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            fs_root = specification(root)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=fs_root,
                ledger={"tasks": [task("T", 10)]},
                start_watcher=False,
            )
            fs_root.write_text("# Easier replacement specification\n", encoding="utf-8")
            with self.assertRaises(harness.HarnessError):
                harness.export_benchmark(
                    db_path=db,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                )

    def test_benchmark_is_derived_from_identity_bound_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            benchmark_binding = {
                "git": {
                    "worktree": str(ROOT),
                    "branch": "candidate",
                    "commit": "a" * 40,
                    "tree": "b" * 40,
                },
                "product_frontier": {
                    "repository": "product/example",
                    "commit": "c" * 40,
                    "tree": "d" * 40,
                },
                "mutation": {
                    "target_failure_id": "L/R/W/T",
                    "changed_policy_keys": ["policy/orchestration.json.ready_order"],
                    "expected_reduction": "repeated_work",
                },
            }
            benchmark_ledger = {
                "tasks": [task("T", 10)],
                "benchmark_binding": benchmark_binding,
            }
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger=benchmark_ledger,
                now=started,
                start_watcher=False,
            )
            receipt = root / "receipt.json"
            artifact = root / "artifact.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            artifact.write_text('{"proof":"real"}\n', encoding="utf-8")
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
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
                now=started + timedelta(seconds=4),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={
                    "tokens": 123,
                    "mutation": benchmark_binding["mutation"]
                    | {"observed_reductions": ["repeated_work"]},
                },
                now=started + timedelta(seconds=5),
            )
            result = harness.export_benchmark(
                db_path=db,
                lineage_id="L",
                run_id="R",
                window_id="W",
            )
            self.assertTrue(all(result["quality"].values()))
            self.assertTrue(result["target_failure_resolved"])
            self.assertEqual(result["deadline"]["elapsed_seconds"], 5)
            self.assertEqual(result["usage"]["tokens"], 123)
            self.assertEqual(result["provenance"]["producer"], "de67-deadline-harness/0.1.0")
            self.assertEqual(result["provenance"]["state_db"], str(db.resolve()))
            self.assertEqual(
                result["provenance"]["definition_hash"],
                harness.benchmark_definition_hash(benchmark_ledger),
            )
            self.assertEqual(
                result["provenance"]["effective_plan_hash"],
                harness.digest_json(benchmark_ledger),
            )
            self.assertEqual(result["provenance"]["git"], benchmark_binding["git"])
            self.assertEqual(
                result["provenance"]["product_frontier"],
                benchmark_binding["product_frontier"],
            )
            self.assertEqual(result["mutation"]["target_failure_id"], "L/R/W/T")

    def test_benchmark_definition_excludes_only_candidate_git_identity(self) -> None:
        binding = {
            "git": {
                "worktree": "C:/parent",
                "branch": "main",
                "commit": "a" * 40,
                "tree": "b" * 40,
            },
            "product_frontier": {
                "repository": "product/example",
                "commit": "c" * 40,
                "tree": "d" * 40,
            },
            "mutation": {
                "target_failure_id": "L/R/W/T",
                "changed_policy_keys": ["policy/orchestration.json.ready_order"],
                "expected_reduction": "repeated_work",
            },
        }
        baseline = {"tasks": [task("T", 10)], "benchmark_binding": binding}
        candidate = {
            "tasks": [task("T", 10)],
            "benchmark_binding": binding
            | {
                "git": {
                    "worktree": "C:/candidate",
                    "branch": "candidate",
                    "commit": "e" * 40,
                    "tree": "f" * 40,
                }
            },
        }
        harness.validate_ledger(baseline)
        harness.validate_ledger(candidate)
        self.assertEqual(
            harness.benchmark_definition_hash(baseline),
            harness.benchmark_definition_hash(candidate),
        )
        self.assertNotEqual(harness.digest_json(baseline), harness.digest_json(candidate))

        semantic_change = {
            "tasks": [dict(task("T", 10), pass_test="different authoritative test")],
            "benchmark_binding": binding,
        }
        product_change = {
            "tasks": [task("T", 10)],
            "benchmark_binding": binding
            | {
                "product_frontier": binding["product_frontier"] | {"tree": "1" * 40}
            },
        }
        mutation_change = {
            "tasks": [task("T", 10)],
            "benchmark_binding": binding
            | {
                "mutation": binding["mutation"]
                | {"target_failure_id": "L/R/W/another-task"}
            },
        }
        baseline_definition = harness.benchmark_definition_hash(baseline)
        for changed in (semantic_change, product_change, mutation_change):
            harness.validate_ledger(changed)
            self.assertNotEqual(
                baseline_definition,
                harness.benchmark_definition_hash(changed),
            )

    def test_child_dispatch_requires_accepted_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("A", 10), task("B", 10, ["A"])]},
                now=started,
                start_watcher=False,
            )
            with self.assertRaises(harness.HarnessError):
                harness.permit_dispatch(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    slot_id="B",
                    worker_profile="terra-high",
                    now=started + timedelta(seconds=1),
                )
            parent = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="A",
                worker_profile="terra-high",
                now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_accepted",
                payload=accepted_payload(root, "A", parent["permit_event_hash"]),
                now=started + timedelta(seconds=2),
            )
            child = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="B",
                worker_profile="terra-high",
                now=started + timedelta(seconds=3),
            )
            self.assertTrue(child["permitted"])

    def test_completion_is_terminal_unique_and_requires_all_acceptances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="completed",
                    payload={},
                    now=started + timedelta(seconds=1),
                )
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_accepted",
                payload=accepted_payload(root, "T", permit["permit_event_hash"]),
                now=started + timedelta(seconds=3),
            )
            for invalid_tokens in (-1, float("inf"), float("nan")):
                with self.assertRaises(harness.HarnessError):
                    harness.record_event(
                        db_path=db,
                        install_root=install,
                        lineage_id="L",
                        run_id="R",
                        window_id="W",
                        kind="completed",
                        payload={"tokens": invalid_tokens},
                        now=started + timedelta(seconds=4),
                    )
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="completed",
                    payload={"tokens": 1},
                    now=started + timedelta(seconds=2),
                )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={"tokens": 1},
                now=started + timedelta(seconds=5),
            )
            for kind in ("completed", "progress"):
                with self.assertRaises(harness.HarnessError):
                    harness.record_event(
                        db_path=db,
                        install_root=install,
                        lineage_id="L",
                        run_id="R",
                        window_id="W",
                        kind=kind,
                        payload={"tokens": 1} if kind == "completed" else {},
                        now=started + timedelta(seconds=6),
                    )

    def test_late_receipt_records_miss_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 1)]},
                now=started,
                start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                slot_id="T",
                worker_profile="terra-high",
                now=started + timedelta(milliseconds=100),
            )
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="completed",
                    payload={},
                    now=started + timedelta(milliseconds=200),
                )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="task_accepted",
                payload=accepted_payload(root, "T", permit["permit_event_hash"]),
                now=started + timedelta(seconds=2),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={},
                now=started + timedelta(seconds=3),
            )
            benchmark = harness.export_benchmark(
                db_path=db, lineage_id="L", run_id="R", window_id="W"
            )
            self.assertEqual(benchmark["deadline"], {"misses": 1, "elapsed_seconds": 3.0})
            self.assertFalse(benchmark["target_failure_resolved"])

    def test_revision_preserves_obligations_and_exports_effective_plan_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            original_task = task("A", 10)
            original = {"tasks": [original_task]}
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger=original,
                now=started,
                start_watcher=False,
            )
            weakened = dict(original_task, pass_test="easy test")
            with self.assertRaises(harness.HarnessError):
                harness.revise_ledger(
                    db_path=db,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    ledger={"tasks": [weakened]},
                )
            revised = {"tasks": [original_task, task("B", 10, ["A"])]}
            revision = harness.revise_ledger(
                db_path=db,
                lineage_id="L",
                run_id="R",
                window_id="W",
                ledger=revised,
                now=started + timedelta(milliseconds=500),
            )
            for offset, slot_id in ((1, "A"), (3, "B")):
                permit = harness.permit_dispatch(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    slot_id=slot_id,
                    worker_profile="terra-high",
                    now=started + timedelta(seconds=offset),
                )
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id="R",
                    window_id="W",
                    kind="task_accepted",
                    payload=accepted_payload(root, slot_id, permit["permit_event_hash"]),
                    now=started + timedelta(seconds=offset + 1),
                )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={},
                now=started + timedelta(seconds=5),
            )
            benchmark = harness.export_benchmark(
                db_path=db, lineage_id="L", run_id="R", window_id="W"
            )
            self.assertEqual(
                benchmark["provenance"]["effective_plan_hash"], revision["ledger_hash"]
            )
            self.assertEqual(
                benchmark["provenance"]["definition_hash"],
                harness.benchmark_definition_hash(revised),
            )
            self.assertNotEqual(benchmark["provenance"]["definition_hash"], harness.digest_json(original))

    def test_three_nonconsecutive_misses_block_until_fresh_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            epoch = datetime(2026, 8, 9, tzinfo=timezone.utc)

            def open_run(run_id: str, started: datetime, seconds: int = 1) -> None:
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=SOURCE,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    fs_root=specification(root),
                    ledger={"tasks": [task("T", seconds)]},
                    now=started,
                    start_watcher=False,
                )

            def complete_run(run_id: str, started: datetime) -> None:
                permit = harness.permit_dispatch(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    slot_id="T",
                    worker_profile="terra-high",
                    now=started + timedelta(seconds=1),
                )
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    kind="task_accepted",
                    payload=accepted_payload(root, run_id, permit["permit_event_hash"])
                    | {"slot_id": "T"},
                    now=started + timedelta(seconds=2),
                )
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    kind="completed",
                    payload={},
                    now=started + timedelta(seconds=3),
                )

            for index in range(5):
                started = epoch + timedelta(seconds=index * 10)
                run_id = f"R{index + 1}"
                open_run(run_id, started, 5 if index in {1, 3} else 1)
                if index in {1, 3}:
                    complete_run(run_id, started)
                else:
                    connection = harness.connect(db)
                    harness.expire_window(
                        connection=connection,
                        install_root=install,
                        lineage_id="L",
                        run_id=run_id,
                        window_id="W",
                        now=started + timedelta(seconds=2),
                    )
                    connection.close()
            with self.assertRaises(harness.HarnessError):
                open_run("R6", epoch + timedelta(seconds=50))
            connection = harness.connect(db)
            state = harness.lineage_review_state(connection, "L")
            parent_skill_hash = harness.get_window(connection, "L", "R5", "W")["skill_hash"]
            connection.close()
            receipt = root / "review.json"
            receipt.write_text('{"review":"fresh"}\n', encoding="utf-8")
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R5",
                window_id="W",
                kind="coordinator_review_completed",
                payload={
                    "reviewer_identity": "fresh-sol/reviewer",
                    "reviewer_profile": "sol-xhigh",
                    "fresh": True,
                    "reviewed_parent_skill_hash": parent_skill_hash,
                    "reviewed_failure_event_hashes": state["miss_event_hashes"],
                    "receipt_path": str(receipt),
                    "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                },
                now=epoch + timedelta(seconds=43),
            )
            open_run("R6", epoch + timedelta(seconds=50))

    def test_third_late_success_waits_for_review_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            epoch = datetime(2026, 8, 9, tzinfo=timezone.utc)

            for index in range(3):
                run_id = f"late-{index + 1}"
                started = epoch + timedelta(seconds=index * 10)
                harness.open_window(
                    db_path=db,
                    install_root=install,
                    source_script=SOURCE,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    fs_root=specification(root),
                    ledger={"tasks": [task("T", 1)]},
                    now=started,
                    start_watcher=False,
                )
                permit = harness.permit_dispatch(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    slot_id="T",
                    worker_profile="terra-high",
                    now=started + timedelta(milliseconds=100),
                )
                harness.record_event(
                    db_path=db,
                    install_root=install,
                    lineage_id="L",
                    run_id=run_id,
                    window_id="W",
                    kind="task_accepted",
                    payload=accepted_payload(root, run_id, permit["permit_event_hash"])
                    | {"slot_id": "T"},
                    now=started + timedelta(seconds=2),
                )
                if index < 2:
                    harness.record_event(
                        db_path=db,
                        install_root=install,
                        lineage_id="L",
                        run_id=run_id,
                        window_id="W",
                        kind="completed",
                        payload={},
                        now=started + timedelta(seconds=3),
                    )
                else:
                    with self.assertRaises(harness.HarnessError):
                        harness.record_event(
                            db_path=db,
                            install_root=install,
                            lineage_id="L",
                            run_id=run_id,
                            window_id="W",
                            kind="completed",
                            payload={},
                            now=started + timedelta(seconds=3),
                        )

            connection = harness.connect(db)
            state = harness.lineage_review_state(connection, "L")
            parent_skill_hash = harness.get_window(
                connection, "L", "late-3", "W"
            )["skill_hash"]
            connection.close()
            self.assertTrue(state["review_required"])
            receipt = root / "late-review.json"
            receipt.write_text('{"review":"three late successes"}\n', encoding="utf-8")
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="late-3",
                window_id="W",
                kind="coordinator_review_completed",
                payload={
                    "reviewer_identity": "fresh-sol/reviewer",
                    "reviewer_profile": "sol-xhigh",
                    "fresh": True,
                    "reviewed_parent_skill_hash": parent_skill_hash,
                    "reviewed_failure_event_hashes": state["miss_event_hashes"],
                    "receipt_path": str(receipt),
                    "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                },
                now=epoch + timedelta(seconds=23),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="late-3",
                window_id="W",
                kind="completed",
                payload={},
                now=epoch + timedelta(seconds=24),
            )
            opened = harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="after-review",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 1)]},
                now=epoch + timedelta(seconds=30),
                start_watcher=False,
            )
            self.assertEqual(opened["run_id"], "after-review")
            connection = harness.connect(db)
            kinds = [
                row["kind"]
                for row in harness.events_for(connection, "L", "late-3", "W")
            ]
            connection.close()
            self.assertEqual(kinds.count("completed"), 1)
            self.assertLess(kinds.index("coordinator_review_completed"), kinds.index("completed"))

    def test_zero_dispatch_preflight_blocker_is_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="L",
                run_id="R",
                window_id="W",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 10)]},
                now=started,
                start_watcher=False,
            )
            receipt = root / "blocker.json"
            receipt.write_text('{"blocker":"missing owner artifact"}\n', encoding="utf-8")
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="preflight_blocked",
                payload={
                    "authorized_by": "specification-owner",
                    "authority_reference": "FS.A/preflight-blocker",
                    "blocker": "required identity artifact is unavailable",
                    "blocked_claim_ids": ["claim:T"],
                    "receipt_path": str(receipt),
                    "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                },
                now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db,
                install_root=install,
                lineage_id="L",
                run_id="R",
                window_id="W",
                kind="completed",
                payload={"outcome": "preflight_blocked", "tokens": 0},
                now=started + timedelta(seconds=2),
            )
            benchmark = harness.export_benchmark(
                db_path=db, lineage_id="L", run_id="R", window_id="W"
            )
            self.assertEqual(benchmark["quality_context"]["window_kind"], "preflight_gate")
            self.assertFalse(benchmark["quality"]["worker_executed"])
            self.assertFalse(benchmark["quality"]["test_completed"])
            self.assertFalse(benchmark["quality"]["acceptance_passed"])
            self.assertTrue(benchmark["quality"]["evidence_valid"])
            connection = harness.connect(db)
            kinds = [row["kind"] for row in harness.events_for(connection, "L", "R", "W")]
            connection.close()
            self.assertNotIn("dispatch_permitted", kinds)

    def test_detached_watcher_acknowledges_and_expires(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            harness.open_window(
                db_path=db,
                install_root=install,
                source_script=SOURCE,
                lineage_id="watch-lineage",
                run_id="watch-run",
                window_id="watch-window",
                fs_root=specification(root),
                ledger={"tasks": [task("T", 0.2)]},
                start_watcher=True,
            )
            kinds: list[str] = []
            for _ in range(60):
                connection = harness.connect(db)
                kinds = [
                    row["kind"]
                    for row in harness.events_for(
                        connection, "watch-lineage", "watch-run", "watch-window"
                    )
                ]
                connection.close()
                if "deadline_missed" in kinds:
                    break
                time.sleep(0.05)
            self.assertIn("watcher_ready", kinds)
            self.assertIn("deadline_missed", kinds)


if __name__ == "__main__":
    unittest.main()
