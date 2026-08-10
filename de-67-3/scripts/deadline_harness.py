#!/usr/bin/env python3
"""Small SQLite-backed deadline tracker for DE-67 task coordination."""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class DeadlineError(RuntimeError):
    """Raised when a deadline operation would violate the task record."""


class DeadlineHarness:
    """Track immutable per-task deadlines and append-only failure incidents."""

    def __init__(self, state_path: str | Path) -> None:
        raw_path = str(state_path)
        if not raw_path.strip():
            raise DeadlineError("State path must not be empty")
        if raw_path != ":memory:":
            path = Path(raw_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            raw_path = str(path)
        self.connection = sqlite3.connect(raw_path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                lineage_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                estimate_seconds REAL NOT NULL CHECK (estimate_seconds > 0),
                started_at REAL NOT NULL,
                deadline_at REAL NOT NULL,
                completed_at REAL,
                completion_evidence TEXT,
                integrity_breached_at REAL,
                integrity_reason TEXT,
                PRIMARY KEY (lineage_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS incidents (
                incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                lineage_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('deadline_miss', 'integrity_breach')),
                recorded_at REAL NOT NULL,
                reason TEXT,
                units INTEGER NOT NULL CHECK (units IN (1, 3)),
                cumulative_before INTEGER NOT NULL,
                cumulative_after INTEGER NOT NULL,
                cadence_threshold INTEGER,
                UNIQUE (lineage_id, task_id, kind),
                FOREIGN KEY (lineage_id, task_id)
                    REFERENCES tasks(lineage_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS lineage_binding (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                lineage_id TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "DeadlineHarness":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _now(value: float | None) -> float:
        result = time.time() if value is None else value
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise DeadlineError("Time must be a finite number")
        result = float(result)
        if not math.isfinite(result):
            raise DeadlineError("Time must be a finite number")
        return result

    @staticmethod
    def _identity(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DeadlineError(f"{label} must not be empty")
        return value.strip()

    @staticmethod
    def _positive_estimate(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DeadlineError("Estimate must be a positive finite number")
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise DeadlineError("Estimate must be a positive finite number")
        return result

    @staticmethod
    def _nonempty_text(value: str, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DeadlineError(f"{label} must not be empty")
        return value.strip()

    def _begin(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

    def _bind_lineage(self, lineage_id: str) -> None:
        binding = self.connection.execute(
            "SELECT lineage_id FROM lineage_binding WHERE singleton = 1"
        ).fetchone()
        if binding is None:
            existing = self.connection.execute(
                "SELECT DISTINCT lineage_id FROM tasks"
            ).fetchall()
            if len(existing) > 1:
                raise DeadlineError("State database already contains multiple lineages")
            bound_lineage = existing[0]["lineage_id"] if existing else lineage_id
            self.connection.execute(
                "INSERT INTO lineage_binding (singleton, lineage_id) VALUES (1, ?)",
                (bound_lineage,),
            )
        else:
            bound_lineage = binding["lineage_id"]
        if bound_lineage != lineage_id:
            raise DeadlineError(
                f"State database is bound to lineage {bound_lineage}; refusing {lineage_id}"
            )

    def _task(self, lineage_id: str, task_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE lineage_id = ? AND task_id = ?",
            (lineage_id, task_id),
        ).fetchone()
        if row is None:
            raise DeadlineError(f"Unknown task: {lineage_id}/{task_id}")
        return row

    def _cumulative_units(self, lineage_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(units), 0) AS total FROM incidents WHERE lineage_id = ?",
            (lineage_id,),
        ).fetchone()
        return int(row["total"])

    @staticmethod
    def _incident_result(row: sqlite3.Row, recorded: bool) -> dict[str, Any]:
        threshold = row["cadence_threshold"]
        return {
            "lineage_id": row["lineage_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "recorded": recorded,
            "recorded_at": row["recorded_at"],
            "reason": row["reason"],
            "units": row["units"],
            "cumulative_before": row["cumulative_before"],
            "cumulative_after": row["cumulative_after"],
            "independent_review_required": True,
            "cadence_crossed": threshold is not None,
            "cadence_threshold": threshold,
        }

    def _record_incident(
        self,
        lineage_id: str,
        task_id: str,
        kind: str,
        units: int,
        recorded_at: float,
        reason: str | None = None,
    ) -> dict[str, Any]:
        existing = self.connection.execute(
            "SELECT * FROM incidents WHERE lineage_id = ? AND task_id = ? AND kind = ?",
            (lineage_id, task_id, kind),
        ).fetchone()
        if existing is not None:
            return self._incident_result(existing, recorded=False)

        prior = self._cumulative_units(lineage_id)
        new = prior + units
        crossed = prior // 3 < new // 3
        threshold = (prior // 3 + 1) * 3 if crossed else None
        cursor = self.connection.execute(
            """
            INSERT INTO incidents (
                lineage_id, task_id, kind, recorded_at, reason, units,
                cumulative_before, cumulative_after, cadence_threshold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lineage_id, task_id, kind, recorded_at, reason, units, prior, new, threshold),
        )
        row = self.connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (cursor.lastrowid,)
        ).fetchone()
        return self._incident_result(row, recorded=True)

    def _record_miss_if_due(
        self, task: sqlite3.Row, now: float, *, completion_invalid: bool = False
    ) -> dict[str, Any] | None:
        completed_at = task["completed_at"]
        missed = now >= task["deadline_at"] and (
            completion_invalid
            or task["integrity_breached_at"] is not None
            or completed_at is None
            or completed_at >= task["deadline_at"]
        )
        if not missed:
            return None
        return self._record_incident(
            task["lineage_id"], task["task_id"], "deadline_miss", 1, now
        )

    def _status(self, lineage_id: str, task_id: str, now: float) -> dict[str, Any]:
        task = self._task(lineage_id, task_id)
        incidents = self.connection.execute(
            """
            SELECT * FROM incidents
            WHERE lineage_id = ? AND task_id = ?
            ORDER BY incident_id
            """,
            (lineage_id, task_id),
        ).fetchall()
        kinds = {row["kind"] for row in incidents}
        completion_accepted = (
            task["completed_at"] is not None and task["integrity_breached_at"] is None
        )
        if task["integrity_breached_at"] is not None:
            state = "integrity_breach"
        elif completion_accepted:
            state = "accepted"
        elif "deadline_miss" in kinds:
            state = "deadline_missed"
        else:
            state = "running"
        return {
            "lineage_id": lineage_id,
            "task_id": task_id,
            "claim_id": task["claim_id"],
            "state": state,
            "estimate_seconds": task["estimate_seconds"],
            "started_at": task["started_at"],
            "deadline_at": task["deadline_at"],
            "checked_at": now,
            "completion_accepted": completion_accepted,
            "completed_at": task["completed_at"],
            "completion_evidence": task["completion_evidence"],
            "deadline_missed": "deadline_miss" in kinds,
            "integrity_breached": "integrity_breach" in kinds,
            "integrity_reason": task["integrity_reason"],
            "cumulative_miss_units": self._cumulative_units(lineage_id),
            "incidents": [self._incident_result(row, recorded=False) for row in incidents],
        }

    def start_task(
        self,
        lineage_id: str,
        task_id: str,
        claim_id: str,
        estimate_seconds: float,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        claim_id = self._identity(claim_id, "Claim id")
        estimate = self._positive_estimate(estimate_seconds)
        started_at = self._now(now)
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO tasks (
                    lineage_id, task_id, claim_id,
                    estimate_seconds, started_at, deadline_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (lineage_id, task_id, claim_id, estimate, started_at, started_at + estimate),
            )
            created = cursor.rowcount == 1
            task = self._task(lineage_id, task_id)
            if not created and task["claim_id"] != claim_id:
                raise DeadlineError("Repeated start cannot change claim id")
            if not created and task["estimate_seconds"] != estimate:
                raise DeadlineError("Repeated start cannot change estimate")
            result = self._status(lineage_id, task_id, started_at)
            result["created"] = created
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def status_task(
        self, lineage_id: str, task_id: str, *, now: float | None = None
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        checked_at = self._now(now)
        self._begin()
        try:
            task = self._task(lineage_id, task_id)
            self._record_miss_if_due(task, checked_at)
            result = self._status(lineage_id, task_id, checked_at)
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def list_tasks(self, *, now: float | None = None) -> dict[str, Any]:
        checked_at = self._now(now)
        self._begin()
        try:
            binding = self.connection.execute(
                "SELECT lineage_id FROM lineage_binding WHERE singleton = 1"
            ).fetchone()
            if binding is None:
                raise DeadlineError("State database has not been bound to a lineage")
            lineage_id = binding["lineage_id"]
            task_rows = self.connection.execute(
                """
                SELECT * FROM tasks
                WHERE lineage_id = ?
                ORDER BY started_at, task_id
                """,
                (lineage_id,),
            ).fetchall()
            for task in task_rows:
                self._record_miss_if_due(task, checked_at)
            tasks = [
                self._status(lineage_id, task["task_id"], checked_at)
                for task in task_rows
            ]
            incidents = self.connection.execute(
                """
                SELECT * FROM incidents
                WHERE lineage_id = ?
                ORDER BY incident_id
                """,
                (lineage_id,),
            ).fetchall()
            result = {
                "lineage_id": lineage_id,
                "checked_at": checked_at,
                "cumulative_miss_units": self._cumulative_units(lineage_id),
                "tasks": tasks,
                "incidents": [
                    self._incident_result(incident, recorded=False)
                    for incident in incidents
                ],
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def expire_task(
        self, lineage_id: str, task_id: str, *, now: float | None = None
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        checked_at = self._now(now)
        self._begin()
        try:
            task = self._task(lineage_id, task_id)
            incident = self._record_miss_if_due(task, checked_at)
            result = {
                "incident": incident,
                "status": self._status(lineage_id, task_id, checked_at),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def complete_task(
        self,
        lineage_id: str,
        task_id: str,
        evidence: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        evidence = self._nonempty_text(evidence, "Completion evidence")
        completed_at = self._now(now)
        self._begin()
        try:
            task = self._task(lineage_id, task_id)
            if task["integrity_breached_at"] is not None:
                raise DeadlineError("An integrity breach invalidates task completion")
            if task["completed_at"] is None:
                self._record_miss_if_due(task, completed_at)
                self.connection.execute(
                    """
                    UPDATE tasks
                    SET completed_at = ?, completion_evidence = ?
                    WHERE lineage_id = ? AND task_id = ?
                    """,
                    (completed_at, evidence, lineage_id, task_id),
                )
            result = self._status(lineage_id, task_id, completed_at)
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def record_integrity_breach(
        self,
        lineage_id: str,
        task_id: str,
        reason: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        reason = self._nonempty_text(reason, "Integrity breach reason")
        recorded_at = self._now(now)
        self._begin()
        try:
            task = self._task(lineage_id, task_id)
            deadline_incident = self._record_miss_if_due(
                task, recorded_at, completion_invalid=True
            )
            incident = self._record_incident(
                lineage_id, task_id, "integrity_breach", 3, recorded_at, reason
            )
            if task["integrity_breached_at"] is None:
                self.connection.execute(
                    """
                    UPDATE tasks
                    SET integrity_breached_at = ?, integrity_reason = ?
                    WHERE lineage_id = ? AND task_id = ?
                    """,
                    (recorded_at, reason, lineage_id, task_id),
                )
            result = {
                "deadline_incident": deadline_incident,
                "incident": incident,
                "status": self._status(lineage_id, task_id, recorded_at),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise


def _state_path_for_watcher(state_path: str | Path) -> str:
    if str(state_path) == ":memory:":
        raise DeadlineError("CLI start requires a persistent SQLite state path")
    return str(Path(state_path).expanduser().resolve())


def spawn_watcher(state_path: str | Path, lineage_id: str, task_id: str) -> None:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--state",
        _state_path_for_watcher(state_path),
        "watch",
        "--lineage",
        lineage_id,
        "--task",
        task_id,
    ]
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)


def watch_task(
    state_path: str | Path, lineage_id: str, task_id: str
) -> dict[str, Any]:
    with DeadlineHarness(state_path) as harness:
        deadline = harness.status_task(lineage_id, task_id)["deadline_at"]
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(remaining)
    with DeadlineHarness(state_path) as harness:
        return harness.expire_task(lineage_id, task_id)


def add_task_identity_flags(command: argparse.ArgumentParser) -> None:
    command.add_argument("--state", dest="command_state")
    command.add_argument("--lineage", required=True)
    command.add_argument("--task", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", help="SQLite state path")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="Start a task once")
    add_task_identity_flags(start)
    start.add_argument("--claim", required=True)
    start.add_argument("--estimate-seconds", required=True, type=float)

    status = commands.add_parser("status", help="Read status and record a due miss")
    add_task_identity_flags(status)

    expire = commands.add_parser("expire", help="Record a due miss once")
    add_task_identity_flags(expire)

    complete = commands.add_parser("complete", help="Accept evidenced completion")
    add_task_identity_flags(complete)
    complete.add_argument("--evidence", required=True)

    breach = commands.add_parser("breach", help="Record an integrity breach once")
    add_task_identity_flags(breach)
    breach.add_argument("--reason", required=True)

    watch = commands.add_parser("watch", help="Wait for and expire one task")
    add_task_identity_flags(watch)

    list_command = commands.add_parser("list", help="List bound-lineage deadline state")
    list_command.add_argument("--state", dest="command_state")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        state_path = arguments.state or arguments.command_state
        if state_path is None:
            raise DeadlineError("A SQLite --state path is required")
        if (
            arguments.state is not None
            and arguments.command_state is not None
            and arguments.state != arguments.command_state
        ):
            raise DeadlineError("Conflicting --state paths")
        if arguments.command == "watch":
            result = watch_task(state_path, arguments.lineage, arguments.task)
        else:
            with DeadlineHarness(state_path) as harness:
                if arguments.command == "start":
                    result = harness.start_task(
                        arguments.lineage,
                        arguments.task,
                        arguments.claim,
                        arguments.estimate_seconds,
                    )
                elif arguments.command == "status":
                    result = harness.status_task(arguments.lineage, arguments.task)
                elif arguments.command == "expire":
                    result = harness.expire_task(arguments.lineage, arguments.task)
                elif arguments.command == "list":
                    result = harness.list_tasks()
                elif arguments.command == "complete":
                    result = harness.complete_task(
                        arguments.lineage, arguments.task, arguments.evidence
                    )
                else:
                    result = harness.record_integrity_breach(
                        arguments.lineage, arguments.task, arguments.reason
                    )
            if arguments.command == "start" and result["created"]:
                spawn_watcher(state_path, arguments.lineage, arguments.task)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DeadlineError, sqlite3.Error, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
