#!/usr/bin/env python3
"""Persistent, tamper-evident deadline clock for DE67 ledger windows."""

from __future__ import annotations

import argparse
import hashlib
import json
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


VERSION = "0.1.0"
ZERO_HASH = "0" * 64
WINDOW_CEILING = 10
COORDINATOR_REVIEW_THRESHOLD = 3
EVENT_KINDS = {
    "progress",
    "task_accepted",
    "task_failed",
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


def default_install_root() -> Path:
    codex_root = os.environ.get("CODEX_HOME")
    base = Path(codex_root) if codex_root else Path.home() / ".codex"
    return base / "de67-lab"


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
        "depends_on",
    }
    by_id: dict[str, dict[str, Any]] = {}
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
        for field in ("intended_task", "pass_test", "worker_profile"):
            if not isinstance(task[field], str) or not task[field].strip():
                raise HarnessError(f"{task_id}.{field} must be a non-empty string")
        estimate = task["estimate_seconds"]
        if isinstance(estimate, bool) or not isinstance(estimate, (int, float)) or estimate <= 0:
            raise HarnessError(f"{task_id}.estimate_seconds must be positive")
        if not isinstance(task["depends_on"], list) or not all(
            isinstance(dep, str) for dep in task["depends_on"]
        ):
            raise HarnessError(f"{task_id}.depends_on must be a list of task ids")
        by_id[task_id] = task

    for task_id, task in by_id.items():
        unknown = sorted(set(task["depends_on"]) - set(by_id))
        if unknown:
            raise HarnessError(f"{task_id} has unknown dependencies: {', '.join(unknown)}")

    reserve = ledger.get("reserve_seconds", 0)
    if isinstance(reserve, bool) or not isinstance(reserve, (int, float)) or reserve < 0:
        raise HarnessError("reserve_seconds must be non-negative")

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
        "duration_seconds": duration,
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
    return connection


def bind_lineage(
    connection: sqlite3.Connection,
    *,
    lineage_id: str,
    fs_root_hash: str,
    fs_root: Path,
    skill_root: Path,
    authority: dict[str, str],
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
    }
    if row is None:
        connection.execute(
            """
            INSERT INTO lineages
              (lineage_id, fs_root_hash, fs_root_path, frozen_hash, harness_hash,
               guard_hash, policy_hash, kernel_hash, skill_root, created_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    previous = connection.execute(
        """
        SELECT event_hash FROM events
        WHERE lineage_id=? AND run_id=? AND window_id=?
        ORDER BY sequence DESC LIMIT 1
        """,
        window_key(lineage_id, run_id, window_id),
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else ZERO_HASH
    record = {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "at_utc": iso(at or utc_now()),
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
            now=started,
        )
    except Exception:
        connection.close()
        raise
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
        "timing": timing,
        "deadline_utc": iso(deadline),
        "harness_deployed": deployed,
        "frozen_authority_hash": authority["frozen_hash"],
    }
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
        return {"expired": True, "new": False, "miss_count": lineage_miss_count(connection, lineage_id)}
    completed = [row for row in rows if row["kind"] == "completed"]
    if completed and parse_iso(completed[0]["at_utc"]) <= deadline:
        return {"expired": False, "new": False, "completed": True}
    if current < deadline:
        return {
            "expired": False,
            "new": False,
            "remaining_seconds": (deadline - current).total_seconds(),
        }

    elapsed = (current - parse_iso(window["started_utc"])).total_seconds()
    payload = {
        "deadline_utc": window["deadline_utc"],
        "observed_utc": iso(current),
        "elapsed_seconds": elapsed,
        "ledger_hash": window["ledger_hash"],
    }
    append_event(connection, lineage_id, run_id, window_id, "deadline_missed", payload, current)
    miss_count = lineage_miss_count(connection, lineage_id)
    review_required = miss_count >= COORDINATOR_REVIEW_THRESHOLD
    if review_required:
        append_event(
            connection,
            lineage_id,
            run_id,
            window_id,
            "coordinator_review_required",
            {
                "distinct_failed_windows": miss_count,
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
    result = {
        "lineage_id": lineage_id,
        "run_id": run_id,
        "window_id": window_id,
        "started_utc": window["started_utc"],
        "deadline_utc": window["deadline_utc"],
        "expiry": expiry,
        "event_kinds": [row["kind"] for row in rows],
        "chain_valid": verify_chain(rows),
        "lineage_miss_count": lineage_miss_count(connection, lineage_id),
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


def validate_terminal_task_event(
    connection: sqlite3.Connection,
    lineage_id: str,
    run_id: str,
    window_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
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
    if not isinstance(payload.get("worker_identity"), str) or not payload["worker_identity"].strip():
        raise HarnessError("Terminal task event requires an observed worker identity")
    if payload.get("test_completed") is not True:
        raise HarnessError("Terminal task event requires a completed test")
    expected_result = "passed" if kind == "task_accepted" else "failed"
    if payload.get("test_result") != expected_result:
        raise HarnessError(f"{kind} requires test_result={expected_result}")
    verify_file_hash(payload.get("receipt_path"), payload.get("receipt_sha256"), "Receipt")
    artifacts = payload.get("artifact_hashes")
    if not isinstance(artifacts, dict) or not artifacts:
        raise HarnessError("Terminal task event requires artifact hashes")
    for artifact_path, artifact_hash in artifacts.items():
        verify_file_hash(artifact_path, artifact_hash, "Artifact")

    for row in events_for(connection, lineage_id, run_id, window_id):
        if row["kind"] not in {"task_accepted", "task_failed"}:
            continue
        prior = json.loads(row["payload_json"])
        if prior.get("permit_event_hash") == permit_hash:
            raise HarnessError("Dispatch permit was already consumed by a terminal task event")


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
    required_slots = {task["id"] for task in ledger["tasks"]}
    accepted: dict[str, dict[str, Any]] = {}
    failed_slots: set[str] = set()
    completed_payload: dict[str, Any] | None = None
    completed_at: datetime | None = None
    for row in rows:
        payload = json.loads(row["payload_json"])
        if row["kind"] == "task_accepted" and isinstance(payload.get("slot_id"), str):
            accepted[payload["slot_id"]] = payload
        elif row["kind"] == "task_failed" and isinstance(payload.get("slot_id"), str):
            failed_slots.add(payload["slot_id"])
        elif row["kind"] == "completed":
            completed_payload = payload
            completed_at = parse_iso(row["at_utc"])

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
    evidence_valid = (
        verify_chain(rows)
        and len(accepted_payloads) == len(required_slots)
        and permits_valid
        and files_valid
    )
    acceptance_passed = set(accepted) == required_slots and completed_payload is not None
    quality = {
        "worker_executed": worker_executed,
        "test_completed": test_completed,
        "acceptance_passed": acceptance_passed,
        "evidence_valid": evidence_valid,
    }
    deadline_misses = sum(row["kind"] == "deadline_missed" for row in rows)
    terminal_at = completed_at or parse_iso(rows[-1]["at_utc"])
    elapsed = (terminal_at - parse_iso(window["started_utc"])).total_seconds()
    tokens = completed_payload.get("tokens") if completed_payload else None
    if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, (int, float))):
        connection.close()
        raise HarnessError("Completed event tokens must be numeric or null")

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
            "definition_hash": window["ledger_hash"],
            "fs_hash": lineage["fs_root_hash"],
            "comparison_epoch": lineage["frozen_hash"],
            "skill_hash": window["skill_hash"],
            "event_chain_hash": rows[-1]["event_hash"],
            "state_db": str(db_path.resolve()),
        },
        "quality": quality,
        "deadline": {"misses": deadline_misses, "elapsed_seconds": elapsed},
        "usage": {"tokens": tokens},
        "skill": {"bytes": skill_bytes},
        "target_failure_resolved": all(quality.values()) and deadline_misses == 0,
        "new_failure_ids": unresolved_failures,
    }
    connection.close()
    return result


def revise_ledger(
    *,
    db_path: Path,
    lineage_id: str,
    run_id: str,
    window_id: str,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    timing = validate_ledger(ledger)
    connection = connect(db_path)
    window = get_window(connection, lineage_id, run_id, window_id)
    payload = {
        "ledger_hash": digest_json(ledger),
        "ledger": ledger,
        "timing_if_new_window": timing,
        "sealed_deadline_utc": window["deadline_utc"],
        "deadline_changed": False,
    }
    append_event(connection, lineage_id, run_id, window_id, "ledger_revised", payload)
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
        if kind in {"task_accepted", "task_failed"}:
            validate_terminal_task_event(
                connection, lineage_id, run_id, window_id, kind, payload
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
    kinds = [row["kind"] for row in rows]
    if expiry.get("expired") or "completed" in kinds or "coordinator_review_required" in kinds:
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
    event_hash = append_event(
        connection,
        lineage_id,
        run_id,
        window_id,
        "dispatch_permitted",
        {
            "slot_id": slot_id,
            "worker_profile": worker_profile,
            "ledger_hash": digest_json(ledger),
        },
        now,
    )
    connection.close()
    return {"permitted": True, "permit_event_hash": event_hash, "deadline": expiry}


def watch(
    *, db_path: Path, install_root: Path, lineage_id: str, run_id: str, window_id: str
) -> None:
    connection = connect(db_path)
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
        connection.close()
        if result.get("expired") or "completed" in [row["kind"] for row in rows]:
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
    permit.add_argument("--install-root", type=Path, default=default_install_root())

    export = subparsers.add_parser("export-benchmark", help="Derive a benchmark receipt from events")
    common_identity(export)
    export.add_argument("--install-root", type=Path, default=default_install_root())

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
            )
        elif arguments.command == "export-benchmark":
            result = export_benchmark(
                db_path=resolve_db(arguments),
                lineage_id=arguments.lineage_id,
                run_id=arguments.run_id,
                window_id=arguments.window_id,
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
