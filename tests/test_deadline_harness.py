from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from scripts import deadline_harness as harness


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "deadline_harness.py"


def skill_with_retry_route(root: Path, retry_route: str) -> Path:
    skill_root = root / "skill"
    shutil.copytree(
        ROOT,
        skill_root,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    policy_path = skill_root / "policy" / "orchestration.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["retry_route"] = retry_route
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return skill_root


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


def proof_binding(root: Path, fs_root: Path, *, seed: int = 7, coordinates=(10, 20)) -> dict:
    artifacts = {}
    for kind in sorted(harness.PROOF_ARTIFACT_KINDS):
        path = root / f"proof-{kind}.dat"
        path.write_text(f"authoritative {kind}\n", encoding="utf-8")
        artifacts[kind] = {str(path): harness.digest_bytes(path.read_bytes())}
    manifest = {
        "conditions": [
            {"id": "condition:feature", "requirement": "feature transition is observed"},
            {"id": "condition:owner", "requirement": "authoritative owner performs transition"},
        ],
        "negative_controls": [
            {"id": "control:no-direct-set", "requirement": "outcome is not set directly"},
            {"id": "control:no-helper", "requirement": "helper-only evidence does not pass"},
        ],
    }
    frontier = {"repository": "product/example", "commit": "a" * 40, "tree": "b" * 40}
    artifact_paths = sorted(path for bindings in artifacts.values() for path in bindings)
    condition_ids = [item["id"] for item in manifest["conditions"]]
    control_ids = [item["id"] for item in manifest["negative_controls"]]
    plan = {
        "version": 1,
        "author_identity": "plan-author/xhigh",
        "artifacts": artifacts,
        "seed": seed,
        "coordinates": list(coordinates),
        "condition_artifacts": {identifier: artifact_paths for identifier in condition_ids},
        "negative_control_artifacts": {identifier: artifact_paths for identifier in control_ids},
    }
    return {
        "contract": {
            "semantic_manifest": manifest,
            "accepted_product_frontier": frontier,
            "authoritative_owner_route": "product owner live conformance",
        },
        "plan": plan,
    }


def proof_review_payload(
    root: Path,
    proof: dict,
    *,
    reviewer="independent-referee/sol",
    conformance_route="minimal_authoritative_conformance",
) -> dict:
    binding = harness.proof_runtime_binding({"proof": proof})
    receipt = root / f"proof-review-{binding['plan_hash'][:12]}.json"
    receipt.write_text(
        json.dumps(
            {
                "reviewer": reviewer,
                "binding": binding,
                "conformance_route": conformance_route,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    payload = {
        **binding,
        "reviewer_identity": reviewer,
        "conformance_route": conformance_route,
        "helper_or_mock_only": False,
        "direct_outcome_setting": False,
        "receipt_path": str(receipt),
        "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
    }
    if conformance_route == "authoritative_owner_then_live_conformance":
        owner_receipt = root / f"owner-review-{binding['plan_hash'][:12]}.json"
        live_receipt = root / f"live-review-{binding['plan_hash'][:12]}.json"
        owner_receipt.write_text('{"owner":"approved"}\n', encoding="utf-8")
        live_receipt.write_text('{"live":"passed"}\n', encoding="utf-8")
        payload.update(
            {
                "owner_identity": "authoritative-owner/product",
                "owner_receipt_path": str(owner_receipt),
                "owner_receipt_sha256": harness.digest_bytes(owner_receipt.read_bytes()),
                "live_receipt_path": str(live_receipt),
                "live_receipt_sha256": harness.digest_bytes(live_receipt.read_bytes()),
                "live_conformance": True,
            }
        )
    return payload


def proof_damage_payload(
    root: Path,
    proof: dict,
    miss_hash: str,
    permit_hash: str,
    failed_hash: str,
    *,
    causal_class: str = "selector overfit",
    conformance_route: str = "minimal_authoritative_conformance",
) -> dict:
    binding = harness.proof_runtime_binding({"proof": proof})
    fingerprint = harness.digest_json(
        {
            "causal_class": causal_class,
            "contract_hash": binding["contract_hash"],
            "authoritative_owner_route": binding["authoritative_owner_route"],
        }
    )
    receipt = root / f"damage-{permit_hash[:12]}.json"
    receipt.write_text(json.dumps({"causal_class": causal_class}), encoding="utf-8")
    return {
        "miss_event_hash": miss_hash,
        "failure_owner": "proof_plan",
        "permit_event_hash": permit_hash,
        "task_failed_event_hash": failed_hash,
        "contract_hash": binding["contract_hash"],
        "plan_hash": binding["plan_hash"],
        "causal_class": causal_class,
        "causal_fingerprint": fingerprint,
        "assessor_identity": "independent/damage-referee",
        "conformance_route": conformance_route,
        "receipt_path": str(receipt),
        "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
    }


class DeadlineHarnessTests(unittest.TestCase):
    def test_receipt_reseal_is_single_use_receipt_only_and_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L7", run_id="R", window_id="W",
                fs_root=specification(root), ledger={"tasks": [task("T", 30)]},
                now=started, start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", now=started + timedelta(seconds=1),
            )
            rejected = accepted_payload(root, "T", permit["permit_event_hash"])
            rejected["receipt_sha256"] = "0" * 64
            corrected_hash = harness.digest_bytes(Path(rejected["receipt_path"]).read_bytes())
            rejection = harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="receipt_rejected", payload=rejected,
                now=started + timedelta(seconds=2),
            )
            reseal_payload = {
                "rejected_event_hash": rejection["event_hash"],
                "corrected_receipt_path": rejected["receipt_path"],
                "corrected_receipt_sha256": corrected_hash,
            }
            reseal = harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="receipt_resealed", payload=reseal_payload,
                now=started + timedelta(seconds=3),
            )
            with self.assertRaisesRegex(harness.HarnessError, "already has a receipt reseal"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_resealed", payload=reseal_payload,
                    now=started + timedelta(seconds=4),
                )
            accepted = dict(
                rejected,
                receipt_sha256=corrected_hash,
                receipt_reseal_event_hash=reseal["event_hash"],
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="task_accepted", payload=accepted,
                now=started + timedelta(seconds=4),
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="completed", payload={},
                now=started + timedelta(seconds=5),
            )
            connection = harness.connect(db)
            try:
                rows = harness.events_for(connection, "L7", "R", "W")
            finally:
                connection.close()
            self.assertEqual(
                [row["kind"] for row in rows],
                [
                    "window_opened", "dispatch_permitted", "receipt_rejected",
                    "receipt_resealed", "task_accepted", "completed",
                ],
            )

    def test_receipt_reseal_rejects_fake_changed_evidence_and_consumed_permit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L7", run_id="R", window_id="W",
                fs_root=specification(root), ledger={"tasks": [task("T", 30)]},
                now=started, start_watcher=False,
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", now=started + timedelta(seconds=1),
            )
            terminal = accepted_payload(root, "T", permit["permit_event_hash"])
            direct_reseal = {
                "rejected_event_hash": permit["permit_event_hash"],
                "corrected_receipt_path": terminal["receipt_path"],
                "corrected_receipt_sha256": terminal["receipt_sha256"],
            }
            with self.assertRaisesRegex(harness.HarnessError, "no sealed rejected receipt"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_resealed", payload=direct_reseal,
                    now=started + timedelta(seconds=2),
                )
            with self.assertRaisesRegex(harness.HarnessError, "genuine receipt hash mismatch"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_rejected", payload=terminal,
                    now=started + timedelta(seconds=2),
                )
            rejected = dict(terminal, receipt_sha256="0" * 64)
            rejection = harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="receipt_rejected", payload=rejected,
                now=started + timedelta(seconds=2),
            )
            with self.assertRaisesRegex(harness.HarnessError, "already has a rejected receipt"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_rejected", payload=rejected,
                    now=started + timedelta(seconds=3),
                )
            reseal_payload = dict(
                rejected_event_hash=rejection["event_hash"],
                corrected_receipt_path=terminal["receipt_path"],
                corrected_receipt_sha256=terminal["receipt_sha256"],
            )
            altered = dict(reseal_payload, rejected_terminal=rejected)
            with self.assertRaisesRegex(harness.HarnessError, "incomplete or open shape"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_resealed", payload=altered,
                    now=started + timedelta(seconds=3),
                )
            reseal = harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="receipt_resealed", payload=reseal_payload,
                now=started + timedelta(seconds=3),
            )
            changed_artifact = root / "changed-artifact.json"
            changed_artifact.write_text('{"proof":"changed"}\n', encoding="utf-8")
            changed = dict(
                terminal,
                worker_identity="worker/other",
                artifact_hashes={str(changed_artifact): harness.digest_bytes(changed_artifact.read_bytes())},
                receipt_reseal_event_hash=reseal["event_hash"],
            )
            with self.assertRaises(harness.HarnessError):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="task_accepted", payload=changed,
                    now=started + timedelta(seconds=4),
                )
            terminal["receipt_reseal_event_hash"] = reseal["event_hash"]
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L7", run_id="R",
                window_id="W", kind="task_accepted", payload=terminal,
                now=started + timedelta(seconds=4),
            )
            with self.assertRaisesRegex(harness.HarnessError, "already consumed"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L7", run_id="R",
                    window_id="W", kind="receipt_resealed", payload=reseal_payload,
                    now=started + timedelta(seconds=5),
                )

    def test_third_equivalent_failure_is_denied_but_changed_cause_is_permitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_root = skill_with_retry_route(root, "same_worker_changed_evidence")
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db, install_root=install,
                source_script=skill_root / "scripts" / "deadline_harness.py",
                lineage_id="L8", run_id="R", window_id="W",
                fs_root=specification(root), ledger={"tasks": [task("T", 60)]},
                now=started, start_watcher=False,
            )
            receipt = root / "receipt.json"
            artifact = root / "artifact.json"
            receipt.write_text('{"causal_class":"missing-tool"}\n', encoding="utf-8")
            artifact.write_text('{"failure":"missing-tool"}\n', encoding="utf-8")
            for attempt in range(2):
                permit = harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=attempt * 2 + 1),
                )
                failed = {
                    "slot_id": "T", "worker_profile": "terra-high",
                    "worker_identity": "worker/T", "test_completed": True,
                    "test_result": "failed", "permit_event_hash": permit["permit_event_hash"],
                    "receipt_path": str(receipt),
                    "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                    "artifact_hashes": {str(artifact): harness.digest_bytes(artifact.read_bytes())},
                }
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L8", run_id="R",
                    window_id="W", kind="task_failed", payload=failed,
                    now=started + timedelta(seconds=attempt * 2 + 2),
                )
            with self.assertRaisesRegex(harness.HarnessError, "unchanged equivalent retry"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=5),
                )
            alternate_receipt = root / "elsewhere" / "receipt.json"
            alternate_artifact = root / "elsewhere" / "artifact.json"
            alternate_receipt.parent.mkdir()
            alternate_receipt.write_text('{  "causal_class" : "missing-tool"  }\n', encoding="utf-8")
            alternate_artifact.write_bytes(artifact.read_bytes())
            cosmetic = harness.causal_evidence_binding(
                alternate_receipt,
                {str(alternate_artifact): harness.digest_bytes(alternate_artifact.read_bytes())},
            )
            with self.assertRaisesRegex(harness.HarnessError, "unchanged equivalent retry"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", causal_evidence=cosmetic,
                    now=started + timedelta(seconds=5),
                )
            changed_receipt = root / "changed-receipt.json"
            changed_artifact = root / "changed-artifact.json"
            changed_receipt.write_text('{"causal_class":"installed-tool"}\n', encoding="utf-8")
            changed_artifact.write_text('{"failure":"new-exit"}\n', encoding="utf-8")
            changed_evidence = harness.causal_evidence_binding(
                changed_receipt,
                {str(changed_artifact): harness.digest_bytes(changed_artifact.read_bytes())},
            )
            changed = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L8", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", causal_evidence=changed_evidence,
                now=started + timedelta(seconds=5),
            )
            self.assertTrue(changed["permitted"])

    def test_each_repeated_causal_group_fuses_and_a_new_group_remains_possible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_root = skill_with_retry_route(root, "same_worker_changed_evidence")
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db, install_root=install,
                source_script=skill_root / "scripts" / "deadline_harness.py",
                lineage_id="L8-groups", run_id="R", window_id="W",
                fs_root=specification(root), ledger={"tasks": [task("T", 60)]},
                now=started, start_watcher=False,
            )
            receipt = root / "receipt.json"
            artifact = root / "artifact.json"

            def write_cause(label: str) -> dict:
                receipt.write_text(json.dumps({"causal_class": label}) + "\n", encoding="utf-8")
                artifact.write_text(json.dumps({"failure": label}) + "\n", encoding="utf-8")
                return harness.causal_evidence_binding(
                    receipt, {str(artifact): harness.digest_bytes(artifact.read_bytes())}
                )

            def fail(permit: dict, second: int) -> None:
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                    window_id="W", kind="task_failed",
                    payload={
                        "slot_id": "T", "worker_profile": "terra-high",
                        "worker_identity": "worker/T", "test_completed": True,
                        "test_result": "failed", "permit_event_hash": permit["permit_event_hash"],
                        "receipt_path": str(receipt),
                        "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                        "artifact_hashes": {
                            str(artifact): harness.digest_bytes(artifact.read_bytes())
                        },
                    },
                    now=started + timedelta(seconds=second),
                )

            write_cause("A")
            for second in (1, 3):
                permit = harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=second),
                )
                fail(permit, second + 1)

            evidence_b = write_cause("B")
            permit_b1 = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", causal_evidence=evidence_b,
                now=started + timedelta(seconds=5),
            )
            fail(permit_b1, 6)
            permit_b2 = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", now=started + timedelta(seconds=7),
            )
            fail(permit_b2, 8)
            with self.assertRaisesRegex(harness.HarnessError, "unchanged equivalent retry"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=9),
                )

            evidence_c = write_cause("C")
            permit_c = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L8-groups", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", causal_evidence=evidence_c,
                now=started + timedelta(seconds=9),
            )
            self.assertTrue(permit_c["permitted"])

    def test_replacement_retry_requires_new_worker_and_receipt_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_root = skill_with_retry_route(root, "replace_worker_changed_owner")
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            harness.open_window(
                db_path=db, install_root=install,
                source_script=skill_root / "scripts" / "deadline_harness.py",
                lineage_id="L8-replace", run_id="R", window_id="W",
                fs_root=specification(root), ledger={"tasks": [task("T", 60)]},
                now=started, start_watcher=False,
            )
            receipt = root / "receipt.json"
            artifact = root / "artifact.json"

            def evidence(cause: str, owner: str) -> dict:
                receipt.write_text(
                    json.dumps({"causal_class": cause, "owner": owner}) + "\n",
                    encoding="utf-8",
                )
                artifact.write_text(json.dumps({"failure": cause}) + "\n", encoding="utf-8")
                return harness.causal_evidence_binding(
                    receipt, {str(artifact): harness.digest_bytes(artifact.read_bytes())}
                )

            evidence("missing-tool", "owner/original")
            for attempt in range(2):
                permit = harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/original", now=started + timedelta(seconds=attempt * 2 + 1),
                )
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                    window_id="W", kind="task_failed",
                    payload={
                        "slot_id": "T", "worker_profile": "terra-high",
                        "worker_identity": "worker/original", "test_completed": True,
                        "test_result": "failed", "permit_event_hash": permit["permit_event_hash"],
                        "receipt_path": str(receipt),
                        "receipt_sha256": harness.digest_bytes(receipt.read_bytes()),
                        "artifact_hashes": {str(artifact): harness.digest_bytes(artifact.read_bytes())},
                    },
                    now=started + timedelta(seconds=attempt * 2 + 2),
                )
            with self.assertRaisesRegex(harness.HarnessError, "unchanged equivalent retry"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/original", now=started + timedelta(seconds=5),
                )
            changed_owner = evidence("installed-tool", "owner/replacement")
            with self.assertRaisesRegex(harness.HarnessError, "replacement worker and changed owner"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/original", causal_evidence=changed_owner,
                    now=started + timedelta(seconds=5),
                )
            changed_same_owner = evidence("installed-tool", "owner/original")
            with self.assertRaisesRegex(harness.HarnessError, "replacement worker and changed owner"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/replacement", causal_evidence=changed_same_owner,
                    now=started + timedelta(seconds=5),
                )
            changed_owner = evidence("installed-tool", "owner/replacement")
            permitted = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L8-replace", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/replacement", causal_evidence=changed_owner,
                now=started + timedelta(seconds=5),
            )
            self.assertTrue(permitted["permitted"])

    def test_both_conformance_routes_require_distinct_evidence_and_execute(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            routes = (
                "minimal_authoritative_conformance",
                "authoritative_owner_then_live_conformance",
            )
            for index, route in enumerate(routes):
                case_root = root / str(index)
                skill_root = case_root / "skill"
                shutil.copytree(
                    ROOT,
                    skill_root,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
                )
                proof_policy = skill_root / "policy" / "proof.json"
                policy = json.loads(proof_policy.read_text(encoding="utf-8"))
                policy["conformance_route"] = route
                proof_policy.write_text(json.dumps(policy), encoding="utf-8")
                fs_root = specification(case_root)
                proof = proof_binding(case_root, fs_root)
                db = case_root / "state.sqlite3"
                harness.open_window(
                    db_path=db, install_root=case_root / "install",
                    source_script=skill_root / "scripts" / "deadline_harness.py",
                    lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                    ledger={"tasks": [task("T", 20)], "proof": proof},
                    now=started, start_watcher=False,
                )

                other_route = routes[1 - index]
                policy["conformance_route"] = other_route
                proof_policy.write_text(json.dumps(policy), encoding="utf-8")
                with self.assertRaisesRegex(harness.HarnessError, "route|shape"):
                    harness.record_event(
                        db_path=db, install_root=case_root / "install", lineage_id="L",
                        run_id="R", window_id="W", kind="proof_reviewed",
                        payload=proof_review_payload(
                            case_root, proof, conformance_route=other_route
                        ),
                        now=started + timedelta(seconds=1),
                    )
                policy["conformance_route"] = route
                proof_policy.write_text(json.dumps(policy), encoding="utf-8")
                valid_review = proof_review_payload(
                    case_root, proof, conformance_route=route
                )
                receipt_path = Path(valid_review["receipt_path"])
                receipt_value = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt_value["conformance_route"] = other_route
                receipt_path.write_text(json.dumps(receipt_value), encoding="utf-8")
                mismatched_receipt = dict(
                    valid_review,
                    receipt_sha256=harness.digest_bytes(receipt_path.read_bytes()),
                )
                with self.assertRaisesRegex(harness.HarnessError, "receipt does not bind"):
                    harness.record_event(
                        db_path=db, install_root=case_root / "install", lineage_id="L",
                        run_id="R", window_id="W", kind="proof_reviewed",
                        payload=mismatched_receipt, now=started + timedelta(seconds=1),
                    )
                valid_review = proof_review_payload(
                    case_root, proof, conformance_route=route
                )
                if route == "authoritative_owner_then_live_conformance":
                    incomplete = dict(valid_review)
                    incomplete.pop("live_receipt_sha256")
                    with self.assertRaisesRegex(harness.HarnessError, "shape"):
                        harness.record_event(
                            db_path=db, install_root=case_root / "install", lineage_id="L",
                            run_id="R", window_id="W", kind="proof_reviewed",
                            payload=incomplete, now=started + timedelta(seconds=1),
                        )
                harness.record_event(
                    db_path=db, install_root=case_root / "install", lineage_id="L",
                    run_id="R", window_id="W", kind="proof_reviewed",
                    payload=valid_review, now=started + timedelta(seconds=1),
                )
                permit = harness.permit_dispatch(
                    db_path=db, install_root=case_root / "install", lineage_id="L",
                    run_id="R", window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=2),
                )
                connection = harness.connect(db)
                try:
                    rows = harness.events_for(connection, "L", "R", "W")
                    permit_payload = harness.event_payload(rows[-1])
                    tampered = dict(permit_payload, conformance_route=other_route)
                    with self.assertRaisesRegex(harness.HarnessError, "conformance_route"):
                        harness.validate_dispatch_event(
                            connection, "L", "R", "W", tampered, rows,
                            started + timedelta(seconds=3),
                        )
                finally:
                    connection.close()
                terminal = accepted_payload(case_root, "T", permit["permit_event_hash"])
                terminal["conformance_route"] = route
                harness.record_event(
                    db_path=db, install_root=case_root / "install", lineage_id="L",
                    run_id="R", window_id="W", kind="task_accepted", payload=terminal,
                    now=started + timedelta(seconds=4),
                )
                harness.record_event(
                    db_path=db, install_root=case_root / "install", lineage_id="L",
                    run_id="R", window_id="W", kind="completed", payload={},
                    now=started + timedelta(seconds=5),
                )
                result = harness.export_benchmark(
                    db_path=db, lineage_id="L", run_id="R", window_id="W"
                )
                self.assertEqual(result["provenance"]["conformance_route"], route)

    def test_authoritative_overfit_proof_plan_replacement_is_dispatchable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            original = {"tasks": [task("T", 20)], "proof": proof_binding(root, fs_root)}
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger=original, now=started, start_watcher=False,
            )
            replacement = {
                "tasks": [task("T", 20)],
                "proof": proof_binding(root, fs_root, seed=991, coordinates=(77, 12)),
            }
            revision = harness.revise_ledger(
                db_path=db, lineage_id="L", run_id="R", window_id="W",
                ledger=replacement, now=started + timedelta(seconds=1),
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="proof_reviewed",
                payload=proof_review_payload(root, replacement["proof"]),
                now=started + timedelta(seconds=2),
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="proof-worker/terra",
                now=started + timedelta(seconds=3),
            )
            self.assertTrue(permit["permitted"])
            self.assertEqual(revision["ledger_hash"], harness.digest_json(replacement))
            self.assertEqual(
                harness.benchmark_definition_hash(original),
                harness.benchmark_definition_hash(replacement),
            )

    def test_proof_revision_freezes_manifest_frontier_and_presence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            original = {"tasks": [task("T", 20)], "proof": proof_binding(root, fs_root)}
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger=original, now=started, start_watcher=False,
            )

            weakened = proof_binding(root, fs_root)
            weakened["contract"]["semantic_manifest"]["conditions"][0]["requirement"] = "weaker"
            removed_control = proof_binding(root, fs_root)
            removed = removed_control["contract"]["semantic_manifest"]["negative_controls"].pop()
            removed_control["plan"]["negative_control_artifacts"].pop(removed["id"])
            moved_frontier = proof_binding(root, fs_root)
            moved_frontier["contract"]["accepted_product_frontier"]["commit"] = "c" * 40

            for revised, message in (
                ({"tasks": [task("T", 20)], "proof": weakened}, "proof contract"),
                ({"tasks": [task("T", 20)], "proof": removed_control}, "proof contract"),
                ({"tasks": [task("T", 20)]}, "proof surface"),
                ({"tasks": [task("T", 20)], "proof": moved_frontier}, "proof contract"),
            ):
                with self.assertRaisesRegex(harness.HarnessError, message):
                    harness.revise_ledger(
                        db_path=db, lineage_id="L", run_id="R", window_id="W",
                        ledger=revised, now=started + timedelta(seconds=1),
                    )

            second_db = root / "second.sqlite3"
            harness.open_window(
                db_path=second_db, install_root=install, source_script=SOURCE,
                lineage_id="without-proof", run_id="R", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 20)]}, now=started, start_watcher=False,
            )
            with self.assertRaisesRegex(harness.HarnessError, "proof surface"):
                harness.revise_ledger(
                    db_path=second_db, lineage_id="without-proof", run_id="R", window_id="W",
                    ledger=original, now=started + timedelta(seconds=1),
                )

    def test_later_lineage_window_cannot_drop_or_change_proof_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            original_proof = proof_binding(root, fs_root)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R1", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 20)], "proof": original_proof},
                now=started, start_watcher=False,
            )
            changed = proof_binding(root, fs_root)
            changed["contract"]["authoritative_owner_route"] = "invented owner route"
            for run_id, ledger in (
                ("R2", {"tasks": [task("T", 20)]}),
                ("R3", {"tasks": [task("T", 20)], "proof": changed}),
            ):
                with self.assertRaisesRegex(harness.HarnessError, "proof_contract"):
                    harness.open_window(
                        db_path=db, install_root=install, source_script=SOURCE,
                        lineage_id="L", run_id=run_id, window_id="W", fs_root=fs_root,
                        ledger=ledger, now=started + timedelta(seconds=1),
                        start_watcher=False,
                    )

    def test_proof_and_benchmark_binding_require_one_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            proof = proof_binding(root, fs_root)
            binding = {
                "git": {
                    "worktree": str(root), "branch": "refs/heads/candidate",
                    "commit": "1" * 40, "tree": "2" * 40,
                },
                "product_frontier": {
                    "repository": "product/example", "commit": "c" * 40, "tree": "b" * 40,
                },
                "mutation": {
                    "target_failure_id": "failure", "changed_policy_keys": ["policy/proof.json.conformance_route"],
                    "expected_reduction": "repeated_work",
                },
            }
            with self.assertRaisesRegex(harness.HarnessError, "same accepted product frontier"):
                harness.validate_ledger(
                    {"tasks": [task("T", 20)], "proof": proof, "benchmark_binding": binding}
                )

    def test_closed_proof_plan_rejects_omitted_condition_or_control_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            for field in ("condition_artifacts", "negative_control_artifacts"):
                proof = proof_binding(root, fs_root)
                proof["plan"][field].pop(next(iter(proof["plan"][field])))
                with self.assertRaises(harness.HarnessError):
                    harness.validate_ledger({"tasks": [task("T", 1)], "proof": proof})

    def test_proof_dispatch_requires_closed_plan_separate_review_and_distinct_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            proof = proof_binding(root, fs_root)
            ledger = {"tasks": [task("T", 10)], "proof": proof}
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            db = root / "state.sqlite3"
            install = root / "install"
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger=ledger, now=started, start_watcher=False,
            )
            with self.assertRaisesRegex(harness.HarnessError, "separate authoritative review"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="proof-worker/terra", now=started,
                )

            open_plan = proof_binding(root, fs_root)
            open_plan["plan"]["force_pass"] = True
            with self.assertRaisesRegex(harness.HarnessError, "open shape"):
                harness.validate_ledger({"tasks": [task("T", 1)], "proof": open_plan})

            for field, value, message in (
                ("helper_or_mock_only", True, "mock-only"),
                ("direct_outcome_setting", True, "direct outcome"),
                ("reviewer_identity", "plan-author/xhigh", "distinct"),
            ):
                review = proof_review_payload(root, proof)
                review[field] = value
                with self.assertRaisesRegex(harness.HarnessError, message):
                    harness.record_event(
                        db_path=db, install_root=install, lineage_id="L", run_id="R",
                        window_id="W", kind="proof_reviewed", payload=review,
                        now=started + timedelta(seconds=1),
                    )

            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="proof_reviewed", payload=proof_review_payload(root, proof),
                now=started + timedelta(seconds=1),
            )
            with self.assertRaisesRegex(harness.HarnessError, "distinct"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="plan-author/xhigh", now=started + timedelta(seconds=2),
                )

    def test_proof_dispatch_rejects_changed_core_or_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            proof = proof_binding(root, fs_root)
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            db = root / "state.sqlite3"
            install = root / "install"
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 10)], "proof": proof},
                now=started, start_watcher=False,
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="proof_reviewed", payload=proof_review_payload(root, proof),
                now=started,
            )
            fs_root.write_text("# changed semantic core\n", encoding="utf-8")
            with self.assertRaisesRegex(harness.HarnessError, "semantic core"):
                harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="proof-worker/terra", now=started,
                )

            fs_root.write_text("# Frozen functional specification\n", encoding="utf-8")
            changed = proof_binding(root, fs_root)
            changed["contract"]["accepted_product_frontier"]["commit"] = "c" * 40
            with self.assertRaisesRegex(harness.HarnessError, "proof contract"):
                harness.revise_ledger(
                    db_path=db, lineage_id="L", run_id="R", window_id="W",
                    ledger={"tasks": [task("T", 10)], "proof": changed}, now=started,
                )

    def test_reviewed_proof_artifact_mutation_is_rejected_at_terminal_acceptance(self) -> None:
        for kind in sorted(harness.PROOF_ARTIFACT_KINDS):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fs_root = specification(root)
                proof = proof_binding(root, fs_root)
                started = datetime(2026, 8, 9, tzinfo=timezone.utc)
                db = root / "state.sqlite3"
                install = root / "install"
                harness.open_window(
                    db_path=db, install_root=install, source_script=SOURCE,
                    lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                    ledger={"tasks": [task("T", 10)], "proof": proof},
                    now=started, start_watcher=False,
                )
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", kind="proof_reviewed",
                    payload=proof_review_payload(root, proof), now=started,
                )
                permit = harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=1),
                )
                artifact = Path(next(iter(proof["plan"]["artifacts"][kind])))
                artifact.write_bytes(artifact.read_bytes() + b"changed\n")
                terminal = accepted_payload(root, "T", permit["permit_event_hash"])
                terminal["conformance_route"] = "minimal_authoritative_conformance"
                with self.assertRaisesRegex(
                    harness.HarnessError, f"Proof {kind} artifact hash mismatch"
                ):
                    harness.record_event(
                        db_path=db, install_root=install, lineage_id="L", run_id="R",
                        window_id="W", kind="task_accepted", payload=terminal,
                        now=started + timedelta(seconds=2),
                    )

    def test_terminal_proof_artifact_mutation_is_rejected_at_benchmark_export(self) -> None:
        for kind in sorted(harness.PROOF_ARTIFACT_KINDS):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fs_root = specification(root)
                proof = proof_binding(root, fs_root)
                started = datetime(2026, 8, 9, tzinfo=timezone.utc)
                db = root / "state.sqlite3"
                install = root / "install"
                harness.open_window(
                    db_path=db, install_root=install, source_script=SOURCE,
                    lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                    ledger={"tasks": [task("T", 10)], "proof": proof},
                    now=started, start_watcher=False,
                )
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", kind="proof_reviewed",
                    payload=proof_review_payload(root, proof), now=started,
                )
                permit = harness.permit_dispatch(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", slot_id="T", worker_profile="terra-high",
                    worker_identity="worker/T", now=started + timedelta(seconds=1),
                )
                terminal = accepted_payload(root, "T", permit["permit_event_hash"])
                terminal["conformance_route"] = "minimal_authoritative_conformance"
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", kind="task_accepted", payload=terminal,
                    now=started + timedelta(seconds=2),
                )
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", kind="completed", payload={},
                    now=started + timedelta(seconds=3),
                )
                artifact = Path(next(iter(proof["plan"]["artifacts"][kind])))
                artifact.write_bytes(artifact.read_bytes() + b"changed\n")
                with self.assertRaisesRegex(
                    harness.HarnessError, f"Proof {kind} artifact hash mismatch"
                ):
                    harness.export_benchmark(
                        db_path=db, lineage_id="L", run_id="R", window_id="W"
                    )

    def test_unchanged_reviewed_proof_artifacts_pass_terminal_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            proof = proof_binding(root, fs_root)
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            db = root / "state.sqlite3"
            install = root / "install"
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 10)], "proof": proof},
                now=started, start_watcher=False,
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="proof_reviewed",
                payload=proof_review_payload(root, proof), now=started,
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", now=started + timedelta(seconds=1),
            )
            terminal = accepted_payload(root, "T", permit["permit_event_hash"])
            terminal["conformance_route"] = "minimal_authoritative_conformance"
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="task_accepted", payload=terminal,
                now=started + timedelta(seconds=2),
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R",
                window_id="W", kind="completed", payload={},
                now=started + timedelta(seconds=3),
            )
            result = harness.export_benchmark(
                db_path=db, lineage_id="L", run_id="R", window_id="W"
            )
            self.assertTrue(all(result["quality"].values()))

    def test_zero_dispatch_and_accepted_execution_cannot_qualify_as_proof_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            db = root / "state.sqlite3"
            install = root / "install"
            epoch = datetime(2026, 8, 9, tzinfo=timezone.utc)
            proof = proof_binding(root, fs_root)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="zero", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 1)], "proof": proof},
                now=epoch, start_watcher=False,
            )
            connection = harness.connect(db)
            harness.expire_window(
                connection=connection, install_root=install, lineage_id="L",
                run_id="zero", window_id="W", now=epoch + timedelta(seconds=2),
            )
            zero_miss = harness.lineage_miss_rows(connection, "L")[-1]["event_hash"]
            connection.close()
            zero_payload = proof_damage_payload(
                root, proof, zero_miss, "1" * 64, "2" * 64
            )
            with self.assertRaisesRegex(harness.HarnessError, "reviewed permit and real task_failed"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="zero",
                    window_id="W", kind="damage_assessment", payload=zero_payload,
                    now=epoch + timedelta(seconds=3),
                )

            started = epoch + timedelta(seconds=10)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="accepted", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 1)], "proof": proof},
                now=started, start_watcher=False,
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="accepted",
                window_id="W", kind="proof_reviewed", payload=proof_review_payload(root, proof),
                now=started,
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L", run_id="accepted",
                window_id="W", slot_id="T", worker_profile="terra-high",
                worker_identity="worker/T", now=started,
            )
            connection = harness.connect(db)
            harness.expire_window(
                connection=connection, install_root=install, lineage_id="L",
                run_id="accepted", window_id="W", now=started + timedelta(seconds=2),
            )
            accepted_miss = harness.lineage_miss_rows(connection, "L")[-1]["event_hash"]
            connection.close()
            accepted_task = accepted_payload(root, "T", permit["permit_event_hash"])
            accepted_task["conformance_route"] = "minimal_authoritative_conformance"
            accepted = harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="accepted",
                window_id="W", kind="task_accepted",
                payload=accepted_task,
                now=started + timedelta(seconds=3),
            )
            accepted_damage = proof_damage_payload(
                root, proof, accepted_miss, permit["permit_event_hash"], accepted["event_hash"]
            )
            with self.assertRaisesRegex(harness.HarnessError, "real task_failed"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="accepted",
                    window_id="W", kind="damage_assessment", payload=accepted_damage,
                    now=started + timedelta(seconds=4),
                )

    def test_reviewed_failed_proof_execution_gets_derived_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fs_root = specification(root)
            db = root / "state.sqlite3"
            install = root / "install"
            started = datetime(2026, 8, 9, tzinfo=timezone.utc)
            proof = proof_binding(root, fs_root)
            harness.open_window(
                db_path=db, install_root=install, source_script=SOURCE,
                lineage_id="L", run_id="R", window_id="W", fs_root=fs_root,
                ledger={"tasks": [task("T", 1)], "proof": proof},
                now=started, start_watcher=False,
            )
            harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R", window_id="W",
                kind="proof_reviewed", payload=proof_review_payload(root, proof), now=started,
            )
            permit = harness.permit_dispatch(
                db_path=db, install_root=install, lineage_id="L", run_id="R", window_id="W",
                slot_id="T", worker_profile="terra-high", worker_identity="worker/T", now=started,
            )
            connection = harness.connect(db)
            harness.expire_window(
                connection=connection, install_root=install, lineage_id="L", run_id="R",
                window_id="W", now=started + timedelta(seconds=2),
            )
            miss_hash = harness.lineage_miss_rows(connection, "L")[-1]["event_hash"]
            connection.close()
            failure = accepted_payload(root, "T", permit["permit_event_hash"])
            failure["test_result"] = "failed"
            failure["conformance_route"] = "minimal_authoritative_conformance"
            wrong_worker = dict(failure, worker_identity="different-worker")
            with self.assertRaisesRegex(harness.HarnessError, "identity differs"):
                harness.record_event(
                    db_path=db, install_root=install, lineage_id="L", run_id="R",
                    window_id="W", kind="task_failed", payload=wrong_worker,
                    now=started + timedelta(seconds=3),
                )
            failed = harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R", window_id="W",
                kind="task_failed", payload=failure, now=started + timedelta(seconds=3),
            )
            damage = proof_damage_payload(
                root, proof, miss_hash, permit["permit_event_hash"], failed["event_hash"]
            )
            recorded = harness.record_event(
                db_path=db, install_root=install, lineage_id="L", run_id="R", window_id="W",
                kind="damage_assessment", payload=damage, now=started + timedelta(seconds=4),
            )
            self.assertTrue(harness.valid_sha256(recorded["event_hash"]))

            forged = dict(damage, causal_fingerprint="f" * 64)
            connection = harness.connect(db)
            try:
                rows = harness.events_for(connection, "L", "R", "W")
                with self.assertRaises(harness.HarnessError):
                    harness.validate_damage_assessment(
                        connection, "L", "R", "W", forged, rows[:-1]
                    )
            finally:
                connection.close()

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
            self.assertEqual(result["provenance"]["producer"], "de67-deadline-harness/0.2.0")
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
