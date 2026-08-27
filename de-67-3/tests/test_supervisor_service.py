from __future__ import annotations
import json, os, shlex, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"; sys.path.insert(0, str(SCRIPTS))
import supervisor_service  # noqa: E402

class SupervisorServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.workspace = (self.root / "workspace").resolve(); (self.workspace / ".de67/state").mkdir(parents=True)
        self.state = self.workspace / ".de67/state/deadlines.sqlite3"; self.state.touch()
        (self.workspace / ".de67/state/workspace.json").write_text(json.dumps(
            {"workspace": str(self.workspace), "clock": {"state": str(self.state), "lineage": "lineage"}}))
        self.platform = patch("supervisor_service.sys.platform", "darwin"); self.platform.start()
        self.legacy_loaded = patch("supervisor_service._legacy_loaded", return_value=False)
        self.legacy_loaded.start()
    def tearDown(self): self.legacy_loaded.stop(); self.platform.stop(); self.temp.cleanup()

    @patch("supervisor_service.shutil.which")
    def test_spec_preserves_environment_without_auto_restart(self, which):
        which.side_effect = lambda value: {"codex": "/opt/bin/codex", "tmux": "/opt/bin/tmux"}.get(value)
        spec = supervisor_service.service_spec(self.workspace); words = shlex.split(spec.shell_command)
        self.assertEqual(spec.tmux, "/opt/bin/tmux"); self.assertEqual(words[0], "exec")
        self.assertIn("DE67_CODEX=/opt/bin/codex", words); self.assertIn(f"PATH={os.environ['PATH']}", words)
        self.assertIn(str(self.state), words); self.assertIn("--runner", words); self.assertNotIn("launchctl", words)

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_status_and_stop_work_without_workspace_config(self, run, _which):
        run.return_value = subprocess.CompletedProcess([], 1, "", "can't find session")
        broken = self.root / "missing"; self.assertEqual(supervisor_service.status_service(broken)[1], "stopped")
        supervisor_service.stop_service(broken)

    @patch("supervisor_service.shutil.which")
    @patch("supervisor_service.subprocess.run")
    def test_start_creates_and_verifies_session(self, run, which):
        which.side_effect = lambda value: "/opt/bin/tmux" if value == "tmux" else "/opt/bin/codex"
        run.side_effect = [subprocess.CompletedProcess([],1,"","can't find session"),
                           subprocess.CompletedProcess([],0,"",""), subprocess.CompletedProcess([],0,"","")]
        spec = supervisor_service.start_service(self.workspace)
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[0:2], ["/opt/bin/tmux", "-S"])
        self.assertEqual(command[3:7], ["new-session","-d","-s",spec.label])

    @patch("supervisor_service.shutil.which")
    @patch("supervisor_service.subprocess.run")
    def test_start_rejects_immediate_exit(self, run, which):
        which.side_effect = lambda value: "/opt/bin/tmux" if value == "tmux" else "/opt/bin/codex"
        run.side_effect = [subprocess.CompletedProcess([],1,"","can't find session"),
                           subprocess.CompletedProcess([],0,"",""), subprocess.CompletedProcess([],1,"","can't find session")]
        with self.assertRaisesRegex(supervisor_service.ServiceError, "exited during"):
            supervisor_service.start_service(self.workspace)

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_stop_kills_exact_session(self, run, _which):
        run.side_effect = [subprocess.CompletedProcess([],0,"",""), subprocess.CompletedProcess([],0,"","")]
        spec = supervisor_service.stop_service(self.workspace)
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[0:2], ["/opt/bin/tmux", "-S"])
        self.assertEqual(command[3:], ["kill-session","-t",f"={spec.label}"])

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_missing_tmux_server_is_normal_absence(self, run, _which):
        run.return_value = subprocess.CompletedProcess([],1,"","no server running on /tmp/tmux")
        self.assertEqual(supervisor_service.status_service(self.workspace)[1], "stopped")

    @patch("supervisor_service._remove_legacy")
    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_stop_migrates_legacy_launchagent(self, run, _which, remove_legacy):
        run.return_value = subprocess.CompletedProcess([],1,"","no server running")
        spec = supervisor_service.stop_service(self.workspace)
        remove_legacy.assert_called_once()
        self.assertEqual(remove_legacy.call_args.args[0].label, spec.label)

    def test_legacy_status_does_not_require_tmux(self):
        with patch("supervisor_service._legacy_loaded", return_value=True), patch(
            "supervisor_service.shutil.which", return_value=None
        ):
            _spec, status = supervisor_service.status_service(self.workspace)
        self.assertEqual(status, "legacy-launchagent-loaded")

    @patch("supervisor_service.shutil.which")
    def test_start_preserves_live_legacy_owner(self, which):
        which.side_effect = lambda value: "/opt/bin/tmux" if value == "tmux" else "/opt/bin/codex"
        with patch("supervisor_service._legacy_loaded", return_value=True), patch(
            "supervisor_service._remove_legacy"
        ) as remove:
            with self.assertRaisesRegex(supervisor_service.ServiceError, "run stop, then start"):
                supervisor_service.start_service(self.workspace)
        remove.assert_not_called()

    @unittest.skipUnless(
        os.environ.get("DE67_RUN_SERVICE_INTEGRATION") == "1",
        "real tmux service integration is opt-in",
    )
    def test_real_tmux_service_survives_separate_control_processes(self):
        root = os.environ.get("DE67_SERVICE_TEST_ROOT")
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            base = Path(temporary)
            workspace = base / "workspace"
            (workspace / ".de67/state").mkdir(parents=True)
            state = workspace / ".de67/state/deadlines.sqlite3"
            state.touch()
            (workspace / ".de67/state/workspace.json").write_text(
                json.dumps({"workspace": str(workspace.resolve()),
                            "clock": {"state": str(state.resolve()), "lineage": "smoke"}})
            )
            scripts = base / "scripts"
            scripts.mkdir()
            launcher = scripts / "supervisor_service.py"
            shutil.copy2(SCRIPTS / "supervisor_service.py", launcher)
            shutil.copy2(
                Path(__file__).parent / "fixtures/service_fake_supervisor.py",
                scripts / "coordinator_supervisor.py",
            )
            (scripts / "codex_runner.py").touch()
            environment = os.environ.copy()
            environment.update({"DE67_CODEX": "/usr/bin/true", "DE67_TMUX": shutil.which("tmux") or ""})
            command = [sys.executable, str(launcher)]
            try:
                started = subprocess.run(
                    [*command, "start", "--workspace", str(workspace)],
                    env=environment, text=True, capture_output=True,
                )
                self.assertEqual(started.returncode, 0, started.stderr)
                status = subprocess.run(
                    [*command, "status", "--workspace", str(workspace)],
                    env=environment, text=True, capture_output=True,
                )
                self.assertEqual(status.returncode, 0, status.stderr)
                self.assertIn("pid=", json.loads(status.stdout)["service"])
            finally:
                stopped = subprocess.run(
                    [*command, "stop", "--workspace", str(workspace)],
                    env=environment, text=True, capture_output=True,
                )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)
            final_status = subprocess.run(
                [*command, "status", "--workspace", str(workspace)],
                env=environment, text=True, capture_output=True,
            )
            self.assertEqual(json.loads(final_status.stdout)["service"], "stopped")

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_query_error_is_not_absence(self, run, _which):
        run.return_value = subprocess.CompletedProcess([],2,"","server failure")
        with self.assertRaisesRegex(supervisor_service.ServiceError, "server failure"):
            supervisor_service.status_service(self.workspace)

if __name__ == "__main__": unittest.main()
