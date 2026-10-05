import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import host_footing as footing


class HostFootingTests(unittest.TestCase):
    def test_exact_repository_dirty_and_detached_are_not_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True,
                               capture_output=True)
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "fixture")
            clean = footing.repository(str(repo))
            self.assertFalse(clean["dirty"])
            self.assertEqual(clean["source_ready"], "not_assessed")
            (repo / "owned.txt").write_text("preserve me")
            dirty = footing.repository(str(repo))
            self.assertTrue(dirty["dirty"])
            self.assertEqual((repo / "owned.txt").read_text(), "preserve me")
            git("checkout", "--detach")
            detached = footing.repository(str(repo))
            self.assertFalse(detached["branch"]["available"])
            self.assertEqual(detached["commit"], clean["commit"])
            nested = repo / "sub"; nested.mkdir()
            self.assertEqual(footing.repository(str(nested))["reason"], "not_repository_root")

    def test_missing_repository_cannot_become_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            row = footing.repository(str(Path(directory) / "missing"))
        self.assertFalse(row["available"])
        self.assertNotIn("dirty", row)

    def test_remote_url_credentials_not_disclosed(self):
        self.assertEqual(footing.safe_remote("https://user:secret@example.com/org/repo?token=secret#x"),
                         "https://example.com/org/repo")

    def test_command_failure_does_not_echo_stderr_or_secrets(self):
        with patch.object(footing.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 7, "", "credential=secret")):
            result = footing.command(["unused"])
        self.assertEqual(result, {"available": False, "reason": "command_failed", "exit_code": 7})

    def test_remote_failure_is_unknown_not_local_fallback(self):
        with patch.object(sys, "argv", ["host_footing.py", "--ssh", "test-host"]), \
             patch.object(footing.subprocess, "run", return_value=subprocess.CompletedProcess([], 255, "", "secret")), \
             patch("builtins.print") as output:
            footing.main()
        row = json.loads(output.call_args.args[0])
        self.assertFalse(row["available"])
        self.assertIsNone(row["host"])
        self.assertEqual(row["launch_admission"], "not_assessed")

    def test_remote_values_travel_on_stdin_not_shell(self):
        fake = {"schema": "de67-host-footing-v1", "host": "remote", "repositories": []}
        with patch.object(sys, "argv", ["host_footing.py", "--ssh", "test-host", "--repo", "C:/a;echo secret"]), \
             patch.object(footing.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(fake), "")) as run, \
             patch("builtins.print"):
            footing.main()
        self.assertNotIn("secret", " ".join(run.call_args.args[0]))
        self.assertIn("C:/a;echo secret", run.call_args.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
