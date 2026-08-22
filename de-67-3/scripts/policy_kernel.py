#!/usr/bin/env python3
"""Compile, validate, minimize, and execute the DE67 Phase-3 policy kernel."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


MAGIC = b"D67P"
HEADER = struct.Struct(">4sB32sI")
FORMAT = "de67.phase3.policy"


class PolicyError(RuntimeError):
    """Raised when policy compilation or execution is not trustworthy."""


@dataclass(frozen=True)
class Decision:
    action: str
    rule_id: str
    reads: tuple[str, ...]
    obligations: tuple[str, ...]


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = dict(value)
    if policy.get("format") != FORMAT or policy.get("version") != 1:
        raise PolicyError("Unsupported Phase-3 policy format or version")
    fallback = policy.get("fallback")
    rules = policy.get("rules")
    if not isinstance(fallback, dict) or not isinstance(rules, list) or not rules:
        raise PolicyError("Policy requires one fallback and at least one rule")
    ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise PolicyError("Every policy rule must be an object")
        rule_id = rule.get("id")
        if not isinstance(rule_id, str) or not rule_id or rule_id in ids:
            raise PolicyError("Policy rule ids must be unique non-empty strings")
        ids.add(rule_id)
        if not isinstance(rule.get("priority"), int):
            raise PolicyError(f"Rule {rule_id} requires an integer priority")
        if not isinstance(rule.get("action"), str) or not rule["action"]:
            raise PolicyError(f"Rule {rule_id} requires an action")
        for key in ("all", "any", "none", "reads", "obligations"):
            if key in rule and not (
                isinstance(rule[key], list)
                and all(isinstance(item, str) and item for item in rule[key])
            ):
                raise PolicyError(f"Rule {rule_id} has invalid {key}")
        if not any(rule.get(key) for key in ("all", "any")):
            raise PolicyError(f"Rule {rule_id} has no positive predicate")
    for key in ("action", "reads", "obligations"):
        if key not in fallback:
            raise PolicyError(f"Fallback requires {key}")
    policy["rules"] = sorted(rules, key=lambda rule: (-rule["priority"], rule["id"]))
    return policy


def compile_policy(policy: Mapping[str, Any]) -> bytes:
    normalized = validate_policy(policy)
    raw = canonical_bytes(normalized)
    digest = hashlib.sha256(raw).digest()
    compressed = zlib.compress(raw, level=9)
    return HEADER.pack(MAGIC, 1, digest, len(raw)) + compressed


def load_policy_bytes(data: bytes) -> dict[str, Any]:
    if len(data) < HEADER.size:
        raise PolicyError("Compiled policy is truncated")
    magic, version, expected_digest, raw_size = HEADER.unpack(data[: HEADER.size])
    if magic != MAGIC or version != 1:
        raise PolicyError("Compiled policy has an invalid header")
    try:
        raw = zlib.decompress(data[HEADER.size :])
    except zlib.error as error:
        raise PolicyError("Compiled policy payload is corrupt") from error
    if len(raw) != raw_size or hashlib.sha256(raw).digest() != expected_digest:
        raise PolicyError("Compiled policy identity does not match its payload")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError("Compiled policy payload is not canonical JSON") from error
    if canonical_bytes(value) != raw:
        raise PolicyError("Compiled policy payload is not canonical")
    return validate_policy(value)


def load_policy(path: Path) -> dict[str, Any]:
    return load_policy_bytes(path.read_bytes())


def _matches(rule: Mapping[str, Any], facts: frozenset[str]) -> bool:
    required = frozenset(rule.get("all", []))
    alternatives = frozenset(rule.get("any", []))
    excluded = frozenset(rule.get("none", []))
    return required <= facts and (not alternatives or bool(alternatives & facts)) and not excluded & facts


def decide(policy: Mapping[str, Any], facts: Iterable[str]) -> Decision:
    normalized = validate_policy(policy)
    observed = frozenset(str(fact) for fact in facts)
    matches = [rule for rule in normalized["rules"] if _matches(rule, observed)]
    if not matches:
        fallback = normalized["fallback"]
        return Decision(
            str(fallback["action"]),
            "fallback",
            tuple(fallback.get("reads", [])),
            tuple(fallback.get("obligations", [])),
        )
    priority = matches[0]["priority"]
    winners = [rule for rule in matches if rule["priority"] == priority]
    actions = {rule["action"] for rule in winners}
    if len(actions) != 1:
        raise PolicyError(
            "Ambiguous policy decision at priority "
            f"{priority}: " + ", ".join(rule["id"] for rule in winners)
        )
    reads = tuple(dict.fromkeys(item for rule in winners for item in rule.get("reads", [])))
    obligations = tuple(
        dict.fromkeys(item for rule in winners for item in rule.get("obligations", []))
    )
    return Decision(str(winners[0]["action"]), "+".join(rule["id"] for rule in winners), reads, obligations)


def decision_json(decision: Decision, facts: Iterable[str]) -> dict[str, Any]:
    return {
        "action": decision.action,
        "rule": decision.rule_id,
        "reads": list(decision.reads),
        "obligations": list(decision.obligations),
        "facts": sorted(set(facts)),
    }


def policy_digest(policy: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(validate_policy(policy))).hexdigest()


def load_contracts(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != "de67.phase3.contracts" or value.get("version") != 1:
        raise PolicyError("Unsupported Phase-3 contract format or version")
    decisions = value.get("decision_cases")
    traces = value.get("trace_cases")
    if not isinstance(decisions, list) or not decisions or not isinstance(traces, list):
        raise PolicyError("Contracts require decision_cases and trace_cases")
    names: set[str] = set()
    for case in [*decisions, *traces]:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            raise PolicyError("Every contract case requires a name")
        if case["name"] in names:
            raise PolicyError(f"Duplicate contract case: {case['name']}")
        names.add(case["name"])
    return value


def guard_policy_candidate(
    candidate: Mapping[str, Any], contracts: Mapping[str, Any]
) -> dict[str, Any]:
    policy = validate_policy(candidate)
    cases: list[tuple[frozenset[str], str]] = []
    for case in contracts["decision_cases"]:
        facts = frozenset(case.get("facts", []))
        expected = case.get("action")
        if not isinstance(expected, str):
            raise PolicyError(f"Decision contract {case['name']} lacks an action")
        actual = decide(policy, facts).action
        if actual != expected:
            raise PolicyError(
                f"Decision contract {case['name']} expected {expected}, got {actual}"
            )
        cases.append((facts, expected))
    for case in contracts["trace_cases"]:
        expected = case.get("lab")
        if not isinstance(expected, bool) or not isinstance(case.get("events"), list):
            raise PolicyError(f"Trace contract {case['name']} is invalid")
        try:
            validate_trace(case["events"])
            actual = True
        except PolicyError:
            actual = False
        if actual != expected:
            raise PolicyError(
                f"Trace contract {case['name']} expected lab={expected}, got {actual}"
            )
    minimized, removed = minimize_policy(policy, cases)
    if removed:
        raise PolicyError("Behaviorally redundant policy rules: " + ", ".join(removed))
    mutation_facts = (
        "integrity_incident", "deadline_incident", "random_mutation_due",
        "dfs_review_due", "universal_review_due",
    )
    for fact in mutation_facts:
        decision = decide(policy, {fact, "pending_suggestions"})
        required = {"probe_pending_suggestions", "disposition_relevant_suggestions"}
        if not required <= set(decision.obligations):
            raise PolicyError(f"Mutation route {fact} can ignore pending suggestions")
    wait = decide(policy, {"live_task"})
    if "wake_no_later_than_item_deadline" not in wait.obligations:
        raise PolicyError("Worker wait can cross the immutable item deadline")
    return minimized


def minimize_policy(
    policy: Mapping[str, Any], cases: Sequence[tuple[frozenset[str], str]]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Delete rules whose removal preserves every supplied behavioral case."""
    candidate = validate_policy(policy)
    removed: list[str] = []
    for rule in list(reversed(candidate["rules"])):
        trial = dict(candidate)
        trial["rules"] = [item for item in candidate["rules"] if item["id"] != rule["id"]]
        if not trial["rules"]:
            continue
        try:
            if all(decide(trial, facts).action == expected for facts, expected in cases):
                candidate = validate_policy(trial)
                removed.append(str(rule["id"]))
        except PolicyError:
            continue
    return candidate, tuple(removed)


def validate_trace(events: Sequence[Mapping[str, Any]]) -> None:
    """Reject lifecycle traces that violate the compiled kernel's temporal contracts."""
    deadline_incident = False
    pending_suggestions = False
    mutation_open = False
    suggestions_dispositioned = False
    attempts: dict[str, str] = {}
    for index, event in enumerate(events):
        kind = event.get("event")
        if kind == "deadline_expired":
            deadline_incident = True
        elif kind == "deadline_incident_reviewed":
            if not deadline_incident:
                raise PolicyError(f"trace[{index}] reviews no deadline incident")
            deadline_incident = False
        elif kind == "claim_accepted" and deadline_incident:
            raise PolicyError(f"trace[{index}] accepts a claim before deadline incident review")
        elif kind == "suggestion_added":
            pending_suggestions = True
        elif kind == "mutation_started":
            if mutation_open:
                raise PolicyError(f"trace[{index}] nests mutation reviews")
            mutation_open = True
            suggestions_dispositioned = not pending_suggestions
        elif kind == "suggestions_dispositioned":
            if not mutation_open:
                raise PolicyError(f"trace[{index}] dispositions suggestions outside mutation")
            pending_suggestions = False
            suggestions_dispositioned = True
        elif kind == "mutation_resolved":
            if not mutation_open:
                raise PolicyError(f"trace[{index}] resolves no mutation")
            if not suggestions_dispositioned:
                raise PolicyError(f"trace[{index}] resolves mutation with pending suggestions")
            mutation_open = False
        elif kind == "task_started":
            task_id = str(event.get("task_id", ""))
            if not task_id or task_id in attempts:
                raise PolicyError(f"trace[{index}] starts a missing or reused task id")
            attempts[task_id] = "live"
        elif kind in {"task_completed", "task_finding", "task_abandoned"}:
            task_id = str(event.get("task_id", ""))
            if attempts.get(task_id) != "live":
                raise PolicyError(f"trace[{index}] terminalizes a non-live task")
            attempts[task_id] = kind


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def workspace_facts(
    workspace: Path, state: Path, lineage_id: str, *, now: float
) -> frozenset[str]:
    facts: set[str] = set()
    current_claim: str | None = None
    connection = sqlite3.connect(f"file:{state.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if _table_exists(connection, "tasks"):
            rows = connection.execute(
                "SELECT * FROM tasks WHERE lineage_id = ? ORDER BY started_at DESC",
                (lineage_id,),
            ).fetchall()
            live = [row for row in rows if row["attempt_terminal_at"] is None]
            if live:
                facts.add("live_task")
            for row in rows:
                kind = row["attempt_terminal_kind"]
                if kind:
                    facts.add(f"worker_{kind}")
                    break
        for table, fact in (
            ("claim_deadline_generation_incidents", "deadline_incident"),
            ("incidents", "integrity_incident"),
            ("coordinator_restart_requests", "restart_requested"),
        ):
            if _table_exists(connection, table):
                if table == "claim_deadline_generation_incidents":
                    query = f"SELECT 1 FROM {table} WHERE lineage_id = ? AND reviewed_at IS NULL LIMIT 1"
                elif table == "coordinator_restart_requests":
                    query = f"SELECT 1 FROM {table} WHERE lineage_id = ? AND acknowledged_at IS NULL LIMIT 1"
                else:
                    query = (
                        f"SELECT 1 FROM {table} WHERE lineage_id = ? AND kind = 'integrity_breach' "
                        "AND reviewed_at IS NULL LIMIT 1"
                    )
                if connection.execute(query, (lineage_id,)).fetchone() is not None:
                    facts.add(fact)
        if _table_exists(connection, "claim_clocks"):
            clock = connection.execute(
                "SELECT * FROM claim_clocks WHERE lineage_id = ? ORDER BY started_at DESC LIMIT 1",
                (lineage_id,),
            ).fetchone()
            if clock is not None:
                current_claim = str(clock["claim_id"])
                facts.add("open_claim")
                if float(clock["deadline_at"]) <= now:
                    facts.add("deadline_expired")
                if str(clock["phase"]) == "closure":
                    facts.add("closure_ready")
        if _table_exists(connection, "closure_gaps") and current_claim is not None:
            if connection.execute(
                """
                SELECT 1 FROM closure_gaps
                WHERE lineage_id = ? AND claim_id = ? AND closed_at IS NULL LIMIT 1
                """,
                (lineage_id, current_claim),
            ).fetchone() is not None:
                facts.add("open_gap")
        if _table_exists(connection, "random_mutation_cycles"):
            random_due = connection.execute(
                """
                SELECT selected_lane FROM random_mutation_cycles
                WHERE lineage_id = ? AND due_task_id IS NOT NULL
                  AND resolution_evidence IS NULL
                ORDER BY cycle_number LIMIT 1
                """,
                (lineage_id,),
            ).fetchone()
            if random_due is not None:
                facts.add("random_mutation_due")
                if str(random_due["selected_lane"]) == "DFS.md":
                    facts.add("dfs_review_due")
    finally:
        connection.close()

    ledger = workspace / ".de67" / "work-ledger.md"
    ledger_text = ledger.read_text(encoding="utf-8") if ledger.is_file() else ""
    if "## " in ledger_text:
        facts.add("ledger_work")
    if "blocked" in ledger_text.lower():
        facts.add("blocked_ledger")
    if any(word in ledger_text.lower() for word in ("next executable", "required mechanism", "active gap")):
        facts.add("executable_route")
    suggestions = workspace / ".de67" / "mutation-suggestions.md"
    if suggestions.is_file():
        pending = suggestions.read_text(encoding="utf-8").partition("## Pending suggestions")[2]
        if any(line.startswith("- ") for line in pending.splitlines()):
            facts.add("pending_suggestions")
    dfs = workspace / ".de67" / "DFS.md"
    dfs_text = dfs.read_text(encoding="utf-8") if dfs.is_file() else ""
    if "🔴" in dfs_text:
        facts.add("red_dfs_work")
    else:
        facts.add("dfs_complete")
    return frozenset(facts)


def source_from_git(ref: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, check=False
    )
    if result.returncode != 0:
        raise PolicyError(result.stderr.decode("utf-8", "replace").strip() or "git show failed")
    return result.stdout


def _parse_facts(raw: str) -> frozenset[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PolicyError("Facts must be a JSON array of strings")
    return frozenset(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--source", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    decide_parser = subparsers.add_parser("decide")
    decide_parser.add_argument("--policy", type=Path, required=True)
    decide_parser.add_argument("--facts")
    decide_parser.add_argument("--workspace", type=Path)
    decide_parser.add_argument("--state", type=Path)
    decide_parser.add_argument("--lineage")
    decide_parser.add_argument("--now", type=float)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--policy", type=Path, required=True)
    guard_parser = subparsers.add_parser("guard")
    guard_parser.add_argument("--candidate", type=Path, required=True)
    guard_parser.add_argument("--contracts", type=Path, required=True)
    guard_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            source = json.loads(args.source.read_text(encoding="utf-8"))
            compiled = compile_policy(source)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(compiled)
            print(json.dumps({"bytes": len(compiled), "digest": policy_digest(source)}))
            return 0
        if args.command == "inspect":
            policy = load_policy(args.policy)
            print(json.dumps({"digest": policy_digest(policy), "rules": len(policy["rules"])}))
            return 0
        if args.command == "guard":
            candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
            contracts = load_contracts(args.contracts)
            guarded = guard_policy_candidate(candidate, contracts)
            compiled = compile_policy(guarded)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(compiled)
            print(json.dumps({
                "bytes": len(compiled), "digest": policy_digest(guarded),
                "rules": len(guarded["rules"]),
            }, sort_keys=True))
            return 0
        policy = load_policy(args.policy)
        if args.facts is not None:
            facts = _parse_facts(args.facts)
        elif args.workspace and args.state and args.lineage:
            import time
            observed_at = args.now if args.now is not None else time.time()
            facts = workspace_facts(
                args.workspace.resolve(), args.state.resolve(), args.lineage, now=observed_at
            )
        else:
            raise PolicyError("decide requires --facts or workspace, state, and lineage")
        print(json.dumps(decision_json(decide(policy, facts), facts), sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, PolicyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
