#!/usr/bin/env python3
"""Compile, validate, minimize, and execute the DE67 Phase-3 policy kernel."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_ROOT = str(Path(__file__).resolve().parent)
if SCRIPT_ROOT not in sys.path:
    sys.path.insert(0, SCRIPT_ROOT)
import symbol_codec


MAGIC = b"D67P"
HEADER = struct.Struct(">4sB32sI")
FORMAT = "de67.phase3.policy"
VERSION = 2


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
    if policy.get("format") != FORMAT or policy.get("version") != VERSION:
        raise PolicyError("Unsupported Phase-3 policy format or version")
    fallback = policy.get("fallback")
    rules = policy.get("rules")
    if not isinstance(fallback, dict) or not isinstance(rules, list) or not rules:
        raise PolicyError("Policy requires one fallback and at least one rule")
    ids: set[str] = set()
    normalized_rules: list[dict[str, Any]] = []
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
        normalized_rule = dict(rule)
        for key in ("all", "any", "none", "reads", "obligations"):
            normalized_rule.setdefault(key, [])
        normalized_rules.append(normalized_rule)
    for key in ("action", "reads", "obligations"):
        if key not in fallback:
            raise PolicyError(f"Fallback requires {key}")
    trace = policy.get("trace")
    if not isinstance(trace, dict) or not isinstance(trace.get("events"), dict):
        raise PolicyError("Policy requires a mutable trace event program")
    normalized_events: dict[str, dict[str, Any]] = {}
    for event, program in trace["events"].items():
        if not isinstance(event, str) or not event or not isinstance(program, dict):
            raise PolicyError("Trace events require named object programs")
        for key in ("requires", "forbids", "set", "clear"):
            if key in program and not (
                isinstance(program[key], list)
                and all(isinstance(item, str) and item for item in program[key])
            ):
                raise PolicyError(f"Trace event {event} has invalid {key}")
        keyed = program.get("keyed")
        if keyed is not None and not (
            isinstance(keyed, dict)
            and isinstance(keyed.get("field"), str)
            and keyed.get("operation") in {"start", "finish"}
        ):
            raise PolicyError(f"Trace event {event} has invalid keyed transition")
        normalized_program = dict(program)
        for key in ("requires", "forbids", "set", "clear"):
            normalized_program.setdefault(key, [])
        if keyed is not None:
            normalized_keyed = dict(keyed)
            normalized_keyed.setdefault("namespace", normalized_keyed["field"])
            normalized_keyed.setdefault("from", "live")
            normalized_keyed.setdefault("state", "live")
            normalized_program["keyed"] = normalized_keyed
        normalized_events[event] = normalized_program
    normalized_fallback = dict(fallback)
    normalized_fallback.setdefault("reads", [])
    normalized_fallback.setdefault("obligations", [])
    policy["fallback"] = normalized_fallback
    policy["rules"] = sorted(normalized_rules, key=lambda rule: (-rule["priority"], rule["id"]))
    policy["trace"] = {"events": normalized_events}
    return policy


def compile_policy(policy: Mapping[str, Any]) -> bytes:
    normalized = validate_policy(policy)
    raw = canonical_bytes(normalized)
    digest = hashlib.sha256(raw).digest()
    tape = symbol_codec.encode(_lower_policy(normalized))
    compressed = zlib.compress(tape, level=9)
    return HEADER.pack(MAGIC, VERSION, digest, len(tape)) + compressed


def load_policy_bytes(data: bytes) -> dict[str, Any]:
    if len(data) < HEADER.size:
        raise PolicyError("Compiled policy is truncated")
    magic, version, expected_digest, raw_size = HEADER.unpack(data[: HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise PolicyError("Compiled policy has an invalid header")
    try:
        tape = zlib.decompress(data[HEADER.size :])
    except zlib.error as error:
        raise PolicyError("Compiled policy payload is corrupt") from error
    if len(tape) != raw_size:
        raise PolicyError("Compiled policy size does not match its payload")
    try:
        value = _raise_policy(symbol_codec.decode(tape))
    except symbol_codec.CodecError as error:
        raise PolicyError("Compiled policy symbol tape is invalid") from error
    normalized = validate_policy(value)
    if hashlib.sha256(canonical_bytes(normalized)).digest() != expected_digest:
        raise PolicyError("Compiled policy identity does not match its payload")
    return normalized


def _lower_policy(policy: Mapping[str, Any]) -> list[Any]:
    """Remove schema words and lower mutable policy values to positional vectors."""
    fallback = policy["fallback"]
    rules = [
        [
            rule["id"], rule["priority"], rule.get("all", []), rule.get("any", []),
            rule.get("none", []), rule["action"], rule.get("reads", []),
            rule.get("obligations", []),
        ]
        for rule in policy["rules"]
    ]
    events = []
    for name, program in sorted(policy["trace"]["events"].items()):
        keyed = program.get("keyed")
        keyed_vector = [] if keyed is None else [
            keyed["field"], keyed.get("namespace", keyed["field"]),
            keyed["operation"], keyed.get("from", "live"),
            keyed.get("state", "live"),
        ]
        events.append([
            name, program.get("requires", []), program.get("forbids", []),
            program.get("set", []), program.get("clear", []), keyed_vector,
        ])
    return [[fallback["action"], fallback.get("reads", []), fallback.get("obligations", [])], rules, events]


def _raise_policy(tape: Any) -> dict[str, Any]:
    """Reconstruct source-shaped policy from a schema-lowered instruction tape."""
    try:
        fallback_vector, rule_vectors, event_vectors = tape
        fallback = {
            "action": fallback_vector[0], "reads": fallback_vector[1],
            "obligations": fallback_vector[2],
        }
        rules = []
        for vector in rule_vectors:
            rule = {
                "id": vector[0], "priority": vector[1], "all": vector[2],
                "any": vector[3], "none": vector[4], "action": vector[5],
                "reads": vector[6], "obligations": vector[7],
            }
            rules.append(rule)
        events = {}
        for vector in event_vectors:
            program = {
                "requires": vector[1], "forbids": vector[2], "set": vector[3],
                "clear": vector[4],
            }
            if vector[5]:
                keyed = vector[5]
                program["keyed"] = {
                    "field": keyed[0], "namespace": keyed[1],
                    "operation": keyed[2], "from": keyed[3], "state": keyed[4],
                }
            events[vector[0]] = program
    except (IndexError, TypeError, ValueError) as error:
        raise PolicyError("Compiled policy instruction tape has an invalid shape") from error
    return {"format": FORMAT, "version": VERSION, "fallback": fallback, "rules": rules,
            "trace": {"events": events}}


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


def _exploration_route(workspace: Path, claim_id: str, task_id: str) -> tuple[str, str]:
    ledger_path = workspace / ".de67/work-ledger.md"
    dfs_path = workspace / ".de67/DFS.md"
    ledger = ledger_path.read_text(encoding="utf-8")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", ledger) if block.strip()]
    def mentions_exact_identifier(block: str, identifier: str) -> bool:
        return re.search(
            r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])",
            block,
        ) is not None

    matching = [
        block for block in blocks
        if mentions_exact_identifier(block, claim_id)
        or mentions_exact_identifier(block, task_id)
    ]
    if not matching:
        raise PolicyError(
            f"Unbound exploration task {task_id} has no matching ledger route for {claim_id}"
        )
    dfs = dfs_path.read_text(encoding="utf-8")
    marker = re.compile(
        r"<!-- DE67:DFS-SLICE:BEGIN[^>]*claim=" + re.escape(claim_id)
        + r"(?=\s|-->)[^>]*-->\n(?P<body>.*?)\n"
        r"<!-- DE67:DFS-SLICE:END[^>]*-->",
        re.DOTALL,
    )
    match = marker.search(dfs)
    if match is None:
        raise PolicyError(
            f"Unbound exploration task {task_id} has no named DFS slice for {claim_id}"
        )
    return "\n\n".join(matching), match.group("body").strip()


def worker_helper_contract() -> str:
    """Describe optional native helper delegation without DE67 bureaucracy."""
    return (
        "If you are the Terra worker, consider an optional Luna helper when bounded work can "
        "return independently, such as an isolated live playtest witness, focused test run, log "
        "analysis, source trace, screenshot inspection, or platform check. Use Codex native "
        "subagents only, with fork_turns=\"none\", a self-contained brief, and the lowest reasoning "
        "effort you judge sufficient; use as many as the runtime permits, and work or wait while "
        "they run. For a playtest, supply the compact charter and isolated run context; the Luna "
        "helper operates the run and returns the smallest journal-cited witness, while you judge "
        "the evidence and own any repair. You remain responsible for the whole outcome, may use or "
        "reject helper results, and must collect or stop every helper before returning. Helpers do "
        "not own deadline tasks or write DE67 clock, ledger, DFS, or mutation state, and must avoid "
        "overlapping source edits or shared mutable runtime state without explicit exclusive "
        "ownership. If you are Luna, do not delegate further."
    )


def worker_outcome_contract() -> str:
    """Keep recoverable work inside the outcome and reserve terminal findings."""
    return (
        "Keep repository-owned implementation, tooling, fixture, scenario, binding, and "
        "observation prerequisites inside this task while they remain useful to its outcome. "
        "When a proof prerequisite depends on output it is about to create, treat that work as "
        "non-credit bootstrap and validate the fresh output independently; do not query the "
        "unchanged prerequisite again. Return completion only when the assigned outcome is "
        "settled. A disproved strategy is progress, not a task exit: preserve its evidence and "
        "continue through a materially different evidence-backed route while repository recovery "
        "remains. Return a formal finding only for a contradicted assigned outcome, materially "
        "different owner outcome, real external or human decision, unavailable capability, "
        "irreversible risk, or an authorized route you have genuinely exhausted."
    )


def _write_worker_dispatch_packet(
    workspace: Path, task_name: str, message: str
) -> tuple[Path, str]:
    """Persist one immutable worker-only brief and return its content identity."""
    encoded = (message.rstrip() + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    packet_directory = workspace / ".de67" / "state" / "worker-dispatch"
    packet_directory.mkdir(parents=True, exist_ok=True)
    packet = packet_directory / f"{task_name}-{digest}.md"
    try:
        with packet.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError:
        if packet.read_bytes() != encoded:
            raise PolicyError(f"Worker dispatch packet identity collision: {packet}")
    return packet.resolve(), digest


def unbound_worker_spawns(
    workspace: Path, state: Path, lineage_id: str
) -> list[dict[str, Any]]:
    """Render the exact post-task-open spawn calls for every unbound task."""
    connection = sqlite3.connect(f"file:{state.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT task.task_id, task.claim_id, task.phase_at_dispatch,
                   task.closure_gap_id, task.closure_gap_revision
            FROM tasks AS task
            LEFT JOIN worker_claims AS worker
              ON worker.lineage_id = task.lineage_id
             AND worker.task_id = task.task_id
            WHERE task.lineage_id = ? AND task.attempt_terminal_at IS NULL
              AND worker.task_id IS NULL
            ORDER BY task.started_at, task.task_id
            """,
            (lineage_id,),
        ).fetchall()
        spawns: list[dict[str, Any]] = []
        for row in rows:
            task_id = str(row["task_id"])
            claim_id = str(row["claim_id"])
            phase = str(row["phase_at_dispatch"])
            gap_id = row["closure_gap_id"]
            revision = row["closure_gap_revision"]
            gap = None
            if gap_id is not None and revision is not None:
                gap = connection.execute(
                    """
                    SELECT description, proof_route
                    FROM closure_gap_revisions
                    WHERE lineage_id = ? AND claim_id = ? AND gap_id = ?
                      AND revision = ?
                    ORDER BY closure_sequence DESC LIMIT 1
                    """,
                    (lineage_id, claim_id, gap_id, revision),
                ).fetchone()
                if gap is None:
                    raise PolicyError(
                        f"Unbound closure task {task_id} references missing gap revision"
                    )
                outcome, proof_route = str(gap["description"]), str(gap["proof_route"])
            elif phase == "exploration":
                outcome, proof_route = _exploration_route(workspace, claim_id, task_id)
            else:
                # Legacy closure attempts predate named gap bindings. Preserve
                # their exact claim route without pretending they are exploration.
                outcome, proof_route = _exploration_route(workspace, claim_id, task_id)
            message = (
                f"Own existing {phase} deadline task {task_id} for claim {claim_id}"
                + (f", closure gap {gap_id} revision {revision}. " if gap_id else ". ")
                + f"Outcome: {outcome} Proof route: {proof_route} "
                + "Retrieve only the evidence needed for the next causal decision. You may repair "
                + "repository-owned implementation, harness, fixture, or observation paths when "
                + "necessary. "
                + worker_outcome_contract()
                + " Return the settled result to the coordinator; do not mutate DE67 deadline "
                + "state yourself. "
                + worker_helper_contract()
            )
            task_name = "task_" + task_id.encode("utf-8").hex()
            packet, packet_digest = _write_worker_dispatch_packet(
                workspace, task_name, message
            )
            spawn_message = (
                f"Own DE67 task {task_id}. Read your complete task brief from {packet}. "
                f"Verify its SHA-256 is {packet_digest}, then follow it."
            )
            spawns.append(
                {
                    "task_id": task_id,
                    "task_name": task_name,
                    "dispatch_packet": {
                        "path": str(packet),
                        "sha256": packet_digest,
                    },
                    "instruction": (
                        "Actually call spawn_agent with these arguments. Announcing an assignment "
                        "is not delegation. After every listed spawn, call wait_agent for the "
                        "spawned worker ids; do not finish while a worker result is outstanding."
                    ),
                    "example_call": {
                        "tool": "spawn_agent",
                        "arguments": {
                            "task_name": task_name,
                            "fork_turns": "none",
                            "model": "gpt-5.6-terra",
                            "reasoning_effort": "medium",
                            "message": spawn_message,
                        },
                    },
                }
            )
        return spawns
    finally:
        connection.close()


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
        decision = decide(policy, facts)
        actual = decision.action
        if actual != expected:
            raise PolicyError(
                f"Decision contract {case['name']} expected {expected}, got {actual}"
            )
        for field in ("reads", "obligations"):
            required = case.get(f"required_{field}", [])
            if not isinstance(required, list) or not set(required) <= set(getattr(decision, field)):
                raise PolicyError(f"Decision contract {case['name']} lacks required {field}")
        cases.append((facts, expected))
    for case in contracts["trace_cases"]:
        expected = case.get("lab")
        if not isinstance(expected, bool) or not isinstance(case.get("events"), list):
            raise PolicyError(f"Trace contract {case['name']} is invalid")
        try:
            validate_trace(policy, case["events"])
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


def validate_trace(policy: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> None:
    """Execute the policy's mutable temporal event program."""
    programs = validate_policy(policy)["trace"]["events"]
    flags: set[str] = set()
    keyed: dict[tuple[str, str], str] = {}
    for index, event in enumerate(events):
        kind = str(event.get("event", ""))
        program = programs.get(kind)
        if program is None:
            continue
        required = set(program.get("requires", []))
        forbidden = set(program.get("forbids", []))
        if not required <= flags:
            raise PolicyError(f"trace[{index}] {kind} lacks state: {sorted(required - flags)}")
        if forbidden & flags:
            raise PolicyError(f"trace[{index}] {kind} conflicts with state: {sorted(forbidden & flags)}")
        transition = program.get("keyed")
        if transition:
            field = transition["field"]
            value = str(event.get(field, ""))
            namespace = str(transition.get("namespace", field))
            key = (namespace, value)
            if not value:
                raise PolicyError(f"trace[{index}] {kind} lacks {field}")
            if transition["operation"] == "start":
                if key in keyed:
                    raise PolicyError(f"trace[{index}] {kind} reuses {field}")
                keyed[key] = str(transition.get("state", "live"))
            else:
                expected = str(transition.get("from", "live"))
                if keyed.get(key) != expected:
                    raise PolicyError(f"trace[{index}] {kind} finishes non-{expected} {field}")
                keyed[key] = str(transition.get("state", kind))
        flags.difference_update(program.get("clear", []))
        flags.update(program.get("set", []))


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _terminal_result_was_consumed(
    connection: sqlite3.Connection, lineage_id: str, task: sqlite3.Row
) -> bool:
    """Return whether a newer durable route transition consumed this result."""
    task_id = str(task["task_id"])
    terminal_at = task["attempt_terminal_at"]
    if terminal_at is None:
        return False
    if _table_exists(connection, "closure_gaps"):
        consumed = connection.execute(
            """
            SELECT 1 FROM closure_gaps
            WHERE lineage_id = ? AND closed_by_task_id = ? AND closed_at >= ?
            LIMIT 1
            """,
            (lineage_id, task_id, float(terminal_at)),
        ).fetchone()
        if consumed is not None:
            return True
    if _table_exists(connection, "closure_gap_revisions"):
        consumed = connection.execute(
            """
            SELECT 1 FROM closure_gap_revisions
            WHERE lineage_id = ? AND basis_task_id = ? AND recorded_at >= ?
            LIMIT 1
            """,
            (lineage_id, task_id, float(terminal_at)),
        ).fetchone()
        if consumed is not None:
            return True
    if _table_exists(connection, "claim_phase_events"):
        consumed = connection.execute(
            """
            SELECT 1 FROM claim_phase_events
            WHERE lineage_id = ? AND basis_task_id = ? AND recorded_at >= ?
            LIMIT 1
            """,
            (lineage_id, task_id, float(terminal_at)),
        ).fetchone()
        if consumed is not None:
            return True
    return False


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
            epoch_generation = None
            if _table_exists(connection, "external_supervisor_epochs"):
                epoch = connection.execute(
                    "SELECT generation FROM external_supervisor_epochs "
                    "WHERE lineage_id = ? ORDER BY generation DESC LIMIT 1",
                    (lineage_id,),
                ).fetchone()
                epoch_generation = int(epoch[0]) if epoch is not None else None
            nonterminal = [row for row in rows if row["attempt_terminal_at"] is None]
            worker_claims_exist = _table_exists(connection, "worker_claims")
            claimed_ids: set[str] = set()
            ever_claimed_ids: set[str] = set()
            if worker_claims_exist:
                ever_claimed_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT task_id FROM worker_claims WHERE lineage_id = ?",
                        (lineage_id,),
                    ).fetchall()
                }
                claimed_ids = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT task_id FROM worker_claims
                        WHERE lineage_id = ? AND released_at IS NULL
                        """,
                        (lineage_id,),
                    ).fetchall()
                }
            live = [
                row for row in nonterminal
                if not worker_claims_exist or str(row["task_id"]) in claimed_ids
            ]
            if live:
                facts.add("live_task")
            if any(str(row["task_id"]) not in ever_claimed_ids for row in nonterminal):
                facts.add("unbound_task")
            if not nonterminal:
                for row in rows:
                    if epoch_generation is not None and int(
                        row["supervisor_epoch_generation"]
                    ) < epoch_generation:
                        continue
                    kind = row["attempt_terminal_kind"]
                    if kind == "restart_normalized":
                        break
                    if kind:
                        if not _terminal_result_was_consumed(
                            connection, lineage_id, row
                        ):
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
            if _table_exists(connection, "claim_deadline_generations"):
                clock = connection.execute(
                    """
                SELECT clock.claim_id, clock.phase,
                       generation.started_at, generation.deadline_at
                FROM claim_clocks AS clock
                JOIN claim_deadline_generations AS generation
                  ON generation.lineage_id = clock.lineage_id
                 AND generation.claim_id = clock.claim_id
                WHERE clock.lineage_id = ?
                  AND generation.retired_at IS NULL
                  AND generation.generation = (
                    SELECT MAX(latest.generation)
                    FROM claim_deadline_generations AS latest
                    WHERE latest.lineage_id = generation.lineage_id
                      AND latest.claim_id = generation.claim_id
                  )
                ORDER BY generation.started_at DESC, clock.claim_id
                LIMIT 1
                    """,
                    (lineage_id,),
                ).fetchone()
            else:
                clock = connection.execute(
                    "SELECT * FROM claim_clocks WHERE lineage_id = ? "
                    "ORDER BY started_at DESC LIMIT 1",
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
            if _table_exists(connection, "closure_gap_revisions"):
                open_gap = connection.execute(
                    """
                SELECT gap.lineage_id, gap.claim_id, gap.closure_sequence, gap.gap_id,
                       revision.proof_route
                FROM closure_gaps AS gap
                JOIN closure_gap_revisions AS revision
                  ON revision.lineage_id = gap.lineage_id
                 AND revision.claim_id = gap.claim_id
                 AND revision.closure_sequence = gap.closure_sequence
                 AND revision.gap_id = gap.gap_id
                 AND revision.revision = (
                    SELECT MAX(latest.revision)
                    FROM closure_gap_revisions AS latest
                    WHERE latest.lineage_id = gap.lineage_id
                      AND latest.claim_id = gap.claim_id
                      AND latest.closure_sequence = gap.closure_sequence
                      AND latest.gap_id = gap.gap_id
                 )
                WHERE gap.lineage_id = ? AND gap.claim_id = ?
                  AND gap.closed_at IS NULL
                ORDER BY gap.gap_id LIMIT 1
                    """,
                    (lineage_id, current_claim),
                ).fetchone()
            else:
                open_gap = connection.execute(
                    """
                    SELECT *, NULL AS proof_route
                    FROM closure_gaps
                    WHERE lineage_id = ? AND claim_id = ? AND closed_at IS NULL
                    LIMIT 1
                    """,
                    (lineage_id, current_claim),
                ).fetchone()
            if open_gap is not None:
                facts.add("open_gap")
                if str(open_gap["proof_route"]).strip():
                    facts.add("executable_route")
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
    if current_claim is None and ledger_text:
        frontier_match = re.search(
            r"(?ms)^## Current delivery frontier\s*$\n(?P<body>.*?)(?=^## |\Z)",
            ledger_text,
        )
        frontier_text = frontier_match.group("body") if frontier_match else ledger_text
        connection = sqlite3.connect(f"file:{state.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            closure_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(closure_gaps)")
            }
            if _table_exists(connection, "closure_gaps") and "gap_id" in closure_columns:
                mentioned = []
                mentioned_executable = False
                for row in connection.execute(
                    """SELECT claim_id, gap_id FROM closure_gaps
                       WHERE lineage_id = ? AND closed_at IS NULL""",
                    (lineage_id,),
                ).fetchall():
                    gap_id = str(row["gap_id"])
                    if re.search(
                        r"(?<![A-Za-z0-9_-])" + re.escape(gap_id)
                        + r"(?![A-Za-z0-9_-])",
                        frontier_text,
                    ):
                        mentioned.append(str(row["claim_id"]))
                        if _table_exists(connection, "closure_gap_revisions"):
                            revision = connection.execute(
                                """
                                SELECT proof_route FROM closure_gap_revisions
                                WHERE lineage_id = ? AND claim_id = ? AND gap_id = ?
                                ORDER BY closure_sequence DESC, revision DESC LIMIT 1
                                """,
                                (lineage_id, str(row["claim_id"]), gap_id),
                            ).fetchone()
                            mentioned_executable = mentioned_executable or (
                                revision is not None
                                and bool(str(revision["proof_route"]).strip())
                            )
                if len(set(mentioned)) == 1:
                    facts.update(("closure_ready", "open_gap"))
                    if mentioned_executable:
                        facts.add("executable_route")
        finally:
            connection.close()
    if any(
        line.lstrip().lower().startswith("- blocked:")
        for line in ledger_text.splitlines()
    ):
        facts.add("blocked_ledger")
    if any(
        word in ledger_text.lower()
        for word in (
            "next executable", "required mechanism", "active gap", "active work",
            "proof boundary",
        )
    ):
        facts.add("executable_route")
    suggestions = workspace / ".de67" / "mutation-suggestions.md"
    if suggestions.is_file():
        pending = suggestions.read_text(encoding="utf-8").partition("## Pending suggestions")[2]
        # Legacy unlabelled entries and explicit [trigger] entries are
        # immediate owner gates.  [defer] entries are proposals for the next
        # regular review and must not retire an otherwise healthy coordinator.
        entries = (
            line[2:].strip()
            for line in pending.splitlines()
            if line.startswith("- ")
        )
        if any(
            entry.lower() != "none."
            and not re.match(
                r"^(?:owner-authorized\s+)?\[defer\]:?\s+",
                entry,
                re.IGNORECASE,
            )
            for entry in entries
        ):
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
    decompile_parser = subparsers.add_parser("decompile")
    decompile_parser.add_argument("--policy", type=Path, required=True)
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
        if args.command == "decompile":
            print(json.dumps(load_policy(args.policy), indent=2, sort_keys=True))
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
        decision = decide(policy, facts)
        payload = decision_json(decision, facts)
        if decision.action == "spawn_worker" and args.facts is None:
            if not (args.state and args.lineage and args.workspace):
                raise PolicyError("spawn_worker requires workspace, state, and lineage")
            payload["worker_spawns"] = unbound_worker_spawns(
                args.workspace.resolve(), args.state.resolve(), args.lineage
            )
            payload["parallel_dispatch"] = (
                "Spawn one distinct worker for each listed independent task before waiting."
            )
            payload["coordinator_next_action"] = (
                "Spawn every listed worker, then call wait_agent for the spawned worker ids. "
                "Do not finish the coordinator turn while a worker result is outstanding."
            )
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error, PolicyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
