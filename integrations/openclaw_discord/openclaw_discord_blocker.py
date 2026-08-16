#!/usr/bin/env python3
"""Optional OpenClaw/Discord owner-contact adapter for a DE67 blocked ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


DISCORD_MESSAGE_LIMIT = 2000


class OpenClawBlockerError(RuntimeError):
    """Raised when the optional contact route cannot produce trustworthy authority."""


@dataclass(frozen=True)
class BlockerReply:
    blocker_digest: str
    notification_message_id: str
    reply_message_id: str
    reply_text: str
    author_id: str


def _blocked_ledger_snapshot(ledger: Path) -> tuple[str, str, str]:
    raw = ledger.read_bytes()
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise OpenClawBlockerError("Ledger is not valid UTF-8") from error
    blocks: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("- Blocked: "):
            if current:
                blocks.append(" ".join(current))
            current = [line.removeprefix("- Blocked: ").strip()]
        elif current is not None and (line.startswith("  ") or not line.strip()):
            if line.strip():
                current.append(line.strip())
        elif current is not None:
            blocks.append(" ".join(current))
            current = None
    if current:
        blocks.append(" ".join(current))
    if not blocks:
        raise OpenClawBlockerError("Ledger has no strict blocked item")
    blocker_text = "\n".join(blocks)
    return (
        hashlib.sha256(blocker_text.encode("utf-8")).hexdigest(),
        blocker_text,
        hashlib.sha256(raw).hexdigest(),
    )


def blocked_ledger_text(ledger: Path) -> tuple[str, str]:
    """Read one ledger snapshot and identify only its normalized strict blockers."""

    digest, blocker_text, _legacy_digest = _blocked_ledger_snapshot(ledger)
    return digest, blocker_text


def simple_blocker_message(lineage_id: str, blocker_text: str) -> str:
    message = (
        "DE67 stopped because it needs your decision.\n\n"
        f"Project: {lineage_id}\n"
        f"Problem: {blocker_text}\n\n"
        "Reply to this message. Tell DE67 what it may do next."
    )
    if len(message) > DISCORD_MESSAGE_LIMIT:
        raise OpenClawBlockerError("Blocked ledger is too long for one Discord message")
    return message


def _message_reference(message: Mapping[str, object]) -> str | None:
    for key in ("message_reference", "messageReference", "reference"):
        reference = message.get(key)
        if not isinstance(reference, Mapping):
            continue
        for id_key in ("message_id", "messageId", "id"):
            value = reference.get(id_key)
            if isinstance(value, str) and value:
                return value
    return None


class OpenClawDiscordAdapter:
    def __init__(
        self,
        *,
        openclaw: str,
        channel_id: str,
        owner_id: str,
        poll_seconds: float,
        allow_unthreaded_owner_answer: bool = False,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not openclaw or not channel_id.strip() or not owner_id.strip():
            raise OpenClawBlockerError("OpenClaw command, channel id, and owner id are required")
        if poll_seconds <= 0:
            raise OpenClawBlockerError("Discord poll interval must be positive")
        self.openclaw = openclaw
        self.channel_id = channel_id
        self.owner_id = owner_id
        self.poll_seconds = poll_seconds
        self.allow_unthreaded_owner_answer = allow_unthreaded_owner_answer
        self.command_runner = command_runner
        self.sleeper = sleeper

    @staticmethod
    def _load(path: Path) -> dict[str, dict[str, object]]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OpenClawBlockerError("OpenClaw blocker state is unreadable") from error
        if not isinstance(value, dict):
            raise OpenClawBlockerError("OpenClaw blocker state must be an object")
        return value

    @staticmethod
    def _save(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(value, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _run(self, arguments: Sequence[str]) -> dict[str, object]:
        completed = self.command_runner(
            [self.openclaw, *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise OpenClawBlockerError("OpenClaw returned invalid JSON") from error
        if not isinstance(value, dict):
            raise OpenClawBlockerError("OpenClaw returned non-object JSON")
        return value

    def wait_for_reply(self, *, workspace: Path, lineage_id: str) -> BlockerReply | None:
        digest, blocker_text, legacy_digest = _blocked_ledger_snapshot(
            workspace / ".de67" / "work-ledger.md"
        )
        state_path = workspace / ".de67" / "state" / "blocker-adapter-state.json"
        legacy_state_path = workspace / ".de67" / "state" / "discord-blockers.json"
        state = self._load(state_path)
        if not state and legacy_state_path.exists():
            legacy_state = self._load(legacy_state_path)
            legacy_record = legacy_state.get(legacy_digest)
            if isinstance(legacy_record, dict):
                state[digest] = dict(legacy_record)
                self._save(state_path, state)
        record = state.get(digest, {})
        if record.get("reply_message_id") is not None:
            return None

        notification_id = record.get("notification_message_id")
        if not isinstance(notification_id, str) or not notification_id:
            sent = self._run(
                [
                    "message", "send", "--channel", "discord", "--account", "default",
                    "--target", f"channel:{self.channel_id}",
                    "--message", simple_blocker_message(lineage_id, blocker_text), "--json",
                ]
            )
            notification_id = sent.get("messageId")
            if not isinstance(notification_id, str) or not notification_id:
                raise OpenClawBlockerError("Discord send returned no message id")
            record = {
                "blocker_text": blocker_text,
                "notification_message_id": notification_id,
                "notified_at": time.time(),
            }
            state[digest] = record
            self._save(state_path, state)

        while True:
            read = self._run(
                [
                    "message", "read", "--channel", "discord", "--account", "default",
                    "--target", f"channel:{self.channel_id}", "--after", notification_id,
                    "--json",
                ]
            )
            payload = read.get("payload")
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
            for message in messages if isinstance(messages, list) else []:
                if not isinstance(message, dict):
                    continue
                author = message.get("author")
                if not isinstance(author, dict) or str(author.get("id")) != self.owner_id:
                    continue
                if (
                    not self.allow_unthreaded_owner_answer
                    and _message_reference(message) != notification_id
                ):
                    continue
                reply_id = message.get("id")
                reply_text = message.get("content")
                if not isinstance(reply_id, str) or not isinstance(reply_text, str):
                    continue
                reply_text = reply_text.strip()
                if not reply_id or not reply_text:
                    continue
                record.update(
                    {
                        "reply_message_id": reply_id,
                        "reply_text": reply_text,
                        "reply_author_id": self.owner_id,
                        "replied_at": time.time(),
                    }
                )
                self._save(state_path, state)
                return BlockerReply(digest, notification_id, reply_id, reply_text, self.owner_id)
            self.sleeper(self.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw", default="openclaw")
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--poll-seconds", type=float, required=True)
    parser.add_argument("--allow-unthreaded-owner-answer", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    wait = commands.add_parser("wait")
    wait.add_argument("--workspace", type=Path, required=True)
    wait.add_argument("--lineage", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        adapter = OpenClawDiscordAdapter(
            openclaw=arguments.openclaw,
            channel_id=arguments.channel_id,
            owner_id=arguments.owner_id,
            poll_seconds=arguments.poll_seconds,
            allow_unthreaded_owner_answer=arguments.allow_unthreaded_owner_answer,
        )
        reply = adapter.wait_for_reply(
            workspace=arguments.workspace.expanduser().resolve(),
            lineage_id=arguments.lineage,
        )
        print(json.dumps(asdict(reply) if reply is not None else None, sort_keys=True))
        return 0
    except (OpenClawBlockerError, OSError, subprocess.SubprocessError) as error:
        print(f"openclaw discord blocker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
