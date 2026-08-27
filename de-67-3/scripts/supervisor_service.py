#!/usr/bin/env python3
"""Install and control one durable macOS launchd owner for a DE67 workspace."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class ServiceError(RuntimeError):
    """Raised when a durable supervisor service cannot be controlled safely."""


@dataclass(frozen=True)
class ServiceSpec:
    label: str
    plist_path: Path
    domain_target: str
    log_directory: Path
    plist_bytes: bytes


def _workspace_config(workspace: Path) -> tuple[Path, str]:
    config_path = workspace / ".de67" / "state" / "workspace.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ServiceError(f"Unreadable DE67 workspace configuration: {error}") from error
    clock = payload.get("clock")
    if payload.get("workspace") != str(workspace) or not isinstance(clock, dict):
        raise ServiceError("DE67 workspace configuration does not match the requested workspace")
    state_value = clock.get("state")
    lineage = clock.get("lineage")
    if not isinstance(state_value, str) or not isinstance(lineage, str) or not lineage:
        raise ServiceError("DE67 workspace configuration lacks its clock state or lineage")
    state = Path(state_value).expanduser().resolve()
    if not state.is_file():
        raise ServiceError(f"DE67 deadline state is missing: {state}")
    return state, lineage


def service_spec(workspace_value: str | Path) -> ServiceSpec:
    if sys.platform != "darwin":
        raise ServiceError("The durable DE67 service launcher currently requires macOS")
    workspace = Path(workspace_value).expanduser().resolve()
    identity = service_identity(workspace)
    state, lineage = _workspace_config(workspace)
    requested_codex = os.environ.get("DE67_CODEX", "codex").strip()
    if not requested_codex:
        raise ServiceError("DE67_CODEX must not be empty")
    codex = shutil.which(requested_codex)
    if codex is None:
        raise ServiceError("Codex CLI was not found")
    scripts = Path(__file__).resolve().parent
    supervisor = scripts / "coordinator_supervisor.py"
    runner = scripts / "codex_runner.py"
    arguments = [
        str(Path(sys.executable).resolve()),
        str(supervisor),
        "--state", str(state),
        "--lineage", lineage,
        "--workspace", str(workspace),
        "--run-root", str(workspace / ".de67" / "state" / "coordinator-runs"),
        "--coordinator-model", "gpt-5.6-sol",
        "--coordinator-reasoning-effort", "low",
        "--runner", str(Path(sys.executable).resolve()), str(runner),
    ]
    service_environment = {
        "DE67_CODEX": str(Path(codex).resolve()),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    }
    codex_state = os.environ.get("DE67_CODEX_STATE", "").strip()
    if codex_state:
        service_environment["DE67_CODEX_STATE"] = str(
            Path(codex_state).expanduser().resolve()
        )
    payload = {
        "Label": identity.label,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(workspace),
        "RunAtLoad": True,
        # A crash must remain visible and require an explicit owner start. This
        # prevents launchd from turning a supervisor defect into a doom loop.
        "KeepAlive": False,
        "ProcessType": "Background",
        "StandardOutPath": str(identity.log_directory / "stdout.log"),
        "StandardErrorPath": str(identity.log_directory / "stderr.log"),
        "EnvironmentVariables": service_environment,
    }
    return ServiceSpec(
        label=identity.label,
        plist_path=identity.plist_path,
        domain_target=identity.domain_target,
        log_directory=identity.log_directory,
        plist_bytes=plistlib.dumps(payload, sort_keys=True),
    )


def service_identity(workspace_value: str | Path) -> ServiceSpec:
    """Resolve control-plane identity without requiring healthy dependencies."""
    if sys.platform != "darwin":
        raise ServiceError("The durable DE67 service launcher currently requires macOS")
    workspace = Path(workspace_value).expanduser().resolve()
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:16]
    label = f"local.de67.supervisor.{digest}"
    return ServiceSpec(
        label=label,
        plist_path=Path.home() / "Library" / "LaunchAgents" / f"{label}.plist",
        domain_target=f"gui/{os.getuid()}/{label}",
        log_directory=workspace / ".de67" / "state" / "supervisor-service",
        plist_bytes=b"",
    )


def _launchctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/launchctl", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def _job_absent(result: subprocess.CompletedProcess[str]) -> bool:
    # launchctl maps an absent service lookup to ESRCH (113 on macOS).
    return result.returncode == 113


@contextmanager
def _service_lock(spec: ServiceSpec):
    spec.plist_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = spec.plist_path.parent / f".{spec.label}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def start_service(workspace: str | Path) -> ServiceSpec:
    spec = service_spec(workspace)
    with _service_lock(spec):
        loaded = _launchctl("print", spec.domain_target)
        if loaded.returncode != 0 and not _job_absent(loaded):
            raise ServiceError(loaded.stderr.strip() or "launchctl service query failed")
        if loaded.returncode == 0:
            if "state = running" in loaded.stdout:
                raise ServiceError(f"DE67 supervisor service is already running: {spec.label}")
            removed = _launchctl("bootout", spec.domain_target)
            if removed.returncode != 0:
                raise ServiceError(removed.stderr.strip() or "launchctl bootout failed")
        spec.log_directory.mkdir(parents=True, exist_ok=True)
        spec.plist_path.write_bytes(spec.plist_bytes)
        result = _launchctl("bootstrap", f"gui/{os.getuid()}", str(spec.plist_path))
        if result.returncode != 0:
            spec.plist_path.unlink(missing_ok=True)
            raise ServiceError(result.stderr.strip() or "launchctl bootstrap failed")
        started = _launchctl("kickstart", "-p", spec.domain_target)
        if started.returncode != 0 or not started.stdout.strip().isdigit():
            _launchctl("bootout", spec.domain_target)
            spec.plist_path.unlink(missing_ok=True)
            raise ServiceError(
                "DE67 supervisor exited during service startup; inspect "
                f"{spec.log_directory / 'stderr.log'}"
            )
    return spec


def stop_service(workspace: str | Path) -> ServiceSpec:
    spec = service_identity(workspace)
    with _service_lock(spec):
        loaded = _launchctl("print", spec.domain_target)
        if loaded.returncode != 0 and not _job_absent(loaded):
            raise ServiceError(loaded.stderr.strip() or "launchctl service query failed")
        if loaded.returncode == 0:
            result = _launchctl("bootout", spec.domain_target)
            if result.returncode != 0:
                raise ServiceError(result.stderr.strip() or "launchctl bootout failed")
        spec.plist_path.unlink(missing_ok=True)
    return spec


def status_service(workspace: str | Path) -> tuple[ServiceSpec, str]:
    spec = service_identity(workspace)
    result = _launchctl("print", spec.domain_target)
    if _job_absent(result):
        return spec, "stopped"
    if result.returncode != 0:
        raise ServiceError(result.stderr.strip() or "launchctl service query failed")
    return spec, result.stdout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop"))
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "start":
            spec = start_service(arguments.workspace)
            print(json.dumps({"status": "started", "label": spec.label,
                              "logs": str(spec.log_directory)}, sort_keys=True))
        elif arguments.command == "stop":
            spec = stop_service(arguments.workspace)
            print(json.dumps({"status": "stopped", "label": spec.label}, sort_keys=True))
        else:
            spec, status = status_service(arguments.workspace)
            print(json.dumps({"label": spec.label, "launchd": status}, sort_keys=True))
        return 0
    except ServiceError as error:
        print(f"de67 supervisor service: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
