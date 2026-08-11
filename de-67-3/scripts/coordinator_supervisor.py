#!/usr/bin/env python3
"""Run DE-67 coordinators under one external, restart-aware parent."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Mapping, Sequence

from deadline_harness import DeadlineError, DeadlineHarness


RED_DFS_CLAIM = re.compile(r"^- \[ \] \N{LARGE RED CIRCLE} ", re.MULTILINE)
ACTIVE_LEDGER_ITEM = re.compile(r"^- \[ \] ", re.MULTILINE)


class SupervisorError(RuntimeError):
    """Raised when coordinator ownership or restart state is inconsistent."""


@dataclass(frozen=True)
class RestartState:
    required: bool
    generation: int | None
    expected_run_id: str | None
    run_id: str | None


@dataclass(frozen=True)
class ChildResult:
    run_id: str
    run_dir: Path
    exit_code: int


def _write(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


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
        return RestartState(False, None, None, None)
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
    return RestartState(required, generation, expected_run_id, run_id)


def read_clock(state_path: Path, lineage_id: str) -> RestartState:
    """Read restart state once; callers decide when another read is warranted."""
    with DeadlineHarness(state_path) as harness:
        return _restart_state(
            harness.coordinator_restart_status(lineage_id), lineage_id
        )


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
    if clock["tasks"] or clock["pending_incident_reviews"]:
        return False
    if restart is not None and restart["pending"]:
        return False

    # The DFS is the product contract. A cadence that became due on its final
    # terminal window cannot manufacture work after that contract is all green.
    return True


def coordinator_prompt(
    workspace: Path,
    state_path: Path,
    lineage_id: str,
    run_id: str,
    generation: int | None,
) -> str:
    lines = [
        f"Run DE-67-3 as a fresh coordinator in {workspace}.",
        "Read the installed DE-67-3 skill, current code and Git state, and only durable .de67 state; do not read predecessor logs or narrative handoffs.",
        "Use DE67_DEADLINE_STATE and DE67_LINEAGE as the exact clock and lineage for every deadline-harness command; do not infer replacements.",
        "The external coordinator supervisor owns this process. Do not launch your successor.",
    ]
    if generation is not None:
        lines.append(
            "Before dispatching work, execute the argument array in "
            "DE67_COORDINATOR_ACK_ARGV_JSON as a subprocess without a shell; "
            "it acknowledges this exact restart generation."
        )
    lines.append("Continue from the durable accepted frontier until the next required retirement or DFS completion.")
    return "\n".join(lines) + "\n"


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
) -> ChildResult:
    if not runner_command:
        raise SupervisorError("Runner command must not be empty")
    run_id = _validate_run_id(run_id)
    run_dir = run_root / run_id
    try:
        run_dir.mkdir(parents=False, exist_ok=False)
    except OSError as error:
        raise SupervisorError(f"Cannot create coordinator run directory: {error}") from error

    prompt = coordinator_prompt(workspace, state_path, lineage_id, run_id, generation)
    _write(run_dir / "prompt.txt", prompt)
    _write(run_dir / "status.txt", "STARTING\n")

    environment = os.environ.copy()
    if extra_env is not None:
        environment.update(extra_env)
    environment.update(
        {
            "DE67_COORDINATOR_RUN_ID": run_id,
            "DE67_DEADLINE_STATE": str(state_path),
            "DE67_LINEAGE": lineage_id,
            "DE67_WORKSPACE": str(workspace),
            "DE67_SUPERVISOR_PID": str(os.getpid()),
        }
    )
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
        return ChildResult(run_id, run_dir, 1)
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
    return ChildResult(run_id, run_dir, exit_code)


def _run_supervisor_locked(
    state_path: str | Path,
    lineage_id: str,
    workspace: str | Path,
    runner_command: Sequence[str],
    run_root: str | Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    run_id_factory: Callable[[int | None], str] = _default_run_id,
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

    if work_is_complete(workdir, state, lineage_id):
        return 0

    records.mkdir(parents=True, exist_ok=True)

    restart = read_clock(state, lineage_id)
    generation = restart.generation if restart.required else None
    attempted_generations: set[int] = set()

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

        result = run_child(
            runner_command,
            workdir,
            state,
            lineage_id,
            records,
            run_id,
            generation,
            extra_env=extra_env,
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

        if result.exit_code != 0:
            return result.exit_code if result.exit_code > 0 else 1
        if work_is_complete(workdir, state, lineage_id):
            return 0
        if not after.required:
            return 0
        if after.generation is None:
            _mark_protocol_failure(result, "Required coordinator restart lacks a generation")
            return 1
        if after.generation in attempted_generations:
            _mark_protocol_failure(
                result,
                f"Restart generation {after.generation} remains pending after its only attempt",
            )
            return 1
        restart = after
        generation = after.generation


def run_supervisor(
    state_path: str | Path,
    lineage_id: str,
    workspace: str | Path,
    runner_command: Sequence[str],
    run_root: str | Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    run_id_factory: Callable[[int | None], str] = _default_run_id,
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
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--lineage", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument(
        "--runner",
        nargs=argparse.REMAINDER,
        help="Runner command; place this option last",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return run_supervisor(
            arguments.state,
            arguments.lineage,
            arguments.workspace,
            arguments.runner or (),
            arguments.run_root,
        )
    except (DeadlineError, SupervisorError, OSError) as error:
        print(f"coordinator supervisor: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
