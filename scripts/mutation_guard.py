#!/usr/bin/env python3
"""Parent-side mutation boundary and stored-baseline benchmark guard."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

try:
    from scripts import deadline_harness
except ImportError:  # Direct execution from the scripts directory.
    import deadline_harness  # type: ignore[no-redef]


class GuardError(RuntimeError):
    pass


IGNORED_PARTS = {".git", ".skill-init", ".de67-lab", "__pycache__", ".pytest_cache"}
ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "mutation-policy.json"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuardError(f"Expected JSON object in {path}")
    return value


def file_map(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(root).as_posix()
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def changed_paths(base: Path, candidate: Path) -> list[str]:
    before = file_map(base)
    after = file_map(candidate)
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def validate_policy_files(root: Path, policy: dict[str, Any]) -> None:
    schemas = policy.get("policy_schemas")
    if not isinstance(schemas, dict):
        raise GuardError("Frozen mutation policy has no policy_schemas")
    for relative, schema in schemas.items():
        if not isinstance(schema, dict):
            raise GuardError(f"Invalid schema for {relative}")
        value = read_json(root / relative)
        unknown = sorted(set(value) - set(schema))
        missing = sorted(set(schema) - set(value))
        if unknown or missing:
            raise GuardError(
                f"{relative} shape changed; unknown={unknown or 'none'}, missing={missing or 'none'}"
            )
        for key, allowed in schema.items():
            if value[key] not in allowed:
                raise GuardError(f"{relative}.{key} is outside the frozen vocabulary")


def changed_policy_keys(base: Path, candidate: Path, policy: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for relative in policy["policy_schemas"]:
        before = read_json(base / relative)
        after = read_json(candidate / relative)
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                keys.append(f"{relative}.{key}")
    return keys


def validate_intent(
    intent: dict[str, Any], base: Path, candidate: Path, policy: dict[str, Any]
) -> list[str]:
    if intent.get("kind") != "efficiency_mutation":
        raise GuardError("Mutation requires kind=efficiency_mutation")
    for field in ("target_failure_id", "observed_bottleneck"):
        if not isinstance(intent.get(field), str) or not intent[field].strip():
            raise GuardError(f"Mutation intent requires {field}")
    if intent.get("quality_contract_unchanged") is not True:
        raise GuardError("Mutation must preserve the frozen quality contract")
    if intent.get("expected_reduction") not in policy["efficiency_reductions"]:
        raise GuardError("Mutation intent has no authorized efficiency objective")
    actual_keys = sorted(changed_policy_keys(base, candidate, policy))
    declared_keys = intent.get("changed_policy_keys")
    if not isinstance(declared_keys, list) or sorted(declared_keys) != actual_keys:
        raise GuardError("Mutation intent does not exactly name the changed policy keys")
    return actual_keys


def validate_worker_evidence(evidence: dict[str, Any]) -> None:
    required_strings = ("worker_identity", "deadline_id", "status")
    if evidence.get("kind") != "worker_failure":
        raise GuardError("Worker mutation requires kind=worker_failure")
    for field in required_strings:
        if not isinstance(evidence.get(field), str) or not evidence[field].strip():
            raise GuardError(f"Worker failure evidence requires {field}")
    if evidence["status"] not in {"failed", "deadline_missed"}:
        raise GuardError("Worker failure status must be failed or deadline_missed")
    if evidence.get("work_performed") is not True:
        raise GuardError("Worker mutation requires evidence that real assigned work began")
    if evidence.get("test_state") not in {"failed", "passed"}:
        raise GuardError("Worker mutation requires a completed test result")
    receipt_hash = evidence.get("receipt_sha256")
    if not isinstance(receipt_hash, str) or len(receipt_hash) != 64:
        raise GuardError("Worker failure evidence requires a receipt SHA-256")
    artifacts = evidence.get("artifact_hashes")
    if not isinstance(artifacts, dict) or not artifacts:
        raise GuardError("Worker failure evidence requires identity-bound artifact hashes")
    if not all(
        isinstance(path, str) and isinstance(value, str) and len(value) == 64
        for path, value in artifacts.items()
    ):
        raise GuardError("Worker artifact hashes must map paths to SHA-256 values")


def validate_coordinator_evidence(evidence: dict[str, Any], threshold: int) -> None:
    if evidence.get("kind") != "coordinator_review":
        raise GuardError("Coordinator mutation requires kind=coordinator_review")
    failures = evidence.get("window_failures")
    if not isinstance(failures, list):
        raise GuardError("Coordinator review requires window_failures")
    identities: set[str] = set()
    for failure in failures:
        if not isinstance(failure, dict):
            raise GuardError("Each window failure must be an object")
        identity = failure.get("deadline_id")
        if not isinstance(identity, str) or not identity.strip():
            raise GuardError("Each window failure requires deadline_id")
        if failure.get("deadline_missed") is not True:
            raise GuardError("Each coordinator failure must be a sealed deadline miss")
        identities.add(identity)
    if len(identities) < threshold:
        raise GuardError(
            f"Coordinator mutation requires {threshold} distinct failed windows; found {len(identities)}"
        )


def frozen_hash(root: Path, policy: dict[str, Any]) -> str:
    allowed = {
        relative
        for scope in policy.get("scopes", {}).values()
        for relative in scope.get("allowed_paths", [])
    }
    values = {
        relative: value
        for relative, value in file_map(root).items()
        if relative not in allowed
    }
    if not values:
        raise GuardError("Frozen parent authority is empty")
    return digest_json(values)


def verify_event_chain(rows: list[sqlite3.Row]) -> None:
    previous_hash = "0" * 64
    for row in rows:
        record = {
            "lineage_id": row["lineage_id"],
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "at_utc": row["at_utc"],
            "kind": row["kind"],
            "payload": json.loads(row["payload_json"]),
            "previous_hash": previous_hash,
        }
        if row["previous_hash"] != previous_hash or row["event_hash"] != digest_json(record):
            raise GuardError("Harness event chain is invalid")
        previous_hash = row["event_hash"]


def evidence_from_harness(
    *,
    db_path: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    scope: str,
    event_hash: str | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    lineage = connection.execute(
        "SELECT * FROM lineages WHERE lineage_id=?", (lineage_id,)
    ).fetchone()
    if lineage is None:
        connection.close()
        raise GuardError("Mutation lineage is not sealed by the deadline harness")
    if Path(lineage["skill_root"]).resolve() != ROOT.resolve():
        connection.close()
        raise GuardError("Guard is not running from the sealed accepted-parent root")
    if lineage["frozen_hash"] != frozen_hash(ROOT, policy):
        connection.close()
        raise GuardError("Frozen parent authority differs from the sealed lineage")

    if scope == "worker":
        window = connection.execute(
            """
            SELECT * FROM windows
            WHERE lineage_id=? AND run_id=? AND window_id=?
            """,
            (lineage_id, run_id, window_id),
        ).fetchone()
        if window is None:
            connection.close()
            raise GuardError("Worker mutation window is not sealed")
        if window["skill_hash"] != digest_json(file_map(ROOT)):
            connection.close()
            raise GuardError("Current parent tree is not the skill version that ran the worker")
        rows = connection.execute(
            """
            SELECT * FROM events WHERE lineage_id=? AND run_id=? AND window_id=?
            ORDER BY sequence
            """,
            (lineage_id, run_id, window_id),
        ).fetchall()
        verify_event_chain(rows)
        event = next((row for row in rows if row["event_hash"] == event_hash), None)
        if event is None or event["kind"] != "task_failed":
            connection.close()
            raise GuardError("Worker mutation requires a sealed task_failed event hash")
        evidence = json.loads(event["payload_json"])
        connection.close()
        return evidence

    failures = connection.execute(
        """
        SELECT w.run_id, w.window_id, w.skill_hash, e.event_hash
        FROM events e
        JOIN windows w USING (lineage_id, run_id, window_id)
        WHERE e.lineage_id=? AND e.kind='deadline_missed'
        ORDER BY e.sequence
        """,
        (lineage_id,),
    ).fetchall()
    connection.close()
    threshold = int(policy["coordinator_review_threshold"])
    distinct = {(row["run_id"], row["window_id"]): row for row in failures}
    if len(distinct) < threshold:
        raise GuardError(f"Coordinator mutation requires {threshold} sealed failed windows")
    latest = list(distinct.values())[-1]
    if latest["skill_hash"] != digest_json(file_map(ROOT)):
        raise GuardError("Current parent tree is not the latest failed coordinator skill version")
    return {
        "kind": "coordinator_review",
        "window_failures": [
            {
                "deadline_id": f"{lineage_id}/{row['run_id']}/{row['window_id']}",
                "deadline_missed": True,
                "event_hash": row["event_hash"],
            }
            for row in distinct.values()
        ],
    }


def validate_mutation(
    *,
    base: Path,
    candidate: Path,
    scope: str,
    evidence: dict[str, Any],
    intent: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    scopes = policy.get("scopes", {})
    if scope not in scopes:
        raise GuardError(f"Unknown mutation scope: {scope}")
    if scope == "worker":
        validate_worker_evidence(evidence)
    elif scope == "coordinator":
        validate_coordinator_evidence(evidence, int(policy["coordinator_review_threshold"]))

    validate_policy_files(base, policy)
    validate_policy_files(candidate, policy)
    policy_keys = validate_intent(intent, base, candidate, policy)
    changes = changed_paths(base, candidate)
    if not changes:
        raise GuardError("Candidate contains no mutation")
    allowed = scopes[scope]["allowed_paths"]
    illegal = [path for path in changes if not matches_any(path, allowed)]
    if illegal:
        raise GuardError(f"Mutation crosses frozen boundary: {', '.join(illegal)}")
    return {
        "scope": scope,
        "changed_paths": changes,
        "changed_policy_keys": policy_keys,
        "expected_reduction": intent["expected_reduction"],
        "allowed_paths": allowed,
    }


def quality_passes(result: dict[str, Any], predicates: list[str]) -> bool:
    quality = result.get("quality")
    return isinstance(quality, dict) and all(quality.get(predicate) is True for predicate in predicates)


def validate_benchmark_provenance(baseline: dict[str, Any], candidate: dict[str, Any]) -> None:
    baseline_source = baseline.get("provenance")
    candidate_source = candidate.get("provenance")
    if not isinstance(baseline_source, dict) or not isinstance(candidate_source, dict):
        raise GuardError("Benchmark results require harness provenance")
    for source in (baseline_source, candidate_source):
        if not isinstance(source.get("producer"), str) or not source["producer"].startswith(
            "de67-deadline-harness/"
        ):
            raise GuardError("Benchmark result was not produced by the deadline harness")
        for field in (
            "definition_hash",
            "fs_hash",
            "comparison_epoch",
            "skill_hash",
            "event_chain_hash",
        ):
            value = source.get(field)
            if not isinstance(value, str) or len(value) != 64:
                raise GuardError(f"Benchmark provenance requires SHA-256 {field}")
    for field in ("definition_hash", "fs_hash", "comparison_epoch"):
        if baseline_source[field] != candidate_source[field]:
            raise GuardError(f"Benchmark comparison changed {field}")


def benchmark_from_harness(
    *,
    install_root: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    expected_skill_root: Path,
) -> dict[str, Any]:
    db_path = install_root / "state.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT skill_root FROM lineages WHERE lineage_id=?",
        (lineage_id,),
    ).fetchone()
    connection.close()
    if row is None:
        raise GuardError("Benchmark lineage is absent from the sealed harness database")
    if Path(row["skill_root"]).resolve() != expected_skill_root.resolve():
        raise GuardError("Benchmark lineage is bound to a different skill tree")
    try:
        return deadline_harness.export_benchmark(
            db_path=db_path,
            lineage_id=lineage_id,
            run_id=run_id,
            window_id=window_id,
        )
    except (deadline_harness.HarnessError, OSError, sqlite3.Error) as error:
        raise GuardError(f"Cannot derive sealed benchmark: {error}") from error


def numeric(result: dict[str, Any], section: str, field: str) -> float | None:
    value = result.get(section, {}).get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardError(f"{section}.{field} must be numeric or null")
    return float(value)


def fitness_values(result: dict[str, Any]) -> dict[str, float | None]:
    misses = numeric(result, "deadline", "misses")
    elapsed = numeric(result, "deadline", "elapsed_seconds")
    if misses is None or elapsed is None:
        raise GuardError("Benchmark result requires deadline.misses and deadline.elapsed_seconds")
    return {
        "deadline_misses": misses,
        "elapsed_seconds": elapsed,
        "tokens": numeric(result, "usage", "tokens"),
        "skill_bytes": numeric(result, "skill", "bytes"),
    }


def compare_benchmark(
    baseline: dict[str, Any], candidate: dict[str, Any], predicates: list[str]
) -> dict[str, Any]:
    validate_benchmark_provenance(baseline, candidate)
    if not quality_passes(candidate, predicates):
        raise GuardError("Candidate violates frozen quality predicates")
    if candidate.get("target_failure_resolved") is not True:
        raise GuardError("Candidate did not resolve the targeted failure")
    new_failures = candidate.get("new_failure_ids", [])
    if not isinstance(new_failures, list) or new_failures:
        raise GuardError("Candidate introduces a new benchmark failure")

    candidate_values = fitness_values(candidate)
    baseline_quality = quality_passes(baseline, predicates)
    baseline_values = fitness_values(baseline)
    dimensions = ["deadline_misses", "elapsed_seconds"]
    for optional in ("tokens", "skill_bytes"):
        baseline_exposes = baseline_values[optional] is not None
        candidate_exposes = candidate_values[optional] is not None
        if baseline_exposes != candidate_exposes:
            raise GuardError(f"Candidate changed metric availability for {optional}")
        if baseline_exposes:
            dimensions.append(optional)
    baseline_fitness = tuple(float(baseline_values[name]) for name in dimensions)
    candidate_fitness = tuple(float(candidate_values[name]) for name in dimensions)
    improved = not baseline_quality or candidate_fitness < baseline_fitness
    if not improved:
        raise GuardError("Candidate does not improve the stored parent benchmark")
    return {
        "promotable": True,
        "baseline_quality": baseline_quality,
        "baseline_fitness": baseline_fitness,
        "candidate_fitness": candidate_fitness,
        "dimensions": dimensions,
        "comparison": "candidate-only run versus stored accepted-parent result",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate candidate mutation boundaries")
    validate.add_argument("--candidate", type=Path, required=True)
    validate.add_argument("--scope", choices=("worker", "coordinator"), required=True)
    validate.add_argument("--install-root", type=Path, default=Path.home() / ".codex" / "de67-lab")
    validate.add_argument("--lineage-id", required=True)
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--window-id", required=True)
    validate.add_argument("--event-hash")
    validate.add_argument("--intent", type=Path, required=True)

    compare = subparsers.add_parser("compare", help="Compare candidate to stored parent benchmark")
    compare.add_argument("--baseline-install-root", type=Path, required=True)
    compare.add_argument("--baseline-lineage-id", required=True)
    compare.add_argument("--baseline-run-id", required=True)
    compare.add_argument("--baseline-window-id", required=True)
    compare.add_argument("--candidate-skill", type=Path, required=True)
    compare.add_argument("--candidate-install-root", type=Path, required=True)
    compare.add_argument("--candidate-lineage-id", required=True)
    compare.add_argument("--candidate-run-id", required=True)
    compare.add_argument("--candidate-window-id", required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        policy = read_json(POLICY_PATH)
        if arguments.command == "validate":
            evidence = evidence_from_harness(
                db_path=arguments.install_root / "state.sqlite3",
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
                scope=arguments.scope,
                event_hash=arguments.event_hash,
                policy=policy,
            )
            result = validate_mutation(
                base=ROOT,
                candidate=arguments.candidate,
                scope=arguments.scope,
                evidence=evidence,
                intent=read_json(arguments.intent),
                policy=policy,
            )
        else:
            baseline = benchmark_from_harness(
                install_root=arguments.baseline_install_root,
                lineage_id=arguments.baseline_lineage_id,
                run_id=arguments.baseline_run_id,
                window_id=arguments.baseline_window_id,
                expected_skill_root=ROOT,
            )
            candidate = benchmark_from_harness(
                install_root=arguments.candidate_install_root,
                lineage_id=arguments.candidate_lineage_id,
                run_id=arguments.candidate_run_id,
                window_id=arguments.candidate_window_id,
                expected_skill_root=arguments.candidate_skill,
            )
            result = compare_benchmark(
                baseline,
                candidate,
                list(policy["quality_predicates"]),
            )
    except (GuardError, OSError, json.JSONDecodeError, KeyError) as error:
        print(canonical({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(canonical({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
