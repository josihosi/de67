#!/usr/bin/env python3
"""Run one auditable DE-67 coordinator through the local Codex CLI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


class RunnerError(RuntimeError):
    """Raised when the local Codex runner cannot start safely."""


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
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "--json",
        "-C",
        str(workspace),
    ]
    if environment.get("DE67_COORDINATOR_RUN_ID"):
        model = environment.get("DE67_COORDINATOR_MODEL", "gpt-5.6-sol").strip()
        effort = environment.get(
            "DE67_COORDINATOR_REASONING_EFFORT", "low"
        ).strip()
        if not model or not effort:
            raise RunnerError("Coordinator model and reasoning effort must not be empty")
        command.extend(["-m", model, "-c", f"model_reasoning_effort={effort}"])
    command.append("-")
    return command


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
            for line in process.stdout:
                output_stream.write(line)
                output_stream.flush()
                print(line, end="", flush=True)
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
