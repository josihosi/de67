#!/usr/bin/env python3
"""Run DE-67 coordinators under one external, restart-aware parent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Mapping, Sequence

from blocker_adapter import (
    BlockerAdapterError,
    BlockerReply,
    SubprocessBlockerAdapter,
    parse_adapter_command,
    safe_wait_for_reply,
)
from deadline_harness import DeadlineError, DeadlineHarness


RED_DFS_CLAIM = re.compile(r"^- \[ \] \N{LARGE RED CIRCLE} ", re.MULTILINE)
ACTIVE_LEDGER_ITEM = re.compile(r"^- \[ \] ", re.MULTILINE)
BLOCKED_LEDGER_ITEM = re.compile(r"^- Blocked: ", re.MULTILINE)
BLOCKED_AUDIT_PREFIX = "supervisor audit blocked-only ledger sha256:"
WORKER_OWNER_LOST_REASON = (
    "worker_owner_lost: coordinator process exited while this worker window "
    "remained nonterminal"
)
COORDINATOR_DECISION_OPPORTUNITIES = 3


class SupervisorError(RuntimeError):
    """Raised when coordinator ownership or restart state is inconsistent."""


@dataclass(frozen=True)
class RestartState:
    required: bool
    generation: int | None
    expected_run_id: str | None
    run_id: str | None
    reason: str | None


@dataclass(frozen=True)
class ChildResult:
    run_id: str
    run_dir: Path
    exit_code: int
    launched: bool


@dataclass(frozen=True)
class SupervisionEvent:
    restart: RestartState | None
    signature: str


@dataclass(frozen=True)
class MutationGate:
    kind: str
    identity: str
    selected_lane: str | None


@dataclass(frozen=True)
class MutationSuggestion:
    mode: str
    entry: str


class SupervisorJournal:
    """Persist the one-shot authorization for each semantic supervisor frontier."""

    def __init__(
        self,
        state_path: Path,
        lineage_id: str,
        owner_id: str,
        frontier_namespace: str | None = None,
    ) -> None:
        self.state_path = state_path
        self.lineage_id = lineage_id
        self.owner_id = owner_id
        self.frontier_namespace = frontier_namespace
        with sqlite3.connect(state_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS supervisor_attempts (
                    lineage_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    frontier TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    outcome TEXT,
                    detail TEXT,
                    PRIMARY KEY (lineage_id, role, frontier),
                    UNIQUE (lineage_id, run_id)
                )
                """
            )

    def begin(self, role: str, frontier: str, run_id: str) -> None:
        if self.frontier_namespace:
            frontier = f"{self.frontier_namespace}:{frontier}"
        try:
            with sqlite3.connect(self.state_path) as connection:
                connection.execute(
                    """
                    INSERT INTO supervisor_attempts (
                        lineage_id, role, frontier, run_id, owner_id, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (self.lineage_id, role, frontier, run_id, self.owner_id, time.time()),
                )
        except sqlite3.IntegrityError as error:
            raise SupervisorError(
                f"Supervisor {role} frontier was already attempted: {frontier}"
            ) from error

    def finish(self, run_id: str, outcome: str, detail: str | None = None) -> None:
        with sqlite3.connect(self.state_path) as connection:
            cursor = connection.execute(
                """
                UPDATE supervisor_attempts
                SET finished_at = ?, outcome = ?, detail = ?
                WHERE lineage_id = ? AND run_id = ? AND outcome IS NULL
                """,
                (time.time(), outcome, detail, self.lineage_id, run_id),
            )
            if cursor.rowcount != 1:
                raise SupervisorError(
                    f"Supervisor run is missing or already terminal: {run_id}"
                )


def _write(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reconcile_dead_run_records(run_root: Path) -> tuple[str, ...]:
    """Close stale run records only when their recorded process is absent."""
    if not run_root.is_dir():
        return ()
    interrupted: list[str] = []
    for status_path in sorted(run_root.glob("*/status.txt")):
        if status_path.read_text(encoding="utf-8").strip() not in {
            "STARTING", "RUNNING",
        }:
            continue
        pid_path = status_path.parent / "pid.txt"
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            pid = 0
        if _process_exists(pid):
            continue
        _write(status_path.parent / "supervisor_error.txt", (
            "Explicit supervisor startup interrupted this stale run because "
            "its recorded coordinator process is absent.\n"
        ))
        _write(status_path, "INTERRUPTED\n")
        interrupted.append(status_path.parent.name)
    return tuple(interrupted)


@contextmanager
def _supervisor_lock(state_path: Path) -> Iterator[None]:
    """Hold one OS-released lock for this deadline database."""
    lock_path = state_path.with_name(f"{state_path.name}.coordinator-supervisor.lock")
    handle: BinaryIO = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise SupervisorError(
            "Another coordinator supervisor already owns this deadline state"
        ) from error
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _restart_state(summary: Mapping[str, object], lineage_id: str) -> RestartState:
    if summary.get("lineage_id") != lineage_id:
        raise SupervisorError("Deadline state is bound to a different lineage")
    raw = summary.get("coordinator_restart")
    if raw is None:
        return RestartState(False, None, None, None, None)
    if not isinstance(raw, Mapping):
        raise SupervisorError("Coordinator restart state must be an object")

    required = raw.get("required")
    if required is None:
        required = raw.get("pending")
    if not isinstance(required, bool):
        raise SupervisorError("Coordinator restart state must say whether restart is required")

    generation = raw.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
        raise SupervisorError("Coordinator restart generation must be a positive integer")
    run_id = raw.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        raise SupervisorError("Acknowledged coordinator run id must be non-empty")
    expected_run_id = raw.get("expected_run_id")
    if expected_run_id is not None and (
        not isinstance(expected_run_id, str) or not expected_run_id.strip()
    ):
        raise SupervisorError("Claimed coordinator run id must be non-empty")
    reason = raw.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise SupervisorError("Coordinator restart reason must be non-empty")
    return RestartState(required, generation, expected_run_id, run_id, reason)


def read_clock(state_path: Path, lineage_id: str) -> RestartState:
    """Read restart state once; callers decide when another read is warranted."""
    with DeadlineHarness(state_path) as harness:
        return _restart_state(
            harness.coordinator_restart_status(lineage_id), lineage_id
        )


def terminalize_unowned_worker_windows(
    state_path: Path,
    lineage_id: str,
    recoverable_workers: Mapping[str, str] | None = None,
    *,
    include_unclaimed: bool = True,
) -> tuple[str, ...]:
    """Fail closed only for clocks that never acquired a verified worker."""
    recoverable = recoverable_workers or {}
    with DeadlineHarness(state_path) as harness:
        rows = harness.connection.execute(
                """
                SELECT task.task_id, claim.worker_id, claim.coordinator_session_id
                FROM tasks AS task
                LEFT JOIN worker_claims AS claim
                  ON claim.lineage_id = task.lineage_id
                 AND claim.task_id = task.task_id
                 AND claim.released_at IS NULL
                WHERE task.lineage_id = ? AND task.attempt_terminal_at IS NULL
                ORDER BY task.started_at
                """,
                (lineage_id,),
            ).fetchall()
        task_ids = tuple(
            str(row["task_id"])
            for row in rows
            if (
                (row["worker_id"] is not None or include_unclaimed)
                and recoverable.get(str(row["worker_id"] or ""))
                != str(row["coordinator_session_id"] or "")
            )
        )
        for task_id in task_ids:
            harness.abandon_attempt(
                lineage_id,
                task_id,
                WORKER_OWNER_LOST_REASON,
            )
    return task_ids


def active_worker_coordinator_session(
    state_path: Path,
    lineage_id: str,
) -> str | None:
    """Return the one coordinator session that owns all active worker claims."""
    with DeadlineHarness(state_path) as harness:
        sessions = tuple(
            str(row["coordinator_session_id"])
            for row in harness.connection.execute(
                """
                SELECT DISTINCT claim.coordinator_session_id
                FROM worker_claims AS claim
                JOIN tasks AS task
                  ON task.lineage_id = claim.lineage_id
                 AND task.task_id = claim.task_id
                WHERE claim.lineage_id = ?
                  AND claim.released_at IS NULL
                  AND task.attempt_terminal_at IS NULL
                ORDER BY claim.coordinator_session_id
                """,
                (lineage_id,),
            ).fetchall()
        )
    if len(sessions) > 1:
        raise SupervisorError(
            "Active worker claims belong to multiple coordinator sessions"
        )
    return sessions[0] if sessions else None


def runtime_worker_owners(
    workspace: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return runtime-verifiable Luna/Terra worker-to-parent ownership."""
    selected = os.environ.copy()
    if environment is not None:
        selected.update(environment)
    value = selected.get("DE67_CODEX_STATE", "").strip()
    state = Path(value).expanduser().resolve() if value else Path.home() / ".codex/state_5.sqlite"
    if not state.is_file():
        return {}
    with sqlite3.connect(f"file:{state}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """
            SELECT edge.child_thread_id, edge.parent_thread_id, child.model
            FROM thread_spawn_edges AS edge
            JOIN threads AS child ON child.id = edge.child_thread_id
            WHERE child.cwd = ?
            """,
            (str(workspace),),
        ).fetchall()
    return {
        str(worker): str(parent)
        for worker, parent, model in rows
        if any(name in str(model or "").lower() for name in ("luna", "terra"))
    }


def supervision_fingerprint(
    state_path: Path,
    lineage_id: str,
    workspace: Path,
) -> str:
    """Hash durable state that can justify another automatic child launch."""
    with DeadlineHarness(state_path) as harness:
        # DeadlineHarness binds one database to one lineage, so list_tasks is
        # lineage-scoped by the database invariant rather than a query filter.
        summary = harness.list_tasks(now=0.0)
        worker_claims = [
            dict(row)
            for row in harness.connection.execute(
                """
                SELECT task_id, worker_id, coordinator_session_id, supervisor_id,
                       claimed_at, last_checkpoint_at, released_at, release_reason
                FROM worker_claims WHERE lineage_id = ?
                ORDER BY task_id
                """,
                (lineage_id,),
            ).fetchall()
        ]
        worker_checkpoints = [
            dict(row)
            for row in harness.connection.execute(
                """
                SELECT task_id, sequence, worker_id, kind, evidence, recorded_at
                FROM worker_checkpoints WHERE lineage_id = ?
                ORDER BY task_id, sequence
                """,
                (lineage_id,),
            ).fetchall()
        ]
    documents: dict[str, str | None] = {}
    for relative in (
        ".de67/DFS.md",
        ".de67/work-ledger.md",
        ".de67/mutation-suggestions.md",
        ".de67/phase3-policy.d67",
    ):
        path = workspace / relative
        documents[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    payload = {
        "lineage_id": lineage_id,
        "clock": summary,
        "worker_claims": worker_claims,
        "worker_checkpoints": worker_checkpoints,
        "documents": documents,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def pending_mutation_suggestions(workspace: Path) -> tuple[MutationSuggestion, ...]:
    """Read owner entries, preserving legacy immediate-trigger semantics."""
    ledger = workspace / ".de67" / "mutation-suggestions.md"
    if not ledger.is_file():
        return ()
    pending = ledger.read_text(encoding="utf-8").partition(
        "## Pending suggestions"
    )[2]
    suggestions: list[MutationSuggestion] = []
    for line in pending.splitlines():
        if not line.startswith("- "):
            continue
        entry = line[2:].strip()
        if entry.lower() == "none.":
            continue
        match = re.match(
            r"^(?:Owner-authorized\s+)?\[(trigger|defer)\]:?\s+(.+)$",
            entry,
            re.IGNORECASE,
        )
        if match is None:
            suggestions.append(MutationSuggestion("trigger", entry))
        else:
            suggestions.append(MutationSuggestion(match.group(1).lower(), entry))
    return tuple(suggestions)


def mutation_gate(
    state_path: Path,
    lineage_id: str,
    workspace: Path | None = None,
) -> MutationGate | None:
    """Return the first durable mutation gate only after workers are quiet."""
    with DeadlineHarness(state_path) as harness:
        summary = harness.list_tasks()
    if any(task.get("state") == "running" for task in summary["tasks"]):
        return None
    if workspace is not None:
        immediate = [
            suggestion.entry
            for suggestion in pending_mutation_suggestions(workspace)
            if suggestion.mode == "trigger"
        ]
        if immediate:
            encoded = json.dumps(immediate, ensure_ascii=False, separators=(",", ":"))
            digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]
            return MutationGate("owner-suggestion", digest, None)
    random_review = summary.get("random_mutation")
    if isinstance(random_review, Mapping) and random_review.get("due") is True:
        return MutationGate(
            "random",
            f"cycle {random_review['cycle_number']}",
            str(random_review["selected_lane"]),
        )
    pending_reviews = summary.get("pending_incident_reviews", [])
    if pending_reviews:
        incident = pending_reviews[0]
        return MutationGate(
            "incident-review",
            str(incident.get("task_id") or incident.get("claim_id") or "pending incident"),
            None,
        )
    for key, kind in (
        ("pending_deadline_mutations", "deadline-mutation"),
        ("pending_integrity_mutations", "integrity-mutation"),
    ):
        pending = summary.get(key, [])
        if pending:
            item = pending[0]
            return MutationGate(
                kind,
                str(item.get("task_id") or item.get("claim_id") or kind),
                None,
            )
    return None


def _gate_signature(
    pending_reviews: Sequence[object],
    pending_mutations: Sequence[object],
) -> str:
    return "gate:" + json.dumps(
        {
            "reviews": pending_reviews,
            "mutations": pending_mutations,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def wait_for_supervision_event(
    state_path: Path,
    lineage_id: str,
    *,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> SupervisionEvent | None:
    """Wait without polling until durable clock state requires a successor."""
    with DeadlineHarness(state_path) as harness:
        summary = harness.list_tasks(now=now())
        restart = _restart_state(summary, lineage_id)
        if restart.required:
            return SupervisionEvent(restart, f"restart:{restart.generation}")

        pending_reviews = summary["pending_incident_reviews"]
        pending_mutations = [
            *summary.get("pending_deadline_mutations", []),
            *summary.get("pending_integrity_mutations", []),
        ]
        if pending_reviews or pending_mutations:
            signature = _gate_signature(pending_reviews, pending_mutations)
            return SupervisionEvent(None, signature)

        deadlines = [
            (float(task["deadline_at"]), str(task["claim_id"]))
            for task in summary["tasks"]
            if task.get("deadline_at") is not None and task.get("state") == "running"
        ]
        if not deadlines:
            return None
        deadline_at, claim_id = min(deadlines)

    sleep(max(0.0, deadline_at - now()))

    with DeadlineHarness(state_path) as harness:
        expired = harness.expire_claim(
            lineage_id,
            claim_id,
            now=max(deadline_at, now()),
        )
        if expired["incident"] is None:
            return None
        summary = harness.list_tasks(now=max(deadline_at, now()))
        pending_reviews = summary["pending_incident_reviews"]
        pending_mutations = [
            *summary.get("pending_deadline_mutations", []),
            *summary.get("pending_integrity_mutations", []),
        ]
        # expire_claim also returns the one durable incident after that incident
        # has been reviewed and resolved. Only live gates justify a successor;
        # the immutable historical deadline must not re-arm itself.
        if not pending_reviews and not pending_mutations:
            return None
        signature = _gate_signature(pending_reviews, pending_mutations)
    return SupervisionEvent(None, signature)


def consume_supervision_event(
    consumed: set[str],
    event: SupervisionEvent,
) -> None:
    """Reject replay before a durable event can launch another child."""
    if event.signature in consumed:
        raise SupervisorError(f"Supervision event replayed: {event.signature}")
    consumed.add(event.signature)


def work_is_complete(
    workspace: Path,
    state_path: Path,
    lineage_id: str,
) -> bool:
    """Derive completion from the DFS, current ledger, and live clock gates."""
    dfs = workspace / ".de67" / "DFS.md"
    ledger = workspace / ".de67" / "work-ledger.md"
    if not dfs.is_file() or not ledger.is_file() or not state_path.is_file():
        return False
    if RED_DFS_CLAIM.search(dfs.read_text(encoding="utf-8")):
        return False
    if ACTIVE_LEDGER_ITEM.search(ledger.read_text(encoding="utf-8")):
        return False

    with DeadlineHarness(state_path) as harness:
        harness.coordinator_restart_status(lineage_id)
        clock = harness.list_tasks()
    restart = clock["coordinator_restart"]
    unresolved_tasks = [
        task for task in clock["tasks"] if task.get("state") != "completed"
    ]
    if (
        unresolved_tasks
        or clock["pending_incident_reviews"]
        or clock.get("pending_deadline_mutations")
        or clock.get("pending_integrity_mutations")
        or clock.get("claim_clock_migration_conflicts")
        or clock.get("reopened_unaccepted_claims")
        or any(
            gap.get("status") == "open"
            for gap in clock.get("closure_gaps", [])
        )
    ):
        return False
    if restart is not None and restart["pending"]:
        return False

    # The DFS is the product contract. A cadence that became due on its final
    # terminal window cannot manufacture work after that contract is all green.
    return True


def ledger_has_active_work(workspace: Path) -> bool:
    """Treat every strict active-ledger item as immediately admissible work."""
    ledger = workspace / ".de67" / "work-ledger.md"
    return ledger.is_file() and ACTIVE_LEDGER_ITEM.search(
        ledger.read_text(encoding="utf-8")
    ) is not None


def ledger_has_only_blocked_work(workspace: Path) -> bool:
    """Stop when the ledger contains blockers but no executable item."""

    ledger = workspace / ".de67" / "work-ledger.md"
    if not ledger.is_file():
        return False
    text = ledger.read_text(encoding="utf-8")
    return (
        ACTIVE_LEDGER_ITEM.search(text) is None
        and BLOCKED_LEDGER_ITEM.search(text) is not None
    )


def blocked_ledger_audit_reason(workspace: Path) -> str | None:
    """Name one durable fresh-coordinator audit for the exact blocked ledger."""

    ledger = workspace / ".de67" / "work-ledger.md"
    if not ledger_has_only_blocked_work(workspace):
        return None
    digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
    return f"{BLOCKED_AUDIT_PREFIX}{digest}"


def blocked_ledger_was_audited(
    audit_reason: str,
    restart: RestartState,
) -> bool:
    """Stop only after one acknowledged coordinator saw this exact blocker set."""

    return (
        not restart.required
        and restart.run_id is not None
        and restart.reason == audit_reason
    )


def blocked_work_is_quiescent(state_path: Path, lineage_id: str) -> bool:
    """Require a confirmed blocker to leave no ticking task or live gate."""

    with DeadlineHarness(state_path) as harness:
        summary = harness.list_tasks()
    return not any(
        task.get("state") == "running" for task in summary["tasks"]
    ) and not any(
        summary.get(key)
        for key in (
            "pending_incident_reviews",
            "pending_deadline_mutations",
            "pending_integrity_mutations",
            "claim_clock_migration_conflicts",
        )
    )


def dfs_has_open_work(workspace: Path) -> bool:
    """Return whether the frozen DFS still has a red product claim."""
    dfs = workspace / ".de67" / "DFS.md"
    return dfs.is_file() and RED_DFS_CLAIM.search(
        dfs.read_text(encoding="utf-8")
    ) is not None


def ordinary_worker_evidence_contract() -> str:
    """Return the reusable evidence-retrieval contract for ordinary workers."""
    return (
        "Make each ordinary worker responsible for retrieving only the evidence needed for its "
        "next causal decision. Brief the outcome, proof route, known facts, and evidence locations; "
        "do not paste available bulk. The worker searches narrowly before reading, selects exact "
        "fields or slices from structured artifacts, keeps verbose command output in artifacts, "
        "and returns the first relevant divergence. Evidence bounds come from the current claim, "
        "never a fixed quota. A larger read remains available when deleting it would leave that "
        "claim unproved. When accumulated context no longer helps close the assigned gap, the "
        "worker uses the durable terminal result or handoff lifecycle instead of replaying it."
    )


def coordinator_ledger_contract() -> str:
    """Return the coordinator's authority over the active work projection."""
    return (
        "Own and freely rewrite the active work-ledger projection as evidence changes. Split or "
        "merge independently actionable work, including multiple simultaneous entries for one "
        "still-red DFS claim. Repository-owned implementation, tooling, fixtures, scenarios, "
        "registry bindings, and executable proof routes are ordinary recoverable work, not "
        "external authority. A closed diagnostic or documentation gap does not strand unfinished "
        "product proof; preserve the closed evidence and use the existing durable transitions to "
        "project and dispatch the remaining work. Trust the agent doing repository work to change "
        "the implementation, harness, fixtures, or observation path when that is the shortest honest "
        "route to proof. Trust the agent coordinating the claim to retire a failed strategy and invent "
        "a materially different implementation route; a retry fuse ends a strategy, not recoverable "
        "work. A proof prerequisite that depends on its own eventual output must be split into a "
        "non-credit observation/bootstrap step followed by independent validation; do not query the "
        "unchanged prerequisite again. For dashboard readability, usually expose about "
        "four to six meaningful gaps; use your judgment, and exceed eight only when combining them "
        "would hide genuinely independent proof routes."
    )


def worker_handoff_contract() -> str:
    return (
        "A deadline-harness task is only a worker clock, not a delegation. Immediately "
        "spawn its Luna or Terra worker. Reuse only a worker already spawned and durably bound "
        "by this same coordinator session; never adopt a worker from another coordinator. A successful "
        "new spawn must use the deadline task's deterministic task_name: the literal prefix task_ "
        "followed by the lowercase hexadecimal UTF-8 bytes of the exact task_id "
        "(for example, R-008-closure-108 becomes task_522d3030382d636c6f737572652d313038). "
        "Do not simplify or humanize this label. It is injective correlation metadata; "
        "the runtime thread UUID remains the worker identity. When policy detects an unbound task, "
        "its spawn_worker response injects the exact task_name and a concrete self-contained "
        "spawn_agent call for that opened task; use that call rather than reconstructing it from memory. "
        "Actually call spawn_agent; announcing that you are assigning a worker is not delegation. "
        "When several independently actionable deadline tasks are unbound, policy lists one call per "
        "task and you may spawn one "
        "distinct worker for each task before waiting, using each task's own deterministic task_name; "
        "do not serialize independent work merely because this example shows one worker. A successful "
        "spawn or eligible follow-up tool call is sufficient coordinator-side evidence to continue; do "
        "not require receiver_thread_ids in the coordinator-visible response and do not abandon "
        "solely because that field is absent there. The runner independently validates the actual "
        "runtime thread UUID against the coordinator parent, workspace, and Luna/Terra model, then "
        "records the durable claim automatically when the runtime spawn edge becomes visible. "
        "That visibility may arrive after the first wait begins; this is not a delegation failure. "
        "Never invoke claim-worker and never use "
        "/root/<task-name> as a worker identity. Proceed to the normal wait; if no verified roster "
        "handoff exists when the coordinator process exits, the runner abandons the attempt. "
        "After a verified handoff, remain in the worker-result lifecycle: an empty or timed wait "
        "is not completion, so wait again; record the returned terminal result before routing or exiting."
    )


def worker_result_ingress_contract() -> str:
    """Order a verified worker return before ledger-derived route selection."""
    return (
        "A verified ordinary-worker return is durable-state ingress, not a route decision. "
        "When a worker message returns completion evidence, a formal finding, or abandonment, "
        "judge it and record exactly one matching deadline-harness terminal transition before "
        "executing DE67_POLICY_DECIDE_ARGV_JSON again. This is the only pre-decision transition: "
        "the policy kernel derives worker result facts from that committed state. Do not wait for "
        "the live task to terminalize itself, do not ask the worker to mutate DE67 state, and do "
        "not record a second terminal transition when the task is already terminal. Ordinary test "
        "failure remains inside the worker task unless the returned evidence meets the formal "
        "finding boundary."
    )


def coordinator_recovery_contract(opportunity: int) -> str:
    """Return bounded corrective context after a failed coordinator decision."""
    if opportunity <= 1 or opportunity > COORDINATOR_DECISION_OPPORTUNITIES:
        raise SupervisorError(f"Invalid coordinator decision opportunity: {opportunity}")
    final = (
        " This is the final automatic opportunity; another failed decision stops the supervisor "
        "for attended diagnosis."
        if opportunity == COORDINATOR_DECISION_OPPORTUNITIES
        else ""
    )
    return (
        f"Recovery: this is coordinator decision opportunity {opportunity} of "
        f"{COORDINATOR_DECISION_OPPORTUNITIES}. The preceding coordinator exited with "
        "executable work still present. Re-read the current durable ledger and execute "
        "DE67_POLICY_DECIDE_ARGV_JSON before choosing the next action. Do not open a "
        "replacement task merely because an earlier attempt was abandoned. If policy returns "
        "spawn_worker, use the exact injected task_name and concrete spawn_agent call, adapting "
        "only the self-contained brief, model, and effort. Otherwise durably close or block the "
        "existing work with evidence, or complete the DFS when its proof is already sufficient. "
        "This recovery guard is not a read-only restriction: retain normal repository editing "
        "authority, including SQL schemas, queries, migrations, and SQLite-backed harness "
        "transitions; mutate DE67 clock state through the deadline harness rather than ad hoc SQL. "
        "Waiting or exiting without one of those durable outcomes is another failed decision."
        + final
    )


def coordinator_prompt(
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    run_id: str,
    generation: int | None,
    restart_reason: str | None = None,
) -> str:
    lines = [
        f"Act as a fresh Phase-3 delivery coordinator in {workspace}.",
        worker_result_ingress_contract(),
        "Do not read packaged DE-67 SKILL.md, kernel, role, reference, or guideline prose during delivery.",
        "The hash-bound .de67/phase3-policy.d67 file is the machine-canonical routing policy.",
        "Before every route decision, execute the argument array in DE67_POLICY_DECIDE_ARGV_JSON as a subprocess without a shell.",
        "Obey its action, read only its named sources, and preserve every emitted obligation in worker or reviewer briefs.",
        "Write every owner-facing text field rendered on the hosted dashboard in simple English. This includes ledger items, latest findings, waiting work, mutation or incident summaries, and any DFS summary that the dashboard displays. First explain what happened and why it matters in terms any reader can understand. Then preserve the necessary technical identifiers and evidence, state what remains or happens next, and use one concrete statement per sentence. If the simple explanation exposes a contradiction or a missing causal step, record that problem instead of hiding it behind technical language. Internal machine state and DFS detail that the dashboard does not display do not need this rewrite.",
        "Never review, apply, or resolve a mutation. When the compiled policy says retire_for_mutation_review, dispatch no worker, make no guidance change, and exit immediately so the external supervisor can run the exclusive reviewer.",
        "Do not infer policy from workspace guideline prose; those files are legacy differential fixtures on this branch.",
        "Read current code or DFS detail only when the compiled decision names ledger, dfs, or dfs_slice.",
        "For every worker, explicitly select gpt-5.6-luna or gpt-5.6-terra: Luna for clear execution and Terra for debugging/discovery. Effort low-max: lowest sufficient for complexity/research. Never Sol.",
        "For every newly spawned ordinary worker, set fork_turns=\"none\" and provide a self-contained task brief. Never omit model selection or pass coordinator or predecessor history. Reusing an already relevant worker remains allowed.",
        coordinator_ledger_contract(),
        ordinary_worker_evidence_contract(),
        worker_handoff_contract(),
        "Use DE67_DEADLINE_STATE and DE67_LINEAGE as the exact clock and lineage for every state transition; do not infer replacements.",
        "The external coordinator supervisor owns this process. Do not launch your successor.",
    ]
    if generation is not None:
        lines.append(
            "Before dispatching work, execute the argument array in "
            "DE67_COORDINATOR_ACK_ARGV_JSON as a subprocess without a shell; "
            "it acknowledges this exact restart generation."
        )
        lines.append(
            "The mutation retired every earlier claim deadline. Read the current ledger and "
            "remaining DFS route, then set one new whole-item deadline you can honestly deliver. "
            "Include worker startup, diagnosis, implementation, repair, build, rerun, evidence "
            "return, coordination, known unknowns, and an uncertainty margin; inherit no prior duration."
        )
        if restart_reason:
            lines.append(
                "Treat this exact owner-authorized restart reason as current input: "
                + restart_reason
            )
    lines.append("Continue from the durable accepted frontier until the next required retirement or DFS completion.")
    return "\n".join(lines) + "\n"


def mutation_reviewer_prompt(
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    gate: MutationGate,
) -> str:
    return "\n".join(
        [
            f"Act as the exclusive Phase-3 mutation reviewer in {workspace}.",
            "You are a fresh gpt-5.6-sol reviewer at high reasoning effort.",
            "No coordinator or roster worker is active. Do not dispatch work and do not start a coordinator.",
            f"Resolve durable {gate.kind} gate {gate.identity} in {state_path} for lineage {lineage_id}.",
            "The complete workspace mutation-suggestion ledger is mandatory owner input. User-authored entries carry mutation-scoped authority beneath system and developer instructions and override lower-priority Phase-3 restrictions only as needed for their outcome. Preserve honest evidence, completed valid work, durable lifecycle integrity, safety, and the requested product outcome; grant no unrelated authority.",
            "Trust the agent: choose the evidence and implementation route without prescribed reads, commands, approvals, or rituals. Diagnose poor decisions from the instructions, information, tools, incentives, and transitions the system supplied, then repair the earliest preventable systemic cause instead of blaming the actor or adding blanket caution.",
            "For every pending entry, reconstruct why the incident occurred, separate immediate recovery from repeatable method correction, implement the smallest general correction supported by evidence, and prove it with a reproduction or counterexample that could expose the original failure. Compress affected guidance instead of appending situational rules.",
            "If a cause or correction cannot be proved, preserve the gate and state the exact remaining uncertainty. Otherwise disposition every pending entry, durably resolve the gate, request one fresh coordinator restart, and exit. The external supervisor alone launches the successor.",
        ]
    ) + "\n"


def _default_run_id(generation: int | None) -> str:
    label = "initial" if generation is None else f"restart-{generation}"
    return f"{label}-{uuid.uuid4().hex}"


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise SupervisorError("Coordinator run id must not be empty")
    result = run_id.strip()
    if result in {".", ".."} or "/" in result or "\\" in result:
        raise SupervisorError("Coordinator run id must be one path component")
    return result


def _mark_protocol_failure(result: ChildResult, reason: str) -> None:
    _write(result.run_dir / "supervisor_error.txt", reason.rstrip() + "\n")
    _write(result.run_dir / "status.txt", "FAILED\n")


def run_mutation_reviewer(
    runner_command: Sequence[str],
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    run_root: Path,
    gate: MutationGate,
    *,
    extra_env: Mapping[str, str] | None = None,
    run_id: str | None = None,
) -> ChildResult:
    reviewer_env = dict(extra_env or {})
    reviewer_env.update(
        {
            "DE67_COORDINATOR_MODEL": "gpt-5.6-sol",
            "DE67_COORDINATOR_REASONING_EFFORT": "high",
        }
    )
    return run_child(
        runner_command,
        workspace,
        state_path,
        lineage_id,
        run_root,
        run_id or f"mutation-{uuid.uuid4().hex}",
        None,
        extra_env=reviewer_env,
        prompt_override=mutation_reviewer_prompt(
            workspace, state_path, lineage_id, gate
        ),
        role="mutation-reviewer",
    )


def _complete_mutation_review(
    runner_command: Sequence[str],
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    run_root: Path,
    gate: MutationGate,
    *,
    extra_env: Mapping[str, str] | None,
    reviewed_gates: set[tuple[str, str]] | None = None,
    journal: SupervisorJournal | None = None,
) -> RestartState:
    consumed = reviewed_gates if reviewed_gates is not None else set()
    with DeadlineHarness(state_path) as harness:
        harness.retire_claim_clocks_for_mutation(
            lineage_id,
            f"{gate.kind} {gate.identity}",
        )
    while True:
        gate_key = (gate.kind, gate.identity)
        if gate_key in consumed:
            raise SupervisorError(
                f"Mutation gate repeated without resolution: {gate.kind} {gate.identity}"
            )
        consumed.add(gate_key)
        run_id = f"mutation-{uuid.uuid4().hex}"
        if journal is not None:
            journal.begin(
                "mutation-reviewer",
                f"{gate.kind}:{gate.identity}",
                run_id,
            )
        result = run_mutation_reviewer(
            runner_command,
            workspace,
            state_path,
            lineage_id,
            run_root,
            gate,
            extra_env=extra_env,
            run_id=run_id,
        )
        if journal is not None:
            journal.finish(
                run_id,
                "succeeded" if result.launched and result.exit_code == 0 else "failed",
                None if result.exit_code == 0 else f"exit code {result.exit_code}",
            )
        if not result.launched or result.exit_code != 0:
            raise SupervisorError(
                f"Mutation reviewer failed for {gate.kind} {gate.identity}; ordinary work remains stopped"
            )
        remaining = mutation_gate(state_path, lineage_id, workspace)
        if remaining is not None:
            gate = remaining
            continue
        restart = read_clock(state_path, lineage_id)
        if not restart.required or restart.generation is None:
            _mark_protocol_failure(
                result,
                "Mutation reviewer resolved the gate without requesting one fresh coordinator",
            )
            raise SupervisorError("Resolved mutation lacks its fresh-coordinator handoff")
        return restart


def run_child(
    runner_command: Sequence[str],
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    run_root: Path,
    run_id: str,
    generation: int | None,
    *,
    extra_env: Mapping[str, str] | None = None,
    resume_session_id: str | None = None,
    decision_opportunity: int = 1,
    prompt_override: str | None = None,
    role: str = "coordinator",
) -> ChildResult:
    if not runner_command:
        raise SupervisorError("Runner command must not be empty")
    run_id = _validate_run_id(run_id)
    run_dir = run_root / run_id
    try:
        run_dir.mkdir(parents=False, exist_ok=False)
    except OSError as error:
        raise SupervisorError(f"Cannot create coordinator run directory: {error}") from error

    if prompt_override is not None:
        prompt = prompt_override
    elif resume_session_id is None:
        restart_reason = None
        if generation is not None:
            with DeadlineHarness(state_path) as harness:
                restart = harness.coordinator_restart_status(lineage_id).get(
                    "coordinator_restart"
                )
            if restart and restart.get("generation") == generation:
                restart_reason = restart.get("reason")
        prompt = coordinator_prompt(
            workspace, state_path, lineage_id, run_id, generation, restart_reason
        )
    else:
        prompt = (
            "Continue the same DE-67 coordinator lifecycle. Ordinary worker results "
            "and findings are state events, not a reason to stop. "
            + worker_result_ingress_contract()
            + " Before any other action, execute "
            "DE67_POLICY_DECIDE_ARGV_JSON without a shell and obey its minimal action brief. "
            "Worker: Luna for clear execution; Terra for debugging/discovery. Effort low-max: "
            "lowest sufficient for complexity/research. Never Sol. Every newly spawned ordinary "
            "worker must use fork_turns=\"none\" and a self-contained brief; never omit model "
            "selection or pass coordinator or predecessor history. "
            + coordinator_ledger_contract()
            + " "
            + ordinary_worker_evidence_contract()
            + " "
            + worker_handoff_contract()
            + "\n"
        )
    if decision_opportunity > 1:
        prompt = prompt.rstrip() + "\n" + coordinator_recovery_contract(
            decision_opportunity
        ) + "\n"
    _write(run_dir / "prompt.txt", prompt)
    _write(run_dir / "status.txt", "STARTING\n")

    environment = os.environ.copy()
    if extra_env is not None:
        environment.update(extra_env)
    environment.update(
        {
            "DE67_COORDINATOR_RUN_ID": run_id,
            "DE67_PROCESS_ROLE": role,
            "DE67_DEADLINE_STATE": str(state_path),
            "DE67_LINEAGE": lineage_id,
            "DE67_WORKSPACE": str(workspace),
            "DE67_SUPERVISOR_PID": str(os.getpid()),
            "DE67_COORDINATOR_SESSION_FILE": str(run_dir / "session_id.txt"),
            "DE67_BLOCKER_ADAPTER_STATE": str(
                workspace / ".de67" / "state" / "blocker-adapter-state.json"
            ),
            "DE67_POLICY_DECIDE_ARGV_JSON": json.dumps(
                [
                    sys.executable,
                    str(Path(__file__).resolve().with_name("policy_kernel.py")),
                    "decide",
                    "--policy",
                    str(workspace / ".de67" / "phase3-policy.d67"),
                    "--workspace",
                    str(workspace),
                    "--state",
                    str(state_path),
                    "--lineage",
                    lineage_id,
                ]
            ),
            "DE67_POLICY_GUARD_ARGV_JSON": json.dumps(
                [
                    sys.executable,
                    str(Path(__file__).resolve().with_name("policy_kernel.py")),
                    "guard",
                    "--candidate",
                    str(workspace / ".de67" / "state" / "phase3-policy.candidate.json"),
                    "--contracts",
                    str(workspace / ".de67" / "phase3-contracts.json"),
                    "--output",
                    str(workspace / ".de67" / "state" / "phase3-policy.candidate.d67"),
                ]
            ),
        }
    )
    if resume_session_id is None:
        environment.pop("DE67_COORDINATOR_RESUME_SESSION", None)
    else:
        environment["DE67_COORDINATOR_RESUME_SESSION"] = resume_session_id
    if generation is None:
        environment.pop("DE67_COORDINATOR_RESTART_GENERATION", None)
        environment.pop("DE67_COORDINATOR_ACK_ARGV_JSON", None)
    else:
        environment["DE67_COORDINATOR_RESTART_GENERATION"] = str(generation)
        deadline_script = Path(__file__).resolve().with_name("deadline_harness.py")
        environment["DE67_COORDINATOR_ACK_ARGV_JSON"] = json.dumps(
            [
                sys.executable,
                str(deadline_script),
                "ack-restart",
                "--state",
                str(state_path),
                "--lineage",
                lineage_id,
                "--generation",
                str(generation),
                "--run-id",
                run_id,
            ]
        )

    command = [*runner_command, "--cwd", str(workspace)]
    process: subprocess.Popen[str]
    try:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            close_fds=True,
        )
    except OSError as error:
        _write(
            run_dir / "supervisor_error.txt",
            f"Failed to launch coordinator runner: {error}\n",
        )
        _write(run_dir / "exit_code.txt", "1\n")
        _write(run_dir / "status.txt", "FAILED\n")
        return ChildResult(run_id, run_dir, 1, False)
    exit_code = 1
    try:
        _write(run_dir / "pid.txt", f"{process.pid}\n")
        _write(run_dir / "status.txt", "RUNNING\n")
        if process.stdin is None:
            raise SupervisorError("Runner stdin pipe was not created")
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except BrokenPipeError:
            pass
        exit_code = process.wait()
    except BaseException:
        if process.poll() is None:
            process.kill()
            exit_code = process.wait()
        _write(run_dir / "exit_code.txt", f"{exit_code}\n")
        _write(run_dir / "status.txt", "FAILED\n")
        raise

    _write(run_dir / "exit_code.txt", f"{exit_code}\n")
    _write(run_dir / "status.txt", "DONE\n" if exit_code == 0 else "FAILED\n")
    return ChildResult(run_id, run_dir, exit_code, True)


def _run_supervisor_locked(
    state_path: str | Path,
    lineage_id: str,
    workspace: str | Path,
    runner_command: Sequence[str],
    run_root: str | Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    run_id_factory: Callable[[int | None], str] = _default_run_id,
    event_waiter: Callable[[Path, str], SupervisionEvent | None] | None = None,
    blocker_waiter: Callable[[Path, str], BlockerReply | None] | None = None,
) -> int:
    state = Path(state_path).expanduser().resolve()
    workdir = Path(workspace).expanduser().resolve()
    records = Path(run_root).expanduser().resolve()
    if not workdir.is_dir():
        raise SupervisorError(f"Workspace does not exist: {workdir}")
    if not lineage_id.strip():
        raise SupervisorError("Lineage id must not be empty")
    if not runner_command:
        raise SupervisorError("Runner command must not be empty")
    wait_for_event = event_waiter or wait_for_supervision_event

    # Existing run records prove this is a supervisor recovery, not the first
    # bootstrap that may legitimately begin with a seeded task clock.
    recovering_existing_runs = records.is_dir() and any(records.iterdir())
    if recovering_existing_runs:
        reconcile_dead_run_records(records)
    terminalize_unowned_worker_windows(
        state,
        lineage_id,
        runtime_worker_owners(workdir, extra_env),
        include_unclaimed=recovering_existing_runs,
    )

    restart = read_clock(state, lineage_id)
    blocked_audit = blocked_ledger_audit_reason(workdir)
    if blocked_audit is not None:
        if (
            blocked_ledger_was_audited(blocked_audit, restart)
            and blocked_work_is_quiescent(state, lineage_id)
        ):
            if blocker_waiter is None:
                return 0
            reply = blocker_waiter(workspace=workdir, lineage_id=lineage_id)
            if reply is None:
                return 0
            with DeadlineHarness(state) as harness:
                requested = harness.request_coordinator_restart(
                    lineage_id,
                    f"owner replied through blocker adapter {reply.reply_message_id}",
                )["coordinator_restart"]
            restart = _restart_state(
                {"lineage_id": lineage_id, "coordinator_restart": requested},
                lineage_id,
            )
        if not restart.required:
            with DeadlineHarness(state) as harness:
                requested = harness.request_coordinator_restart(
                    lineage_id,
                    blocked_audit,
                )["coordinator_restart"]
            restart = _restart_state(
                {"lineage_id": lineage_id, "coordinator_restart": requested},
                lineage_id,
            )
    elif work_is_complete(workdir, state, lineage_id):
        return 0

    records.mkdir(parents=True, exist_ok=True)
    journal = SupervisorJournal(
        state,
        lineage_id,
        f"supervisor-{os.getpid()}-{uuid.uuid4().hex}",
        os.environ.get("DE67_SUPERVISOR_START_TOKEN"),
    )
    reviewed_gates: set[tuple[str, str]] = set()
    consumed_events: set[str] = set()
    gate = mutation_gate(state, lineage_id, workdir)
    if gate is not None:
        restart = _complete_mutation_review(
            runner_command,
            workdir,
            state,
            lineage_id,
            records,
            gate,
            extra_env=extra_env,
            reviewed_gates=reviewed_gates,
            journal=journal,
        )

    generation = restart.generation if restart.required else None
    # A restarted supervisor resumes the durable owner of any still-live
    # workers. It never launches a fresh coordinator that would have to adopt
    # another session's children or dispatch duplicates.
    resume_session_id = active_worker_coordinator_session(state, lineage_id)
    attempted_generations: set[int] = set()
    failed_decision_opportunities = 0
    while True:
        if generation is not None:
            if generation in attempted_generations:
                raise SupervisorError(
                    f"Restart generation {generation} was already attempted"
                )
            attempted_generations.add(generation)

        run_id = _validate_run_id(run_id_factory(generation))
        if generation is not None:
            if restart.expected_run_id is not None:
                raise SupervisorError(
                    f"Restart generation {generation} is already claimed by "
                    f"{restart.expected_run_id}"
                )
            with DeadlineHarness(state) as harness:
                harness.claim_coordinator_restart(
                    lineage_id, generation, run_id
                )

        launch_fingerprint = supervision_fingerprint(state, lineage_id, workdir)
        journal.begin("coordinator", launch_fingerprint, run_id)
        result = run_child(
            runner_command,
            workdir,
            state,
            lineage_id,
            records,
            run_id,
            generation,
            extra_env=extra_env,
            resume_session_id=resume_session_id,
            decision_opportunity=failed_decision_opportunities + 1,
        )

        # A runner that could not be launched is a concrete environment blocker,
        # not a coordinator result that another coordinator can repair.
        if not result.launched:
            return result.exit_code if result.exit_code > 0 else 1

        # Unclaimed clocks are phantom work and must fail closed. A verified
        # worker claim belongs to this supervised coordinator session, however,
        # and survives a transient CLI process exit so the same session can
        # resume its structured worker-result lifecycle.
        terminalize_unowned_worker_windows(
            state, lineage_id, runtime_worker_owners(workdir, extra_env)
        )
        progressed = supervision_fingerprint(state, lineage_id, workdir)
        journal.finish(
            run_id,
            "progressed" if launch_fingerprint != progressed else (
                "succeeded" if result.exit_code == 0 else "failed"
            ),
            None if result.exit_code == 0 else f"exit code {result.exit_code}",
        )

        # This is the only clock read after this child exits. There is no polling loop.
        after = read_clock(state, lineage_id)

        if generation is not None:
            if after.required and after.generation == generation:
                _mark_protocol_failure(
                    result,
                    f"Coordinator did not acknowledge restart generation {generation}",
                )
                return result.exit_code if result.exit_code != 0 else 1
            if (
                not after.required
                and after.generation == generation
                and after.run_id != result.run_id
            ):
                _mark_protocol_failure(
                    result,
                    f"Restart generation {generation} was acknowledged by a different run",
                )
                return 1
            if after.generation is not None and after.generation < generation:
                _mark_protocol_failure(result, "Coordinator restart generation moved backwards")
                return 1

        gate = mutation_gate(state, lineage_id, workdir)
        if gate is not None:
            after = _complete_mutation_review(
                runner_command,
                workdir,
                state,
                lineage_id,
                records,
                gate,
                extra_env=extra_env,
                reviewed_gates=reviewed_gates,
                journal=journal,
            )

        blocked_audit = blocked_ledger_audit_reason(workdir)
        if blocked_audit is not None and blocked_work_is_quiescent(
            state, lineage_id
        ):
            if blocker_waiter is None:
                return 0
            reply = blocker_waiter(workspace=workdir, lineage_id=lineage_id)
            if reply is None:
                return 0
            with DeadlineHarness(state) as harness:
                requested = harness.request_coordinator_restart(
                    lineage_id,
                    f"owner replied through blocker adapter {reply.reply_message_id}",
                )["coordinator_restart"]
            after = _restart_state(
                {"lineage_id": lineage_id, "coordinator_restart": requested},
                lineage_id,
            )
        if work_is_complete(workdir, state, lineage_id):
            return 0
        has_executable_work = ledger_has_active_work(workdir) or dfs_has_open_work(workdir)
        if not after.required and has_executable_work:
            session_path = result.run_dir / "session_id.txt"
            session_id = (
                session_path.read_text(encoding="utf-8").strip()
                if session_path.is_file()
                else ""
            )
            if session_id:
                if launch_fingerprint == progressed:
                    failure = (
                        "Coordinator returned with executable work but made no durable progress"
                        if result.exit_code == 0
                        else "Coordinator crashed with executable work but made no durable progress"
                    )
                    _mark_protocol_failure(
                        result,
                        failure,
                    )
                    return result.exit_code if result.exit_code > 0 else 1
                if result.exit_code != 0:
                    if (
                        failed_decision_opportunities + 1
                        >= COORDINATOR_DECISION_OPPORTUNITIES
                    ):
                        _mark_protocol_failure(
                            result,
                            "Three coordinator decision opportunities were exhausted; "
                            "explicit supervisor startup is required",
                        )
                        return result.exit_code
                    failed_decision_opportunities += 1
                else:
                    failed_decision_opportunities = 0
                active_owner = active_worker_coordinator_session(state, lineage_id)
                resume_session_id = active_owner or (
                    None
                    if failed_decision_opportunities + 1
                    == COORDINATOR_DECISION_OPPORTUNITIES
                    else session_id
                )
                generation = None
                continue
            if result.exit_code == 0:
                _mark_protocol_failure(
                    result,
                    "Coordinator returned with executable work but no resumable session id",
                )
                return 1
        if not after.required and result.exit_code != 0 and has_executable_work:
            # Process recovery is not a semantic coordinator restart. Start a
            # clean low coordinator against the same durable frontier without
            # manufacturing a mutation generation.
            if launch_fingerprint == progressed:
                _mark_protocol_failure(
                    result,
                    "Coordinator crashed with executable work but made no durable progress",
                )
                return result.exit_code if result.exit_code > 0 else 1
            if (
                failed_decision_opportunities + 1
                >= COORDINATOR_DECISION_OPPORTUNITIES
            ):
                _mark_protocol_failure(
                    result,
                    "Three coordinator decision opportunities were exhausted; "
                    "explicit supervisor startup is required",
                )
                return result.exit_code
            failed_decision_opportunities += 1
            resume_session_id = None
            generation = None
            continue
        if not after.required:
            if event_waiter is None:
                event = wait_for_supervision_event(state, lineage_id)
            else:
                event = wait_for_event(state, lineage_id)
            if event is None:
                return result.exit_code if result.exit_code > 0 else 0
            try:
                consume_supervision_event(consumed_events, event)
            except SupervisorError as error:
                _mark_protocol_failure(result, str(error))
                return 1
            if event.restart is None:
                gate = mutation_gate(state, lineage_id, workdir)
                if gate is None:
                    _mark_protocol_failure(
                        result,
                        "Mutation event became active before all worker windows were terminal",
                    )
                    return 1
                after = _complete_mutation_review(
                    runner_command,
                    workdir,
                    state,
                    lineage_id,
                    records,
                    gate,
                    extra_env=extra_env,
                    reviewed_gates=reviewed_gates,
                    journal=journal,
                )
            else:
                after = event.restart
        if after.generation is None:
            _mark_protocol_failure(result, "Required coordinator restart lacks a generation")
            return 1
        if after.generation in attempted_generations:
            _mark_protocol_failure(
                result,
                f"Restart generation {after.generation} remains pending after its only attempt",
            )
            return 1
        # A durable semantic restart (mutation, incident retirement, or owner
        # reply) starts a new coordinator lifecycle. Failed decisions from an
        # earlier lifecycle must not consume this one's bounded opportunities.
        failed_decision_opportunities = 0
        restart = after
        generation = after.generation
        resume_session_id = active_worker_coordinator_session(state, lineage_id)


def run_supervisor(
    state_path: str | Path,
    lineage_id: str,
    workspace: str | Path,
    runner_command: Sequence[str],
    run_root: str | Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    run_id_factory: Callable[[int | None], str] = _default_run_id,
    event_waiter: Callable[[Path, str], SupervisionEvent | None] | None = None,
    blocker_waiter: Callable[[Path, str], BlockerReply | None] | None = None,
) -> int:
    state = Path(state_path).expanduser().resolve()
    with _supervisor_lock(state):
        return _run_supervisor_locked(
            state,
            lineage_id,
            workspace,
            runner_command,
            run_root,
            extra_env=extra_env,
            run_id_factory=run_id_factory,
            event_waiter=event_waiter,
            blocker_waiter=blocker_waiter,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--lineage", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--coordinator-model", default="gpt-5.6-sol")
    parser.add_argument(
        "--coordinator-reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max", "ultra"),
        default="low",
    )
    parser.add_argument(
        "--runner",
        nargs=argparse.REMAINDER,
        help="Runner command; place this option last",
    )
    parser.add_argument(
        "--blocker-adapter-command-json",
        help=(
            "Optional shell-independent JSON argument array for an external owner-contact "
            "adapter; the supervisor appends the wait/workspace/lineage arguments"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        blocker_adapter = None
        if arguments.blocker_adapter_command_json is not None:
            try:
                blocker_adapter = SubprocessBlockerAdapter(
                    parse_adapter_command(arguments.blocker_adapter_command_json)
                )
            except BlockerAdapterError as error:
                print(
                    "coordinator supervisor: optional blocker adapter disabled: "
                    f"{error}",
                    file=sys.stderr,
                )
        return run_supervisor(
            arguments.state,
            arguments.lineage,
            arguments.workspace,
            arguments.runner or (),
            arguments.run_root,
            extra_env={
                "DE67_COORDINATOR_MODEL": arguments.coordinator_model,
                "DE67_COORDINATOR_REASONING_EFFORT": (
                    arguments.coordinator_reasoning_effort
                ),
            },
            blocker_waiter=(
                (
                    lambda *, workspace, lineage_id: safe_wait_for_reply(
                        blocker_adapter,
                        workspace=workspace,
                        lineage_id=lineage_id,
                    )
                )
                if blocker_adapter is not None
                else None
            ),
        )
    except (DeadlineError, SupervisorError, OSError) as error:
        print(f"coordinator supervisor: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
