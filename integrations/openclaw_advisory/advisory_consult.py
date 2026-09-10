#!/usr/bin/env python3
"""Bounded advisory calls from a live DE67 coordinator to OpenClaw.

This is deliberately separate from the owner Discord relay.  The caller supplies
the coordinator binding, but SQLite and the current assignment text are the
authority for that binding.  A failed or interrupted transport is retained and
is never retried implicitly.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


class AdvisoryError(RuntimeError):
    """The consultation route cannot return trustworthy advice."""


class AuthorizationError(AdvisoryError):
    """The caller is not the currently-owned coordinator task."""


@dataclass(frozen=True)
class ConsultationReply:
    request_id: str
    status: str
    reply: str | None
    gateway: Mapping[str, Any] | None
    reason: str | None = None


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdvisoryError(f"consultation field {field} must be non-empty text")
    return value.strip()


def _digest(value: object, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise AdvisoryError(f"consultation field {field} must be a SHA-256 digest")
    return value.lower()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def assignment_revision(workspace: Path, task_id: str) -> str:
    """Hash only the current ledger assignment, matching context_library."""

    ledger = workspace / ".de67" / "work-ledger.md"
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise AdvisoryError(f"current assignment is unavailable: {error}") from error
    prefix = "  - Assignment " + task_id + ":"
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise AuthorizationError(
            f"current assignment for {task_id} is not unique ({len(matches)} matches)"
        )
    body = [lines[matches[0]][len(prefix) :].strip()]
    for line in lines[matches[0] + 1 :]:
        if line.startswith(("  - ", "- ", "#")):
            break
        body.append(line.strip())
    return hashlib.sha256("\n".join(body).strip().encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_name(path.name + ".lock").open("a+b")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


class AdvisoryAdapter:
    """One-shot, durable consultation adapter for the configured Astra role."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.workspace = Path(_text(config.get("workspace"), "workspace")).expanduser().resolve()
        self.openclaw = _text(config.get("openclaw"), "openclaw")
        self.agent = _text(config.get("agent"), "agent")
        self.session_key = _text(config.get("session_key"), "session_key")
        self.recipient_role = _text(config.get("recipient_role"), "recipient_role")
        self.role_source = Path(_text(config.get("role_source"), "role_source")).expanduser().resolve()
        try:
            role_bytes = self.role_source.read_bytes()
        except OSError as error:
            raise AdvisoryError(f"recipient role guidance is unavailable: {error}") from error
        self.role_source_sha256 = hashlib.sha256(role_bytes).hexdigest()
        configured_digest = config.get("role_source_sha256")
        if configured_digest is not None and _digest(configured_digest, "role_source_sha256") != self.role_source_sha256:
            raise AdvisoryError("recipient role guidance digest does not match host configuration")
        expected_prefix = f"agent:{self.agent}:"
        if not self.session_key.startswith(expected_prefix):
            raise AdvisoryError("session_key is not bound to configured agent")
        self.command_runner = command_runner
        self.clock = clock

    @staticmethod
    def _load_state(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"schema": 1, "requests": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AdvisoryError(f"advisory state is unreadable: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("requests", {}), dict):
            raise AdvisoryError("advisory state must contain an object requests map")
        if value.get("schema", 1) != 1:
            raise AdvisoryError("unsupported advisory state schema")
        return value

    def _authorize(self, packet: Mapping[str, Any], workspace: Path, lineage: str) -> str:
        packet_workspace = Path(_text(packet.get("workspace"), "workspace")).expanduser().resolve()
        if packet_workspace != workspace:
            raise AuthorizationError("workspace is not the adapter workspace")
        if _text(packet.get("lineage_id"), "lineage_id") != lineage:
            raise AuthorizationError("lineage is not the current bound lineage")
        task_id = _text(packet.get("task_id"), "task_id")
        sender_run = _text(packet.get("sender_run_id"), "sender_run_id")
        sender_session = _text(packet.get("sender_session_id"), "sender_session_id")
        sender_supervisor = _text(packet.get("sender_supervisor_id"), "sender_supervisor_id")
        supplied_revision = _digest(packet.get("assignment_revision"), "assignment_revision")
        current_revision = assignment_revision(workspace, task_id)
        if supplied_revision != current_revision:
            raise AuthorizationError("assignment revision is stale")
        state = workspace / ".de67" / "state" / "deadlines.sqlite3"
        try:
            with sqlite3.connect(state) as database:
                database.row_factory = sqlite3.Row
                binding = database.execute("SELECT lineage_id FROM lineage_binding WHERE singleton=1").fetchone()
                task = database.execute(
                    "SELECT task_id, attempt_terminal_at FROM tasks WHERE lineage_id=? AND task_id=?",
                    (lineage, task_id),
                ).fetchone()
                claim = database.execute(
                    "SELECT coordinator_session_id, supervisor_id FROM worker_claims "
                    "WHERE lineage_id=? AND task_id=? AND released_at IS NULL",
                    (lineage, task_id),
                ).fetchone()
                run = database.execute(
                    "SELECT run_id, owner_id FROM supervisor_attempts "
                    "WHERE lineage_id=? AND role='coordinator' AND run_id=? AND finished_at IS NULL",
                    (lineage, sender_run),
                ).fetchone()
        except sqlite3.Error as error:
            raise AdvisoryError(f"sender validation unavailable: {error}") from error
        if binding is None or binding["lineage_id"] != lineage:
            raise AuthorizationError("workspace lineage binding is not current")
        if task is None or task["attempt_terminal_at"] is not None:
            raise AuthorizationError("task is missing or already terminal")
        if claim is None or claim["coordinator_session_id"] != sender_session:
            raise AuthorizationError("sender session does not own the task")
        if run is None or not run["owner_id"].startswith(f"supervisor-{sender_supervisor}-"):
            raise AuthorizationError("sender run is not owned by the current supervisor")
        task_view = workspace / ".de67" / "state" / "context-library" / "tasks" / f"{task_id}.json"
        if task_view.exists():
            try:
                view = json.loads(task_view.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise AdvisoryError(f"task context is unreadable: {error}") from error
            if view.get("assignment_revision") != supplied_revision:
                raise AuthorizationError("task context assignment revision is stale")
        return task_id

    def _message(self, packet: Mapping[str, Any], request_id: str) -> str:
        evidence = packet.get("evidence_refs", [])
        if not isinstance(evidence, list) or any(not isinstance(item, str) or not item.strip() for item in evidence):
            raise AdvisoryError("evidence_refs must be a list of non-empty references")
        if len(evidence) > 32:
            raise AdvisoryError("evidence_refs contains too many entries")
        fields = (
            ("Intended outcome", packet.get("intended_outcome")),
            ("Current state", packet.get("current_state")),
            ("First divergence", packet.get("first_divergence")),
            ("Tried and learned", packet.get("tried_learned")),
            ("Constraints/live owner", packet.get("constraints_live_owner")),
            ("Decision needed", packet.get("decision_needed")),
        )
        body = [
            "DE67 ADVISORY CONSULTATION — agent-authored, non-authorizing advice only.",
            f"CONSULTATION_REQUEST_ID: {request_id}",
            f"Task/run/revision: {packet['task_id']} / {packet['sender_run_id']} / {packet['assignment_revision']}",
            f"Lineage: {packet['lineage_id']}",
        ]
        for label, value in fields:
            body.append(f"{label}: {_text(value, label)}")
        body.append("Evidence references: " + ", ".join(evidence) if evidence else "Evidence references: none")
        body.extend([
            "Return concise diagnosis/options, evidence limits, and a change/no-change recommendation.",
            "Do not alter owner intent, repair authority, DFS, gates, live ownership, queue provenance, or shared files.",
            "Return only advisory reasoning; do not enqueue anything and do not echo this request envelope.",
        ])
        return "\n".join(body) + "\n"

    @staticmethod
    def _reply_text(payload: Mapping[str, Any]) -> str | None:
        final = payload.get("final")
        if isinstance(final, str) and final.strip():
            return final.strip()
        payloads = payload.get("payloads")
        if isinstance(payloads, list):
            texts = [item.get("text", "").strip() for item in payloads if isinstance(item, dict) and isinstance(item.get("text"), str)]
            if texts:
                return texts[-1]
        nested = payload.get("result")
        if isinstance(nested, dict):
            return AdvisoryAdapter._reply_text(nested)
        return None

    def consult(self, packet: Mapping[str, Any], *, retry_unavailable: bool = False) -> ConsultationReply:
        workspace = self.workspace
        lineage = _text(packet.get("lineage_id"), "lineage_id")
        try:
            current_role_digest = hashlib.sha256(self.role_source.read_bytes()).hexdigest()
        except OSError as error:
            raise AdvisoryError(f"recipient role guidance is unavailable: {error}") from error
        if current_role_digest != self.role_source_sha256:
            raise AdvisoryError("recipient role guidance changed after adapter binding")
        task_id = self._authorize(packet, workspace, lineage)
        identity_data = dict(packet)
        identity_data["recipient_role"] = self.recipient_role
        identity_data["role_source_sha256"] = self.role_source_sha256
        request_id = hashlib.sha256(_canonical(identity_data).encode("utf-8")).hexdigest()
        message = self._message(packet, request_id)
        state_path = workspace / ".de67" / "state" / "advisory-consultations.json"
        with _state_lock(state_path):
            state = self._load_state(state_path)
            requests = state["requests"]
            prior = requests.get(request_id)
            if isinstance(prior, dict):
                status = prior.get("status")
                if status in {"replied", "unavailable", "submitting", "uncertain"} and not (status == "unavailable" and retry_unavailable):
                    return ConsultationReply(request_id, str(status), prior.get("reply"), prior.get("gateway"), prior.get("reason"))
            request_dir = state_path.parent / "advisory-consultations" / request_id
            request_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            request_path = request_dir / "request.txt"
            request_path.write_text(message, encoding="utf-8")
            request_path.chmod(0o600)
            record = {
                "request_id": request_id, "status": "submitting", "created_at": self.clock(),
                "workspace": str(workspace), "lineage_id": lineage, "task_id": task_id,
                "sender_run_id": packet["sender_run_id"], "sender_session_id": packet["sender_session_id"],
                "assignment_revision": packet["assignment_revision"], "recipient_role": self.recipient_role,
                "role_source_sha256": self.role_source_sha256, "request_path": str(request_path),
            }
            requests[request_id] = record
            _atomic_json(state_path, state)
            argv = [self.openclaw, "agent", "--agent", self.agent, "--session-key", self.session_key,
                    "--message-file", str(request_path), "--json"]
            try:
                result = self.command_runner(argv, check=False, capture_output=True, text=True)
            except (OSError, subprocess.SubprocessError) as error:
                record.update(status="unavailable", reason=f"OpenClaw execution unavailable: {error}", finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, None, record["reason"])
            if result.returncode != 0:
                detail = (result.stderr or "").strip().splitlines()
                reason = f"OpenClaw returned exit {result.returncode}" + (f": {detail[-1]}" if detail else "")
                record.update(status="unavailable", reason=reason, finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, None, reason)
            try:
                payload = json.loads(result.stdout)
            except (TypeError, json.JSONDecodeError) as error:
                reason = f"OpenClaw returned invalid JSON: {error}"
                record.update(status="unavailable", reason=reason, finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, None, reason)
            if not isinstance(payload, dict):
                reason = "OpenClaw returned non-object JSON"
                record.update(status="unavailable", reason=reason, finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, None, reason)
            reply = self._reply_text(payload)
            if payload.get("status") not in (None, "ok") or payload.get("ok") is False or not reply:
                reason = "OpenClaw completed without a correlated advisory reply"
                record.update(status="unavailable", reason=reason, gateway=payload, finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, payload, reason)
            if reply == message.strip() or message.strip() in reply:
                reason = "OpenClaw reply was a request echo"
                record.update(status="unavailable", reason=reason, gateway=payload, finished_at=self.clock())
                _atomic_json(state_path, state)
                return ConsultationReply(request_id, "unavailable", None, payload, reason)
            record.update(status="replied", reply=reply, gateway=payload, finished_at=self.clock())
            _atomic_json(state_path, state)
            return ConsultationReply(request_id, "replied", reply, payload)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--packet", required=True, help="JSON consultation packet")
    parser.add_argument("--retry-unavailable", action="store_true",
                        help="Explicitly retry a previously unavailable request")
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
        reply = AdvisoryAdapter(config).consult(packet, retry_unavailable=args.retry_unavailable)
    except (OSError, UnicodeError, json.JSONDecodeError, AdvisoryError) as error:
        print(json.dumps({"status": "unavailable", "reason": str(error)}))
        return 0
    print(json.dumps({"request_id": reply.request_id, "status": reply.status, "reply": reply.reply,
                      "gateway": reply.gateway, "reason": reply.reason}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
