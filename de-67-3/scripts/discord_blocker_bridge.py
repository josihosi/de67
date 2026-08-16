#!/usr/bin/env python3
"""Send one DE-67 blocker to Discord and return one authenticated reply."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


DISCORD_MESSAGE_LIMIT = 2000


class DiscordBlockerError(RuntimeError):
    """Raised when the configured blocker message route is not trustworthy."""


@dataclass(frozen=True)
class BlockerReply:
    blocker_digest: str
    notification_message_id: str
    reply_message_id: str
    reply_text: str
    author_id: str


def blocked_ledger_text(ledger: Path) -> tuple[str, str]:
    """Return the exact blocked ledger digest and its normalized blocker prose."""

    raw = ledger.read_bytes()
    lines = ledger.read_text(encoding="utf-8").splitlines()
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
        raise DiscordBlockerError("Ledger has no strict blocked item")
    return hashlib.sha256(raw).hexdigest(), "\n".join(blocks)


def simple_blocker_message(lineage_id: str, blocker_text: str) -> str:
    """Use short Simplified-Technical-English-style sentences."""

    message = (
        "DE-67 stopped because it needs your decision.\n\n"
        f"Project: {lineage_id}\n"
        f"Problem: {blocker_text}\n\n"
        "Reply to this message. Tell DE-67 what it may do next."
    )
    if len(message) > DISCORD_MESSAGE_LIMIT:
        raise DiscordBlockerError(
            "Blocked ledger is too long for one Discord message; make it concise"
        )
    return message


class DiscordBlockerBridge:
    def __init__(
        self,
        *,
        openclaw: str,
        channel_id: str,
        owner_id: str,
        poll_seconds: float,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not channel_id.strip() or not owner_id.strip():
            raise DiscordBlockerError("Discord channel and owner ids are required")
        if poll_seconds <= 0:
            raise DiscordBlockerError("Discord poll interval must be positive")
        self.openclaw = openclaw
        self.channel_id = channel_id
        self.owner_id = owner_id
        self.poll_seconds = poll_seconds
        self.command_runner = command_runner
        self.sleeper = sleeper

    @staticmethod
    def _load(path: Path) -> dict[str, dict[str, object]]:
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise DiscordBlockerError("Discord blocker state must be an object")
        return value

    @staticmethod
    def _save(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _run(self, arguments: Sequence[str]) -> dict[str, object]:
        environment = os.environ.copy()
        environment["PATH"] = (
            "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/bin:/bin:/usr/sbin:/sbin:"
            + environment.get("PATH", "")
        )
        completed = self.command_runner(
            [self.openclaw, *arguments],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise DiscordBlockerError("OpenClaw returned non-object JSON")
        return value

    def wait_for_reply(
        self,
        *,
        workspace: Path,
        lineage_id: str,
    ) -> BlockerReply | None:
        ledger = workspace / ".de67" / "work-ledger.md"
        digest, blocker_text = blocked_ledger_text(ledger)
        state_path = workspace / ".de67" / "state" / "discord-blockers.json"
        state = self._load(state_path)
        record = state.get(digest, {})
        if record.get("reply_message_id") is not None:
            return None

        notification_id = record.get("notification_message_id")
        if not isinstance(notification_id, str) or not notification_id:
            sent = self._run(
                [
                    "message", "send",
                    "--channel", "discord",
                    "--account", "default",
                    "--target", f"channel:{self.channel_id}",
                    "--message", simple_blocker_message(lineage_id, blocker_text),
                    "--json",
                ]
            )
            notification_id = sent.get("messageId")
            if not isinstance(notification_id, str) or not notification_id:
                raise DiscordBlockerError("Discord send returned no message id")
            record = {
                "notification_message_id": notification_id,
                "notified_at": time.time(),
            }
            state[digest] = record
            self._save(state_path, state)

        while True:
            read = self._run(
                [
                    "message", "read",
                    "--channel", "discord",
                    "--account", "default",
                    "--target", f"channel:{self.channel_id}",
                    "--after", notification_id,
                    "--json",
                ]
            )
            payload = read.get("payload")
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
            for message in messages if isinstance(messages, list) else []:
                if not isinstance(message, dict):
                    continue
                author = message.get("author")
                if not isinstance(author, dict):
                    continue
                if str(author.get("id")) != self.owner_id:
                    continue
                reply_id = message.get("id")
                reply_text = message.get("content")
                if not isinstance(reply_id, str) or not isinstance(reply_text, str):
                    continue
                reply_text = reply_text.strip()
                if not reply_text:
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
                return BlockerReply(
                    digest,
                    notification_id,
                    reply_id,
                    reply_text,
                    self.owner_id,
                )
            self.sleeper(self.poll_seconds)
