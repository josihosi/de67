#!/usr/bin/env python3
"""Run one auditable DE-67 coordinator through the local Codex CLI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


class RunnerError(RuntimeError):
    """Raised when the local Codex runner cannot start safely."""


class CoordinatorLoopGuard:
    """Reject a coordinator wait while a durable task has no roster handoff."""

    def __init__(
        self,
        *,
        initial_unbound_tasks: Sequence[str] = (),
        roster_resolver: Callable[[str, float, str | None, frozenset[str]], str | None]
        | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._unbound = {
            task_id: clock() for task_id in dict.fromkeys(initial_unbound_tasks)
        }
        self._task_workers: dict[str, str] = {}
        self._parent_thread_id: str | None = None
        self._roster_resolver = roster_resolver

    @property
    def unbound_tasks(self) -> tuple[str, ...]:
        return tuple(self._unbound)

    @staticmethod
    def _command_result(item: dict[str, object]) -> dict[str, object] | None:
        if item.get("type") != "command_execution" or item.get("status") != "completed":
            return None
        if item.get("exit_code") not in (0, None):
            return None
        output = item.get("aggregated_output")
        if not isinstance(output, str):
            return None
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            return None
        return result if isinstance(result, dict) else None

    def observe(self, event: dict[str, object]) -> None:
        item = event.get("item")
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                self._parent_thread_id = thread_id
            return
        if not isinstance(item, dict):
            return

        result = self._command_result(item)
        if result is not None:
            task_id = result.get("task_id")
            if isinstance(task_id, str) and task_id:
                if result.get("attempt_created") is True and result.get("state") == "running":
                    if task_id not in self._unbound and task_id not in self._task_workers:
                        self._unbound[task_id] = self._clock()
                if result.get("attempt_completed") is True or result.get("state") in {
                    "completed", "finding", "abandoned"
                }:
                    if task_id in self._unbound:
                        del self._unbound[task_id]
                    self._task_workers.pop(task_id, None)

        if item.get("type") != "collab_tool_call":
            return
        tool = item.get("tool")
        receivers = item.get("receiver_thread_ids")
        worker_ids = [value for value in receivers or [] if isinstance(value, str) and value]
        if (
            tool in {"spawn_agent", "followup_task"}
            and event.get("type") == "item.completed"
            and item.get("status") == "completed"
            and worker_ids
            and self._unbound
        ):
            task_id = next(iter(self._unbound))
            del self._unbound[task_id]
            self._task_workers[task_id] = worker_ids[0]
            return
        if tool == "wait" and event.get("type") == "item.started":
            if self._roster_resolver is not None:
                for task_id, started_at in tuple(self._unbound.items()):
                    worker_id = self._roster_resolver(
                        task_id,
                        started_at,
                        self._parent_thread_id,
                        frozenset(self._task_workers.values()),
                    )
                    if worker_id:
                        del self._unbound[task_id]
                        self._task_workers[task_id] = worker_id
            if not self._unbound:
                return
            tasks = ", ".join(self._unbound)
            raise RunnerError(f"Running task {tasks} has no roster worker before wait")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}"


def _codex_executable(environment: dict[str, str]) -> str:
    requested = environment.get("DE67_CODEX", "codex").strip()
    if not requested:
        raise RunnerError("DE67_CODEX must not be empty")
    resolved = shutil.which(requested)
    if resolved is None:
        raise RunnerError(f"Codex CLI was not found: {requested}")
    return resolved


def _command(codex: str, workspace: Path, environment: dict[str, str]) -> list[str]:
    sandbox = environment.get("DE67_COORDINATOR_SANDBOX", "danger-full-access").strip()
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise RunnerError(f"Unsupported Codex sandbox: {sandbox}")
    resume_session = environment.get("DE67_COORDINATOR_RESUME_SESSION", "").strip()
    command = [codex, "exec", "--sandbox", sandbox]
    if resume_session:
        command.append("resume")
    command.extend(["--json"])
    if not resume_session:
        command.extend(
            [
                "--skip-git-repo-check",
                "-C",
                str(workspace),
            ]
        )
    if environment.get("DE67_COORDINATOR_RUN_ID"):
        model = environment.get("DE67_COORDINATOR_MODEL", "gpt-5.6-sol").strip()
        effort = environment.get(
            "DE67_COORDINATOR_REASONING_EFFORT", "low"
        ).strip()
        if not model or not effort:
            raise RunnerError("Coordinator model and reasoning effort must not be empty")
        command.extend(["-m", model, "-c", f"model_reasoning_effort={effort}"])
    if resume_session:
        command.append(resume_session)
    command.append("-")
    return command


def _record_session(line: str, environment: dict[str, str]) -> str | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if event.get("type") != "thread.started":
        return None
    session_id = event.get("thread_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    target_value = environment.get("DE67_COORDINATOR_SESSION_FILE", "").strip()
    if target_value:
        target = Path(target_value).expanduser().resolve()
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(session_id.strip() + "\n", encoding="utf-8")
        temporary.replace(target)
    return session_id.strip()


def _initial_unbound_tasks(environment: dict[str, str]) -> tuple[str, ...]:
    state_value = environment.get("DE67_DEADLINE_STATE", "").strip()
    lineage = environment.get("DE67_LINEAGE", "").strip()
    if not state_value or not lineage:
        return ()
    state = Path(state_value).expanduser().resolve()
    if not state.is_file():
        return ()
    connection = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            """
            SELECT task_id FROM tasks
            WHERE lineage_id = ? AND attempt_terminal_at IS NULL
            ORDER BY started_at
            """,
            (lineage,),
        ).fetchall()
    finally:
        connection.close()
    return tuple(str(row[0]) for row in rows)


def _roster_resolver(
    workspace: Path, environment: dict[str, str]
) -> Callable[[str, float, str | None, frozenset[str]], str | None]:
    state_value = environment.get("DE67_CODEX_STATE", "").strip()
    state = (
        Path(state_value).expanduser().resolve()
        if state_value
        else Path.home() / ".codex" / "state_5.sqlite"
    )

    def resolve(
        _task_id: str,
        started_at: float,
        parent_thread_id: str | None,
        used_workers: frozenset[str],
    ) -> str | None:
        if parent_thread_id is None or not state.is_file():
            return None
        connection = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                """
                SELECT child.id, child.model, child.updated_at_ms, child.updated_at
                FROM thread_spawn_edges AS edge
                JOIN threads AS child ON child.id = edge.child_thread_id
                WHERE edge.parent_thread_id = ? AND child.cwd = ?
                ORDER BY COALESCE(child.updated_at_ms, child.updated_at * 1000) DESC
                """,
                (parent_thread_id, str(workspace)),
            ).fetchall()
        finally:
            connection.close()
        for worker_id, model, updated_at_ms, updated_at in rows:
            updated = (
                float(updated_at_ms) / 1000.0
                if updated_at_ms is not None
                else float(updated_at)
            )
            if (
                str(worker_id) not in used_workers
                and updated >= started_at
                and any(name in str(model or "").lower() for name in ("luna", "terra"))
            ):
                return str(worker_id)
        return None

    return resolve


def _abandon_unbound_tasks(
    task_ids: Sequence[str], environment: dict[str, str]
) -> None:
    state = environment.get("DE67_DEADLINE_STATE", "").strip()
    lineage = environment.get("DE67_LINEAGE", "").strip()
    if not state or not lineage:
        return
    harness = Path(__file__).resolve().with_name("deadline_harness.py")
    for task_id in task_ids:
        subprocess.run(
            [
                sys.executable,
                str(harness),
                "abandon-attempt",
                "--state",
                state,
                "--lineage",
                lineage,
                "--task",
                task_id,
                "--reason",
                "Coordinator attempted to wait without delegating this task to a roster worker.",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def run(
    workspace_path: str | Path,
    prompt: str,
    *,
    environment: dict[str, str] | None = None,
) -> int:
    workspace = Path(workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise RunnerError(f"Workspace does not exist: {workspace}")
    if not prompt.strip():
        raise RunnerError("Provide non-empty prompt text on standard input")

    selected_environment = os.environ.copy() if environment is None else environment.copy()
    codex = _codex_executable(selected_environment)
    root_value = selected_environment.get("DE67_RUNNER_ROOT", "").strip()
    root = (
        Path(root_value).expanduser().resolve()
        if root_value
        else workspace / ".de67" / "state" / "runner-runs"
    )
    run_directory = root / _run_id()
    run_directory.mkdir(parents=True, exist_ok=False)

    prompt_path = run_directory / "prompt.txt"
    output_path = run_directory / "events.jsonl"
    status_path = run_directory / "status.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    started_at = _timestamp()
    status_path.write_text(
        json.dumps({"status": "running", "started_at": started_at}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"DE67_RUN_DIR={run_directory}", flush=True)

    command = _command(codex, workspace, selected_environment)
    loop_guard = CoordinatorLoopGuard(
        initial_unbound_tasks=_initial_unbound_tasks(selected_environment),
        roster_resolver=_roster_resolver(workspace, selected_environment),
    )
    started = time.monotonic()
    try:
        with prompt_path.open("r", encoding="utf-8") as prompt_stream, output_path.open(
            "w", encoding="utf-8", newline="\n"
        ) as output_stream:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=selected_environment,
                stdin=prompt_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process.stdout is None:
                process.kill()
                raise RunnerError("Codex output pipe was not created")
            session_id: str | None = None
            for line in process.stdout:
                output_stream.write(line)
                output_stream.flush()
                print(line, end="", flush=True)
                session_id = _record_session(line, selected_environment) or session_id
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    loop_guard.observe(event)
                except RunnerError:
                    process.terminate()
                    _abandon_unbound_tasks(
                        loop_guard.unbound_tasks, selected_environment
                    )
                    raise
            exit_code = process.wait()
    except OSError as error:
        raise RunnerError(f"Failed to launch Codex: {error}") from error

    finished_at = _timestamp()
    status_path.write_text(
        json.dumps(
            {
                "status": "done" if exit_code == 0 else "failed",
                "exit_code": exit_code,
                "started_at": started_at,
                "finished_at": finished_at,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "model": selected_environment.get("DE67_COORDINATOR_MODEL"),
                "reasoning_effort": selected_environment.get(
                    "DE67_COORDINATOR_REASONING_EFFORT"
                ),
                "session_id": session_id,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", required=True, help="Coordinator workspace")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return run(arguments.cwd, sys.stdin.read())
    except (RunnerError, OSError) as error:
        print(f"DE-67 Codex runner: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
