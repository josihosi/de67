from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import codex_runner  # noqa: E402


class FakeProcess:
    def __init__(self, lines: list[str], exit_code: int) -> None:
        self.stdout = iter(lines)
        self.exit_code = exit_code

    def wait(self) -> int:
        return self.exit_code

    def kill(self) -> None:
        pass


class CodexRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def environment(self) -> dict[str, str]:
        return {
            "DE67_CODEX": "codex-test",
            "DE67_RUNNER_ROOT": str(self.root / "runs"),
            "DE67_COORDINATOR_RUN_ID": "run-1",
            "DE67_COORDINATOR_MODEL": "gpt-5.6-sol",
            "DE67_COORDINATOR_REASONING_EFFORT": "low",
        }

    def test_runner_uses_supervisor_model_and_records_auditable_result(self) -> None:
        captured: dict[str, object] = {}

        def launch(command: list[str], **options: object) -> FakeProcess:
            captured["command"] = command
            captured["options"] = options
            return FakeProcess(
                [
                    '{"type":"thread.started","thread_id":"session-1"}\n',
                    '{"type":"turn.started"}\n',
                ],
                0,
            )

        with patch("codex_runner.shutil.which", return_value="/tools/codex"), patch(
            "codex_runner.subprocess.Popen", side_effect=launch
        ):
            result = codex_runner.run(
                self.workspace, "coordinate this\n", environment=self.environment()
            )

        self.assertEqual(result, 0)
        command = captured["command"]
        self.assertEqual(command[0:2], ["/tools/codex", "exec"])
        self.assertIn("--json", command)
        self.assertIn("gpt-5.6-sol", command)
        self.assertIn("model_reasoning_effort=low", command)
        run_directory = next((self.root / "runs").iterdir())
        self.assertEqual(
            (run_directory / "prompt.txt").read_text(encoding="utf-8"),
            "coordinate this\n",
        )
        self.assertIn("turn.started", (run_directory / "events.jsonl").read_text())
        status = json.loads((run_directory / "status.json").read_text())
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["model"], "gpt-5.6-sol")
        self.assertEqual(status["session_id"], "session-1")

    def test_runner_resumes_the_exact_coordinator_session(self) -> None:
        captured: dict[str, object] = {}
        environment = self.environment()
        environment["DE67_COORDINATOR_RESUME_SESSION"] = "session-1"

        def launch(command: list[str], **options: object) -> FakeProcess:
            captured["command"] = command
            return FakeProcess(
                ['{"type":"thread.started","thread_id":"session-1"}\n'], 0
            )

        with patch("codex_runner.shutil.which", return_value="/tools/codex"), patch(
            "codex_runner.subprocess.Popen", side_effect=launch
        ):
            self.assertEqual(
                codex_runner.run(self.workspace, "continue\n", environment=environment),
                0,
            )

        command = captured["command"]
        self.assertEqual(command[0:3], ["/tools/codex", "exec", "resume"])
        self.assertIn("session-1", command)
        self.assertNotIn("--skip-git-repo-check", command)

    def test_runner_propagates_codex_failure(self) -> None:
        with patch("codex_runner.shutil.which", return_value="codex"), patch(
            "codex_runner.subprocess.Popen", return_value=FakeProcess([], 7)
        ):
            result = codex_runner.run(
                self.workspace, "coordinate this", environment=self.environment()
            )
        self.assertEqual(result, 7)
        run_directory = next((self.root / "runs").iterdir())
        status = json.loads((run_directory / "status.json").read_text())
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["exit_code"], 7)

    def test_runner_rejects_missing_cli_and_empty_prompt(self) -> None:
        with patch("codex_runner.shutil.which", return_value=None):
            with self.assertRaisesRegex(codex_runner.RunnerError, "was not found"):
                codex_runner.run(
                    self.workspace, "coordinate this", environment=self.environment()
                )
        with self.assertRaisesRegex(codex_runner.RunnerError, "non-empty prompt"):
            codex_runner.run(self.workspace, "  ", environment=self.environment())


if __name__ == "__main__":
    unittest.main()
