#!/usr/bin/env python3
"""Small SQLite-backed deadline tracker for DE-67 task coordination."""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


RANDOM_INTERVAL_MIN = 10
RANDOM_INTERVAL_MAX = 30
RANDOM_MUTATION_LANES = (
    "test-and-task-guidelines.md",
    "orchestrator-guidelines.md",
    "DFS.md",
)
RECENT_FAILURE_VERDICT_LIMIT = 10
INCIDENT_KINDS = ("deadline_miss", "integrity_breach")


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
                terminal_at REAL,
                PRIMARY KEY (lineage_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS incidents (
                incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                lineage_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('deadline_miss', 'integrity_breach')),
                recorded_at REAL NOT NULL,
                reason TEXT,
                short_verdict TEXT NOT NULL,
                long_detail TEXT NOT NULL,
                reviewed_at REAL,
                units INTEGER NOT NULL CHECK (units IN (1, 3)),
                cumulative_before INTEGER NOT NULL,
                cumulative_after INTEGER NOT NULL,
                cadence_threshold INTEGER,
                UNIQUE (lineage_id, task_id, kind),
                FOREIGN KEY (lineage_id, task_id)
                    REFERENCES tasks(lineage_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS worker_findings (
                lineage_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('blocker', 'unexpected')),
                reported_at REAL NOT NULL,
                short_verdict TEXT NOT NULL,
                evidence TEXT NOT NULL,
                PRIMARY KEY (lineage_id, task_id),
                FOREIGN KEY (lineage_id, task_id)
                    REFERENCES tasks(lineage_id, task_id)
            );

            CREATE TABLE IF NOT EXISTS lineage_binding (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                lineage_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS random_mutation_cycles (
                lineage_id TEXT NOT NULL,
                cycle_number INTEGER NOT NULL CHECK (cycle_number > 0),
                interval_windows INTEGER NOT NULL CHECK (
                    interval_windows BETWEEN 10 AND 30
                ),
                due_after_terminal_windows INTEGER NOT NULL CHECK (
                    due_after_terminal_windows >= interval_windows
                ),
                selected_lane TEXT NOT NULL CHECK (
                    selected_lane IN (
                        'test-and-task-guidelines.md',
                        'orchestrator-guidelines.md',
                        'DFS.md'
                    )
                ),
                due_task_id TEXT,
                resolution_evidence TEXT,
                PRIMARY KEY (lineage_id, cycle_number)
            );

            CREATE TABLE IF NOT EXISTS coordinator_restart_requests (
                lineage_id TEXT NOT NULL,
                generation INTEGER NOT NULL CHECK (generation > 0),
                requested_at REAL NOT NULL,
                reason TEXT NOT NULL,
                claimed_at REAL,
                expected_run_id TEXT,
                acknowledged_at REAL,
                run_id TEXT,
                PRIMARY KEY (lineage_id, generation),
                CHECK (
                    (claimed_at IS NULL AND expected_run_id IS NULL) OR
                    (claimed_at IS NOT NULL AND expected_run_id IS NOT NULL)
                ),
                CHECK (
                    (acknowledged_at IS NULL AND run_id IS NULL) OR
                    (acknowledged_at IS NOT NULL AND run_id IS NOT NULL)
                )
            );
            """
        )
        task_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        needs_terminal_backfill = "terminal_at" not in task_columns
        if needs_terminal_backfill:
            self.connection.execute("ALTER TABLE tasks ADD COLUMN terminal_at REAL")
            self.connection.executescript(
                """
                UPDATE tasks AS current
                SET terminal_at = (
                    SELECT MIN(event_at) FROM (
                        SELECT current.completed_at AS event_at
                        UNION ALL SELECT current.integrity_breached_at
                        UNION ALL SELECT reported_at FROM worker_findings
                            WHERE lineage_id = current.lineage_id
                              AND task_id = current.task_id
                        UNION ALL SELECT recorded_at FROM incidents
                            WHERE lineage_id = current.lineage_id
                              AND task_id = current.task_id
                    )
                )
                WHERE current.terminal_at IS NULL;
                """
            )
        restart_columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(coordinator_restart_requests)"
            ).fetchall()
        }
        if "claimed_at" not in restart_columns:
            self.connection.execute(
                "ALTER TABLE coordinator_restart_requests ADD COLUMN claimed_at REAL"
            )
        if "expected_run_id" not in restart_columns:
            self.connection.execute(
                "ALTER TABLE coordinator_restart_requests ADD COLUMN expected_run_id TEXT"
            )
        incident_columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(incidents)").fetchall()
        }
        if "short_verdict" not in incident_columns:
            self.connection.execute("ALTER TABLE incidents ADD COLUMN short_verdict TEXT")
        if "long_detail" not in incident_columns:
            self.connection.execute("ALTER TABLE incidents ADD COLUMN long_detail TEXT")
        if "reviewed_at" not in incident_columns:
            self.connection.execute("ALTER TABLE incidents ADD COLUMN reviewed_at REAL")
        self.connection.execute(
            """
            UPDATE incidents
            SET short_verdict = replace(kind, '_', ' ')
            WHERE short_verdict IS NULL OR trim(short_verdict) = ''
            """
        )
        self.connection.execute(
            """
            UPDATE incidents
            SET long_detail = CASE
                WHEN reason IS NOT NULL AND trim(reason) != '' THEN reason
                WHEN kind = 'deadline_miss' THEN
                    'The immutable deadline passed without an on-time terminal result.'
                ELSE 'An integrity breach invalidated the task result.'
            END
            WHERE long_detail IS NULL OR trim(long_detail) = ''
            """
        )
        finding_columns = {
            row["name"]
            for row in self.connection.execute(
                "PRAGMA table_info(worker_findings)"
            ).fetchall()
        }
        if "short_verdict" not in finding_columns:
            self.connection.execute(
                "ALTER TABLE worker_findings ADD COLUMN short_verdict TEXT"
            )
        self.connection.execute(
            """
            UPDATE worker_findings
            SET short_verdict = replace(kind, '_', ' ')
            WHERE short_verdict IS NULL OR trim(short_verdict) = ''
            """
        )
        self.connection.commit()

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

    @staticmethod
    def _default_incident_detail(kind: str, reason: str | None) -> str:
        if reason is not None and reason.strip():
            return reason.strip()
        if kind == "deadline_miss":
            return "The immutable deadline passed without an on-time terminal result."
        return "An integrity breach invalidated the task result."

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

    def coordinator_restart_status(self, lineage_id: str) -> dict[str, Any]:
        """Bind a fresh clock if needed and return only its restart baton."""
        lineage_id = self._identity(lineage_id, "Lineage id")
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            result = {
                "lineage_id": lineage_id,
                "coordinator_restart": self._coordinator_restart_status(lineage_id),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

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

    def _terminal_window_count(self, lineage_id: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS total FROM tasks
            WHERE lineage_id = ? AND terminal_at IS NOT NULL
            """,
            (lineage_id,),
        ).fetchone()
        return int(row["total"])

    @staticmethod
    def _draw_random_cycle() -> tuple[int, str]:
        interval_width = RANDOM_INTERVAL_MAX - RANDOM_INTERVAL_MIN + 1
        interval = RANDOM_INTERVAL_MIN + secrets.randbelow(interval_width)
        lane = RANDOM_MUTATION_LANES[secrets.randbelow(len(RANDOM_MUTATION_LANES))]
        return interval, lane

    def _latest_random_cycle(self, lineage_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM random_mutation_cycles
            WHERE lineage_id = ?
            ORDER BY cycle_number DESC
            LIMIT 1
            """,
            (lineage_id,),
        ).fetchone()

    def _latest_coordinator_restart(self, lineage_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM coordinator_restart_requests
            WHERE lineage_id = ?
            ORDER BY generation DESC
            LIMIT 1
            """,
            (lineage_id,),
        ).fetchone()

    @staticmethod
    def _coordinator_restart_result(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "generation": row["generation"],
            "pending": row["acknowledged_at"] is None,
            "requested_at": row["requested_at"],
            "reason": row["reason"],
            "claimed_at": row["claimed_at"],
            "expected_run_id": row["expected_run_id"],
            "acknowledged_at": row["acknowledged_at"],
            "run_id": row["run_id"],
        }

    def _coordinator_restart_status(
        self, lineage_id: str
    ) -> dict[str, Any] | None:
        row = self._latest_coordinator_restart(lineage_id)
        return self._coordinator_restart_result(row) if row is not None else None

    def _request_coordinator_restart(
        self,
        lineage_id: str,
        reason: str,
        requested_at: float,
    ) -> tuple[sqlite3.Row, bool]:
        latest = self._latest_coordinator_restart(lineage_id)
        if latest is not None and latest["acknowledged_at"] is None:
            return latest, False
        generation = 1 if latest is None else int(latest["generation"]) + 1
        self.connection.execute(
            """
            INSERT INTO coordinator_restart_requests (
                lineage_id, generation, requested_at, reason
            ) VALUES (?, ?, ?, ?)
            """,
            (lineage_id, generation, requested_at, reason),
        )
        created = self.connection.execute(
            """
            SELECT * FROM coordinator_restart_requests
            WHERE lineage_id = ? AND generation = ?
            """,
            (lineage_id, generation),
        ).fetchone()
        if created is None:
            raise DeadlineError("Failed to persist coordinator restart request")
        return created, True

    def _ensure_random_cycle(self, lineage_id: str) -> sqlite3.Row:
        cycle = self._latest_random_cycle(lineage_id)
        if cycle is not None and cycle["resolution_evidence"] is None:
            return cycle
        completed = self._terminal_window_count(lineage_id)
        number = 1 if cycle is None else int(cycle["cycle_number"]) + 1
        cycle_start = 0 if cycle is None else completed
        interval, lane = self._draw_random_cycle()
        self.connection.execute(
            """
            INSERT INTO random_mutation_cycles (
                lineage_id, cycle_number, interval_windows,
                due_after_terminal_windows, selected_lane
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (lineage_id, number, interval, cycle_start + interval, lane),
        )
        cycle = self._latest_random_cycle(lineage_id)
        if cycle is None:
            raise DeadlineError("Failed to persist random mutation cycle")
        if completed >= cycle["due_after_terminal_windows"]:
            boundary = self.connection.execute(
                """
                SELECT task_id FROM tasks
                WHERE lineage_id = ? AND terminal_at IS NOT NULL
                ORDER BY terminal_at, task_id
                LIMIT 1 OFFSET ?
                """,
                (lineage_id, cycle["due_after_terminal_windows"] - 1),
            ).fetchone()
            self.connection.execute(
                """
                UPDATE random_mutation_cycles SET due_task_id = ?
                WHERE lineage_id = ? AND cycle_number = ?
                """,
                (boundary["task_id"], lineage_id, cycle["cycle_number"]),
            )
            cycle = self._latest_random_cycle(lineage_id)
        return cycle

    def _random_cycle_result(self, row: sqlite3.Row) -> dict[str, Any]:
        completed = self._terminal_window_count(row["lineage_id"])
        due = row["due_task_id"] is not None and row["resolution_evidence"] is None
        return {
            "cycle_number": row["cycle_number"],
            "interval_windows": row["interval_windows"],
            "due_after_terminal_windows": row["due_after_terminal_windows"],
            "selected_lane": row["selected_lane"],
            "completed_terminal_windows": completed,
            "due": due,
            "due_task_id": row["due_task_id"],
        }

    def _random_mutation_status(self, lineage_id: str) -> dict[str, Any]:
        return self._random_cycle_result(self._ensure_random_cycle(lineage_id))

    def _record_terminal_window(
        self,
        task: sqlite3.Row,
        terminal_at: float,
    ) -> None:
        if self._task(task["lineage_id"], task["task_id"])["terminal_at"] is not None:
            return
        cycle = self._ensure_random_cycle(task["lineage_id"])
        self.connection.execute(
            """
            UPDATE tasks SET terminal_at = ?
            WHERE lineage_id = ? AND task_id = ? AND terminal_at IS NULL
            """,
            (
                terminal_at,
                task["lineage_id"],
                task["task_id"],
            ),
        )
        completed = self._terminal_window_count(task["lineage_id"])
        if (
            cycle["due_task_id"] is None
            and completed >= cycle["due_after_terminal_windows"]
        ):
            self.connection.execute(
                """
                UPDATE random_mutation_cycles
                SET due_task_id = ?
                WHERE lineage_id = ? AND cycle_number = ?
                """,
                (
                    task["task_id"],
                    task["lineage_id"],
                    cycle["cycle_number"],
                ),
            )

    @staticmethod
    def _incident_result(row: sqlite3.Row, recorded: bool) -> dict[str, Any]:
        threshold = row["cadence_threshold"]
        return {
            "lineage_id": row["lineage_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "recorded": recorded,
            "recorded_at": row["recorded_at"],
            "short_verdict": row["short_verdict"],
            "reviewed_at": row["reviewed_at"],
            "reason": row["reason"],
            "long_detail": row["long_detail"],
            "units": row["units"],
            "cumulative_before": row["cumulative_before"],
            "cumulative_after": row["cumulative_after"],
            "independent_review_required": row["reviewed_at"] is None,
            "cadence_crossed": threshold is not None,
            "cadence_threshold": threshold,
        }

    @staticmethod
    def _finding_result(row: sqlite3.Row, recorded: bool) -> dict[str, Any]:
        return {
            "lineage_id": row["lineage_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "reported_at": row["reported_at"],
            "short_verdict": row["short_verdict"],
            "evidence": row["evidence"],
            "recorded": recorded,
        }

    def _worker_finding(
        self, lineage_id: str, task_id: str
    ) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM worker_findings
            WHERE lineage_id = ? AND task_id = ?
            """,
            (lineage_id, task_id),
        ).fetchone()

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
        short_verdict = kind.replace("_", " ")
        long_detail = self._default_incident_detail(kind, reason)
        cursor = self.connection.execute(
            """
            INSERT INTO incidents (
                lineage_id, task_id, kind, recorded_at, reason,
                short_verdict, long_detail, units,
                cumulative_before, cumulative_after, cadence_threshold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_id,
                task_id,
                kind,
                recorded_at,
                reason,
                short_verdict,
                long_detail,
                units,
                prior,
                new,
                threshold,
            ),
        )
        row = self.connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (cursor.lastrowid,)
        ).fetchone()
        return self._incident_result(row, recorded=True)

    def _record_miss_if_due(
        self, task: sqlite3.Row, now: float, *, completion_invalid: bool = False
    ) -> dict[str, Any] | None:
        completed_at = task["completed_at"]
        finding = self._worker_finding(task["lineage_id"], task["task_id"])
        finding_at = finding["reported_at"] if finding is not None else None
        terminal_on_time = (
            completed_at is not None and completed_at < task["deadline_at"]
        ) or (
            finding_at is not None and finding_at < task["deadline_at"]
        )
        missed = now >= task["deadline_at"] and (
            completion_invalid
            or task["integrity_breached_at"] is not None
            or not terminal_on_time
        )
        if not missed:
            return None
        incident = self._record_incident(
            task["lineage_id"], task["task_id"], "deadline_miss", 1, now
        )
        self._record_terminal_window(task, now)
        return incident

    def _status(self, lineage_id: str, task_id: str, now: float) -> dict[str, Any]:
        task = self._task(lineage_id, task_id)
        finding = self._worker_finding(lineage_id, task_id)
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
            task["completed_at"] is not None
            and task["integrity_breached_at"] is None
            and finding is None
        )
        if task["integrity_breached_at"] is not None:
            state = "integrity_breach"
        elif completion_accepted:
            state = "accepted"
        elif finding is not None:
            state = "worker_finding"
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
            "finding_reported": finding is not None,
            "worker_finding": (
                self._finding_result(finding, recorded=False)
                if finding is not None
                else None
            ),
            "deadline_missed": "deadline_miss" in kinds,
            "integrity_breached": "integrity_breach" in kinds,
            "integrity_reason": task["integrity_reason"],
            "cumulative_miss_units": self._cumulative_units(lineage_id),
            "incidents": [self._incident_result(row, recorded=False) for row in incidents],
        }

    @staticmethod
    def _compact_task_result(status: dict[str, Any]) -> dict[str, Any]:
        finding = status["worker_finding"]
        incidents_by_kind = {
            incident["kind"]: incident for incident in status["incidents"]
        }
        if status["state"] == "integrity_breach":
            current_short_verdict = incidents_by_kind["integrity_breach"][
                "short_verdict"
            ]
        elif finding is not None:
            current_short_verdict = finding["short_verdict"]
        else:
            current_incident = next(
                (
                    incidents_by_kind[kind]
                    for kind in ("integrity_breach", "deadline_miss")
                    if kind in incidents_by_kind
                ),
                None,
            )
            current_short_verdict = (
                current_incident["short_verdict"]
                if current_incident is not None
                else None
            )
        return {
            "task_id": status["task_id"],
            "claim_id": status["claim_id"],
            "state": status["state"],
            "deadline_at": status["deadline_at"],
            "current_short_verdict": current_short_verdict,
        }

    def _pending_incident_reviews(self, lineage_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT incidents.task_id, tasks.claim_id, incidents.kind,
                   incidents.recorded_at
            FROM incidents
            JOIN tasks USING (lineage_id, task_id)
            WHERE incidents.lineage_id = ? AND incidents.reviewed_at IS NULL
            ORDER BY incidents.recorded_at, incidents.incident_id
            """,
            (lineage_id,),
        ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "claim_id": row["claim_id"],
                "kind": row["kind"],
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def _recent_failure_verdicts(self, lineage_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT task_id, claim_id, kind, recorded_at, short_verdict
            FROM (
                SELECT incidents.task_id, tasks.claim_id, incidents.kind,
                       incidents.recorded_at, incidents.short_verdict,
                       0 AS source_order
                FROM incidents
                JOIN tasks USING (lineage_id, task_id)
                WHERE incidents.lineage_id = ?
                  AND incidents.reviewed_at IS NOT NULL
                UNION ALL
                SELECT worker_findings.task_id, tasks.claim_id,
                       worker_findings.kind, worker_findings.reported_at,
                       worker_findings.short_verdict, 1 AS source_order
                FROM worker_findings
                JOIN tasks USING (lineage_id, task_id)
                WHERE worker_findings.lineage_id = ?
            )
            ORDER BY recorded_at DESC, task_id DESC, source_order DESC, kind DESC
            LIMIT ?
            """,
            (lineage_id, lineage_id, RECENT_FAILURE_VERDICT_LIMIT),
        ).fetchall()
        return [
            {
                "task_id": row["task_id"],
                "claim_id": row["claim_id"],
                "kind": row["kind"],
                "recorded_at": row["recorded_at"],
                "short_verdict": row["short_verdict"],
            }
            for row in rows
        ]

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
            self._ensure_random_cycle(lineage_id)
            existing = self.connection.execute(
                """
                SELECT * FROM tasks
                WHERE lineage_id = ? AND task_id = ?
                """,
                (lineage_id, task_id),
            ).fetchone()
            random_mutation = self._random_mutation_status(lineage_id)
            coordinator_restart = self._coordinator_restart_status(lineage_id)
            if (
                existing is None
                and coordinator_restart is not None
                and coordinator_restart["pending"]
            ):
                raise DeadlineError(
                    "Coordinator restart generation "
                    f"{coordinator_restart['generation']} is pending; "
                    "acknowledge it before dispatching a new task"
                )
            if existing is None and random_mutation["due"]:
                raise DeadlineError(
                    "Random improvement review is due; resolve it before dispatching a new task"
                )
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
            result["random_mutation"] = self._random_mutation_status(lineage_id)
            result["coordinator_restart"] = self._coordinator_restart_status(
                lineage_id
            )
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
            result["random_mutation"] = self._random_mutation_status(lineage_id)
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
            task_ids = self.connection.execute(
                """
                SELECT current.task_id
                FROM tasks AS current
                WHERE current.lineage_id = ?
                  AND (
                    current.completed_at IS NULL
                    OR current.integrity_breached_at IS NOT NULL
                  )
                  AND (
                    current.terminal_at IS NULL
                    OR NOT EXISTS (
                      SELECT 1
                      FROM tasks AS newer
                      WHERE newer.lineage_id = current.lineage_id
                        AND newer.claim_id = current.claim_id
                        AND (
                          newer.started_at > current.started_at
                          OR (
                            newer.started_at = current.started_at
                            AND newer.task_id > current.task_id
                          )
                        )
                    )
                )
                ORDER BY current.started_at, current.task_id
                """,
                (lineage_id,),
            ).fetchall()
            for row in task_ids:
                task = self._task(lineage_id, row["task_id"])
                self._record_miss_if_due(task, checked_at)
            tasks = [
                self._compact_task_result(
                    self._status(lineage_id, row["task_id"], checked_at)
                )
                for row in task_ids
            ]
            result = {
                "lineage_id": lineage_id,
                "checked_at": checked_at,
                "cumulative_miss_units": self._cumulative_units(lineage_id),
                "random_mutation": self._random_mutation_status(lineage_id),
                "coordinator_restart": self._coordinator_restart_status(lineage_id),
                "tasks": tasks,
                "pending_incident_reviews": self._pending_incident_reviews(
                    lineage_id
                ),
                "recent_failure_verdicts": self._recent_failure_verdicts(lineage_id),
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
                "random_mutation": self._random_mutation_status(lineage_id),
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
            if self._worker_finding(lineage_id, task_id) is not None:
                raise DeadlineError(
                    "A worker finding terminates this task without accepting completion"
                )
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
                self._record_terminal_window(task, completed_at)
            result = self._status(lineage_id, task_id, completed_at)
            result["random_mutation"] = self._random_mutation_status(lineage_id)
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def report_worker_finding(
        self,
        lineage_id: str,
        task_id: str,
        kind: str,
        evidence: str,
        *,
        short_verdict: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        kind = self._identity(kind, "Worker finding kind")
        if kind not in {"blocker", "unexpected"}:
            raise DeadlineError("Worker finding kind must be blocker or unexpected")
        evidence = self._nonempty_text(evidence, "Worker finding evidence")
        if short_verdict is not None:
            short_verdict = self._nonempty_text(
                short_verdict, "Worker finding short verdict"
            )
        reported_at = self._now(now)
        self._begin()
        try:
            task = self._task(lineage_id, task_id)
            if task["integrity_breached_at"] is not None:
                raise DeadlineError(
                    "An integrity breach prevents a worker finding from being recorded"
                )
            if task["completed_at"] is not None:
                raise DeadlineError(
                    "An accepted task cannot later report a worker finding"
                )

            existing = self._worker_finding(lineage_id, task_id)
            if short_verdict is None:
                short_verdict = (
                    existing["short_verdict"]
                    if existing is not None
                    else kind.replace("_", " ")
                )
            if existing is not None and (
                existing["kind"] != kind
                or existing["short_verdict"] != short_verdict
                or existing["evidence"] != evidence
            ):
                raise DeadlineError("A worker finding is immutable once recorded")

            deadline_incident = self._record_miss_if_due(task, reported_at)
            if existing is None:
                self.connection.execute(
                    """
                    INSERT INTO worker_findings (
                        lineage_id, task_id, kind, reported_at,
                        short_verdict, evidence
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lineage_id,
                        task_id,
                        kind,
                        reported_at,
                        short_verdict,
                        evidence,
                    ),
                )
                finding = self._worker_finding(lineage_id, task_id)
                recorded = True
            else:
                finding = existing
                recorded = False

            self._record_terminal_window(task, reported_at)

            result = {
                "deadline_incident": deadline_incident,
                "finding": self._finding_result(finding, recorded=recorded),
                "status": self._status(lineage_id, task_id, reported_at),
                "random_mutation": self._random_mutation_status(lineage_id),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def diagnose_incident(
        self,
        lineage_id: str,
        task_id: str,
        kind: str,
        short_verdict: str,
        diagnosis: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Attach one immutable independent review to an exact incident."""
        lineage_id = self._identity(lineage_id, "Lineage id")
        task_id = self._identity(task_id, "Task id")
        kind = self._identity(kind, "Incident kind")
        if kind not in INCIDENT_KINDS:
            raise DeadlineError(
                "Incident kind must be deadline_miss or integrity_breach"
            )
        short_verdict = self._nonempty_text(short_verdict, "Short verdict")
        diagnosis = self._nonempty_text(diagnosis, "Long diagnosis")
        reviewed_at = self._now(now)
        self._begin()
        try:
            self._task(lineage_id, task_id)
            incident = self.connection.execute(
                """
                SELECT * FROM incidents
                WHERE lineage_id = ? AND task_id = ? AND kind = ?
                """,
                (lineage_id, task_id, kind),
            ).fetchone()
            if incident is None:
                raise DeadlineError(
                    f"Unknown incident: {lineage_id}/{task_id}/{kind}"
                )
            if incident["reviewed_at"] is None:
                self.connection.execute(
                    """
                    UPDATE incidents
                    SET short_verdict = ?, long_detail = ?, reviewed_at = ?
                    WHERE lineage_id = ? AND task_id = ? AND kind = ?
                    """,
                    (
                        short_verdict,
                        diagnosis,
                        reviewed_at,
                        lineage_id,
                        task_id,
                        kind,
                    ),
                )
                recorded = True
            elif (
                incident["short_verdict"] == short_verdict
                and incident["long_detail"] == diagnosis
            ):
                recorded = False
            else:
                raise DeadlineError(
                    "An incident diagnosis is immutable once recorded"
                )
            diagnosed = self.connection.execute(
                """
                SELECT * FROM incidents
                WHERE lineage_id = ? AND task_id = ? AND kind = ?
                """,
                (lineage_id, task_id, kind),
            ).fetchone()
            if diagnosed is None:
                raise DeadlineError("Failed to read the diagnosed incident")
            result = {
                "recorded": recorded,
                "incident": self._incident_result(diagnosed, recorded=False),
            }
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
            self._record_terminal_window(task, recorded_at)
            result = {
                "deadline_incident": deadline_incident,
                "incident": incident,
                "status": self._status(lineage_id, task_id, recorded_at),
                "random_mutation": self._random_mutation_status(lineage_id),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def request_coordinator_restart(
        self,
        lineage_id: str,
        reason: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        reason = self._nonempty_text(reason, "Coordinator restart reason")
        requested_at = self._now(now)
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            request, created = self._request_coordinator_restart(
                lineage_id, reason, requested_at
            )
            result = {
                "created": created,
                "coordinator_restart": self._coordinator_restart_result(request),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def claim_coordinator_restart(
        self,
        lineage_id: str,
        generation: int,
        run_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Bind a pending generation to the supervisor-issued successor id."""
        lineage_id = self._identity(lineage_id, "Lineage id")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        if generation <= 0:
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        run_id = self._nonempty_text(run_id, "Coordinator run id")
        claimed_at = self._now(now)
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            request = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if request is None:
                raise DeadlineError(
                    f"Unknown coordinator restart generation: {lineage_id}/{generation}"
                )
            if request["acknowledged_at"] is not None:
                raise DeadlineError("Acknowledged coordinator restart cannot be claimed")
            if request["expected_run_id"] is None:
                self.connection.execute(
                    """
                    UPDATE coordinator_restart_requests
                    SET claimed_at = ?, expected_run_id = ?
                    WHERE lineage_id = ? AND generation = ?
                    """,
                    (claimed_at, run_id, lineage_id, generation),
                )
                recorded = True
            elif request["expected_run_id"] == run_id:
                recorded = False
            else:
                raise DeadlineError(
                    "Coordinator restart is already claimed by a different run"
                )
            claimed = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if claimed is None:
                raise DeadlineError("Failed to read coordinator restart claim")
            result = {
                "recorded": recorded,
                "coordinator_restart": self._coordinator_restart_result(claimed),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def release_coordinator_restart_claim(
        self,
        lineage_id: str,
        generation: int,
        run_id: str,
    ) -> dict[str, Any]:
        """Release one unacknowledged claim after its runner is confirmed gone."""
        lineage_id = self._identity(lineage_id, "Lineage id")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        if generation <= 0:
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        run_id = self._nonempty_text(run_id, "Coordinator run id")
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            request = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if request is None:
                raise DeadlineError(
                    f"Unknown coordinator restart generation: {lineage_id}/{generation}"
                )
            if request["acknowledged_at"] is not None:
                raise DeadlineError("Acknowledged coordinator restart claim cannot be released")
            if request["expected_run_id"] != run_id:
                raise DeadlineError("Coordinator restart claim does not match that run")
            self.connection.execute(
                """
                UPDATE coordinator_restart_requests
                SET claimed_at = NULL, expected_run_id = NULL
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            )
            released = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if released is None:
                raise DeadlineError("Failed to read released coordinator restart claim")
            self.connection.commit()
            return {
                "released": True,
                "coordinator_restart": self._coordinator_restart_result(released),
            }
        except Exception:
            self.connection.rollback()
            raise

    def acknowledge_coordinator_restart(
        self,
        lineage_id: str,
        generation: int,
        run_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        if generation <= 0:
            raise DeadlineError("Coordinator restart generation must be a positive integer")
        run_id = self._nonempty_text(run_id, "Coordinator run id")
        acknowledged_at = self._now(now)
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            request = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if request is None:
                raise DeadlineError(
                    f"Unknown coordinator restart generation: {lineage_id}/{generation}"
                )
            if request["expected_run_id"] is None:
                raise DeadlineError(
                    "Coordinator restart must be claimed by its supervisor before acknowledgement"
                )
            if request["expected_run_id"] != run_id:
                raise DeadlineError(
                    "Coordinator restart acknowledgement does not match its claimed run"
                )
            if request["acknowledged_at"] is None:
                self.connection.execute(
                    """
                    UPDATE coordinator_restart_requests
                    SET acknowledged_at = ?, run_id = ?
                    WHERE lineage_id = ? AND generation = ?
                    """,
                    (acknowledged_at, run_id, lineage_id, generation),
                )
                recorded = True
            elif request["run_id"] == run_id:
                recorded = False
            else:
                raise DeadlineError(
                    "Coordinator restart acknowledgement is immutable once recorded"
                )
            acknowledged = self.connection.execute(
                """
                SELECT * FROM coordinator_restart_requests
                WHERE lineage_id = ? AND generation = ?
                """,
                (lineage_id, generation),
            ).fetchone()
            if acknowledged is None:
                raise DeadlineError("Failed to read coordinator restart acknowledgement")
            result = {
                "recorded": recorded,
                "coordinator_restart": self._coordinator_restart_result(acknowledged),
            }
            self.connection.commit()
            return result
        except Exception:
            self.connection.rollback()
            raise

    def resolve_random_mutation(
        self,
        lineage_id: str,
        cycle_number: int,
        evidence: str,
    ) -> dict[str, Any]:
        lineage_id = self._identity(lineage_id, "Lineage id")
        if isinstance(cycle_number, bool) or not isinstance(cycle_number, int):
            raise DeadlineError("Cycle number must be a positive integer")
        if cycle_number <= 0:
            raise DeadlineError("Cycle number must be a positive integer")
        evidence = self._nonempty_text(evidence, "Random review evidence")
        self._begin()
        try:
            self._bind_lineage(lineage_id)
            cycle = self.connection.execute(
                """
                SELECT * FROM random_mutation_cycles
                WHERE lineage_id = ? AND cycle_number = ?
                """,
                (lineage_id, cycle_number),
            ).fetchone()
            if cycle is None:
                raise DeadlineError(
                    f"Unknown random mutation cycle: {lineage_id}/{cycle_number}"
                )
            if cycle["due_task_id"] is None:
                raise DeadlineError("Random mutation cycle is not due")
            if cycle["resolution_evidence"] is None:
                self.connection.execute(
                    """
                    UPDATE random_mutation_cycles
                    SET resolution_evidence = ?
                    WHERE lineage_id = ? AND cycle_number = ?
                    """,
                    (
                        evidence,
                        lineage_id,
                        cycle_number,
                    ),
                )
                recorded = True
                restart, _ = self._request_coordinator_restart(
                    lineage_id,
                    f"random mutation cycle {cycle_number} resolved",
                    self._now(None),
                )
            else:
                if cycle["resolution_evidence"] != evidence:
                    raise DeadlineError(
                        "Random mutation resolution is immutable once recorded"
                    )
                recorded = False
                restart = self._latest_coordinator_restart(lineage_id)

            next_cycle = self._ensure_random_cycle(lineage_id)
            result = {
                "recorded": recorded,
                "cycle_number": cycle_number,
                "selected_lane": cycle["selected_lane"],
                "resolution_evidence": evidence,
                "random_mutation": self._random_cycle_result(next_cycle),
                "coordinator_restart": (
                    self._coordinator_restart_result(restart)
                    if restart is not None
                    else None
                ),
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

    status = commands.add_parser(
        "status",
        help="Read one exact task with long evidence and record a due miss",
    )
    add_task_identity_flags(status)

    expire = commands.add_parser("expire", help="Record a due miss once")
    add_task_identity_flags(expire)

    complete = commands.add_parser("complete", help="Accept evidenced completion")
    add_task_identity_flags(complete)
    complete.add_argument("--evidence", required=True)

    finding = commands.add_parser(
        "finding", help="Record one terminal worker blocker or unexpected result"
    )
    add_task_identity_flags(finding)
    finding.add_argument("--kind", choices=("blocker", "unexpected"), required=True)
    finding.add_argument("--short-verdict")
    finding.add_argument("--evidence", required=True)

    diagnose = commands.add_parser(
        "diagnose",
        help="Attach one immutable short verdict and long diagnosis to an incident",
    )
    add_task_identity_flags(diagnose)
    diagnose.add_argument("--kind", choices=INCIDENT_KINDS, required=True)
    diagnose.add_argument("--short-verdict", required=True)
    diagnose.add_argument("--diagnosis", required=True)

    breach = commands.add_parser("breach", help="Record an integrity breach once")
    add_task_identity_flags(breach)
    breach.add_argument("--reason", required=True)

    watch = commands.add_parser("watch", help="Wait for and expire one task")
    add_task_identity_flags(watch)

    list_command = commands.add_parser(
        "list", help="Show compact bound-lineage startup state"
    )
    list_command.add_argument("--state", dest="command_state")

    resolve_random = commands.add_parser(
        "resolve-random-mutation",
        help="Record one guarded random improvement review",
    )
    resolve_random.add_argument("--state", dest="command_state")
    resolve_random.add_argument("--lineage", required=True)
    resolve_random.add_argument("--cycle", required=True, type=int)
    resolve_random.add_argument("--evidence", required=True)

    request_restart = commands.add_parser(
        "request-restart",
        help="Request one durable fresh-coordinator handover",
    )
    request_restart.add_argument("--state", dest="command_state")
    request_restart.add_argument("--lineage", required=True)
    request_restart.add_argument("--reason", required=True)

    acknowledge_restart = commands.add_parser(
        "ack-restart",
        help="Acknowledge one live fresh coordinator",
    )
    acknowledge_restart.add_argument("--state", dest="command_state")
    acknowledge_restart.add_argument("--lineage", required=True)
    acknowledge_restart.add_argument("--generation", required=True, type=int)
    acknowledge_restart.add_argument("--run-id", required=True)

    release_restart = commands.add_parser(
        "release-restart-claim",
        help="Release one dead unacknowledged successor claim",
    )
    release_restart.add_argument("--state", dest="command_state")
    release_restart.add_argument("--lineage", required=True)
    release_restart.add_argument("--generation", required=True, type=int)
    release_restart.add_argument("--run-id", required=True)
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
                elif arguments.command == "finding":
                    result = harness.report_worker_finding(
                        arguments.lineage,
                        arguments.task,
                        arguments.kind,
                        arguments.evidence,
                        short_verdict=arguments.short_verdict,
                    )
                elif arguments.command == "diagnose":
                    result = harness.diagnose_incident(
                        arguments.lineage,
                        arguments.task,
                        arguments.kind,
                        arguments.short_verdict,
                        arguments.diagnosis,
                    )
                elif arguments.command == "resolve-random-mutation":
                    result = harness.resolve_random_mutation(
                        arguments.lineage,
                        arguments.cycle,
                        arguments.evidence,
                    )
                elif arguments.command == "request-restart":
                    result = harness.request_coordinator_restart(
                        arguments.lineage,
                        arguments.reason,
                    )
                elif arguments.command == "ack-restart":
                    result = harness.acknowledge_coordinator_restart(
                        arguments.lineage,
                        arguments.generation,
                        arguments.run_id,
                    )
                elif arguments.command == "release-restart-claim":
                    result = harness.release_coordinator_restart_claim(
                        arguments.lineage,
                        arguments.generation,
                        arguments.run_id,
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
