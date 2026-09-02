import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("fratbro_narrator.py")
SPEC = importlib.util.spec_from_file_location("fratbro_narrator", MODULE_PATH)
narrator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(narrator)


class FratbroNarratorTests(unittest.TestCase):
    def test_luna_medium_is_read_only_and_structured(self) -> None:
        answer = {key: key for key in ("cooking", "changed", "snag", "next", "health")}
        event = {"type": "item.completed", "item": {
            "type": "agent_message", "text": json.dumps(answer)
        }}
        completed = type("Completed", (), {
            "returncode": 0, "stdout": json.dumps(event) + "\n", "stderr": ""
        })()
        with patch.object(narrator.subprocess, "run", return_value=completed) as run:
            result = narrator.run_luna(Path("/tmp/work"), {"evidence": True}, "codex")

        command = run.call_args.args[0]
        self.assertIn("gpt-5.6-luna", command)
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(command[command.index("-C") + 1], "/tmp")
        self.assertEqual(result, answer)

    def test_activity_read_does_not_change_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "work"
            sessions = Path(temporary) / "sessions"
            (workspace / ".de67").mkdir(parents=True)
            sessions.mkdir()
            ledger = workspace / ".de67/work-ledger.md"
            ledger.write_text("# Ledger\n", encoding="utf-8")
            session = sessions / "rollout-worker.jsonl"
            session.write_text("\n".join(json.dumps(item) for item in (
                {"type": "session_meta", "payload": {
                    "id": "worker", "parent_thread_id": None, "cwd": str(workspace)
                }},
                {"type": "response_item", "payload": {
                    "type": "message", "role": "assistant",
                    "content": [{"text": "Testing smoke."}]
                }},
            )) + "\n", encoding="utf-8")
            before = ledger.read_bytes(), session.read_bytes()

            payload = narrator.activity_payload(workspace, sessions)

            self.assertEqual(before, (ledger.read_bytes(), session.read_bytes()))
            self.assertEqual(payload["current_thread_messages"][0]["latest_message"],
                             "Testing smoke.")


if __name__ == "__main__":
    unittest.main()
