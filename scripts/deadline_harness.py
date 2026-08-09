#!/usr/bin/env python3
"""Persistent, tamper-evident deadline clock for DE67 ledger windows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any


VERSION = "0.3.0"
ZERO_HASH = "0" * 64
WINDOW_CEILING = 10
COORDINATOR_REVIEW_THRESHOLD = 3
EVENT_KINDS = {
    "progress",
    "receipt_rejected",
    "receipt_resealed",
    "task_accepted",
    "task_failed",
    "proof_reviewed",
    "preflight_blocked",
    "coordinator_review_completed",
    "damage_assessment",
    "completed",
}


class HarnessError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise HarnessError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical(value).encode("utf-8"))


def receipt_semantics(path: Any) -> Any:
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        raise HarnessError("Causal evidence requires a receipt path")
    data = Path(path).read_bytes()
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"normalized_text_sha256": digest_bytes(b" ".join(data.split()))}


def causal_evidence_binding(receipt_path: Any, artifact_hashes: Any) -> dict[str, Any]:
    if not isinstance(artifact_hashes, dict) or not artifact_hashes:
        raise HarnessError("Causal evidence requires artifact hashes")
    hashes = sorted(artifact_hashes.values())
    if not all(valid_sha256(value) for value in hashes):
        raise HarnessError("Causal evidence requires artifact SHA-256s")
    return {"receipt": receipt_semantics(receipt_path), "artifact_sha256s": hashes}


def validate_causal_evidence_binding(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"receipt", "artifact_sha256s"}:
        raise HarnessError("Retry causal evidence has an incomplete or open shape")
    hashes = value["artifact_sha256s"]
    if (
        not isinstance(hashes, list)
        or not hashes
        or hashes != sorted(hashes)
        or not all(valid_sha256(item) for item in hashes)
    ):
        raise HarnessError("Retry causal evidence requires sorted artifact SHA-256s")


def default_install_root() -> Path:
    codex_root = os.environ.get("CODEX_HOME")
    base = Path(codex_root) if codex_root else Path.home() / ".codex"
    return base / "de67-lab"


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def stated_provenance(value: Any) -> bool:
    if non_empty_text(value):
        return True
    return isinstance(value, dict) and bool(value)


def task_obligation(task: dict[str, Any]) -> dict[str, Any]:
    pass_evidence_digest = digest_json(
        {
            "pass_test": task["pass_test"],
            "evidence_requirements": task["evidence_requirements"],
        }
    )
    binding = {
        "slot_id": task["id"],
        "claim_id": task["claim_id"],
        "intended_task": task["intended_task"],
        "owner": task["owner"],
        "worker_profile": task["worker_profile"],
        "preconditions": task["preconditions"],
        "depends_on": task["depends_on"],
        "authoritative_route": task["authoritative_route"],
        "pass_evidence_digest": pass_evidence_digest,
    }
    binding["obligation_digest"] = digest_json(binding)
    return binding


def obligation_map(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["claim_id"]: task_obligation(task) for task in ledger["tasks"]}


def valid_git_object_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def validate_benchmark_binding(binding: Any) -> None:
    if not isinstance(binding, dict):
        raise HarnessError("benchmark_binding must be an object")
    git = binding.get("git")
    if not isinstance(git, dict):
        raise HarnessError("benchmark_binding.git is required")
    for field in ("worktree", "branch"):
        if not non_empty_text(git.get(field)):
            raise HarnessError(f"benchmark_binding.git.{field} is required")
    for field in ("commit", "tree"):
        if not valid_git_object_id(git.get(field)):
            raise HarnessError(f"benchmark_binding.git.{field} must be a Git object id")
    frontier = binding.get("product_frontier")
    if not isinstance(frontier, dict) or not non_empty_text(frontier.get("repository")):
        raise HarnessError("benchmark_binding.product_frontier.repository is required")
    for field in ("commit", "tree"):
        if not valid_git_object_id(frontier.get(field)):
            raise HarnessError(
                f"benchmark_binding.product_frontier.{field} must be a Git object id"
            )
    mutation = binding.get("mutation")
    if not isinstance(mutation, dict):
        raise HarnessError("benchmark_binding.mutation is required")
    for field in ("target_failure_id", "expected_reduction"):
        if not non_empty_text(mutation.get(field)):
            raise HarnessError(f"benchmark_binding.mutation.{field} is required")
    keys = mutation.get("changed_policy_keys")
    if not isinstance(keys, list) or not keys or not all(non_empty_text(key) for key in keys):
        raise HarnessError("benchmark_binding.mutation.changed_policy_keys must be non-empty")
    if keys != sorted(set(keys)):
        raise HarnessError("benchmark_binding mutation policy keys must be unique and sorted")


PROOF_ARTIFACT_KINDS = {"source", "binary", "fixture", "test"}


def manifest_ids(items: Any, label: str) -> list[str]:
    if not isinstance(items, list) or not items:
        raise HarnessError(f"proof.semantic_manifest.{label} must be non-empty")
    ids: list[str] = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "requirement"}:
            raise HarnessError(f"Each proof {label} entry requires only id and requirement")
        if not non_empty_text(item.get("id")) or not non_empty_text(item.get("requirement")):
            raise HarnessError(f"Each proof {label} entry requires id and requirement")
        ids.append(item["id"])
    if ids != sorted(set(ids)):
        raise HarnessError(f"proof {label} ids must be unique and sorted")
    return ids


def validate_proof_contract(contract: Any) -> None:
    if not isinstance(contract, dict) or set(contract) != {
        "semantic_manifest", "accepted_product_frontier", "authoritative_owner_route"
    }:
        raise HarnessError("proof contract has an incomplete or open shape")
    manifest = contract["semantic_manifest"]
    if not isinstance(manifest, dict) or set(manifest) != {"conditions", "negative_controls"}:
        raise HarnessError("proof contract semantic_manifest requires conditions and negative_controls")
    manifest_ids(manifest["conditions"], "conditions")
    manifest_ids(manifest["negative_controls"], "negative_controls")
    frontier = contract["accepted_product_frontier"]
    if not isinstance(frontier, dict) or not non_empty_text(frontier.get("repository")):
        raise HarnessError("proof accepted product frontier requires repository")
    for field in ("commit", "tree"):
        if not valid_git_object_id(frontier.get(field)):
            raise HarnessError(f"proof accepted product frontier requires Git {field}")
    if not non_empty_text(contract["authoritative_owner_route"]):
        raise HarnessError("proof contract requires authoritative_owner_route")


def validate_proof_plan(plan: Any, contract: dict[str, Any]) -> None:
    required = {
        "version", "author_identity", "seed", "coordinates", "artifacts",
        "condition_artifacts", "negative_control_artifacts",
    }
    if not isinstance(plan, dict) or set(plan) != required:
        raise HarnessError("proof plan has an incomplete or open shape")
    if plan.get("version") != 1 or not non_empty_text(plan.get("author_identity")):
        raise HarnessError("proof plan requires version=1 and author_identity")
    seed = plan.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, (str, int)) or (isinstance(seed, str) and not seed.strip()):
        raise HarnessError("proof plan seed must be a non-empty string or integer")
    coordinates = plan.get("coordinates")
    if (
        not isinstance(coordinates, list)
        or len(coordinates) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in coordinates)
    ):
        raise HarnessError("proof plan coordinates must contain two finite numbers")
    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != PROOF_ARTIFACT_KINDS:
        raise HarnessError("proof plan requires exact source/binary/fixture/test artifacts")
    for kind, bindings in artifacts.items():
        if not isinstance(bindings, dict) or not bindings:
            raise HarnessError(f"proof plan {kind} artifacts must be non-empty")
        if not all(non_empty_text(path) and valid_sha256(value) for path, value in bindings.items()):
            raise HarnessError(f"proof plan {kind} artifacts require path to SHA-256 bindings")
    artifact_paths = {path for bindings in artifacts.values() for path in bindings}
    manifest = contract["semantic_manifest"]
    expected_mappings = {
        "condition_artifacts": manifest_ids(manifest["conditions"], "conditions"),
        "negative_control_artifacts": manifest_ids(
            manifest["negative_controls"], "negative_controls"
        ),
    }
    for field, identifiers in expected_mappings.items():
        mappings = plan[field]
        if not isinstance(mappings, dict) or sorted(mappings) != identifiers:
            raise HarnessError(f"proof plan {field} must exactly cover the frozen manifest")
        for identifier, references in mappings.items():
            if (
                not isinstance(references, list)
                or not references
                or references != sorted(set(references))
                or any(reference not in artifact_paths for reference in references)
            ):
                raise HarnessError(
                    f"proof plan {field}.{identifier} must reference exact bound artifacts"
                )


def validate_proof_shape(proof: Any) -> None:
    if not isinstance(proof, dict) or set(proof) != {"contract", "plan"}:
        raise HarnessError("proof requires exactly contract and plan")
    validate_proof_contract(proof["contract"])
    validate_proof_plan(proof["plan"], proof["contract"])


def proof_contract(ledger: dict[str, Any]) -> dict[str, Any] | None:
    proof = ledger.get("proof")
    return proof["contract"] if isinstance(proof, dict) else None


def benchmark_definition_hash(ledger: dict[str, Any]) -> str:
    normalized = json.loads(canonical(ledger))
    binding = normalized.get("benchmark_binding")
    if isinstance(binding, dict):
        binding.pop("git", None)
    proof = normalized.get("proof")
    if isinstance(proof, dict):
        proof.pop("plan", None)
    return digest_json(normalized)


def validate_ledger(ledger: dict[str, Any], ceiling: int = WINDOW_CEILING) -> dict[str, Any]:
    tasks = ledger.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise HarnessError("Ledger must contain at least one task")
    if len(tasks) > ceiling:
        raise HarnessError(f"Ledger contains {len(tasks)} tasks; ceiling is {ceiling}")

    required = {
        "id",
        "intended_task",
        "pass_test",
        "worker_profile",
        "estimate_seconds",
        "estimate_provenance",
        "depends_on",
        "claim_id",
        "owner",
        "preconditions",
        "authoritative_route",
        "evidence_requirements",
    }
    by_id: dict[str, dict[str, Any]] = {}
    claim_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise HarnessError("Each ledger task must be an object")
        missing = sorted(required - set(task))
        if missing:
            raise HarnessError(f"Ledger task is missing fields: {', '.join(missing)}")
        task_id = task["id"]
        if not isinstance(task_id, str) or not task_id.strip():
            raise HarnessError("Task id must be a non-empty string")
        if task_id in by_id:
            raise HarnessError(f"Duplicate task id: {task_id}")
        for field in (
            "intended_task",
            "pass_test",
            "worker_profile",
            "claim_id",
            "owner",
            "authoritative_route",
        ):
            if not non_empty_text(task[field]):
                raise HarnessError(f"{task_id}.{field} must be a non-empty string")
        if task["claim_id"] in claim_ids:
            raise HarnessError(f"Duplicate stable claim id: {task['claim_id']}")
        claim_ids.add(task["claim_id"])
        estimate = task["estimate_seconds"]
        if (
            isinstance(estimate, bool)
            or not isinstance(estimate, (int, float))
            or not math.isfinite(estimate)
            or estimate <= 0
        ):
            raise HarnessError(f"{task_id}.estimate_seconds must be positive and finite")
        if not stated_provenance(task["estimate_provenance"]):
            raise HarnessError(f"{task_id}.estimate_provenance must state its source")
        if not isinstance(task["depends_on"], list) or not all(
            non_empty_text(dep) for dep in task["depends_on"]
        ):
            raise HarnessError(f"{task_id}.depends_on must be a list of task ids")
        if len(task["depends_on"]) != len(set(task["depends_on"])):
            raise HarnessError(f"{task_id}.depends_on contains duplicates")
        if not isinstance(task["preconditions"], list) or not all(
            non_empty_text(precondition) for precondition in task["preconditions"]
        ):
            raise HarnessError(f"{task_id}.preconditions must be a list of non-empty strings")
        evidence_requirements = task["evidence_requirements"]
        if not isinstance(evidence_requirements, (dict, list)) or not evidence_requirements:
            raise HarnessError(f"{task_id}.evidence_requirements must be a non-empty object or list")
        by_id[task_id] = task

    for task_id, task in by_id.items():
        unknown = sorted(set(task["depends_on"]) - set(by_id))
        if unknown:
            raise HarnessError(f"{task_id} has unknown dependencies: {', '.join(unknown)}")

    reserve = ledger.get("reserve_seconds", 0)
    if (
        isinstance(reserve, bool)
        or not isinstance(reserve, (int, float))
        or not math.isfinite(reserve)
        or reserve < 0
    ):
        raise HarnessError("reserve_seconds must be non-negative and finite")
    if "reserve_seconds" in ledger and not stated_provenance(ledger.get("reserve_provenance")):
        raise HarnessError("reserve_provenance must state the source of reserve_seconds")
    if "benchmark_binding" in ledger:
        validate_benchmark_binding(ledger["benchmark_binding"])
    if "proof" in ledger:
        validate_proof_shape(ledger["proof"])
    if "benchmark_binding" in ledger and "proof" in ledger:
        if (
            ledger["benchmark_binding"]["product_frontier"]
            != ledger["proof"]["contract"]["accepted_product_frontier"]
        ):
            raise HarnessError(
                "benchmark_binding and proof must name the same accepted product frontier"
            )

    visiting: set[str] = set()
    memo: dict[str, float] = {}

    def path_to(task_id: str) -> float:
        if task_id in memo:
            return memo[task_id]
        if task_id in visiting:
            raise HarnessError(f"Ledger dependency cycle reaches {task_id}")
        visiting.add(task_id)
        task = by_id[task_id]
        prefix = max((path_to(dep) for dep in task["depends_on"]), default=0.0)
        visiting.remove(task_id)
        memo[task_id] = prefix + float(task["estimate_seconds"])
        return memo[task_id]

    critical_path = max(path_to(task_id) for task_id in by_id)
    duration = critical_path + float(reserve)
    return {
        "task_count": len(tasks),
        "critical_path_seconds": critical_path,
        "reserve_seconds": float(reserve),
        "reserve_provenance": ledger.get("reserve_provenance"),
        "duration_seconds": duration,
        "obligation_hash": digest_json(obligation_map(ledger)),
    }


def ensure_installed(source: Path, install_root: Path) -> tuple[Path, bool]:
    source = source.resolve()
    install_root = install_root.resolve()
    target = install_root / "bin" / "deadline_harness.py"
    manifest_path = install_root / "install-manifest.json"
    source_hash = digest_bytes(source.read_bytes())
    expected = {
        "version": VERSION,
        "source_sha256": source_hash,
        "installed_path": str(target),
    }

    current: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None

    target_matches = target.exists() and digest_bytes(target.read_bytes()) == source_hash
    changed = current != expected or not target_matches
    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(canonical(expected) + "\n", encoding="utf-8")
    return target, changed


def skill_file_map(skill_root: Path) -> dict[str, str]:
    ignored = {".git", ".skill-init", ".de67-lab", "__pycache__", ".pytest_cache"}
    result: dict[str, str] = {}
    for path in skill_root.rglob("*"):
        if not path.is_file() or any(part in ignored for part in path.relative_to(skill_root).parts):
            continue
        result[path.relative_to(skill_root).as_posix()] = digest_bytes(path.read_bytes())
    return result


def skill_size_bytes(skill_root: Path) -> int:
    ignored = {".git", ".skill-init", ".de67-lab", "__pycache__", ".pytest_cache"}
    return sum(
        path.stat().st_size
        for path in skill_root.rglob("*")
        if path.is_file()
        and not any(part in ignored for part in path.relative_to(skill_root).parts)
    )


def specification_hash(fs_root: Path) -> str:
    fs_root = fs_root.resolve()
    if fs_root.is_file():
        return digest_json({"type": "file", "content": digest_bytes(fs_root.read_bytes())})
    if not fs_root.is_dir():
        raise HarnessError(f"Functional specification does not exist: {fs_root}")
    files = {
        path.relative_to(fs_root).as_posix(): digest_bytes(path.read_bytes())
        for path in fs_root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(fs_root).parts
    }
    if not files:
        raise HarnessError("Functional specification root contains no files")
    return digest_json({"type": "directory", "files": files})


def authority_snapshot(skill_root: Path) -> dict[str, str]:
    policy_path = skill_root / "contracts" / "mutation-policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    allowed = {
        relative
        for scope in policy.get("scopes", {}).values()
        for relative in scope.get("allowed_paths", [])
    }
    files = skill_file_map(skill_root)
    frozen = {relative: value for relative, value in files.items() if relative not in allowed}
    if not frozen:
        raise HarnessError("Mutation policy produced an empty frozen authority")
    return {
        "skill_hash": digest_json(skill_file_map(skill_root)),
        "frozen_hash": digest_json(frozen),
        "harness_hash": digest_bytes((skill_root / "scripts" / "deadline_harness.py").read_bytes()),
        "guard_hash": digest_bytes((skill_root / "scripts" / "mutation_guard.py").read_bytes()),
        "policy_hash": digest_bytes(policy_path.read_bytes()),
        "kernel_hash": digest_bytes((skill_root / "references" / "kernel.md").read_bytes()),
    }


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS lineages (
            lineage_id TEXT PRIMARY KEY,
            fs_root_hash TEXT NOT NULL,
            fs_root_path TEXT NOT NULL,
            frozen_hash TEXT NOT NULL,
            harness_hash TEXT NOT NULL,
            guard_hash TEXT NOT NULL,
            policy_hash TEXT NOT NULL,
            kernel_hash TEXT NOT NULL,
            skill_root TEXT NOT NULL,
            proof_contract_hash TEXT,
            proof_contract_json TEXT,
            created_utc TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS windows (
            lineage_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            window_id TEXT NOT NULL,
            fs_hash TEXT NOT NULL,
            skill_hash TEXT NOT NULL,
            ledger_hash TEXT NOT NULL,
            ledger_json TEXT NOT NULL,
            started_utc TEXT NOT NULL,
            deadline_utc TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            harness_version TEXT NOT NULL,
            PRIMARY KEY (lineage_id, run_id, window_id)
        );

        CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            lineage_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            window_id TEXT NOT NULL,
            at_utc TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE,
            FOREIGN KEY (lineage_id, run_id, window_id)
              REFERENCES windows (lineage_id, run_id, window_id)
        );

        CREATE TRIGGER IF NOT EXISTS windows_no_update
        BEFORE UPDATE ON windows BEGIN
            SELECT RAISE(ABORT, 'sealed windows are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS windows_no_delete
        BEFORE DELETE ON windows BEGIN
            SELECT RAISE(ABORT, 'sealed windows are immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS events_no_update
        BEFORE UPDATE ON events BEGIN
            SELECT RAISE(ABORT, 'deadline events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete
        BEFORE DELETE ON events BEGIN
            SELECT RAISE(ABORT, 'deadline events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS lineages_no_update
        BEFORE UPDATE ON lineages BEGIN
            SELECT RAISE(ABORT, 'lineage authority is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS lineages_no_delete
        BEFORE DELETE ON lineages BEGIN
            SELECT RAISE(ABORT, 'lineage authority is immutable');
        END;
        """
    )
    lineage_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(lineages)").fetchall()
    }
    for column in ("proof_contract_hash", "proof_contract_json"):
        if column not in lineage_columns:
            connection.execute(f"ALTER TABLE lineages ADD COLUMN {column} TEXT")
    return connection


def bind_lineage(
    connection: sqlite3.Connection,
    *,
    lineage_id: str,
    fs_root_hash: str,
    fs_root: Path,
    skill_root: Path,
    authority: dict[str, str],
    proof_contract_value: dict[str, Any] | None,
    now: datetime,
) -> None:
    row = connection.execute(
        "SELECT * FROM lineages WHERE lineage_id=?", (lineage_id,)
    ).fetchone()
    expected = {
        "fs_root_hash": fs_root_hash,
        "fs_root_path": str(fs_root.resolve()),
        "frozen_hash": authority["frozen_hash"],
        "harness_hash": authority["harness_hash"],
        "guard_hash": authority["guard_hash"],
        "policy_hash": authority["policy_hash"],
        "kernel_hash": authority["kernel_hash"],
        "skill_root": str(skill_root.resolve()),
        "proof_contract_hash": digest_json(proof_contract_value),
        "proof_contract_json": canonical(proof_contract_value),
    }
    if row is None:
        connection.execute(
            """
            INSERT INTO lineages
              (lineage_id, fs_root_hash, fs_root_path, frozen_hash, harness_hash,
               guard_hash, policy_hash, kernel_hash, skill_root, proof_contract_hash,
               proof_contract_json, created_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_id,
                expected["fs_root_hash"],
                expected["fs_root_path"],
                expected["frozen_hash"],
                expected["harness_hash"],
                expected["guard_hash"],
                expected["policy_hash"],
                expected["kernel_hash"],
                expected["skill_root"],
                expected["proof_contract_hash"],
                expected["proof_contract_json"],
                iso(now),
            ),
        )
        connection.commit()
        return
    mismatches = [field for field, value in expected.items() if row[field] != value]
    if mismatches:
        raise HarnessError(
            "Lineage authority changed after sealing: " + ", ".join(sorted(mismatches))
        )


def window_key(lineage_id: str, run_id: str, window_id: str) -> tuple[str, str, str]:
    return lineage_id, run_id, window_id


def get_window(
    connection: sqlite3.Connection, lineage_id: str, run_id: str, window_id: str
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT * FROM windows
        WHERE lineage_id=? AND run_id=? AND window_id=?
        """,
        window_key(lineage_id, run_id, window_id),
    ).fetchone()
    if row is None:
        raise HarnessError(f"Unknown window: {lineage_id}/{run_id}/{window_id}")
    return row


def event_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        raise HarnessError("Event payload must be an object")
    return payload


def validate_token_use(payload: dict[str, Any]) -> None:
    tokens = payload.get("tokens")
    if tokens is None:
        return
    if (
        isinstance(tokens, bool)
        or not isinstance(tokens, (int, float))
        or not math.isfinite(tokens)
        or tokens < 0
    ):
        raise HarnessError("Completed event tokens must be non-negative and finite or null")


def validate_completion_event(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
    verify_files: bool = True,
    enforce_review_gate: bool = True,
) -> str:
    if any(row["kind"] == "completed" for row in prior_rows):
        raise HarnessError("A window permits exactly one completed event")
    validate_token_use(payload)
    if enforce_review_gate and lineage_review_state(connection, lineage_id)["review_required"]:
        raise HarnessError(
            "Completion denied: lineage requires a fresh coordinator review receipt"
        )
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, prior_rows)
    benchmark_binding = ledger.get("benchmark_binding")
    terminal_mutation = payload.get("mutation")
    if benchmark_binding is not None:
        if not isinstance(terminal_mutation, dict):
            raise HarnessError("Mutation benchmark completion requires terminal mutation evidence")
        sealed_mutation = benchmark_binding["mutation"]
        for field in ("target_failure_id", "changed_policy_keys", "expected_reduction"):
            if terminal_mutation.get(field) != sealed_mutation[field]:
                raise HarnessError(f"Terminal mutation evidence changed sealed field {field}")
        observed = terminal_mutation.get("observed_reductions")
        if not isinstance(observed, list) or not all(non_empty_text(item) for item in observed):
            raise HarnessError("Terminal mutation evidence requires observed_reductions")
    elif terminal_mutation is not None:
        raise HarnessError("Terminal mutation evidence was not bound when the window was sealed")
    required_slots = {task["id"] for task in ledger["tasks"]}
    outcome = payload.get("outcome", "execution")
    if outcome == "execution":
        accepted_rows = [row for row in prior_rows if row["kind"] == "task_accepted"]
        accepted_slots = [event_payload(row).get("slot_id") for row in accepted_rows]
        if len(accepted_slots) != len(set(accepted_slots)):
            raise HarnessError("Completion requires exactly one acceptance per execution task")
        if set(accepted_slots) != required_slots:
            missing = sorted(required_slots - set(accepted_slots))
            raise HarnessError(
                "Completion requires valid terminal acceptance for every execution task"
                + (f": {', '.join(missing)}" if missing else "")
            )
        for row in accepted_rows:
            validate_terminal_task_event(
                connection,
                lineage_id,
                run_id,
                window_id,
                "task_accepted",
                event_payload(row),
                current_event_hash=row["event_hash"],
                verify_files=verify_files,
            )
        return "execution"
    if outcome == "preflight_blocked":
        blocker_rows = [row for row in prior_rows if row["kind"] == "preflight_blocked"]
        if len(blocker_rows) != 1:
            raise HarnessError("Preflight completion requires one authorized blocker outcome")
        validate_preflight_blocker(
            connection,
            lineage_id,
            run_id,
            window_id,
            event_payload(blocker_rows[0]),
            prior_rows[: prior_rows.index(blocker_rows[0])],
            verify_files=verify_files,
        )
        return "preflight_gate"
    raise HarnessError("Completed event outcome must be execution or preflight_blocked")


def valid_completed_row(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    rows: list[sqlite3.Row] | None = None,
) -> sqlite3.Row | None:
    rows = rows if rows is not None else events_for(connection, lineage_id, run_id, window_id)
    completed = [row for row in rows if row["kind"] == "completed"]
    if len(completed) != 1 or rows[-1]["event_hash"] != completed[0]["event_hash"]:
        return None
    completed_index = rows.index(completed[0])
    try:
        validate_completion_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            event_payload(completed[0]),
            rows[:completed_index],
            verify_files=False,
            enforce_review_gate=False,
        )
    except HarnessError:
        return None
    return completed[0]


def append_event(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    kind: str,
    payload: dict[str, Any],
    at: datetime | None = None,
) -> str:
    get_window(connection, lineage_id, run_id, window_id)
    rows = events_for(connection, lineage_id, run_id, window_id)
    if rows and valid_completed_row(connection, lineage_id, run_id, window_id, rows):
        raise HarnessError("No events are permitted after window completion")
    if not rows and kind != "window_opened":
        raise HarnessError("The first window event must be window_opened")
    if rows and kind == "window_opened":
        raise HarnessError("window_opened is unique")
    event_at = at or utc_now()
    if rows and event_at < parse_iso(rows[-1]["at_utc"]):
        raise HarnessError("Event timestamps must follow append order")
    if kind == "dispatch_permitted":
        validate_dispatch_event(
            connection, lineage_id, run_id, window_id, payload, rows, event_at
        )
    elif kind == "receipt_rejected":
        validate_receipt_rejected(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    elif kind == "receipt_resealed":
        validate_receipt_resealed(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    elif kind in {"task_accepted", "task_failed"}:
        causal_fingerprint = validate_terminal_task_event(
            connection, lineage_id, run_id, window_id, kind, payload
        )
        if kind == "task_failed":
            payload["causal_evidence"] = causal_evidence_binding(
                payload.get("receipt_path"), payload.get("artifact_hashes")
            )
            payload["causal_fingerprint"] = causal_fingerprint
    elif kind == "preflight_blocked":
        validate_preflight_blocker(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    elif kind == "coordinator_review_completed":
        validate_coordinator_review(
            connection, lineage_id, run_id, window_id, payload, event_at
        )
    elif kind == "damage_assessment":
        validate_damage_assessment(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    elif kind == "proof_reviewed":
        validate_proof_review(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    elif kind == "completed":
        validate_completion_event(
            connection, lineage_id, run_id, window_id, payload, rows
        )
    previous_hash = rows[-1]["event_hash"] if rows else ZERO_HASH
    record = {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "at_utc": iso(event_at),
        "kind": kind,
        "payload": payload,
        "previous_hash": previous_hash,
    }
    event_hash = digest_json(record)
    connection.execute(
        """
        INSERT INTO events
          (lineage_id, run_id, window_id, at_utc, kind, payload_json,
           previous_hash, event_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lineage_id,
            run_id,
            window_id,
            record["at_utc"],
            kind,
            canonical(payload),
            previous_hash,
            event_hash,
        ),
    )
    connection.commit()
    return event_hash


def events_for(
    connection: sqlite3.Connection, lineage_id: str, run_id: str, window_id: str
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT * FROM events
        WHERE lineage_id=? AND run_id=? AND window_id=?
        ORDER BY sequence
        """,
        window_key(lineage_id, run_id, window_id),
    ).fetchall()


def verify_chain(rows: list[sqlite3.Row]) -> bool:
    previous_hash = ZERO_HASH
    for row in rows:
        payload = json.loads(row["payload_json"])
        record = {
            "lineage_id": row["lineage_id"],
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "at_utc": row["at_utc"],
            "kind": row["kind"],
            "payload": payload,
            "previous_hash": previous_hash,
        }
        if row["previous_hash"] != previous_hash or row["event_hash"] != digest_json(record):
            return False
        previous_hash = row["event_hash"]
    return True


def spawn_watcher(
    installed_script: Path,
    db_path: Path,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
) -> int:
    command = [
        sys.executable,
        str(installed_script),
        "watch",
        "--db",
        str(db_path),
        "--install-root",
        str(install_root),
        "--lineage-id",
        lineage_id,
        "--run-id",
        run_id,
        "--window-id",
        window_id,
    ]
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    threading.Thread(target=process.wait, daemon=True).start()
    return process.pid


def open_window(
    *,
    db_path: Path,
    install_root: Path,
    source_script: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    fs_root: Path,
    ledger: dict[str, Any],
    now: datetime | None = None,
    start_watcher: bool = True,
) -> dict[str, Any]:
    timing = validate_ledger(ledger)
    started = now or utc_now()
    deadline = started + timedelta(seconds=timing["duration_seconds"])
    fs_hash = specification_hash(fs_root)
    skill_root = source_script.resolve().parents[1]
    authority = authority_snapshot(skill_root)
    connection = connect(db_path)
    try:
        bind_lineage(
            connection,
            lineage_id=lineage_id,
            fs_root_hash=fs_hash,
            fs_root=fs_root,
            skill_root=skill_root,
            authority=authority,
            proof_contract_value=proof_contract(ledger),
            now=started,
        )
    except Exception:
        connection.close()
        raise
    review_state = lineage_review_state(connection, lineage_id)
    if review_state["review_required"]:
        connection.close()
        raise HarnessError(
            "New window denied: lineage requires a fresh externally bound coordinator review"
        )
    lineage_install = install_root / "lineages" / digest_bytes(lineage_id.encode("utf-8"))[:16]
    installed_script, deployed = ensure_installed(source_script, lineage_install)
    try:
        connection.execute(
            """
            INSERT INTO windows
              (lineage_id, run_id, window_id, fs_hash, skill_hash, ledger_hash,
               ledger_json, started_utc, deadline_utc, duration_seconds, harness_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_id,
                run_id,
                window_id,
                fs_hash,
                authority["skill_hash"],
                digest_json(ledger),
                canonical(ledger),
                iso(started),
                iso(deadline),
                timing["duration_seconds"],
                VERSION,
            ),
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        connection.close()
        raise HarnessError("Window identity is already sealed; its clock cannot be reset") from error

    opened = {
        "ledger_hash": digest_json(ledger),
        "effective_plan_hash": digest_json(ledger),
        "task_obligations": obligation_map(ledger),
        "timing": timing,
        "deadline_utc": iso(deadline),
        "harness_deployed": deployed,
        "frozen_authority_hash": authority["frozen_hash"],
        "retry_route": orchestration_retry_route(skill_root),
    }
    if isinstance(ledger.get("proof"), dict):
        opened["proof_conformance_route"] = proof_policy_route(skill_root)
    append_event(connection, lineage_id, run_id, window_id, "window_opened", opened, started)
    watcher_pid = None
    if start_watcher:
        watcher_pid = spawn_watcher(
            installed_script, db_path.resolve(), install_root.resolve(), lineage_id, run_id, window_id
        )
        append_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            "watcher_started",
            {"pid": watcher_pid, "installed_script": str(installed_script)},
        )
    connection.close()
    return {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "started_utc": iso(started),
        "deadline_utc": iso(deadline),
        "duration_seconds": timing["duration_seconds"],
        "critical_path_seconds": timing["critical_path_seconds"],
        "harness_deployed": deployed,
        "watcher_pid": watcher_pid,
        "db": str(db_path.resolve()),
    }


def lineage_miss_count(connection: sqlite3.Connection, lineage_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(DISTINCT run_id || char(31) || window_id) AS failures
        FROM events WHERE lineage_id=? AND kind='deadline_missed'
        """,
        (lineage_id,),
    ).fetchone()
    return int(row["failures"])


def lineage_miss_rows(connection: sqlite3.Connection, lineage_id: str) -> list[sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT * FROM events
        WHERE lineage_id=? AND kind='deadline_missed'
        ORDER BY sequence
        """,
        (lineage_id,),
    ).fetchall()
    distinct: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        distinct.setdefault((row["run_id"], row["window_id"]), row)
    return list(distinct.values())


def valid_lineage_review_batches(
    connection: sqlite3.Connection, lineage_id: str
) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
    misses = lineage_miss_rows(connection, lineage_id)
    reviews = connection.execute(
        """
        SELECT * FROM events
        WHERE lineage_id=? AND kind='coordinator_review_completed'
        ORDER BY sequence
        """,
        (lineage_id,),
    ).fetchall()
    reviewed_through_sequence = 0
    valid_batches: list[tuple[sqlite3.Row, list[sqlite3.Row]]] = []
    for review in reviews:
        batch = [
            row for row in misses
            if reviewed_through_sequence < row["sequence"] < review["sequence"]
        ]
        if len(batch) < COORDINATOR_REVIEW_THRESHOLD:
            continue
        try:
            payload = event_payload(review)
            batch_hashes = [row["event_hash"] for row in batch]
            latest_window = get_window(
                connection,
                batch[-1]["lineage_id"],
                batch[-1]["run_id"],
                batch[-1]["window_id"],
            )
            verify_file_hash(
                payload.get("receipt_path"), payload.get("receipt_sha256"), "Review receipt"
            )
            valid = (
                payload.get("reviewed_failure_event_hashes") == batch_hashes
                and parse_iso(review["at_utc"]) > parse_iso(batch[-1]["at_utc"])
                and payload.get("fresh") is True
                and payload.get("reviewer_profile") == "sol-xhigh"
                and non_empty_text(payload.get("reviewer_identity"))
                and payload.get("reviewed_parent_skill_hash") == latest_window["skill_hash"]
            )
        except (HarnessError, json.JSONDecodeError, IndexError):
            valid = False
        if valid:
            reviewed_through_sequence = review["sequence"]
            valid_batches.append((review, batch))
    return valid_batches


def lineage_review_state(connection: sqlite3.Connection, lineage_id: str) -> dict[str, Any]:
    misses = lineage_miss_rows(connection, lineage_id)
    valid_batches = valid_lineage_review_batches(connection, lineage_id)
    latest_valid_review = valid_batches[-1][0] if valid_batches else None
    reviewed_through_sequence = (
        latest_valid_review["sequence"] if latest_valid_review is not None else 0
    )

    unreviewed = [row for row in misses if row["sequence"] > reviewed_through_sequence]
    miss_hashes = [row["event_hash"] for row in unreviewed]
    required = len(unreviewed) >= COORDINATOR_REVIEW_THRESHOLD
    return {
        "miss_count": len(misses),
        "reviewed_miss_count": len(misses) - len(unreviewed),
        "unreviewed_miss_count": len(unreviewed),
        "threshold": COORDINATOR_REVIEW_THRESHOLD,
        "review_required": required,
        "review_valid": latest_valid_review is not None,
        "review_hash": (
            latest_valid_review["event_hash"] if latest_valid_review is not None else None
        ),
        "miss_event_hashes": miss_hashes,
        "all_miss_event_hashes": [row["event_hash"] for row in misses],
    }


def expire_window(
    *,
    connection: sqlite3.Connection,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    window = get_window(connection, lineage_id, run_id, window_id)
    rows = events_for(connection, lineage_id, run_id, window_id)
    kinds = [row["kind"] for row in rows]
    deadline = parse_iso(window["deadline_utc"])
    if "deadline_missed" in kinds:
        review_state = lineage_review_state(connection, lineage_id)
        return {
            "expired": True,
            "new": False,
            "miss_count": review_state["miss_count"],
            "unreviewed_miss_count": review_state["unreviewed_miss_count"],
            "coordinator_review_required": review_state["review_required"],
        }
    completed = valid_completed_row(connection, lineage_id, run_id, window_id, rows)
    if completed is not None and parse_iso(completed["at_utc"]) <= deadline:
        return {"expired": False, "new": False, "completed": True}
    if current < deadline:
        return {
            "expired": False,
            "new": False,
            "remaining_seconds": (deadline - current).total_seconds(),
        }

    elapsed = (current - parse_iso(window["started_utc"])).total_seconds()
    effective_plan = effective_ledger(window, rows)
    payload = {
        "deadline_utc": window["deadline_utc"],
        "observed_utc": iso(current),
        "elapsed_seconds": elapsed,
        "ledger_hash": digest_json(effective_plan),
    }
    append_event(connection, lineage_id, run_id, window_id, "deadline_missed", payload, current)
    review_state = lineage_review_state(connection, lineage_id)
    miss_count = review_state["miss_count"]
    review_required = review_state["review_required"]
    if review_required:
        append_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            "coordinator_review_required",
            {
                "distinct_failed_windows": miss_count,
                "unreviewed_failed_windows": review_state["unreviewed_miss_count"],
                "threshold": COORDINATOR_REVIEW_THRESHOLD,
            },
            current,
        )

    damage_dir = install_root / "damage"
    damage_dir.mkdir(parents=True, exist_ok=True)
    damage_path = damage_dir / f"{lineage_id}--{run_id}--{window_id}.json"
    snapshot = {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "fs_hash": window["fs_hash"],
        "skill_hash": window["skill_hash"],
        "ledger_hash": window["ledger_hash"],
        "started_utc": window["started_utc"],
        "deadline_utc": window["deadline_utc"],
        "observed_utc": iso(current),
        "miss_count": miss_count,
        "unreviewed_miss_count": review_state["unreviewed_miss_count"],
        "coordinator_review_required": review_required,
        "event_kinds": [row["kind"] for row in events_for(connection, lineage_id, run_id, window_id)],
        "assessment_required": [
            "planned",
            "achieved",
            "first_divergence",
            "wall_time",
            "exposed_tokens",
            "external_wait",
            "accepted_commits",
            "quarantined_artifacts",
            "causal_class",
            "quality_state",
            "proposed_efficiency_direction",
        ],
    }
    damage_path.write_text(canonical(snapshot) + "\n", encoding="utf-8")
    return {
        "expired": True,
        "new": True,
        "miss_count": miss_count,
        "unreviewed_miss_count": review_state["unreviewed_miss_count"],
        "coordinator_review_required": review_required,
        "damage_path": str(damage_path),
    }


def status_window(
    *,
    db_path: Path,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    connection = connect(db_path)
    expiry = expire_window(
        connection=connection,
        install_root=install_root,
        lineage_id=lineage_id,
        run_id=run_id,
        window_id=window_id,
        now=now,
    )
    window = get_window(connection, lineage_id, run_id, window_id)
    rows = events_for(connection, lineage_id, run_id, window_id)
    review_state = lineage_review_state(connection, lineage_id)
    result = {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "started_utc": window["started_utc"],
        "deadline_utc": window["deadline_utc"],
        "expiry": expiry,
        "event_kinds": [row["kind"] for row in rows],
        "chain_valid": verify_chain(rows),
        "lineage_miss_count": review_state["miss_count"],
        "lineage_review": review_state,
    }
    connection.close()
    return result


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value.lower()
    )


def effective_ledger(
    window: sqlite3.Row, rows: list[sqlite3.Row]
) -> dict[str, Any]:
    ledger = json.loads(window["ledger_json"])
    for row in rows:
        if row["kind"] == "ledger_revised":
            payload = json.loads(row["payload_json"])
            if isinstance(payload.get("ledger"), dict):
                ledger = payload["ledger"]
    return ledger


def verify_file_hash(path_text: Any, expected: Any, label: str) -> None:
    if not isinstance(path_text, str) or not path_text.strip():
        raise HarnessError(f"{label} path is required")
    if not valid_sha256(expected):
        raise HarnessError(f"{label} requires a SHA-256")
    path = Path(path_text)
    if not path.is_file():
        raise HarnessError(f"{label} file is missing: {path}")
    actual = digest_bytes(path.read_bytes())
    if actual != expected:
        raise HarnessError(f"{label} hash mismatch: {path}")


def verify_proof_artifacts(ledger: dict[str, Any]) -> None:
    proof = ledger.get("proof")
    if not isinstance(proof, dict):
        return
    for kind, bindings in proof["plan"]["artifacts"].items():
        for path, value in bindings.items():
            verify_file_hash(path, value, f"Proof {kind} artifact")


def proof_runtime_binding(ledger: dict[str, Any]) -> dict[str, Any]:
    proof = ledger["proof"]
    contract = proof["contract"]
    plan = proof["plan"]
    return {
        "contract_hash": digest_json(contract),
        "plan_hash": digest_json(plan),
        "artifacts_hash": digest_json(plan["artifacts"]),
        "condition_mapping_hash": digest_json(plan["condition_artifacts"]),
        "negative_control_mapping_hash": digest_json(plan["negative_control_artifacts"]),
        "authoritative_owner_route": contract["authoritative_owner_route"],
    }


def proof_policy_route(skill_root: Path) -> str:
    policy_path = skill_root / "policy" / "proof.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    route = policy.get("conformance_route")
    if route not in {
        "minimal_authoritative_conformance",
        "authoritative_owner_then_live_conformance",
    }:
        raise HarnessError("Accepted proof policy route is outside the closed vocabulary")
    return route


def orchestration_retry_route(skill_root: Path) -> str:
    policy = json.loads((skill_root / "policy" / "orchestration.json").read_text(encoding="utf-8"))
    route = policy.get("retry_route")
    if route not in {"same_worker_changed_evidence", "replace_worker_changed_owner"}:
        raise HarnessError("Accepted orchestration retry route is outside the closed vocabulary")
    return route


def accepted_retry_route(rows: list[sqlite3.Row]) -> str:
    opened = next((row for row in rows if row["kind"] == "window_opened"), None)
    route = event_payload(opened).get("retry_route") if opened is not None else None
    if route not in {"same_worker_changed_evidence", "replace_worker_changed_owner"}:
        raise HarnessError("Sealed orchestration retry route is outside the closed vocabulary")
    return route


def accepted_proof_route(prior_rows: list[sqlite3.Row]) -> str:
    opened = next((row for row in prior_rows if row["kind"] == "window_opened"), None)
    if opened is None:
        raise HarnessError("Proof review requires a sealed window route")
    route = event_payload(opened).get("proof_conformance_route")
    if route not in {
        "minimal_authoritative_conformance",
        "authoritative_owner_then_live_conformance",
    }:
        raise HarnessError("Sealed proof policy route is outside the closed vocabulary")
    return route


def validate_proof_review(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
) -> None:
    common = {
        "contract_hash", "plan_hash", "artifacts_hash", "condition_mapping_hash",
        "negative_control_mapping_hash", "authoritative_owner_route", "reviewer_identity",
        "helper_or_mock_only", "direct_outcome_setting", "receipt_path", "receipt_sha256",
        "conformance_route",
    }
    route = accepted_proof_route(prior_rows)
    required = set(common)
    if route == "authoritative_owner_then_live_conformance":
        required.update(
            {
                "owner_identity", "owner_receipt_path", "owner_receipt_sha256",
                "live_receipt_path", "live_receipt_sha256", "live_conformance",
            }
        )
    if set(payload) != required:
        raise HarnessError("Proof review has an incomplete or open shape")
    if payload.get("conformance_route") != route:
        raise HarnessError("Proof review route differs from the accepted P2 policy")
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, prior_rows)
    proof = ledger.get("proof")
    if not isinstance(proof, dict):
        raise HarnessError("Proof review requires a sealed proof contract and plan")
    expected = proof_runtime_binding(ledger)
    for field, value in expected.items():
        if payload.get(field) != value:
            raise HarnessError(f"Proof review changed or omitted {field}")
    reviewer = payload.get("reviewer_identity")
    author = proof["plan"]["author_identity"]
    if not non_empty_text(reviewer) or reviewer == author:
        raise HarnessError("Proof reviewer must be distinct from the plan author")
    if payload.get("helper_or_mock_only") is not False:
        raise HarnessError("Proof review rejects helper- or mock-only evidence")
    if payload.get("direct_outcome_setting") is not False:
        raise HarnessError("Proof review rejects direct outcome setting")
    verify_proof_artifacts(ledger)
    verify_file_hash(
        payload.get("receipt_path"), payload.get("receipt_sha256"), "Proof review receipt"
    )
    try:
        receipt = json.loads(Path(payload["receipt_path"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HarnessError("Proof review receipt is not readable JSON") from error
    if not isinstance(receipt, dict) or receipt.get("conformance_route") != route:
        raise HarnessError("Proof review receipt does not bind the accepted conformance route")
    if route == "authoritative_owner_then_live_conformance":
        if not non_empty_text(payload.get("owner_identity")):
            raise HarnessError("Owner-then-live proof review requires owner_identity")
        if payload.get("live_conformance") is not True:
            raise HarnessError("Owner-then-live proof review requires live_conformance=true")
        verify_file_hash(
            payload.get("owner_receipt_path"), payload.get("owner_receipt_sha256"),
            "Authoritative owner receipt",
        )
        verify_file_hash(
            payload.get("live_receipt_path"), payload.get("live_receipt_sha256"),
            "Live conformance receipt",
        )


def matching_proof_review(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    ledger: dict[str, Any],
    rows: list[sqlite3.Row],
) -> sqlite3.Row:
    expected = proof_runtime_binding(ledger)
    for row in reversed(rows):
        if row["kind"] != "proof_reviewed":
            continue
        payload = event_payload(row)
        if all(payload.get(field) == value for field, value in expected.items()):
            review_index = rows.index(row)
            validate_proof_review(
                connection, lineage_id, run_id, window_id, payload, rows[:review_index]
            )
            return row
    raise HarnessError("Dispatch denied: current proof plan lacks a separate authoritative review")


def validate_dispatch_event(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    rows: list[sqlite3.Row],
    at: datetime,
) -> None:
    window = get_window(connection, lineage_id, run_id, window_id)
    if at >= parse_iso(window["deadline_utc"]):
        raise HarnessError("Dispatch denied: the sealed deadline has expired")
    if lineage_review_state(connection, lineage_id)["review_required"]:
        raise HarnessError("Dispatch denied: lineage coordinator review is required")
    ledger = effective_ledger(window, rows)
    slot_id = payload.get("slot_id")
    task = next((item for item in ledger["tasks"] if item["id"] == slot_id), None)
    if task is None:
        raise HarnessError("Dispatch denied: slot is absent from the effective ledger")
    if task["worker_profile"] != payload.get("worker_profile"):
        raise HarnessError("Dispatch denied: worker profile differs from the effective ledger")
    if payload.get("ledger_hash") != digest_json(ledger):
        raise HarnessError("Dispatch denied: effective-plan hash mismatch")
    binding = task_obligation(task)
    if payload.get("obligation_digest") != binding["obligation_digest"]:
        raise HarnessError("Dispatch denied: stable task obligation mismatch")
    proof = ledger.get("proof")
    if isinstance(proof, dict):
        lineage = connection.execute(
            "SELECT * FROM lineages WHERE lineage_id=?", (lineage_id,)
        ).fetchone()
        if specification_hash(Path(lineage["fs_root_path"])) != lineage["fs_root_hash"]:
            raise HarnessError("Dispatch denied: proof semantic core changed after lineage seal")
        if digest_json(proof["contract"]) != lineage["proof_contract_hash"]:
            raise HarnessError("Dispatch denied: proof contract differs from the sealed lineage")
        review = matching_proof_review(
            connection, lineage_id, run_id, window_id, ledger, rows
        )
        review_payload = event_payload(review)
        worker = payload.get("worker_identity")
        identities = {
            proof["plan"]["author_identity"], review_payload["reviewer_identity"], worker
        }
        if not non_empty_text(worker) or len(identities) != 3:
            raise HarnessError("Proof author, reviewer, and intended worker must be distinct")
        expected_proof = {
            **proof_runtime_binding(ledger),
            "proof_review_event_hash": review["event_hash"],
            "conformance_route": review_payload["conformance_route"],
        }
        for field, value in expected_proof.items():
            if payload.get(field) != value:
                raise HarnessError(f"Dispatch denied: proof permit changed {field}")
    accepted_slots = {
        event_payload(row).get("slot_id")
        for row in rows
        if row["kind"] == "task_accepted"
    }
    missing_parents = sorted(set(task["depends_on"]) - accepted_slots)
    if missing_parents:
        raise HarnessError(
            "Dispatch denied: dependencies lack accepted terminal receipts: "
            + ", ".join(missing_parents)
        )
    if slot_id in accepted_slots:
        raise HarnessError("Dispatch denied: task is already accepted")
    terminal_permits = {
        event_payload(row).get("permit_event_hash")
        for row in rows
        if row["kind"] in {"task_accepted", "task_failed"}
    }
    for row in rows:
        if row["kind"] != "dispatch_permitted" or row["event_hash"] in terminal_permits:
            continue
        if event_payload(row).get("slot_id") == slot_id:
            raise HarnessError("Dispatch denied: task already has an active permit")
    if any(row["kind"] == "preflight_blocked" for row in rows):
        raise HarnessError("Dispatch denied: the window has a preflight blocker outcome")


def validate_preflight_blocker(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
    verify_files: bool = True,
) -> None:
    if any(
        row["kind"] in {"dispatch_permitted", "task_accepted", "task_failed", "preflight_blocked"}
        for row in prior_rows
    ):
        raise HarnessError("Preflight blocker outcome requires a zero-dispatch window")
    for field in ("authorized_by", "authority_reference", "blocker"):
        if not non_empty_text(payload.get(field)):
            raise HarnessError(f"Preflight blocker requires {field}")
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, prior_rows)
    expected_claims = sorted(task["claim_id"] for task in ledger["tasks"])
    if payload.get("blocked_claim_ids") != expected_claims:
        raise HarnessError("Preflight blocker must bind every unresolved stable claim")
    if verify_files:
        verify_file_hash(
            payload.get("receipt_path"), payload.get("receipt_sha256"), "Blocker receipt"
        )
    elif not non_empty_text(payload.get("receipt_path")) or not valid_sha256(
        payload.get("receipt_sha256")
    ):
        raise HarnessError("Preflight blocker requires a bound receipt path and SHA-256")


def validate_damage_assessment(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
) -> None:
    if any(row["kind"] == "damage_assessment" for row in prior_rows):
        raise HarnessError("A failed window permits one authoritative damage assessment")
    misses = [row for row in prior_rows if row["kind"] == "deadline_missed"]
    if len(misses) != 1 or payload.get("miss_event_hash") != misses[0]["event_hash"]:
        raise HarnessError("Damage assessment must bind this window's sealed deadline miss")
    owner = payload.get("failure_owner")
    if owner not in {"proof_plan", "product", "harness"}:
        raise HarnessError("Damage assessment failure_owner is outside the closed vocabulary")
    if not non_empty_text(payload.get("assessor_identity")):
        raise HarnessError("Damage assessment requires assessor_identity")
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, prior_rows)
    if owner == "proof_plan":
        required = {
            "miss_event_hash", "failure_owner", "permit_event_hash", "task_failed_event_hash",
            "contract_hash", "plan_hash", "causal_class", "causal_fingerprint",
            "assessor_identity", "receipt_path", "receipt_sha256", "conformance_route",
        }
        if set(payload) != required:
            raise HarnessError("Proof-plan damage assessment has an incomplete or open shape")
        proof = ledger.get("proof")
        if not isinstance(proof, dict):
            raise HarnessError("A proof_plan-owned failure requires a sealed proof contract")
        permit = next(
            (
                row for row in prior_rows
                if row["kind"] == "dispatch_permitted"
                and row["event_hash"] == payload.get("permit_event_hash")
            ),
            None,
        )
        failed = next(
            (
                row for row in prior_rows
                if row["kind"] == "task_failed"
                and row["event_hash"] == payload.get("task_failed_event_hash")
            ),
            None,
        )
        if permit is None or failed is None:
            raise HarnessError(
                "Proof-plan damage assessment requires a reviewed permit and real task_failed"
            )
        permit_payload = event_payload(permit)
        failed_payload = event_payload(failed)
        if failed_payload.get("permit_event_hash") != permit["event_hash"]:
            raise HarnessError("Proof-plan assessment task_failed did not consume its permit")
        validate_terminal_task_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            "task_failed",
            failed_payload,
            current_event_hash=failed["event_hash"],
        )
        binding = proof_runtime_binding(ledger)
        if (
            payload.get("contract_hash") != binding["contract_hash"]
            or payload.get("plan_hash") != binding["plan_hash"]
            or permit_payload.get("contract_hash") != binding["contract_hash"]
            or permit_payload.get("plan_hash") != binding["plan_hash"]
            or not valid_sha256(permit_payload.get("proof_review_event_hash"))
            or payload.get("conformance_route") != permit_payload.get("conformance_route")
        ):
            raise HarnessError("Proof-plan assessment changed contract, plan, or reviewed permit")
        causal_class = payload.get("causal_class")
        if not non_empty_text(causal_class):
            raise HarnessError("Proof-plan assessment requires an authoritative causal_class")
        fingerprint = digest_json(
            {
                "causal_class": causal_class,
                "contract_hash": binding["contract_hash"],
                "authoritative_owner_route": binding["authoritative_owner_route"],
            }
        )
        if payload.get("causal_fingerprint") != fingerprint:
            raise HarnessError("Proof-plan causal fingerprint must be harness-derived")
        if payload["assessor_identity"] == permit_payload.get("worker_identity"):
            raise HarnessError("Damage assessment cannot be self-classified by the worker")
    else:
        fingerprint = payload.get("causal_fingerprint")
        if not valid_sha256(fingerprint):
            raise HarnessError("Damage assessment requires a causal fingerprint SHA-256")
        if not non_empty_text(payload.get("authoritative_route")):
            raise HarnessError("Damage assessment requires authoritative_route")
    existing = connection.execute(
        "SELECT payload_json FROM events WHERE lineage_id=? AND kind='damage_assessment'",
        (lineage_id,),
    ).fetchall()
    for row in existing:
        prior = json.loads(row["payload_json"])
        if (
            prior.get("causal_fingerprint") == fingerprint
            and prior.get("failure_owner") != owner
        ):
            raise HarnessError("A causal fingerprint cannot be relabeled across failure owners")
    verify_file_hash(
        payload.get("receipt_path"), payload.get("receipt_sha256"), "Damage assessment receipt"
    )


def validate_coordinator_review(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    state = lineage_review_state(connection, lineage_id)
    if (
        state["unreviewed_miss_count"] < COORDINATOR_REVIEW_THRESHOLD
        or not state["review_required"]
    ):
        raise HarnessError("Coordinator review requires the current authorized missed-window gate")
    if not non_empty_text(payload.get("reviewer_identity")):
        raise HarnessError("Coordinator review requires reviewer_identity")
    if payload.get("reviewer_profile") != "sol-xhigh":
        raise HarnessError("Coordinator review requires reviewer_profile=sol-xhigh")
    if payload.get("fresh") is not True:
        raise HarnessError("Coordinator review must explicitly attest fresh=true")
    if payload.get("reviewed_failure_event_hashes") != state["miss_event_hashes"]:
        raise HarnessError("Coordinator review must bind the complete current unreviewed failure set")
    unreviewed_hashes = set(state["miss_event_hashes"])
    misses = [
        row for row in lineage_miss_rows(connection, lineage_id)
        if row["event_hash"] in unreviewed_hashes
    ]
    latest_miss = misses[-1]
    latest_window = get_window(
        connection,
        latest_miss["lineage_id"],
        latest_miss["run_id"],
        latest_miss["window_id"],
    )
    parent_hash = payload.get("reviewed_parent_skill_hash")
    if not valid_sha256(parent_hash) or parent_hash != latest_window["skill_hash"]:
        raise HarnessError("Coordinator review must bind the current parent skill hash")
    if at <= parse_iso(latest_miss["at_utc"]):
        raise HarnessError("Coordinator review must be recorded after the latest missed window")
    verify_file_hash(payload.get("receipt_path"), payload.get("receipt_sha256"), "Review receipt")


def validate_receipt_rejected(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
) -> None:
    permit_hash = payload.get("permit_event_hash")
    if any(
        row["kind"] == "receipt_rejected"
        and event_payload(row).get("permit_event_hash") == permit_hash
        for row in prior_rows
    ):
        raise HarnessError("Dispatch permit already has a rejected receipt event")
    if any(
        row["kind"] in {"task_accepted", "task_failed"}
        and event_payload(row).get("permit_event_hash") == permit_hash
        for row in prior_rows
    ):
        raise HarnessError("Receipt rejection denied: dispatch permit was already consumed")
    validate_terminal_task_event(
        connection, lineage_id, run_id, window_id, "task_accepted", payload,
        verify_files=False,
    )
    receipt_path = Path(payload["receipt_path"])
    actual_hash = digest_bytes(receipt_path.read_bytes())
    if payload["receipt_sha256"] == actual_hash:
        raise HarnessError("Receipt rejection requires a genuine receipt hash mismatch")
    for artifact_path, artifact_hash in payload["artifact_hashes"].items():
        verify_file_hash(artifact_path, artifact_hash, "Artifact")


def validate_receipt_resealed(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    payload: dict[str, Any],
    prior_rows: list[sqlite3.Row],
) -> None:
    if set(payload) != {
        "rejected_event_hash", "corrected_receipt_path", "corrected_receipt_sha256",
    }:
        raise HarnessError("Receipt reseal has an incomplete or open shape")
    rejected_event_hash = payload.get("rejected_event_hash")
    if not valid_sha256(rejected_event_hash):
        raise HarnessError("Receipt reseal requires a rejected receipt event hash")
    rejected_row = next(
        (
            row for row in prior_rows
            if row["kind"] == "receipt_rejected" and row["event_hash"] == rejected_event_hash
        ),
        None,
    )
    if rejected_row is None:
        raise HarnessError("Receipt reseal references no sealed rejected receipt event")
    rejected = event_payload(rejected_row)
    permit_hash = rejected.get("permit_event_hash")
    if any(
        row["kind"] in {"task_accepted", "task_failed"}
        and event_payload(row).get("permit_event_hash") == permit_hash
        for row in prior_rows
    ):
        raise HarnessError("Receipt reseal denied: dispatch permit was already consumed")
    if any(
        row["kind"] == "receipt_resealed"
        and event_payload(row).get("rejected_event_hash") == rejected_event_hash
        for row in prior_rows
    ):
        raise HarnessError("Dispatch permit already has a receipt reseal")
    corrected_path = payload.get("corrected_receipt_path")
    corrected_hash = payload.get("corrected_receipt_sha256")
    if not non_empty_text(corrected_path) or not valid_sha256(corrected_hash):
        raise HarnessError("Receipt reseal requires the corrected receipt path and SHA-256")
    if rejected.get("receipt_sha256") == corrected_hash:
        raise HarnessError("Receipt reseal requires a genuinely rejected receipt hash")
    corrected = dict(rejected, receipt_path=corrected_path, receipt_sha256=corrected_hash)
    validate_terminal_task_event(
        connection, lineage_id, run_id, window_id, "task_accepted", corrected
    )


def validate_terminal_task_event(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    kind: str,
    payload: dict[str, Any],
    current_event_hash: str | None = None,
    verify_files: bool = True,
) -> str:
    permit_hash = payload.get("permit_event_hash")
    if not valid_sha256(permit_hash):
        raise HarnessError("Terminal task event requires a dispatch permit event hash")
    permit = connection.execute(
        """
        SELECT * FROM events
        WHERE lineage_id=? AND run_id=? AND window_id=?
          AND event_hash=? AND kind='dispatch_permitted'
        """,
        (lineage_id, run_id, window_id, permit_hash),
    ).fetchone()
    if permit is None:
        raise HarnessError("Terminal task event references no sealed dispatch permit")
    permit_payload = json.loads(permit["payload_json"])
    if payload.get("slot_id") != permit_payload.get("slot_id"):
        raise HarnessError("Terminal task slot does not match its dispatch permit")
    if payload.get("worker_profile") != permit_payload.get("worker_profile"):
        raise HarnessError("Terminal task worker profile does not match its dispatch permit")
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, events_for(connection, lineage_id, run_id, window_id))
    task = next((item for item in ledger["tasks"] if item["id"] == payload.get("slot_id")), None)
    if task is None:
        raise HarnessError("Terminal task is absent from the effective ledger")
    if kind == "task_accepted":
        verify_proof_artifacts(ledger)
    binding = task_obligation(task)
    if permit_payload.get("obligation_digest") != binding["obligation_digest"]:
        raise HarnessError("Terminal task permit is not bound to the stable obligation")
    if not isinstance(payload.get("worker_identity"), str) or not payload["worker_identity"].strip():
        raise HarnessError("Terminal task event requires an observed worker identity")
    intended_worker = permit_payload.get("worker_identity")
    if non_empty_text(intended_worker) and payload["worker_identity"] != intended_worker:
        raise HarnessError("Terminal task worker identity differs from its dispatch permit")
    permit_route = permit_payload.get("conformance_route")
    if non_empty_text(permit_route) and payload.get("conformance_route") != permit_route:
        raise HarnessError("Terminal task conformance route differs from its proof permit")
    if payload.get("test_completed") is not True:
        raise HarnessError("Terminal task event requires a completed test")
    expected_result = "passed" if kind == "task_accepted" else "failed"
    if payload.get("test_result") != expected_result:
        raise HarnessError(f"{kind} requires test_result={expected_result}")
    if verify_files:
        verify_file_hash(payload.get("receipt_path"), payload.get("receipt_sha256"), "Receipt")
    elif not non_empty_text(payload.get("receipt_path")) or not valid_sha256(
        payload.get("receipt_sha256")
    ):
        raise HarnessError("Terminal task event requires a bound receipt path and SHA-256")
    artifacts = payload.get("artifact_hashes")
    if not isinstance(artifacts, dict) or not artifacts:
        raise HarnessError("Terminal task event requires artifact hashes")
    for artifact_path, artifact_hash in artifacts.items():
        if verify_files:
            verify_file_hash(artifact_path, artifact_hash, "Artifact")
        elif not non_empty_text(artifact_path) or not valid_sha256(artifact_hash):
            raise HarnessError("Terminal task event requires bound artifact paths and SHA-256s")

    evidence = causal_evidence_binding(payload.get("receipt_path"), artifacts)
    supplied_evidence = payload.get("causal_evidence")
    if supplied_evidence is not None and supplied_evidence != evidence:
        raise HarnessError("Terminal task causal evidence must be harness-derived")
    sealed_evidence = permit_payload.get("causal_evidence")
    if sealed_evidence is not None and sealed_evidence != evidence:
        raise HarnessError("Terminal task causal evidence differs from its retry permit")

    all_rows = events_for(connection, lineage_id, run_id, window_id)
    rejection_hashes = {
        row["event_hash"] for row in all_rows
        if row["kind"] == "receipt_rejected"
        and event_payload(row).get("permit_event_hash") == permit_hash
    }
    reseals = [
        row for row in all_rows
        if row["kind"] == "receipt_resealed"
        and event_payload(row).get("rejected_event_hash") in rejection_hashes
    ]
    reseal_hash = payload.get("receipt_reseal_event_hash")
    if reseals:
        if len(reseals) != 1 or reseal_hash != reseals[0]["event_hash"]:
            raise HarnessError("Terminal acceptance must bind its single receipt reseal")
        reseal = event_payload(reseals[0])
        rejected_row = next(
            (
                row for row in events_for(connection, lineage_id, run_id, window_id)
                if row["kind"] == "receipt_rejected"
                and row["event_hash"] == reseal["rejected_event_hash"]
            ),
            None,
        )
        if rejected_row is None:
            raise HarnessError("Receipt reseal lost its rejected receipt event")
        corrected = dict(
            event_payload(rejected_row),
            receipt_path=reseal["corrected_receipt_path"],
            receipt_sha256=reseal["corrected_receipt_sha256"],
        )
        expected = dict(payload)
        expected.pop("receipt_reseal_event_hash", None)
        if kind != "task_accepted" or corrected != expected:
            raise HarnessError("Terminal acceptance changed resealed worker, test, or artifact evidence")
    elif reseal_hash is not None:
        raise HarnessError("Terminal task references no sealed receipt reseal")

    for row in events_for(connection, lineage_id, run_id, window_id):
        if current_event_hash is not None and row["event_hash"] == current_event_hash:
            continue
        if row["kind"] not in {"task_accepted", "task_failed"}:
            continue
        prior = json.loads(row["payload_json"])
        if prior.get("permit_event_hash") == permit_hash:
            raise HarnessError("Dispatch permit was already consumed by a terminal task event")
        if kind == "task_accepted" and prior.get("slot_id") == payload.get("slot_id") and row["kind"] == kind:
            raise HarnessError("Task already has an accepted terminal event")
    fingerprint = digest_json(
        {
            "obligation_digest": permit_payload["obligation_digest"],
            "worker_identity": payload["worker_identity"],
            "causal_evidence": evidence,
        }
    )
    supplied = payload.get("causal_fingerprint")
    if supplied is not None and supplied != fingerprint:
        raise HarnessError("Terminal task causal fingerprint must be harness-derived")
    return fingerprint


def export_benchmark(
    *, db_path: Path, lineage_id: str, run_id: str, window_id: str
) -> dict[str, Any]:
    connection = connect(db_path)
    window = get_window(connection, lineage_id, run_id, window_id)
    lineage = connection.execute(
        "SELECT * FROM lineages WHERE lineage_id=?", (lineage_id,)
    ).fetchone()
    rows = events_for(connection, lineage_id, run_id, window_id)
    if not rows:
        connection.close()
        raise HarnessError("Cannot export a benchmark without sealed events")
    if specification_hash(Path(lineage["fs_root_path"])) != lineage["fs_root_hash"]:
        connection.close()
        raise HarnessError("Functional specification changed after lineage seal")
    ledger = effective_ledger(window, rows)
    try:
        verify_proof_artifacts(ledger)
    except HarnessError:
        connection.close()
        raise
    effective_plan_hash = digest_json(ledger)
    definition_hash = benchmark_definition_hash(ledger)
    required_slots = {task["id"] for task in ledger["tasks"]}
    accepted: dict[str, dict[str, Any]] = {}
    failed_slots: set[str] = set()
    completed_row = valid_completed_row(connection, lineage_id, run_id, window_id, rows)
    if completed_row is None:
        connection.close()
        raise HarnessError("Cannot export a benchmark without one valid terminal completion")
    completed_payload = event_payload(completed_row)
    completion_mode = (
        "preflight_gate"
        if completed_payload.get("outcome") == "preflight_blocked"
        else "execution"
    )
    for row in rows:
        payload = json.loads(row["payload_json"])
        if row["kind"] == "task_accepted" and isinstance(payload.get("slot_id"), str):
            accepted[payload["slot_id"]] = payload
        elif row["kind"] == "task_failed" and isinstance(payload.get("slot_id"), str):
            failed_slots.add(payload["slot_id"])

    permits = {
        row["event_hash"]: json.loads(row["payload_json"])
        for row in rows
        if row["kind"] == "dispatch_permitted"
    }
    accepted_payloads = [accepted[slot] for slot in required_slots if slot in accepted]
    permit_hashes = [payload.get("permit_event_hash") for payload in accepted_payloads]
    permits_valid = (
        len(permit_hashes) == len(set(permit_hashes))
        and all(valid_sha256(value) and value in permits for value in permit_hashes)
        and all(
            permits[payload["permit_event_hash"]].get("slot_id") == payload.get("slot_id")
            and permits[payload["permit_event_hash"]].get("worker_profile")
            == payload.get("worker_profile")
            for payload in accepted_payloads
        )
    )
    worker_executed = len(accepted_payloads) == len(required_slots) and all(
        isinstance(payload.get("worker_identity"), str) and payload["worker_identity"].strip()
        for payload in accepted_payloads
    ) and permits_valid
    test_completed = len(accepted_payloads) == len(required_slots) and all(
        payload.get("test_completed") is True and payload.get("test_result") == "passed"
        for payload in accepted_payloads
    )
    files_valid = True
    try:
        for payload in accepted_payloads:
            verify_file_hash(payload.get("receipt_path"), payload.get("receipt_sha256"), "Receipt")
            artifacts = payload.get("artifact_hashes")
            if not isinstance(artifacts, dict) or not artifacts:
                raise HarnessError("Accepted task has no artifact hashes")
            for artifact_path, artifact_hash in artifacts.items():
                verify_file_hash(artifact_path, artifact_hash, "Artifact")
    except HarnessError:
        files_valid = False
    if completion_mode == "preflight_gate":
        blocker_rows = [row for row in rows if row["kind"] == "preflight_blocked"]
        try:
            blocker_index = rows.index(blocker_rows[0])
            validate_preflight_blocker(
                connection,
                lineage_id,
                run_id,
                window_id,
                event_payload(blocker_rows[0]),
                rows[:blocker_index],
                verify_files=True,
            )
        except (HarnessError, IndexError):
            files_valid = False
    evidence_valid = verify_chain(rows) and (
        (completion_mode == "preflight_gate" and files_valid)
        or (
            len(accepted_payloads) == len(required_slots)
            and permits_valid
            and files_valid
        )
    )
    acceptance_passed = completion_mode == "execution" and set(accepted) == required_slots
    if completion_mode == "preflight_gate":
        worker_executed = False
        test_completed = False
    quality = {
        "worker_executed": worker_executed,
        "test_completed": test_completed,
        "acceptance_passed": acceptance_passed,
        "evidence_valid": evidence_valid,
    }
    deadline_misses = sum(row["kind"] == "deadline_missed" for row in rows)
    terminal_at = parse_iso(completed_row["at_utc"])
    elapsed = (terminal_at - parse_iso(window["started_utc"])).total_seconds()
    validate_token_use(completed_payload)
    tokens = completed_payload.get("tokens")

    skill_root = Path(lineage["skill_root"])
    current_skill_hash = digest_json(skill_file_map(skill_root))
    if current_skill_hash != window["skill_hash"]:
        connection.close()
        raise HarnessError("Cannot export benchmark from a skill tree changed after window seal")
    skill_bytes = skill_size_bytes(skill_root)
    unresolved_failures = sorted(failed_slots - set(accepted))
    result = {
        "provenance": {
            "producer": f"de67-deadline-harness/{VERSION}",
            "lineage_id": lineage_id,
            "run_id": run_id,
            "window_id": window_id,
            "definition_hash": definition_hash,
            "effective_plan_hash": effective_plan_hash,
            "fs_hash": lineage["fs_root_hash"],
            "comparison_epoch": lineage["frozen_hash"],
            "skill_hash": window["skill_hash"],
            "event_chain_hash": rows[-1]["event_hash"],
            "state_db": str(db_path.resolve()),
        },
        "quality": quality,
        "quality_context": {
            "window_kind": completion_mode,
            "execution_quality_applicable": completion_mode == "execution",
            "authorized_preflight_blocker": completion_mode == "preflight_gate",
        },
        "deadline": {"misses": deadline_misses, "elapsed_seconds": elapsed},
        "usage": {"tokens": tokens},
        "skill": {"bytes": skill_bytes},
        "target_failure_resolved": all(quality.values()) and deadline_misses == 0,
        "new_failure_ids": unresolved_failures,
    }
    benchmark_binding = ledger.get("benchmark_binding")
    if benchmark_binding is not None:
        result["provenance"]["git"] = benchmark_binding["git"]
        result["provenance"]["product_frontier"] = benchmark_binding["product_frontier"]
        result["mutation"] = completed_payload["mutation"]
    proof = ledger.get("proof")
    if isinstance(proof, dict):
        result["provenance"]["semantic_condition_manifest_hash"] = digest_json(
            proof["contract"]["semantic_manifest"]
        )
        result["provenance"]["proof_plan_hash"] = digest_json(proof["plan"])
        result["provenance"]["product_frontier"] = proof["contract"][
            "accepted_product_frontier"
        ]
        proof_routes = {
            payload.get("conformance_route")
            for payload in permits.values()
            if non_empty_text(payload.get("proof_review_event_hash"))
        }
        if len(proof_routes) != 1:
            connection.close()
            raise HarnessError("Proof benchmark requires one exercised conformance route")
        result["provenance"]["conformance_route"] = next(iter(proof_routes))
    connection.close()
    return result


def revise_ledger(
    *,
    db_path: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    ledger: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    timing = validate_ledger(ledger)
    connection = connect(db_path)
    window = get_window(connection, lineage_id, run_id, window_id)
    rows = events_for(connection, lineage_id, run_id, window_id)
    current_ledger = effective_ledger(window, rows)
    if current_ledger.get("benchmark_binding") != ledger.get("benchmark_binding"):
        connection.close()
        raise HarnessError("Ledger revision cannot change the sealed benchmark binding")
    current_proof = current_ledger.get("proof")
    revised_proof = ledger.get("proof")
    if (current_proof is None) != (revised_proof is None):
        connection.close()
        raise HarnessError("Ledger revision cannot add or remove the proof surface")
    if (
        isinstance(current_proof, dict)
        and isinstance(revised_proof, dict)
        and current_proof["contract"] != revised_proof["contract"]
    ):
        connection.close()
        raise HarnessError("Ledger revision cannot change the frozen proof contract")
    current_obligations = obligation_map(current_ledger)
    revised_obligations = obligation_map(ledger)
    missing_claims = sorted(set(current_obligations) - set(revised_obligations))
    if missing_claims:
        connection.close()
        raise HarnessError(
            "Ledger revision cannot delete stable claims: " + ", ".join(missing_claims)
        )
    changed_claims = sorted(
        claim_id
        for claim_id, binding in current_obligations.items()
        if revised_obligations[claim_id] != binding
    )
    if changed_claims:
        connection.close()
        raise HarnessError(
            "Ledger revision cannot weaken or replace stable task obligations: "
            + ", ".join(changed_claims)
        )
    payload = {
        "ledger_hash": digest_json(ledger),
        "previous_ledger_hash": digest_json(current_ledger),
        "ledger": ledger,
        "task_obligations": revised_obligations,
        "timing_if_new_window": timing,
        "sealed_deadline_utc": window["deadline_utc"],
        "deadline_changed": False,
    }
    try:
        append_event(connection, lineage_id, run_id, window_id, "ledger_revised", payload, now)
    finally:
        connection.close()
    return payload


def record_event(
    *,
    db_path: Path,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    kind: str,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    if kind not in EVENT_KINDS:
        raise HarnessError(f"Unsupported external event kind: {kind}")
    connection = connect(db_path)
    try:
        expiry = expire_window(
            connection=connection,
            install_root=install_root,
            lineage_id=lineage_id,
            run_id=run_id,
            window_id=window_id,
            now=now,
        )
        event_hash = append_event(connection, lineage_id, run_id, window_id, kind, payload, now)
        return {"event_hash": event_hash, "deadline_state": expiry}
    finally:
        connection.close()


def permit_dispatch(
    *,
    db_path: Path,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    slot_id: str,
    worker_profile: str,
    worker_identity: str | None = None,
    causal_evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    connection = connect(db_path)
    expiry = expire_window(
        connection=connection,
        install_root=install_root,
        lineage_id=lineage_id,
        run_id=run_id,
        window_id=window_id,
        now=now,
    )
    rows = events_for(connection, lineage_id, run_id, window_id)
    if (
        expiry.get("expired")
        or valid_completed_row(connection, lineage_id, run_id, window_id, rows)
        or lineage_review_state(connection, lineage_id)["review_required"]
    ):
        connection.close()
        raise HarnessError("Dispatch denied: the sealed window no longer permits new work")
    window = get_window(connection, lineage_id, run_id, window_id)
    ledger = effective_ledger(window, rows)
    task = next((item for item in ledger["tasks"] if item["id"] == slot_id), None)
    if task is None:
        connection.close()
        raise HarnessError("Dispatch denied: slot is absent from the sealed ledger")
    if task["worker_profile"] != worker_profile:
        connection.close()
        raise HarnessError("Dispatch denied: worker profile differs from the sealed ledger")
    permit_payload = {
        "slot_id": slot_id,
        "worker_profile": worker_profile,
        "ledger_hash": digest_json(ledger),
        "obligation_digest": task_obligation(task)["obligation_digest"],
    }
    if worker_identity is not None:
        permit_payload["worker_identity"] = worker_identity
    prior_failures = [
        event_payload(row) for row in rows
        if row["kind"] == "task_failed" and event_payload(row).get("slot_id") == slot_id
    ]
    if prior_failures:
        candidate_evidence = causal_evidence or prior_failures[-1]["causal_evidence"]
        validate_causal_evidence_binding(candidate_evidence)
        permit_payload["causal_evidence"] = candidate_evidence
        candidate_fingerprint = digest_json(
            {
                "obligation_digest": permit_payload["obligation_digest"],
                "worker_identity": worker_identity,
                "causal_evidence": candidate_evidence,
            }
        )
        groups: dict[str, list[dict[str, Any]]] = {}
        for failure in prior_failures:
            groups.setdefault(failure.get("causal_fingerprint", ""), []).append(failure)
        repeated_fingerprints = {
            fingerprint for fingerprint, group in groups.items() if len(group) >= 2
        }
        if repeated_fingerprints:
            route = accepted_retry_route(rows)
            latest_failure = prior_failures[-1]
            prior_worker = latest_failure.get("worker_identity")
            if candidate_fingerprint in repeated_fingerprints:
                connection.close()
                raise HarnessError(
                    "Dispatch denied: unchanged equivalent retry already failed twice"
                )
            if route == "same_worker_changed_evidence" and worker_identity != prior_worker:
                connection.close()
                raise HarnessError(
                    "Dispatch denied: retry route requires the same worker with changed evidence"
                )
            receipt = (
                candidate_evidence.get("receipt") if isinstance(candidate_evidence, dict) else None
            )
            prior_receipt = latest_failure.get("causal_evidence", {}).get("receipt")
            owner = receipt.get("owner") if isinstance(receipt, dict) else None
            prior_owner = prior_receipt.get("owner") if isinstance(prior_receipt, dict) else None
            if route == "replace_worker_changed_owner" and (
                worker_identity == prior_worker or not non_empty_text(owner) or owner == prior_owner
            ):
                connection.close()
                raise HarnessError(
                    "Dispatch denied: retry route requires a replacement worker and changed owner"
                )
    if isinstance(ledger.get("proof"), dict):
        if not non_empty_text(worker_identity):
            connection.close()
            raise HarnessError("Proof dispatch requires an intended worker identity")
        try:
            review = matching_proof_review(
                connection, lineage_id, run_id, window_id, ledger, rows
            )
        except Exception:
            connection.close()
            raise
        permit_payload.update(proof_runtime_binding(ledger))
        permit_payload["proof_review_event_hash"] = review["event_hash"]
        permit_payload["conformance_route"] = event_payload(review)["conformance_route"]
    try:
        event_hash = append_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            "dispatch_permitted",
            permit_payload,
            now,
        )
    finally:
        connection.close()
    return {"permitted": True, "permit_event_hash": event_hash, "deadline": expiry}


def watch(
    *, db_path: Path, install_root: Path, lineage_id: str, run_id: str, window_id: str
) -> None:
    connection = connect(db_path)
    rows = events_for(connection, lineage_id, run_id, window_id)
    if valid_completed_row(connection, lineage_id, run_id, window_id, rows):
        connection.close()
        return
    append_event(
        connection,
        lineage_id,
        run_id,
        window_id,
        "watcher_ready",
        {"pid": os.getpid()},
    )
    connection.close()
    while True:
        connection = connect(db_path)
        result = expire_window(
            connection=connection,
            install_root=install_root,
            lineage_id=lineage_id,
            run_id=run_id,
            window_id=window_id,
        )
        rows = events_for(connection, lineage_id, run_id, window_id)
        completed = valid_completed_row(connection, lineage_id, run_id, window_id, rows)
        connection.close()
        if result.get("expired") or completed is not None:
            return
        time.sleep(min(max(float(result["remaining_seconds"]), 0.1), 30.0))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessError(f"Expected JSON object in {path}")
    return value


def common_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lineage-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--window-id", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    opened = subparsers.add_parser("open-window", help="Deploy, seal, and start a ledger clock")
    common_identity(opened)
    opened.add_argument("--fs-root", type=Path, required=True)
    opened.add_argument("--ledger", type=Path, required=True)
    opened.add_argument("--install-root", type=Path, default=default_install_root())

    status = subparsers.add_parser("status", help="Read and enforce a sealed window status")
    common_identity(status)
    status.add_argument("--install-root", type=Path, default=default_install_root())

    revise = subparsers.add_parser("revise-ledger", help="Record a revision without changing time")
    common_identity(revise)
    revise.add_argument("--ledger", type=Path, required=True)
    revise.add_argument("--install-root", type=Path, default=default_install_root())

    record = subparsers.add_parser("record", help="Append a compact window event")
    common_identity(record)
    record.add_argument("--kind", choices=sorted(EVENT_KINDS), required=True)
    record.add_argument("--payload", type=Path, required=True)
    record.add_argument("--install-root", type=Path, default=default_install_root())

    permit = subparsers.add_parser("permit-dispatch", help="Issue a sealed pre-spawn permit")
    common_identity(permit)
    permit.add_argument("--slot-id", required=True)
    permit.add_argument("--worker-profile", required=True)
    permit.add_argument("--worker-identity")
    permit.add_argument("--causal-evidence", type=Path)
    permit.add_argument("--install-root", type=Path, default=default_install_root())

    export = subparsers.add_parser("export-benchmark", help="Derive a benchmark receipt from events")
    common_identity(export)
    export.add_argument("--install-root", type=Path, default=default_install_root())

    review = subparsers.add_parser(
        "record-lineage-review", help="Bind a fresh external review to all current lineage misses"
    )
    common_identity(review)
    review.add_argument("--payload", type=Path, required=True)
    review.add_argument("--install-root", type=Path, default=default_install_root())

    watcher = subparsers.add_parser("watch", help=argparse.SUPPRESS)
    common_identity(watcher)
    watcher.add_argument("--install-root", type=Path, required=True)
    watcher.add_argument("--db", type=Path, required=True)
    return parser


def resolve_db(arguments: argparse.Namespace) -> Path:
    return arguments.install_root / "state.sqlite3"


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    try:
        if arguments.command == "open-window":
            result = open_window(
                db_path=resolve_db(arguments),
                install_root=arguments.install_root,
                source_script=Path(__file__),
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                fs_root=arguments.fs_root,
                ledger=read_json(arguments.ledger),
            )
        elif arguments.command == "status":
            result = status_window(
                db_path=resolve_db(arguments),
                install_root=arguments.install_root,
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
            )
        elif arguments.command == "revise-ledger":
            result = revise_ledger(
                db_path=resolve_db(arguments),
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                ledger=read_json(arguments.ledger),
            )
        elif arguments.command == "record":
            result = record_event(
                db_path=resolve_db(arguments),
                install_root=arguments.install_root,
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                kind=arguments.kind,
                payload=read_json(arguments.payload),
            )
        elif arguments.command == "permit-dispatch":
            result = permit_dispatch(
                db_path=resolve_db(arguments),
                install_root=arguments.install_root,
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                slot_id=arguments.slot_id,
                worker_profile=arguments.worker_profile,
                worker_identity=arguments.worker_identity,
                causal_evidence=(
                    read_json(arguments.causal_evidence) if arguments.causal_evidence else None
                ),
            )
        elif arguments.command == "export-benchmark":
            result = export_benchmark(
                db_path=resolve_db(arguments),
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
            )
        elif arguments.command == "record-lineage-review":
            result = record_event(
                db_path=resolve_db(arguments),
                install_root=arguments.install_root,
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                kind="coordinator_review_completed",
                payload=read_json(arguments.payload),
            )
        elif arguments.command == "watch":
            watch(
                db_path=arguments.db,
                install_root=arguments.install_root,
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
            )
            return 0
        else:
            parser.error("Unknown command")
            return 2
    except (HarnessError, OSError, sqlite3.Error, json.JSONDecodeError) as error:
        print(canonical({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(canonical({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
