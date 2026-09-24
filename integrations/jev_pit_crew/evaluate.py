#!/usr/bin/env python3
"""Run the Pit Crew's controlled, provider-free selector comparison.

The fixture keeps independent relevance labels separate from the controlled stub
choices.  It therefore reports useful, irrelevant, and missed relationships
without claiming that a real provider, agent outcome, or cost was observed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any, Mapping
from unittest.mock import patch

import pit_crew as pit


RELATIONSHIPS = {
    "relevant_new_evidence",
    "duplicated_investigation",
    "challenged_assumption",
}


# The fixture controls independent labels and the local stub's choices.  These
# deterministic event shapes exercise Pit Crew itself in a temporary *shadow*
# workspace; they are not samples of a provider or a coordinator decision.
SCENARIOS: dict[str, dict[str, Any]] = {
    "relevant_new_evidence": {
        "objective": "Verify cache invalidation after writes.",
        "evidence": "Evidence: observed cache invalidation after write completes.",
    },
    "duplicated_investigation": {
        "objective": "Investigate cache invalidation retry behavior.",
        "evidence": "Investigating cache invalidation retry behavior found a stale cache.",
        "peer_objective": "Investigate cache invalidation retry behavior for concurrent writes.",
    },
    "challenged_assumption": {
        "objective": "Validate storage reliability.",
        "assumption": "Cache invalidation completes after every write.",
        "evidence": "Finding: cache invalidation after write is inconsistent with the stated result.",
    },
    "irrelevant_control": {
        "objective": "Verify cache invalidation after writes.",
        "evidence": "Evidence: observed cache invalidation after write completes.",
    },
}


class EvaluationError(ValueError):
    pass


def _identities(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(item not in RELATIONSHIPS for item in value):
        raise EvaluationError("invalid_" + field)
    if len(value) != len(set(value)):
        raise EvaluationError("duplicate_" + field)
    return list(value)


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise EvaluationError("invalid_stub_usage")
    result: dict[str, int] = {}
    for key in ("calls", "input_tokens", "output_tokens"):
        item = value.get(key)
        if type(item) is not int or item < 0:
            raise EvaluationError("invalid_stub_usage")
        result[key] = item
    return result


def _effort(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise EvaluationError("invalid_effort")
    result: dict[str, int] = {}
    for key in ("baseline_follow_up_minutes", "advisory_follow_up_minutes"):
        item = value.get(key)
        if type(item) is not int or item < 0:
            raise EvaluationError("invalid_effort")
        result[key] = item
    return result


def _case(case: Any) -> dict[str, Any]:
    if not isinstance(case, dict) or set(case) != {
        "id", "scenario", "independent_labels", "stub_choices", "stub_usage", "effort", "outcome"
    }:
        raise EvaluationError("invalid_case")
    if not isinstance(case["id"], str) or not case["id"]:
        raise EvaluationError("invalid_case_id")
    if not isinstance(case["scenario"], str) or case["scenario"] not in SCENARIOS:
        raise EvaluationError("invalid_case_scenario")
    if not isinstance(case["outcome"], str) or not case["outcome"]:
        raise EvaluationError("invalid_case_outcome")
    labels = _identities(case["independent_labels"], "independent_labels")
    choices = _identities(case["stub_choices"], "stub_choices")
    return {"id": case["id"], "scenario": case["scenario"], "labels": labels, "choices": choices,
            "usage": _usage(case["stub_usage"]), "effort": _effort(case["effort"]),
            "outcome": case["outcome"]}


def _packet(root: Path, task_id: str, objective: str, assumption: str | None = None) -> Path:
    path = root / ".de67" / "state" / "worker-dispatch" / (task_id + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "Objective: " + objective + "\n"
    if assumption:
        text += "Assumption [A-evaluation]: " + assumption + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _active_tasks(path: Path, tasks: list[str]) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE tasks(lineage_id TEXT NOT NULL, task_id TEXT NOT NULL, attempt_terminal_at REAL)")
        db.executemany("INSERT INTO tasks(lineage_id,task_id,attempt_terminal_at) VALUES ('evaluation',?,NULL)",
                       [(task_id,) for task_id in tasks])


def _event(path: Path, task_id: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"worker_name": "controlled-evaluation", "task_id": task_id, "observed_at": 0,
             "method": "item/completed", "params": {"threadId": "controlled-worker",
             "turnId": "controlled-turn", "item": {"type": "agentMessage", "id": "controlled-final",
             "phase": "final", "text": text}}}
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _config(root: Path, case_id: str) -> dict[str, Any]:
    state = root / ".de67" / "state"
    return {
        "mode": "shadow",
        "state_path": str(state / "pit-crew.sqlite3"),
        "max_scan_bytes": 65536,
        "max_candidates": 12,
        "max_admissions": 12,
        "cooldown_seconds": 0,
        "selection_timeout_seconds": 2,
        "provider_guard": {
            "mode": "shadow",
            "scope_id": "pit-crew-evaluation-" + case_id,
            "state_path": str(state / "provider-guard.sqlite3"),
            "max_calls": 12,
            "max_request_bytes": 8192,
            "max_in_flight": 1,
            "timeout_seconds": 2,
            "max_retries": 0,
            "retry_backoff_seconds": 0,
        },
    }


def _run_case(case: Mapping[str, Any]) -> dict[str, Any]:
    scenario = SCENARIOS[case["scenario"]]
    with tempfile.TemporaryDirectory(prefix="pit-crew-evaluation-") as directory:
        root = Path(directory)
        task_id, peer_task_id = "task-" + case["id"], "peer-" + case["id"]
        state_path = root / ".de67" / "state" / "tasks.sqlite3"
        task_ids = [task_id] + ([peer_task_id] if "peer_objective" in scenario else [])
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _active_tasks(state_path, task_ids)
        packet = _packet(root, task_id, scenario["objective"], scenario.get("assumption"))
        assignment: dict[str, Any] = {"id": "assignment-" + case["id"], "name": "controlled-evaluation",
                                      "task_id": task_id, "state_path": str(state_path), "lineage": "evaluation",
                                      "packet": str(packet)}
        if "peer_objective" in scenario:
            peer_packet = _packet(root, peer_task_id, scenario["peer_objective"])
            registry = root / ".de67" / "state" / "worker-library" / "registry.sqlite3"
            registry.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(registry) as db:
                db.execute("CREATE TABLE assignments(task_id TEXT, packet TEXT, state_path TEXT, lineage TEXT)")
                db.execute("INSERT INTO assignments VALUES (?,?,?,?)",
                           (peer_task_id, str(peer_packet), str(state_path), "evaluation"))
        source = root / ".de67" / "state" / "worker-library" / "events" / (assignment["id"] + ".jsonl")
        _event(source, task_id, scenario["evidence"])
        config = _config(root, case["id"])
        chosen: list[str] = []
        transport_calls: list[str] = []

        def controlled_stub(body: dict[str, Any], timeout: float) -> dict[str, Any]:
            del timeout
            relationship = body["choice"]["relationship"]
            transport_calls.append(relationship)
            if relationship in case["choices"]:
                chosen.append(relationship)
                choice: str | dict[str, str] = {"candidate_id": body["choice"]["candidate_id"],
                                                "relationship": relationship}
            else:
                choice = "none"
            return {"choice": choice, "usage": {"input_tokens": case["usage"]["input_tokens"],
                                                     "output_tokens": case["usage"]["output_tokens"]}}

        # The guarded selector normally rejects temporary owner state.  This
        # evaluator uses the same local test seam as the package tests solely
        # around a disposable, no-network controlled stub.
        guard = pit._guard_module()
        with patch.object(guard, "_disposable_context_roots", return_value=()):
            started = time.monotonic()
            result = pit.run(root, assignment, config=config, source=source, selector=controlled_stub)
            latency = time.monotonic() - started
        with pit._locked(config) as db:
            candidates = [row[0] for row in db.execute("SELECT relationship FROM pit_crew_candidates")]
        mailbox = root / ".de67" / "state" / "agent-mail" / "coordinator"
        mailbox_count = len(list(mailbox.glob("*.json"))) if mailbox.exists() else 0
    if result["deliveries"] or mailbox_count:
        raise EvaluationError("shadow_evaluation_enqueued_notice")
    if len(transport_calls) != case["usage"]["calls"]:
        raise EvaluationError("controlled_stub_call_count_changed")
    return {"candidates": sorted(candidates), "selected": sorted(chosen),
            "transport_calls": transport_calls, "latency_seconds": latency,
            "mailbox_notices": mailbox_count, "result": result}


def run(cases_path: Path | None = None) -> dict[str, Any]:
    cases_path = Path(cases_path or Path(__file__).with_name("evaluation.json"))
    try:
        source = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise EvaluationError("evaluation_fixture_unavailable") from error
    if not isinstance(source, dict) or set(source) != {"schema", "cases"} or source["schema"] != "de67.pit-crew-evaluation.v1":
        raise EvaluationError("invalid_evaluation_fixture")
    if not isinstance(source["cases"], list) or not source["cases"]:
        raise EvaluationError("invalid_evaluation_cases")
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    for raw in source["cases"]:
        case = _case(raw)
        observed = _run_case(case)
        labels, choices = set(case["labels"]), set(observed["selected"])
        rows.append({
            "id": case["id"],
            "independent_labels": sorted(labels),
            "stub_selected": sorted(choices),
            "useful": sorted(labels & choices),
            "irrelevant": sorted(choices - labels),
            "missed": sorted(labels - choices),
            "effort": case["effort"],
            "usage": {"calls": len(observed["transport_calls"]),
                      "input_tokens": case["usage"]["input_tokens"] * len(observed["transport_calls"]),
                      "output_tokens": case["usage"]["output_tokens"] * len(observed["transport_calls"])},
            "latency_seconds": observed["latency_seconds"],
            "outcome": case["outcome"],
            "observed_outcome": {"mode": "shadow", "candidate_relationships": observed["candidates"],
                                 "mailbox_notices": observed["mailbox_notices"],
                                 "provider_transport": "controlled_local_stub"},
        })
    totals = {
        key: sum(len(row[key]) for row in rows)
        for key in ("useful", "irrelevant", "missed")
    }
    totals.update({
        "stub_calls": sum(row["usage"]["calls"] for row in rows),
        "input_tokens": sum(row["usage"]["input_tokens"] for row in rows),
        "output_tokens": sum(row["usage"]["output_tokens"] for row in rows),
        "baseline_follow_up_minutes": sum(row["effort"]["baseline_follow_up_minutes"] for row in rows),
        "advisory_follow_up_minutes": sum(row["effort"]["advisory_follow_up_minutes"] for row in rows),
    })
    return {
        "schema": "de67.pit-crew-comparison.v1",
        "provider_requested": False,
        "provider_transport": "controlled_local_stub",
        "labels": "Independent fixture labels; not generated by the local stub.",
        "cases": rows,
        "totals": totals,
        "elapsed_seconds": time.monotonic() - started,
        "conclusion": "Negative or mixed usefulness is valid. This controlled shadow comparison exercises the local guard and Pit Crew selector seam, but establishes no live-provider, cost, or coordinator outcome claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.cases)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
