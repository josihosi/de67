from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from discord_blocker_bridge import (  # noqa: E402
    DiscordBlockerBridge,
    blocked_ledger_text,
    simple_blocker_message,
)


class DiscordBlockerBridgeTests(unittest.TestCase):
    def test_message_is_short_plain_and_actionable(self) -> None:
        message = simple_blocker_message("project", "R-001 needs one owner choice.")
        self.assertIn("DE-67 stopped", message)
        self.assertIn("Problem:", message)
        self.assertIn("Reply to this message", message)

    def test_authenticated_owner_answer_is_durable_and_once_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root = workspace / ".de67"
            root.mkdir()
            ledger = root / "work-ledger.md"
            ledger.write_text(
                "# Work ledger\n\n## Blocked work\n\n"
                "- Blocked: R-001 — Choose the recovery route.\n",
                encoding="utf-8",
            )
            digest, _ = blocked_ledger_text(ledger)
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
                                    "id": "ignored",
                                    "content": "wrong person",
                                    "author": {"id": "intruder"},
                                },
                                {
                                    "id": "reply-1",
                                    "content": "Build a clean scenario.",
                                    "author": {"id": "owner"},
                                },
                            ]
                        }
                    }
                return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

            bridge = DiscordBlockerBridge(
                openclaw="openclaw",
                channel_id="channel",
                owner_id="owner",
                poll_seconds=1,
                command_runner=fake_run,
                sleeper=lambda _seconds: None,
            )

            reply = bridge.wait_for_reply(workspace=workspace, lineage_id="project")

            self.assertIsNotNone(reply)
            assert reply is not None
            self.assertEqual(reply.reply_text, "Build a clean scenario.")
            saved = json.loads(
                (root / "state" / "discord-blockers.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved[digest]["reply_message_id"], "reply-1")
            self.assertIsNone(
                bridge.wait_for_reply(workspace=workspace, lineage_id="project")
            )
            self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
