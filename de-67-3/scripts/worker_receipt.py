#!/usr/bin/env python3
"""Validate and compact durable DE-67 worker result receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "de67.worker-result-receipt.v1"
DISPOSITIONS = {"checkpoint", "completed", "finding", "abandoned"}


class WorkerReceiptError(RuntimeError):
    """Raised when a worker receipt could not preserve its claimed evidence."""


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise WorkerReceiptError(f"{name} must be text")
    result = value.strip()
    if not result and not allow_empty:
        raise WorkerReceiptError(f"{name} must not be empty")
    return result


def _text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise WorkerReceiptError(f"{name} must be a list")
    return [_text(item, f"{name} item") for item in value]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(
    value: Any, name: str, workspace: Path | None,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise WorkerReceiptError(f"{name} must be an object")
    path_text = _text(value.get("path"), f"{name}.path")
    digest = _text(value.get("sha256"), f"{name}.sha256").lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise WorkerReceiptError(f"{name}.sha256 must be lowercase SHA-256")
    role = _text(value.get("role"), f"{name}.role")
    if workspace is not None:
        root = workspace.resolve()
        path = Path(path_text)
        resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as error:
            raise WorkerReceiptError(f"{name}.path must stay inside the workspace") from error
        if not resolved.is_file():
            raise WorkerReceiptError(f"{name}.path is not a file: {relative}")
        if _sha256(resolved) != digest:
            raise WorkerReceiptError(f"{name}.sha256 does not match {relative}")
        path_text = relative.as_posix()
    return {"path": path_text, "sha256": digest, "role": role}


def normalize_worker_receipt(
    value: Any,
    *,
    lineage_id: str,
    task_id: str,
    claim_id: str,
    worker_id: str,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Return one canonical receipt after identity and artifact validation."""

    if not isinstance(value, Mapping):
        raise WorkerReceiptError("Worker receipt must be an object")
    if value.get("schema") != SCHEMA:
        raise WorkerReceiptError(f"Worker receipt schema must be {SCHEMA}")
    expected = {
        "lineage_id": lineage_id,
        "task_id": task_id,
        "claim_id": claim_id,
        "worker_id": worker_id,
    }
    for field, expected_value in expected.items():
        actual = _text(value.get(field), field)
        if actual != expected_value:
            raise WorkerReceiptError(
                f"Worker receipt {field} mismatch: expected {expected_value}, got {actual}"
            )
    disposition = _text(value.get("disposition"), "disposition")
    if disposition not in DISPOSITIONS:
        raise WorkerReceiptError(
            "disposition must be checkpoint, completed, finding, or abandoned"
        )
    verdict = _text(value.get("verdict"), "verdict")
    finding_kind_value = value.get("finding_kind")
    finding_kind: str | None = None
    if disposition == "finding":
        finding_kind = _text(finding_kind_value, "finding_kind")
        if finding_kind not in {"blocker", "unexpected"}:
            raise WorkerReceiptError("finding_kind must be blocker or unexpected")
    elif finding_kind_value is not None:
        raise WorkerReceiptError("finding_kind is only valid for a finding receipt")
    outcome = _text(value.get("outcome"), "outcome")
    summary = _text(value.get("summary"), "summary")
    material_changes = _text_list(value.get("material_changes"), "material_changes")
    tests = _text_list(value.get("tests"), "tests")
    live_actions = _text_list(value.get("live_actions"), "live_actions")
    evidence_ceiling = _text_list(value.get("evidence_ceiling"), "evidence_ceiling")
    accepted_no_replay = _text_list(
        value.get("accepted_no_replay"), "accepted_no_replay"
    )
    active_work = _text_list(value.get("active_work"), "active_work")
    narrow_queries = _text_list(value.get("narrow_queries"), "narrow_queries")
    entrypoints = _text_list(value.get("entrypoints"), "entrypoints")
    first_open_boundary = _text(
        value.get("first_open_boundary"), "first_open_boundary", allow_empty=True
    )
    if disposition in {"checkpoint", "abandoned"} and not first_open_boundary:
        raise WorkerReceiptError(
            f"{disposition} receipt requires a first_open_boundary"
        )

    bindings_value = value.get("bindings")
    if not isinstance(bindings_value, Mapping):
        raise WorkerReceiptError("bindings must be an object")
    bindings = {
        _text(key, "binding key"): _text(item, f"bindings.{key}")
        for key, item in bindings_value.items()
    }

    artifacts_value = value.get("artifacts")
    if not isinstance(artifacts_value, list):
        raise WorkerReceiptError("artifacts must be a list")
    artifacts = [
        _artifact(item, f"artifacts[{index}]", workspace)
        for index, item in enumerate(artifacts_value)
    ]
    artifact_paths = {item["path"] for item in artifacts}

    entries_value = value.get("journal_entries")
    if not isinstance(entries_value, list):
        raise WorkerReceiptError("journal_entries must be a list")
    journal_entries: list[dict[str, str]] = []
    allowed_entry_fields = {
        "id", "sequence", "event_type", "evidence_class", "actor_id",
        "action_id", "receipt_id", "artifact_ref", "summary",
    }
    for index, item in enumerate(entries_value):
        if not isinstance(item, Mapping):
            raise WorkerReceiptError(f"journal_entries[{index}] must be an object")
        unknown = set(item) - allowed_entry_fields
        if unknown:
            raise WorkerReceiptError(
                f"journal_entries[{index}] has unsupported fields: {sorted(unknown)}"
            )
        sequence_value = item.get("sequence")
        if isinstance(sequence_value, bool) or not isinstance(
            sequence_value, (int, str)
        ):
            raise WorkerReceiptError(
                f"journal_entries[{index}].sequence must be an integer or text"
            )
        entry = {
            "id": _text(item.get("id"), f"journal_entries[{index}].id"),
            "sequence": _text(
                str(sequence_value), f"journal_entries[{index}].sequence"
            ),
            "event_type": _text(
                item.get("event_type"), f"journal_entries[{index}].event_type"
            ),
            "evidence_class": _text(
                item.get("evidence_class"),
                f"journal_entries[{index}].evidence_class",
            ),
            "summary": _text(
                item.get("summary"), f"journal_entries[{index}].summary"
            ),
        }
        for field in ("actor_id", "action_id", "receipt_id", "artifact_ref"):
            if field in item and str(item[field]).strip():
                entry[field] = _text(item[field], f"journal_entries[{index}].{field}")
        if "artifact_ref" in entry and entry["artifact_ref"] not in artifact_paths:
            raise WorkerReceiptError(
                f"journal_entries[{index}].artifact_ref is not in artifacts"
            )
        journal_entries.append(entry)

    divergence_value = value.get("first_divergence")
    first_divergence: dict[str, str] | None
    if divergence_value is None:
        first_divergence = None
    elif isinstance(divergence_value, Mapping):
        first_divergence = {
            "class": _text(divergence_value.get("class"), "first_divergence.class"),
            "summary": _text(
                divergence_value.get("summary"), "first_divergence.summary"
            ),
        }
    else:
        raise WorkerReceiptError("first_divergence must be null or an object")

    context_metrics = value.get("context_metrics", {})
    if not isinstance(context_metrics, Mapping):
        raise WorkerReceiptError("context_metrics must be an object")
    normalized_metrics: dict[str, int | float | str] = {}
    for key, item in context_metrics.items():
        metric = _text(key, "context metric key")
        if not isinstance(item, (int, float, str)) or isinstance(item, bool):
            raise WorkerReceiptError(f"context_metrics.{metric} must be scalar")
        normalized_metrics[metric] = item.strip() if isinstance(item, str) else item

    normalized = {
        "schema": SCHEMA,
        **expected,
        "disposition": disposition,
        "verdict": verdict,
        "outcome": outcome,
        "summary": summary,
        "material_changes": material_changes,
        "tests": tests,
        "live_actions": live_actions,
        "evidence_ceiling": evidence_ceiling,
        "bindings": dict(sorted(bindings.items())),
        "journal_entries": journal_entries,
        "artifacts": artifacts,
        "first_divergence": first_divergence,
        "accepted_no_replay": accepted_no_replay,
        "active_work": active_work,
        "first_open_boundary": first_open_boundary,
        "narrow_queries": narrow_queries,
        "entrypoints": entrypoints,
        "context_metrics": dict(sorted(normalized_metrics.items())),
    }
    if finding_kind is not None:
        normalized["finding_kind"] = finding_kind
    return normalized


def receipt_id(receipt: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def receipt_envelope(receipt: Mapping[str, Any]) -> dict[str, Any]:
    return {"receipt_id": receipt_id(receipt), "receipt": dict(receipt)}


def compact_worker_receipt(
    receipt: Mapping[str, Any], *, recorded_at: float | None = None,
) -> dict[str, Any]:
    artifacts = receipt.get("artifacts", [])
    entries = receipt.get("journal_entries", [])
    result: dict[str, Any] = {
        "receipt_id": receipt_id(receipt),
        "claim_id": receipt["claim_id"],
        "task_id": receipt["task_id"],
        "worker_id": receipt["worker_id"],
        "disposition": receipt["disposition"],
        "finding_kind": receipt.get("finding_kind"),
        "verdict": receipt["verdict"],
        "summary": receipt["summary"],
        "bindings": receipt["bindings"],
        "first_divergence": receipt["first_divergence"],
        "accepted_no_replay": receipt["accepted_no_replay"],
        "active_work": receipt["active_work"],
        "first_open_boundary": receipt["first_open_boundary"],
        "narrow_queries": receipt["narrow_queries"],
        "entrypoints": receipt["entrypoints"],
        "journal_entry_ids": [item["id"] for item in entries],
        "artifact_refs": [
            {"path": item["path"], "sha256": item["sha256"], "role": item["role"]}
            for item in artifacts
        ],
    }
    if recorded_at is not None:
        result["recorded_at"] = recorded_at
    return result
