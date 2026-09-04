from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from worker_receipt import (  # noqa: E402
    WorkerReceiptError,
    compact_worker_receipt,
    normalize_worker_receipt,
)


class WorkerReceiptTests(unittest.TestCase):
    def value(self, artifact: Path, digest: str) -> dict[str, object]:
        return {
            "schema": "de67.worker-result-receipt.v1",
            "lineage_id": "project",
            "task_id": "task-1",
            "claim_id": "R-1",
            "worker_id": "worker-1",
            "disposition": "checkpoint",
            "verdict": "continuation",
            "outcome": "Prove the next live boundary.",
            "summary": "The exact footing and next boundary are preserved.",
            "material_changes": [],
            "tests": ["The compact projection was validated."],
            "live_actions": [],
            "evidence_ceiling": ["No product closure is claimed."],
            "bindings": {"run_id": "run-1"},
            "journal_entries": [
                {
                    "id": "event-1",
                    "sequence": 1,
                    "event_type": "observation",
                    "evidence_class": "live",
                    "artifact_ref": artifact.name,
                    "summary": "The first live boundary was observed.",
                }
            ],
            "artifacts": [
                {"path": artifact.name, "sha256": digest, "role": "full transcript"}
            ],
            "first_divergence": {
                "class": "next-boundary",
                "summary": "The next causal response is still open.",
            },
            "accepted_no_replay": ["Do not replay event-1."],
            "active_work": ["Observe the next causal response."],
            "first_open_boundary": "Observe the next causal response.",
            "narrow_queries": ["event_type=observation"],
            "entrypoints": ["src/route.cpp"],
            "context_metrics": {"source_bytes": 42},
        }

    def test_compact_projection_preserves_bindings_and_digest_not_full_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            artifact = workspace / "transcript.jsonl"
            artifact.write_text('{"event":"ready"}\n', encoding="utf-8")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            receipt = normalize_worker_receipt(
                self.value(artifact, digest),
                lineage_id="project",
                task_id="task-1",
                claim_id="R-1",
                worker_id="worker-1",
                workspace=workspace,
            )
            compact = compact_worker_receipt(receipt)
            self.assertEqual(compact["bindings"]["run_id"], "run-1")
            self.assertEqual(compact["artifact_refs"][0]["sha256"], digest)
            self.assertEqual(compact["journal_entry_ids"], ["event-1"])
            self.assertNotIn("journal_entries", compact)

    def test_digest_mismatch_and_missing_open_boundary_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            artifact = workspace / "transcript.jsonl"
            artifact.write_text('{"event":"ready"}\n', encoding="utf-8")
            value = self.value(artifact, "0" * 64)
            with self.assertRaisesRegex(WorkerReceiptError, "does not match"):
                normalize_worker_receipt(
                    value,
                    lineage_id="project",
                    task_id="task-1",
                    claim_id="R-1",
                    worker_id="worker-1",
                    workspace=workspace,
                )
            value["artifacts"] = []
            value["journal_entries"] = []
            value["first_open_boundary"] = ""
            with self.assertRaisesRegex(WorkerReceiptError, "first_open_boundary"):
                normalize_worker_receipt(
                    value,
                    lineage_id="project",
                    task_id="task-1",
                    claim_id="R-1",
                    worker_id="worker-1",
                )


if __name__ == "__main__":
    unittest.main()
