from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from openclaw_discord_blocker import (
    OpenClawBlockerError,
    OpenClawDiscordAdapter,
    blocked_ledger_text,
)


class OpenClawDiscordAdapterTests(unittest.TestCase):
    def workspace(self, directory: str, blocker: str = "Choose the recovery route.") -> Path:
        workspace = Path(directory)
        root = workspace / ".de67"
        root.mkdir()
        (root / "work-ledger.md").write_text(
            "# Work ledger\n\n## Active work\n\n## Blocked work\n\n"
            f"- Blocked: R-001 — {blocker}\n",
            encoding="utf-8",
        )
        return workspace

    def test_blocker_digest_ignores_unrelated_ledger_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            ledger = workspace / ".de67" / "work-ledger.md"
            first, text = blocked_ledger_text(ledger)
            ledger.write_text(
                "# Reformatted ledger\n\n## Blocked work\n\n"
                f"- Blocked: {text}\n",
                encoding="utf-8",
            )
            second, _ = blocked_ledger_text(ledger)
            self.assertEqual(first, second)

    def test_invalid_utf8_and_nonblocked_ledger_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            ledger = workspace / ".de67" / "work-ledger.md"
            ledger.write_bytes(b"\xff")
            with self.assertRaisesRegex(OpenClawBlockerError, "valid UTF-8"):
                blocked_ledger_text(ledger)
            ledger.write_text("# Work ledger\n", encoding="utf-8")
            with self.assertRaisesRegex(OpenClawBlockerError, "no strict blocked"):
                blocked_ledger_text(ledger)

    def test_authenticated_bound_reply_is_durable_and_once_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            calls: list[list[str]] = []

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                if command[1:3] == ["message", "send"]:
                    value = {"messageId": "notice-1"}
                else:
                    value = {
                        "payload": {
                            "messages": [
                                {
                                    "id": "wrong-owner",
                                    "content": "Ignore",
                                    "author": {"id": "intruder"},
                                    "message_reference": {"message_id": "notice-1"},
                                },
                                {
                                    "id": "wrong-reference",
                                    "content": "Ignore",
                                    "author": {"id": "owner"},
                                    "message_reference": {"message_id": "elsewhere"},
                                },
                                {
                                    "id": "reply-1",
                                    "content": "Use the clean route.",
                                    "author": {"id": "owner"},
                                    "message_reference": {"message_id": "notice-1"},
                                },
                            ]
                        }
                    }
                return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

            adapter = OpenClawDiscordAdapter(
                openclaw="openclaw",
                channel_id="channel",
                owner_id="owner",
                poll_seconds=1,
                command_runner=fake_run,
                sleeper=lambda _seconds: None,
            )
            reply = adapter.wait_for_reply(workspace=workspace, lineage_id="project")
            self.assertEqual(reply.reply_message_id if reply else None, "reply-1")
            self.assertIsNone(adapter.wait_for_reply(workspace=workspace, lineage_id="project"))
            self.assertEqual(len(calls), 2)

    def test_unthreaded_answer_requires_explicit_weaker_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            responses = iter(
                [
                    {"messageId": "notice-1"},
                    {
                        "payload": {
                            "messages": [
                                {"id": "reply-1", "content": "Continue.", "author": {"id": "owner"}}
                            ]
                        }
                    },
                ]
            )

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(command, 0, json.dumps(next(responses)), "")

            adapter = OpenClawDiscordAdapter(
                openclaw="openclaw",
                channel_id="channel",
                owner_id="owner",
                poll_seconds=1,
                allow_unthreaded_owner_answer=True,
                command_runner=fake_run,
                sleeper=lambda _seconds: None,
            )
            reply = adapter.wait_for_reply(workspace=workspace, lineage_id="project")
            self.assertEqual(reply.reply_text if reply else None, "Continue.")

    def test_malformed_state_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            state = workspace / ".de67" / "state" / "blocker-adapter-state.json"
            state.parent.mkdir()
            state.write_text("not-json", encoding="utf-8")
            adapter = OpenClawDiscordAdapter(
                openclaw="openclaw", channel_id="channel", owner_id="owner", poll_seconds=1
            )
            with self.assertRaisesRegex(OpenClawBlockerError, "state is unreadable"):
                adapter.wait_for_reply(workspace=workspace, lineage_id="project")
            self.assertEqual(state.read_text(encoding="utf-8"), "not-json")

    def test_matching_legacy_record_moves_to_generic_state_without_resend(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.workspace(directory)
            ledger = workspace / ".de67" / "work-ledger.md"
            legacy_digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
            legacy = workspace / ".de67" / "state" / "discord-blockers.json"
            legacy.parent.mkdir()
            legacy.write_text(
                json.dumps(
                    {
                        legacy_digest: {
                            "notification_message_id": "notice-1",
                            "reply_message_id": "reply-1",
                        }
                    }
                ),
                encoding="utf-8",
            )
            adapter = OpenClawDiscordAdapter(
                openclaw="openclaw", channel_id="channel", owner_id="owner", poll_seconds=1
            )

            self.assertIsNone(adapter.wait_for_reply(workspace=workspace, lineage_id="project"))
            generic = workspace / ".de67" / "state" / "blocker-adapter-state.json"
            self.assertTrue(generic.exists())
            self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
