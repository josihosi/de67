#!/usr/bin/env python3
"""Parent-side mutation boundary and stored-baseline benchmark guard."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
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
RECEIPT_VERSION = 1


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def seal_receipt(value: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(value)
    sealed.pop("receipt_hash", None)
    sealed["receipt_hash"] = digest_json(sealed)
    return sealed


def verify_receipt(receipt: dict[str, Any], kind: str) -> None:
    if receipt.get("kind") != kind or receipt.get("version") != RECEIPT_VERSION:
        raise GuardError(f"Expected a version {RECEIPT_VERSION} {kind} receipt")
    claimed = receipt.get("receipt_hash")
    if not valid_sha256(claimed):
        raise GuardError(f"{kind} receipt has no valid receipt hash")
    unsealed = dict(receipt)
    unsealed.pop("receipt_hash", None)
    if digest_json(unsealed) != claimed:
        raise GuardError(f"{kind} receipt was changed after it was sealed")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuardError(f"Expected JSON object in {path}")
    return value


def git_output(root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or "").strip()
        raise GuardError(f"Git identity check failed for {root}: {detail or error}") from error
    return completed.stdout.strip()


def registered_worktrees(root: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in git_output(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return records


def git_identity(root: Path, *, require_clean: bool = True) -> dict[str, Any]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise GuardError(f"Candidate Git worktree does not exist: {resolved}")
    top = Path(git_output(resolved, "rev-parse", "--show-toplevel")).resolve()
    if top != resolved:
        raise GuardError("Mutation path must be the exact root of a Git worktree")
    common_text = git_output(resolved, "rev-parse", "--git-common-dir")
    common = Path(common_text)
    if not common.is_absolute():
        common = (resolved / common).resolve()
    else:
        common = common.resolve()
    branch_ref = git_output(resolved, "symbolic-ref", "-q", "HEAD")
    if not branch_ref.startswith("refs/heads/"):
        raise GuardError("Mutation candidate must be on a dedicated local branch")
    commit = git_output(resolved, "rev-parse", "HEAD^{commit}")
    tree = git_output(resolved, "rev-parse", "HEAD^{tree}")
    status = git_output(resolved, "status", "--porcelain=v1", "--untracked-files=all")
    if require_clean and status:
        raise GuardError("Mutation Git worktree must be clean and fully committed")
    matching = [
        record
        for record in registered_worktrees(resolved)
        if Path(record.get("worktree", "")).resolve() == resolved
    ]
    if len(matching) != 1:
        raise GuardError("Mutation path is not a uniquely registered Git worktree")
    registered = matching[0]
    if registered.get("HEAD") != commit or registered.get("branch") != branch_ref:
        raise GuardError("Registered worktree identity differs from candidate HEAD")
    return {
        "worktree": str(resolved),
        "common_git_dir": str(common),
        "branch": branch_ref,
        "commit": commit,
        "tree": tree,
        "skill_hash": digest_json(file_map(resolved)),
        "clean": not bool(status),
    }


def accepted_ref_name(value: str) -> str:
    if value.startswith("refs/heads/"):
        return value
    if not value or value.startswith("refs/"):
        raise GuardError("Accepted ref must name a local branch")
    return f"refs/heads/{value}"


def git_candidate_pair(base: Path, candidate: Path, accepted_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parent = git_identity(base)
    child = git_identity(candidate)
    expected_ref = accepted_ref_name(accepted_ref)
    if parent["branch"] != expected_ref:
        raise GuardError("Accepted-parent worktree is not checked out on the accepted branch")
    accepted_commit = git_output(base, "rev-parse", f"{expected_ref}^{{commit}}")
    if accepted_commit != parent["commit"]:
        raise GuardError("Accepted branch and accepted-parent HEAD differ")
    if parent["common_git_dir"] != child["common_git_dir"]:
        raise GuardError("Candidate is not a worktree of the accepted-parent repository")
    if parent["worktree"] == child["worktree"] or parent["branch"] == child["branch"]:
        raise GuardError("Candidate requires a separate dedicated branch and worktree")
    parents = git_output(candidate, "show", "-s", "--format=%P", child["commit"]).split()
    if parents != [parent["commit"]]:
        raise GuardError("Candidate must be derived directly from the last accepted parent")
    child["parent_commits"] = parents
    parent["accepted_ref"] = expected_ref
    return parent, child


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
    if not valid_sha256(receipt_hash):
        raise GuardError("Worker failure evidence requires a receipt SHA-256")
    artifacts = evidence.get("artifact_hashes")
    if not isinstance(artifacts, dict) or not artifacts:
        raise GuardError("Worker failure evidence requires identity-bound artifact hashes")
    if not all(
        isinstance(path, str) and valid_sha256(value)
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
        if not valid_sha256(failure.get("event_hash")):
            raise GuardError("Each coordinator failure requires its sealed deadline event hash")
        identities.add(identity)
    if len(identities) < threshold:
        raise GuardError(
            f"Coordinator mutation requires {threshold} distinct failed windows; found {len(identities)}"
        )
    review = evidence.get("fresh_review")
    if not isinstance(review, dict):
        raise GuardError("Coordinator mutation requires a sealed fresh Sol xhigh review")
    if review.get("reviewer_profile") != "sol-xhigh":
        raise GuardError("Coordinator mutation requires reviewer_profile=sol-xhigh")
    if not isinstance(review.get("reviewer_identity"), str) or not review["reviewer_identity"].strip():
        raise GuardError("Coordinator review requires a reviewer identity")
    if review.get("fresh") is not True or not valid_sha256(review.get("review_event_hash")):
        raise GuardError("Coordinator review must be fresh and sealed by the harness")
    if not valid_sha256(review.get("reviewed_parent_skill_hash")):
        raise GuardError("Coordinator review must bind the reviewed accepted-parent skill hash")
    reviewed = review.get("reviewed_failure_event_hashes")
    failure_hashes = sorted(failure["event_hash"] for failure in failures)
    if not isinstance(reviewed, list) or sorted(reviewed) != failure_hashes:
        raise GuardError("Fresh review does not exactly cover the sealed failed windows")


def validate_proof_policy_evidence(evidence: dict[str, Any], threshold: int) -> None:
    failures = evidence.get("proof_plan_failures")
    if not isinstance(failures, list):
        raise GuardError("P2 mutation requires proof_plan-owned failed windows")
    fingerprints: set[str] = set()
    identities: set[str] = set()
    for failure in failures:
        if not isinstance(failure, dict) or failure.get("failure_owner") != "proof_plan":
            raise GuardError("Product and harness failures cannot qualify for P2 mutation")
        fingerprint = failure.get("causal_fingerprint")
        if not valid_sha256(fingerprint):
            raise GuardError("P2 failure requires a causal fingerprint")
        if fingerprint in fingerprints:
            raise GuardError("Duplicate proof-plan causal fingerprints count once")
        fingerprints.add(fingerprint)
        identity = failure.get("deadline_id")
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise GuardError("P2 mutation requires distinct failed windows")
        identities.add(identity)
        if not valid_sha256(failure.get("assessment_event_hash")):
            raise GuardError("P2 failure requires a sealed authoritative assessment")
    if len(fingerprints) < threshold:
        raise GuardError(
            f"P2 mutation requires {threshold} causally distinct proof-plan failures; "
            f"found {len(fingerprints)}"
        )


def evidence_failure_ids(evidence: dict[str, Any]) -> set[str]:
    if evidence.get("kind") == "worker_failure":
        return {evidence["deadline_id"]}
    failures = evidence.get("window_failures", [])
    return {
        failure["deadline_id"]
        for failure in failures
        if isinstance(failure, dict) and isinstance(failure.get("deadline_id"), str)
    }


def validate_target_binding(intent: dict[str, Any], evidence: dict[str, Any]) -> None:
    target = intent.get("target_failure_id")
    if target not in evidence_failure_ids(evidence):
        raise GuardError("Mutation intent targets a failure outside the sealed failure evidence")


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
        SELECT w.run_id, w.window_id, w.skill_hash, e.event_hash, e.sequence
        FROM events e
        JOIN windows w USING (lineage_id, run_id, window_id)
        WHERE e.lineage_id=? AND e.kind='deadline_missed'
        ORDER BY e.sequence
        """,
        (lineage_id,),
    ).fetchall()
    threshold = int(policy["coordinator_review_threshold"])
    review_row = connection.execute(
        """
        SELECT * FROM events
        WHERE lineage_id=? AND event_hash=? AND kind='coordinator_review_completed'
        """,
        (lineage_id, event_hash),
    ).fetchone()
    try:
        if review_row is not None:
            review_rows = connection.execute(
                """
                SELECT * FROM events WHERE lineage_id=? AND run_id=? AND window_id=?
                ORDER BY sequence
                """,
                (lineage_id, review_row["run_id"], review_row["window_id"]),
            ).fetchall()
            verify_event_chain(review_rows)
    except (GuardError, sqlite3.Error, json.JSONDecodeError):
        connection.close()
        raise
    if review_row is None:
        connection.close()
        raise GuardError("Coordinator mutation requires a sealed coordinator_review_completed event")
    valid_review_batches = deadline_harness.valid_lineage_review_batches(connection, lineage_id)
    selected_valid_batch = next(
        (
            batch
            for valid_review, batch in valid_review_batches
            if valid_review["event_hash"] == event_hash
        ),
        None,
    )
    if selected_valid_batch is None:
        connection.close()
        raise GuardError("Coordinator mutation requires a currently valid sealed review receipt")
    review_payload = json.loads(review_row["payload_json"])
    reviewed_hashes = review_payload.get("reviewed_failure_event_hashes")
    if (
        not isinstance(reviewed_hashes, list)
        or len(reviewed_hashes) < threshold
        or len(reviewed_hashes) != len(set(reviewed_hashes))
    ):
        connection.close()
        raise GuardError(
            f"Coordinator mutation requires {threshold} distinct reviewed failed windows"
        )
    failures_by_hash = {row["event_hash"]: row for row in failures}
    reviewed_failures = [failures_by_hash.get(event_hash) for event_hash in reviewed_hashes]
    if any(row is None for row in reviewed_failures):
        connection.close()
        raise GuardError("Coordinator review cites an unknown missed-window event")
    reviewed = [row for row in reviewed_failures if row is not None]
    reviewed.sort(key=lambda row: row["sequence"])
    if reviewed_hashes != [row["event_hash"] for row in reviewed]:
        connection.close()
        raise GuardError("Coordinator review failure hashes are not in sealed event order")
    if reviewed_hashes != [row["event_hash"] for row in selected_valid_batch]:
        connection.close()
        raise GuardError("Coordinator review does not match its replay-validated failure batch")
    distinct = {(row["run_id"], row["window_id"]): row for row in reviewed}
    if len(distinct) != len(reviewed):
        connection.close()
        raise GuardError("Coordinator review repeats a failed ledger window")
    try:
        for row in reviewed:
            window_rows = connection.execute(
                """
                SELECT * FROM events WHERE lineage_id=? AND run_id=? AND window_id=?
                ORDER BY sequence
                """,
                (lineage_id, row["run_id"], row["window_id"]),
            ).fetchall()
            verify_event_chain(window_rows)
    except (GuardError, sqlite3.Error, json.JSONDecodeError):
        connection.close()
        raise
    latest = reviewed[-1]
    if latest["skill_hash"] != digest_json(file_map(ROOT)):
        connection.close()
        raise GuardError("Current parent tree is not the latest failed coordinator skill version")
    if review_row["sequence"] <= max(row["sequence"] for row in reviewed):
        connection.close()
        raise GuardError("Coordinator review predates one or more reviewed failed windows")
    review_payload["review_event_hash"] = review_row["event_hash"]
    all_events = connection.execute(
        "SELECT * FROM events WHERE lineage_id=? ORDER BY sequence", (lineage_id,)
    ).fetchall()
    assessments = [row for row in all_events if row["kind"] == "damage_assessment"]
    reviewed_windows = {(row["run_id"], row["window_id"]) for row in reviewed}
    qualified: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for assessment in assessments:
        if assessment["sequence"] >= review_row["sequence"]:
            continue
        if (assessment["run_id"], assessment["window_id"]) not in reviewed_windows:
            continue
        payload = json.loads(assessment["payload_json"])
        if payload.get("failure_owner") != "proof_plan":
            continue
        assessment_rows = connection.execute(
            """
            SELECT * FROM events WHERE lineage_id=? AND run_id=? AND window_id=?
            ORDER BY sequence
            """,
            (lineage_id, assessment["run_id"], assessment["window_id"]),
        ).fetchall()
        verify_event_chain(assessment_rows)
        assessment_index = next(
            index for index, row in enumerate(assessment_rows)
            if row["event_hash"] == assessment["event_hash"]
        )
        try:
            deadline_harness.validate_damage_assessment(
                connection,
                lineage_id,
                assessment["run_id"],
                assessment["window_id"],
                payload,
                assessment_rows[:assessment_index],
            )
        except deadline_harness.HarnessError as error:
            connection.close()
            raise GuardError(f"Invalid proof-plan damage assessment: {error}") from error
        fingerprint = payload.get("causal_fingerprint")
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        qualified.append(
            {
                "deadline_id": (
                    f"{lineage_id}/{assessment['run_id']}/{assessment['window_id']}"
                ),
                "failure_owner": "proof_plan",
                "causal_fingerprint": fingerprint,
                "assessment_event_hash": assessment["event_hash"],
            }
        )
    connection.close()
    return {
        "kind": "coordinator_review",
        "window_failures": [
            {
                "deadline_id": f"{lineage_id}/{row['run_id']}/{row['window_id']}",
                "deadline_missed": True,
                "event_hash": row["event_hash"],
            }
            for row in reviewed
        ],
        "proof_plan_failures": qualified,
        "fresh_review": review_payload,
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
    validate_target_binding(intent, evidence)
    changes_proof_policy = any(key.startswith("policy/proof.json.") for key in policy_keys)
    if changes_proof_policy:
        validate_proof_policy_evidence(evidence, int(policy["coordinator_review_threshold"]))
        proof_failure_ids = {
            failure["deadline_id"] for failure in evidence["proof_plan_failures"]
        }
        if intent.get("target_failure_id") not in proof_failure_ids:
            raise GuardError("P2 mutation target is not a qualifying proof-plan failure")
    changes = changed_paths(base, candidate)
    if not changes:
        raise GuardError("Candidate contains no mutation")
    allowed = scopes[scope]["allowed_paths"]
    illegal = [path for path in changes if not matches_any(path, allowed)]
    if illegal:
        raise GuardError(f"Mutation crosses frozen boundary: {', '.join(illegal)}")
    result = {
        "scope": scope,
        "changed_paths": changes,
        "changed_policy_keys": policy_keys,
        "expected_reduction": intent["expected_reduction"],
        "allowed_paths": allowed,
    }
    if changes_proof_policy:
        result["parent_conformance_route"] = read_json(
            base / "policy" / "proof.json"
        )["conformance_route"]
        result["candidate_conformance_route"] = read_json(
            candidate / "policy" / "proof.json"
        )["conformance_route"]
    return result


def valid_git_oid(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def validate_product_frontier(frontier: dict[str, Any]) -> None:
    if not isinstance(frontier.get("repository"), str) or not frontier["repository"].strip():
        raise GuardError("Product frontier requires a repository identity")
    for field in ("commit", "tree"):
        if not valid_git_oid(frontier.get(field)):
            raise GuardError(f"Product frontier requires a full Git {field} identity")


def validate_benchmark_identity(
    result: dict[str, Any],
    skill: dict[str, Any],
    product_frontier: dict[str, Any],
    *,
    required: bool = False,
) -> None:
    provenance = result.get("provenance")
    if not isinstance(provenance, dict):
        raise GuardError("Benchmark result requires provenance")
    supplied_git = provenance.get("git")
    if required and not isinstance(supplied_git, dict):
        raise GuardError("Mutation benchmark requires exact Git provenance")
    if supplied_git is not None:
        expected_git = {
            "worktree": skill["worktree"],
            "branch": skill["branch"],
            "commit": skill["commit"],
            "tree": skill["tree"],
        }
        if supplied_git != expected_git:
            raise GuardError("Benchmark Git provenance differs from the bound skill worktree")
    supplied_frontier = provenance.get("product_frontier")
    if required and not isinstance(supplied_frontier, dict):
        raise GuardError("Mutation benchmark requires exact product frontier provenance")
    if supplied_frontier is not None and supplied_frontier != product_frontier:
        raise GuardError("Benchmark product frontier differs from the bound accepted frontier")


def validate_effective_plan_receipt(result: dict[str, Any]) -> None:
    provenance = result.get("provenance")
    if not isinstance(provenance, dict) or not valid_sha256(
        provenance.get("effective_plan_hash")
    ):
        raise GuardError("Mutation benchmark requires SHA-256 effective_plan_hash provenance")


def create_validation_receipt(
    *,
    base: Path,
    candidate: Path,
    accepted_ref: str,
    scope: str,
    evidence: dict[str, Any],
    intent: dict[str, Any],
    policy: dict[str, Any],
    product_frontier: dict[str, Any],
    baseline_benchmark: dict[str, Any],
) -> dict[str, Any]:
    parent, child = git_candidate_pair(base, candidate, accepted_ref)
    mutation = validate_mutation(
        base=base,
        candidate=candidate,
        scope=scope,
        evidence=evidence,
        intent=intent,
        policy=policy,
    )
    validate_product_frontier(product_frontier)
    validate_benchmark_provenance(baseline_benchmark, baseline_benchmark)
    provenance = baseline_benchmark["provenance"]
    if provenance["skill_hash"] != parent["skill_hash"]:
        raise GuardError("Stored parent benchmark is for a different accepted-parent skill")
    validate_benchmark_identity(
        baseline_benchmark, parent, product_frontier, required=True
    )
    validate_effective_plan_receipt(baseline_benchmark)
    if scope == "coordinator":
        reviewed_hash = evidence["fresh_review"]["reviewed_parent_skill_hash"]
        if reviewed_hash != parent["skill_hash"]:
            raise GuardError("Fresh coordinator review covers a different accepted parent")
    return seal_receipt(
        {
            "kind": "de67-mutation-validation",
            "version": RECEIPT_VERSION,
            "decision": "validated",
            "accepted_parent": parent,
            "candidate": child,
            "mutation": {
                **mutation,
                "target_failure_id": intent["target_failure_id"],
                "evidence_hash": digest_json(evidence),
                "intent_hash": digest_json(intent),
            },
            "product_frontier": product_frontier,
            "product_frontier_hash": digest_json(product_frontier),
            "benchmark": {
                "definition_hash": provenance["definition_hash"],
                "baseline_result_hash": digest_json(baseline_benchmark),
            },
        }
    )


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
            if not valid_sha256(value):
                raise GuardError(f"Benchmark provenance requires SHA-256 {field}")
    for field in ("definition_hash", "fs_hash", "comparison_epoch"):
        if baseline_source[field] != candidate_source[field]:
            raise GuardError(f"Benchmark comparison changed {field}")
    for source in (baseline_source, candidate_source):
        proof_plan_hash = source.get("proof_plan_hash")
        if proof_plan_hash is not None and not valid_sha256(proof_plan_hash):
            raise GuardError("Benchmark provenance proof_plan_hash must be a SHA-256")
        route = source.get("conformance_route")
        if route is not None and route not in {
            "minimal_authoritative_conformance",
            "authoritative_owner_then_live_conformance",
        }:
            raise GuardError("Benchmark provenance conformance_route is outside the closed vocabulary")
    for field in ("semantic_condition_manifest_hash", "product_frontier"):
        baseline_value = baseline_source.get(field)
        candidate_value = candidate_source.get(field)
        if (baseline_value is None) != (candidate_value is None):
            label = "product frontier provenance" if field == "product_frontier" else field
            raise GuardError(f"Benchmark comparison changed availability of {label}")
        if baseline_value is not None and baseline_value != candidate_value:
            if field == "product_frontier":
                raise GuardError("Benchmark product frontier differs between compared results")
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
    operational_dimensions = [name for name in dimensions if name != "skill_bytes"]
    operational_improvement = any(
        float(candidate_values[name]) < float(baseline_values[name])
        for name in operational_dimensions
    )
    if baseline_quality and not operational_improvement:
        raise GuardError("Candidate cannot win only by shortening skill bytes")
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


def validate_benchmark_mutation_binding(
    baseline: dict[str, Any], candidate: dict[str, Any], validation: dict[str, Any]
) -> None:
    mutation = candidate.get("mutation")
    expected = validation["mutation"]
    if not isinstance(mutation, dict):
        raise GuardError("Candidate benchmark does not identify the mutation it exercised")
    for field in ("target_failure_id", "changed_policy_keys", "expected_reduction"):
        if mutation.get(field) != expected[field]:
            raise GuardError(f"Candidate benchmark changed bound mutation field {field}")
    observed = mutation.get("observed_reductions")
    if not isinstance(observed, list) or expected["expected_reduction"] not in observed:
        raise GuardError("Benchmark did not observe the mutation's declared expected reduction")

    baseline_values = fitness_values(baseline)
    candidate_values = fitness_values(candidate)
    reduction = expected["expected_reduction"]
    deadline_or_elapsed = (
        candidate_values["deadline_misses"] < baseline_values["deadline_misses"]
        or candidate_values["elapsed_seconds"] < baseline_values["elapsed_seconds"]
    )
    token_reduction = (
        baseline_values["tokens"] is not None
        and candidate_values["tokens"] is not None
        and candidate_values["tokens"] < baseline_values["tokens"]
    )
    if reduction == "context_tokens":
        measured = token_reduction
    elif reduction in {"repeated_work", "build_or_live_cost"}:
        measured = deadline_or_elapsed or token_reduction
    else:
        measured = deadline_or_elapsed
    if not measured:
        raise GuardError("Benchmark metrics do not substantiate the declared expected reduction")


def validate_bound_benchmark_provenance(
    baseline: dict[str, Any], candidate: dict[str, Any], validation: dict[str, Any]
) -> None:
    validate_benchmark_provenance(baseline, candidate)
    parent = validation["accepted_parent"]
    child = validation["candidate"]
    benchmark = validation["benchmark"]
    if digest_json(baseline) != benchmark["baseline_result_hash"]:
        raise GuardError("Comparison did not consume the exact validated parent benchmark")
    if baseline["provenance"]["skill_hash"] != parent["skill_hash"]:
        raise GuardError("Parent benchmark skill hash differs from the validation receipt")
    if candidate["provenance"]["skill_hash"] != child["skill_hash"]:
        raise GuardError("Candidate benchmark skill hash differs from the validated candidate")
    if candidate["provenance"]["definition_hash"] != benchmark["definition_hash"]:
        raise GuardError("Candidate benchmark definition differs from validation")
    frontier = validation["product_frontier"]
    validate_benchmark_identity(baseline, parent, frontier, required=True)
    validate_benchmark_identity(candidate, child, frontier, required=True)
    validate_effective_plan_receipt(baseline)
    validate_effective_plan_receipt(candidate)
    if any(
        key.startswith("policy/proof.json.")
        for key in validation["mutation"]["changed_policy_keys"]
    ):
        expected_routes = (
            validation["mutation"].get("parent_conformance_route"),
            validation["mutation"].get("candidate_conformance_route"),
        )
        for result, expected_route in zip((baseline, candidate), expected_routes):
            provenance = result["provenance"]
            for field in ("semantic_condition_manifest_hash", "proof_plan_hash"):
                if not valid_sha256(provenance.get(field)):
                    raise GuardError(
                        f"P2 benchmark requires proof-window provenance {field}"
                    )
            if provenance.get("product_frontier") != frontier:
                raise GuardError("P2 benchmark requires the exact accepted product frontier")
            if provenance.get("conformance_route") != expected_route:
                raise GuardError(
                    "P2 benchmark did not execute the conformance route selected by its policy"
                )


def compare_validated_candidate(
    *,
    validation_receipt: dict[str, Any],
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    candidate_root: Path,
    predicates: list[str],
) -> dict[str, Any]:
    verify_receipt(validation_receipt, "de67-mutation-validation")
    if validation_receipt.get("decision") != "validated":
        raise GuardError("Only a validated candidate may be compared")
    validation_hash = validation_receipt["receipt_hash"]
    candidate_result_hash = digest_json(candidate)
    try:
        current = git_identity(candidate_root)
        expected = validation_receipt["candidate"]
        for field in (
            "worktree",
            "common_git_dir",
            "branch",
            "commit",
            "tree",
            "skill_hash",
        ):
            if current[field] != expected[field]:
                raise GuardError("Comparison candidate differs from the exact validated Git candidate")
        validate_bound_benchmark_provenance(baseline, candidate, validation_receipt)
        validate_benchmark_mutation_binding(baseline, candidate, validation_receipt)
        comparison = compare_benchmark(baseline, candidate, predicates)
        decision = "promotable"
        error = None
    except GuardError as rejected:
        comparison = None
        decision = "rejected"
        error = str(rejected)
    return seal_receipt(
        {
            "kind": "de67-mutation-comparison",
            "version": RECEIPT_VERSION,
            "decision": decision,
            "validation_receipt_hash": validation_hash,
            "candidate_commit": validation_receipt["candidate"]["commit"],
            "candidate_result_hash": candidate_result_hash,
            "comparison": comparison,
            "error": error,
        }
    )


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise GuardError((completed.stderr or completed.stdout or "Git ancestry check failed").strip())


def create_promotion_plan(
    *,
    validation_receipt: dict[str, Any],
    comparison_receipt: dict[str, Any],
    accepted_root: Path,
    candidate_root: Path,
) -> dict[str, Any]:
    verify_receipt(validation_receipt, "de67-mutation-validation")
    verify_receipt(comparison_receipt, "de67-mutation-comparison")
    if comparison_receipt.get("decision") != "promotable":
        raise GuardError("Rejected candidates are ineligible for promotion or parenthood")
    if comparison_receipt.get("validation_receipt_hash") != validation_receipt["receipt_hash"]:
        raise GuardError("Promotion comparison belongs to a different validation receipt")
    parent = git_identity(accepted_root)
    candidate = git_identity(candidate_root)
    bound_parent = validation_receipt["accepted_parent"]
    bound_candidate = validation_receipt["candidate"]
    accepted_ref = bound_parent["accepted_ref"]
    current_accepted = git_output(accepted_root, "rev-parse", f"{accepted_ref}^{{commit}}")
    if current_accepted != bound_parent["commit"]:
        raise GuardError("Accepted main moved after validation; candidate is stale")
    for field in ("worktree", "common_git_dir", "branch", "commit", "tree", "skill_hash"):
        if parent[field] != bound_parent[field]:
            raise GuardError("Promotion accepted-parent path or Git identity changed after validation")
    for field in ("worktree", "common_git_dir", "branch", "commit", "tree", "skill_hash"):
        if candidate[field] != bound_candidate[field]:
            raise GuardError("Promotion candidate differs from the exact compared Git candidate")
    if parent["common_git_dir"] != candidate["common_git_dir"]:
        raise GuardError("Promotion paths belong to different Git repositories")
    if not is_ancestor(accepted_root, bound_parent["commit"], bound_candidate["commit"]):
        raise GuardError("Candidate cannot fast-forward the accepted parent")
    if comparison_receipt.get("candidate_commit") != bound_candidate["commit"]:
        raise GuardError("Comparison receipt names a different candidate commit")
    command = [
        "git",
        "-C",
        parent["worktree"],
        "merge",
        "--ff-only",
        bound_candidate["commit"],
    ]
    return seal_receipt(
        {
            "kind": "de67-mutation-promotion",
            "version": RECEIPT_VERSION,
            "decision": "eligible",
            "validation_receipt_hash": validation_receipt["receipt_hash"],
            "comparison_receipt_hash": comparison_receipt["receipt_hash"],
            "accepted_ref": accepted_ref,
            "base_commit": bound_parent["commit"],
            "candidate_commit": bound_candidate["commit"],
            "git_mutated": False,
            "command_plan": [command],
        }
    )


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
    validate.add_argument("--accepted-ref", default="main")
    validate.add_argument("--product-frontier", type=Path, required=True)
    validate.add_argument("--baseline-benchmark", type=Path, required=True)

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
    compare.add_argument("--validation-receipt", type=Path, required=True)

    promote = subparsers.add_parser("promote", help="Recheck and emit a fast-forward command plan")
    promote.add_argument("--candidate", type=Path, required=True)
    promote.add_argument("--validation-receipt", type=Path, required=True)
    promote.add_argument("--comparison-receipt", type=Path, required=True)
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
            result = create_validation_receipt(
                base=ROOT,
                candidate=arguments.candidate,
                accepted_ref=arguments.accepted_ref,
                scope=arguments.scope,
                evidence=evidence,
                intent=read_json(arguments.intent),
                policy=policy,
                product_frontier=read_json(arguments.product_frontier),
                baseline_benchmark=read_json(arguments.baseline_benchmark),
            )
        elif arguments.command == "compare":
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
            result = compare_validated_candidate(
                validation_receipt=read_json(arguments.validation_receipt),
                baseline=baseline,
                candidate=candidate,
                candidate_root=arguments.candidate_skill,
                predicates=list(policy["quality_predicates"]),
            )
        else:
            result = create_promotion_plan(
                validation_receipt=read_json(arguments.validation_receipt),
                comparison_receipt=read_json(arguments.comparison_receipt),
                accepted_root=ROOT,
                candidate_root=arguments.candidate,
            )
    except (GuardError, OSError, json.JSONDecodeError, KeyError) as error:
        print(canonical({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(canonical({"ok": True, "result": result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
