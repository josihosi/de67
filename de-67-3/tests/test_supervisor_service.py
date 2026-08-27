from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import supervisor_service  # noqa: E402


class SupervisorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home_patcher = patch(
            "supervisor_service.Path.home", return_value=self.root / "home"
        )
        self.platform_patcher = patch("supervisor_service.sys.platform", "darwin")
        self.home_patcher.start()
        self.platform_patcher.start()
        self.workspace = self.root / "workspace"
        (self.workspace / ".de67" / "state").mkdir(parents=True)
        self.workspace = self.workspace.resolve()
        self.state = self.workspace / ".de67" / "state" / "deadlines.sqlite3"
        self.state.touch()
        (self.workspace / ".de67" / "state" / "workspace.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "workspace": str(self.workspace),
                    "clock": {"state": str(self.state), "lineage": "test-lineage"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.platform_patcher.stop()
        self.home_patcher.stop()
        self.temporary.cleanup()

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    def test_service_spec_is_durable_non_looping_and_absolute(self, _which) -> None:
        spec = supervisor_service.service_spec(self.workspace)
        payload = plistlib.loads(spec.plist_bytes)

        self.assertFalse(payload["KeepAlive"])
        self.assertTrue(payload["RunAtLoad"])
        self.assertEqual(payload["WorkingDirectory"], str(self.workspace))
        self.assertEqual(payload["EnvironmentVariables"]["DE67_CODEX"], "/opt/bin/codex")
        self.assertEqual(payload["EnvironmentVariables"]["PATH"], os.environ["PATH"])
        arguments = payload["ProgramArguments"]
        self.assertTrue(Path(arguments[0]).is_absolute())
        self.assertIn(str(self.state), arguments)
        self.assertIn("test-lineage", arguments)
        self.assertEqual(arguments[-3], "--runner")
        self.assertTrue(Path(arguments[-2]).is_absolute())
        self.assertTrue(Path(arguments[-1]).is_absolute())
        self.assertTrue(str(spec.plist_path).startswith(str(Path.home() / "Library/LaunchAgents")))

    @patch.dict("os.environ", {"DE67_CODEX_STATE": "/tmp/custom-codex.sqlite"})
    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    def test_service_preserves_explicit_codex_roster_database(self, _which) -> None:
        payload = plistlib.loads(supervisor_service.service_spec(self.workspace).plist_bytes)
        self.assertEqual(
            payload["EnvironmentVariables"]["DE67_CODEX_STATE"],
            str(Path("/tmp/custom-codex.sqlite").resolve()),
        )

    @patch.dict("os.environ", {"DE67_CODEX": "/custom/bin/codex"})
    @patch("supervisor_service.shutil.which", return_value="/custom/bin/codex")
    def test_service_preserves_configured_codex_executable(self, which) -> None:
        payload = plistlib.loads(supervisor_service.service_spec(self.workspace).plist_bytes)
        which.assert_called_once_with("/custom/bin/codex")
        self.assertEqual(
            payload["EnvironmentVariables"]["DE67_CODEX"], "/custom/bin/codex"
        )

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_start_refuses_second_loaded_instance(self, run, _which) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "state = running", "")
        with self.assertRaisesRegex(supervisor_service.ServiceError, "already running"):
            supervisor_service.start_service(self.workspace)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertIn("print", run.call_args.args[0])

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_start_bootstraps_after_proving_service_absent(self, run, _which) -> None:
        run.side_effect = [
            subprocess.CompletedProcess([], 113, "", "not found"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "12345\n", ""),
        ]
        spec = supervisor_service.start_service(self.workspace)
        self.assertTrue(spec.plist_path.is_file())
        self.assertEqual(run.call_args_list[1].args[0][1], "bootstrap")
        self.assertEqual(
            run.call_args_list[2].args[0],
            ["/bin/launchctl", "kickstart", "-p", spec.domain_target],
        )

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_start_reloads_loaded_stopped_service(self, run, _which) -> None:
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "state = exited", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "12345\n", ""),
        ]
        spec = supervisor_service.start_service(self.workspace)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/bin/launchctl", "bootout", spec.domain_target],
        )
        self.assertEqual(run.call_args_list[2].args[0][1], "bootstrap")

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_stop_uses_launchd_job_identity(self, run, _which) -> None:
        spec = supervisor_service.service_spec(self.workspace)
        spec.plist_path.parent.mkdir(parents=True, exist_ok=True)
        spec.plist_path.touch()
        run.side_effect = [
            subprocess.CompletedProcess([], 0, "state = running", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        spec = supervisor_service.stop_service(self.workspace)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/bin/launchctl", "bootout", spec.domain_target],
        )
        self.assertFalse(spec.plist_path.exists())

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_start_rejects_immediate_supervisor_exit(self, run, _which) -> None:
        run.side_effect = [
            subprocess.CompletedProcess([], 113, "", "not found"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 5, "", "exited"),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        spec = supervisor_service.service_spec(self.workspace)
        with self.assertRaisesRegex(supervisor_service.ServiceError, "exited during"):
            supervisor_service.start_service(self.workspace)
        self.assertFalse(spec.plist_path.exists())
        self.assertEqual(run.call_args_list[3].args[0][1], "bootout")

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/codex")
    @patch("supervisor_service.subprocess.run")
    def test_failed_bootstrap_removes_partial_install(self, run, _which) -> None:
        run.side_effect = [
            subprocess.CompletedProcess([], 113, "", "not found"),
            subprocess.CompletedProcess([], 5, "", "bootstrap failed"),
        ]
        spec = supervisor_service.service_spec(self.workspace)
        with self.assertRaisesRegex(supervisor_service.ServiceError, "bootstrap failed"):
            supervisor_service.start_service(self.workspace)
        self.assertFalse(spec.plist_path.exists())

    @patch("supervisor_service.subprocess.run")
    def test_status_and_stop_do_not_require_healthy_workspace(self, run) -> None:
        broken = self.root / "missing-workspace"
        run.side_effect = [
            subprocess.CompletedProcess([], 113, "", "not found"),
            subprocess.CompletedProcess([], 113, "", "not found"),
        ]
        spec, status = supervisor_service.status_service(broken)
        self.assertEqual(status, "stopped")
        self.assertEqual(supervisor_service.stop_service(broken).label, spec.label)

    @patch("supervisor_service.subprocess.run")
    def test_stop_removes_plist_when_job_is_already_unloaded(self, run) -> None:
        spec = supervisor_service.service_identity(self.workspace)
        spec.plist_path.parent.mkdir(parents=True, exist_ok=True)
        spec.plist_path.touch()
        run.return_value = subprocess.CompletedProcess([], 113, "", "not found")
        supervisor_service.stop_service(self.workspace)
        self.assertFalse(spec.plist_path.exists())
        self.assertEqual(len(run.call_args_list), 1)

    @patch("supervisor_service.subprocess.run")
    def test_query_failure_does_not_masquerade_as_stopped(self, run) -> None:
        spec = supervisor_service.service_identity(self.workspace)
        spec.plist_path.parent.mkdir(parents=True, exist_ok=True)
        spec.plist_path.touch()
        run.return_value = subprocess.CompletedProcess([], 1, "", "permission denied")
        with self.assertRaisesRegex(supervisor_service.ServiceError, "permission denied"):
            supervisor_service.stop_service(self.workspace)
        self.assertTrue(spec.plist_path.exists())
        with self.assertRaisesRegex(supervisor_service.ServiceError, "permission denied"):
            supervisor_service.status_service(self.workspace)


if __name__ == "__main__":
    unittest.main()
