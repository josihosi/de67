from __future__ import annotations
import json, os, shlex, shutil, subprocess, sys, tempfile, time, unittest
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
        self.assertIn("DE67_COORDINATOR_SANDBOX=danger-full-access", words)
        self.assertEqual(
            len([word for word in words if word.startswith("DE67_SUPERVISOR_START_TOKEN=")]),
            1,
        )
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

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_exiting_final_tmux_server_is_normal_absence(self, run, _which):
        run.return_value = subprocess.CompletedProcess([],1,"","server exited unexpectedly")
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

    @unittest.skipUnless(
        os.environ.get("DE67_RUN_SERVICE_STACK_INTEGRATION") == "1",
        "real multi-round tmux stack integration is opt-in",
    )
    def test_real_tmux_service_runs_multiple_rounds_mutation_and_fresh_coordinator(self):
        root = os.environ.get("DE67_SERVICE_TEST_ROOT")
        fixture_root = Path(__file__).parent / "fixtures"
        environment_root = fixture_root / "service_stack_environment"
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            base = Path(temporary)
            workspace = (base / "workspace").resolve()
            state_root = workspace / ".de67/state"
            state_root.mkdir(parents=True)
            shutil.copy2(environment_root / "DFS.md", workspace / ".de67/DFS.md")
            shutil.copy2(environment_root / "work-ledger.md", workspace / ".de67/work-ledger.md")
            shutil.copy2(
                environment_root / "mutation-suggestions.md",
                workspace / ".de67/mutation-suggestions.md",
            )
            shutil.copy2(environment_root / "product.txt", workspace / "product.txt")

            state = state_root / "deadlines.sqlite3"
            from deadline_harness import DeadlineHarness
            with DeadlineHarness(state) as harness:
                harness.start_task("stack-test", "bootstrap", "R-STACK", 60, now=time.time())
                harness.complete_task("stack-test", "bootstrap", "stack fixture ready")
            # A prior external supervisor may have attempted this exact durable
            # frontier. The explicit new service start must get one fresh epoch.
            from coordinator_supervisor import SupervisorJournal, supervision_fingerprint
            prior = SupervisorJournal(state, "stack-test", "prior-service")
            prior.begin(
                "coordinator",
                supervision_fingerprint(state, "stack-test", workspace),
                "prior-run",
            )
            prior.finish("prior-run", "failed", "simulated prior service death")
            (state_root / "workspace.json").write_text(json.dumps(
                {"workspace": str(workspace),
                 "clock": {"state": str(state), "lineage": "stack-test"}}
            ))

            scripts = base / "scripts"
            scripts.mkdir()
            for name in (
                "supervisor_service.py", "coordinator_supervisor.py", "codex_runner.py",
                "deadline_harness.py", "blocker_adapter.py", "policy_kernel.py",
            ):
                shutil.copy2(SCRIPTS / name, scripts / name)
            fake_codex = scripts / "service_stack_fake_codex.py"
            shutil.copy2(fixture_root / "service_stack_fake_codex.py", fake_codex)
            fake_codex.chmod(0o755)

            environment = os.environ.copy()
            environment.update({
                "DE67_CODEX": str(fake_codex),
                "DE67_TMUX": shutil.which("tmux") or "",
            })
            command = [sys.executable, str(scripts / "supervisor_service.py")]
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

                (state_root / "service-test-release").touch()
                # Four local Python process boundaries complete well inside the
                # bootstrap clock; use that clock as the integration failure bound.
                with DeadlineHarness(state) as harness:
                    deadline = float(harness.status_task("stack-test", "bootstrap")["deadline_at"])
                while time.time() < deadline:
                    current = subprocess.run(
                        [*command, "status", "--workspace", str(workspace)],
                        env=environment, text=True, capture_output=True,
                    )
                    self.assertEqual(current.returncode, 0, current.stderr)
                    if json.loads(current.stdout)["service"] == "stopped":
                        break
                    time.sleep(0.05)
                else:
                    self.fail("multi-round tmux stack did not finish before its bootstrap deadline")
            finally:
                stopped = subprocess.run(
                    [*command, "stop", "--workspace", str(workspace)],
                    env=environment, text=True, capture_output=True,
                )
            self.assertEqual(stopped.returncode, 0, stopped.stderr)

            events = [json.loads(line) for line in
                      (state_root / "stack-events.jsonl").read_text().splitlines()]
            self.assertEqual([event["role"] for event in events], [
                "coordinator", "coordinator", "mutation-reviewer", "coordinator",
            ])
            self.assertTrue(all(event["sandbox"] == "danger-full-access" for event in events))
            self.assertEqual(len({event["start_token"] for event in events}), 1)
            self.assertTrue(events[0]["start_token"])
            self.assertEqual(events[-1]["generation"], "1")
            self.assertEqual((workspace / "product.txt").read_text().splitlines(), [
                "Editable stack-test product state.",
                "round one worker result",
                "round two worker result",
                "mutation reviewer inspected editable state",
                "post-mutation worker result",
            ])
            self.assertIn("- [x] R-STACK", (workspace / ".de67/DFS.md").read_text())
            self.assertNotIn("- [ ]", (workspace / ".de67/work-ledger.md").read_text())
            self.assertIn("Consumed by stack mutation reviewer", (
                workspace / ".de67/mutation-suggestions.md").read_text())

    @patch("supervisor_service.shutil.which", return_value="/opt/bin/tmux")
    @patch("supervisor_service.subprocess.run")
    def test_query_error_is_not_absence(self, run, _which):
        run.return_value = subprocess.CompletedProcess([],2,"","server failure")
        with self.assertRaisesRegex(supervisor_service.ServiceError, "server failure"):
            supervisor_service.status_service(self.workspace)

if __name__ == "__main__": unittest.main()
