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
    return {
        "id": task_id,
        "intended_task": f"Perform {task_id}",
        "pass_test": f"test {task_id}",
        "worker_profile": "terra-high",
        "estimate_seconds": seconds,
        "depends_on": depends_on or [],
    }


def specification(root: Path) -> Path:
    path = root / "FS.md"
    if not path.exists():
        path.write_text("# Frozen functional specification\n", encoding="utf-8")
    return path


class DeadlineHarnessTests(unittest.TestCase):
    def test_critical_path_uses_parallel_max_and_serial_sum(self) -> None:
        ledger = {
            "tasks": [task("A", 10), task("B", 20), task("C", 5, ["A"])],
            "reserve_seconds": 3,
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
            ledger = {"tasks": [task("T01", 30)], "reserve_seconds": 5}
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

            revised = {"tasks": [task("T01-renamed", 300)]}
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
            connection = harness.connect(db)
            harness.append_event(connection, "L", "R", "W", "completed", {}, started + timedelta(seconds=5))
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
                payload={"tokens": 123},
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
