from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workspace_setup import (  # noqa: E402
    CONFIG_RELATIVE_PATH,
    DEADLINE_STATE_RELATIVE_PATH,
    MANAGED_HOOK_MARKER,
    PUSH_STATUS_RELATIVE_PATH,
    SetupError,
    configure,
    push_checkpoints,
)
import workspace_setup  # noqa: E402


VERIFIED_WORKERS = (
    ("gpt-5.6-luna", "high"),
    ("gpt-5.6-terra", "low"),
)


class WorkspaceSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.origin = self.root / "origin.git"
        self.workspace = self.root / "work"
        self.git(self.root, "init", "--bare", str(self.origin))
        self.git(self.root, "init", str(self.workspace))
        self.git(self.workspace, "config", "user.name", "DE67 Test")
        self.git(self.workspace, "config", "user.email", "de67@example.invalid")
        self.git(self.workspace, "checkout", "-b", "dev")
        (self.workspace / ".gitignore").write_text(
            ".de67/state/\n", encoding="utf-8"
        )
        (self.workspace / "tracked.txt").write_text("one\n", encoding="utf-8")
        self.git(self.workspace, "add", ".gitignore", "tracked.txt")
        self.git(self.workspace, "commit", "-m", "initial")
        self.git(self.workspace, "remote", "add", "origin", str(self.origin))
        self.git(self.workspace, "push", "-u", "origin", "dev")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def git(cwd: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            text=True,
            capture_output=True,
            check=check,
        )

    def head(self, repository: Path, reference: str = "HEAD") -> str:
        return self.git(repository, "rev-parse", reference).stdout.strip()

    def configure_push(self) -> dict[str, object]:
        return configure(
            self.workspace, [("origin", "dev")], bind_clock=False
        )

    def commit_file(self, name: str, content: str, message: str) -> str:
        (self.workspace / name).write_text(content, encoding="utf-8")
        self.git(self.workspace, "add", name)
        self.git(self.workspace, "commit", "-m", message)
        return self.head(self.workspace)

    def freeze_dfs(self) -> None:
        (self.workspace / ".de67").mkdir(exist_ok=True)
        (self.workspace / ".de67/DFS.md").write_text(
            "# Feature DFS\n\nStatus: Frozen against inspected source baseline\n",
            encoding="utf-8",
        )

    def test_configuration_pushes_backlog_and_post_commit_pushes_next_head(self) -> None:
        backlog = self.commit_file("tracked.txt", "two\n", "backlog")
        result = self.configure_push()

        self.assertTrue(result["push"]["ok"])
        self.assertEqual(self.head(self.origin, "refs/heads/dev"), backlog)
        hook = Path(str(result["hook"]))
        self.assertIn(MANAGED_HOOK_MARKER, hook.read_text(encoding="utf-8"))

        next_head = self.commit_file("next.txt", "next\n", "next")
        self.assertEqual(self.head(self.origin, "refs/heads/dev"), next_head)

    def test_configuration_rejects_multiple_automatic_targets(self) -> None:
        checkpoint = self.root / "checkpoint.git"
        self.git(self.root, "init", "--bare", str(checkpoint))
        self.git(self.workspace, "remote", "add", "checkpoint", str(checkpoint))

        with self.assertRaisesRegex(SetupError, "Exactly one --target"):
            configure(
                self.workspace,
                [("origin", "dev"), ("checkpoint", "main")],
                bind_clock=False,
            )

    def test_repeated_setup_is_idempotent_and_rejects_added_target(self) -> None:
        self.freeze_dfs()
        first = configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            lineage="stable-lineage",
            worker_capabilities=VERIFIED_WORKERS,
        )
        initial_config = json.loads(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
        )

        repeated = configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            worker_capabilities=VERIFIED_WORKERS,
        )
        repeated_config = json.loads(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(repeated_config, initial_config)
        self.assertEqual(repeated["clock"], first["clock"])

        checkpoint = self.root / "checkpoint-additive.git"
        self.git(self.root, "init", "--bare", str(checkpoint))
        self.git(self.workspace, "remote", "add", "checkpoint", str(checkpoint))
        with self.assertRaisesRegex(SetupError, "Exactly one --target"):
            configure(
                self.workspace,
                [("origin", "dev"), ("checkpoint", "main")],
                bind_clock=True,
                worker_capabilities=VERIFIED_WORKERS,
            )
        self.assertEqual(
            json.loads(
                (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
            ),
            initial_config,
        )

    def test_repeated_setup_cannot_repin_changed_remote_url(self) -> None:
        self.freeze_dfs()
        configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            lineage="stable-lineage",
            worker_capabilities=VERIFIED_WORKERS,
        )
        original_config = (self.workspace / CONFIG_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
        replacement = self.root / "replacement-for-setup.git"
        self.git(self.root, "init", "--bare", str(replacement))
        self.git(
            self.workspace,
            "remote",
            "set-url",
            "--push",
            "origin",
            str(replacement),
        )

        with self.assertRaisesRegex(SetupError, "URL cannot be changed"):
            configure(
                self.workspace,
                [("origin", "dev")],
                bind_clock=True,
                worker_capabilities=VERIFIED_WORKERS,
            )
        self.assertEqual(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8"),
            original_config,
        )

    def test_repeated_setup_cannot_repin_changed_source_branch(self) -> None:
        self.freeze_dfs()
        configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            lineage="stable-lineage",
            worker_capabilities=VERIFIED_WORKERS,
        )
        original_config = (self.workspace / CONFIG_RELATIVE_PATH).read_text(
            encoding="utf-8"
        )
        self.git(self.workspace, "checkout", "-b", "other")
        self.git(self.workspace, "push", "-u", "origin", "other")

        with self.assertRaisesRegex(SetupError, "source branch cannot be changed"):
            configure(
                self.workspace,
                [("origin", "other")],
                bind_clock=True,
                worker_capabilities=VERIFIED_WORKERS,
            )
        self.assertEqual(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8"),
            original_config,
        )

    def test_dirty_worktree_pushes_only_committed_head(self) -> None:
        self.configure_push()
        (self.workspace / "tracked.txt").write_text("dirty and local\n", encoding="utf-8")
        committed = self.commit_file("separate.txt", "committed\n", "separate")

        self.assertEqual(self.head(self.origin, "refs/heads/dev"), committed)
        self.assertIn(" M tracked.txt", self.git(self.workspace, "status", "--short").stdout)
        status = json.loads(
            (self.workspace / PUSH_STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertNotIn("dirty", status)
        self.assertTrue(status["ok"])

    def test_wrong_branch_is_not_pushed(self) -> None:
        self.configure_push()
        original_remote = self.head(self.origin, "refs/heads/dev")
        self.git(self.workspace, "checkout", "-b", "other")
        other_head = self.commit_file("other.txt", "other\n", "other")

        self.assertNotEqual(other_head, original_remote)
        self.assertEqual(self.head(self.origin, "refs/heads/dev"), original_remote)
        with self.assertRaisesRegex(SetupError, "Configured source"):
            push_checkpoints(self.workspace)
        status = json.loads(
            (self.workspace / PUSH_STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertFalse(status["ok"])
        self.assertIn("Configured source", status["error"])

    def test_unconfigured_sibling_worktree_does_not_use_shared_hook(self) -> None:
        self.configure_push()
        original_remote = self.head(self.origin, "refs/heads/dev")
        sibling = self.root / "sibling"
        self.git(self.workspace, "worktree", "add", "-b", "sibling", str(sibling))
        (sibling / "sibling.txt").write_text("sibling\n", encoding="utf-8")
        self.git(sibling, "add", "sibling.txt")
        self.git(sibling, "commit", "-m", "sibling")

        self.assertFalse((sibling / CONFIG_RELATIVE_PATH).exists())
        self.assertEqual(self.head(self.origin, "refs/heads/dev"), original_remote)

    def test_changed_remote_url_is_recorded_as_a_safe_push_failure(self) -> None:
        self.configure_push()
        replacement = self.root / "replacement.git"
        self.git(self.root, "init", "--bare", str(replacement))
        self.git(
            self.workspace,
            "remote",
            "set-url",
            "--push",
            "origin",
            str(replacement),
        )

        status = push_checkpoints(self.workspace)

        self.assertFalse(status["ok"])
        self.assertIn("URL changed", status["targets"][0]["error"])
        self.assertEqual(
            self.head(self.origin, "refs/heads/dev"), self.head(self.workspace)
        )

    def test_changed_upstream_and_detached_head_are_refused(self) -> None:
        self.configure_push()
        self.git(self.workspace, "push", "origin", "HEAD:refs/heads/other")
        self.git(
            self.workspace,
            "branch",
            "--set-upstream-to=origin/other",
            "dev",
        )
        with self.assertRaisesRegex(SetupError, "upstream changed"):
            push_checkpoints(self.workspace)
        status = json.loads(
            (self.workspace / PUSH_STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertFalse(status["ok"])
        self.assertIn("upstream changed", status["error"])

        self.git(self.workspace, "branch", "--set-upstream-to=origin/dev", "dev")
        self.git(self.workspace, "checkout", "--detach")
        with self.assertRaisesRegex(SetupError, "attached local branch"):
            push_checkpoints(self.workspace)
        status = json.loads(
            (self.workspace / PUSH_STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertFalse(status["ok"])
        self.assertIn("attached local branch", status["error"])

    def test_custom_hooks_path_outside_common_git_dir_is_refused(self) -> None:
        custom_hooks = self.root / "shared-hooks"
        self.git(self.workspace, "config", "core.hooksPath", str(custom_hooks))

        with self.assertRaisesRegex(SetupError, "core.hooksPath"):
            self.configure_push()

        self.assertFalse((custom_hooks / "post-commit").exists())

    def test_file_only_state_ignore_rules_do_not_satisfy_setup(self) -> None:
        (self.workspace / ".gitignore").write_text(
            ".de67/state/workspace.json\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(SetupError, "whole .de67/state"):
            self.configure_push()

        self.assertFalse((self.workspace / CONFIG_RELATIVE_PATH).exists())

    def test_push_explicitly_disables_force_tags_and_submodule_recursion(self) -> None:
        self.configure_push()
        self.git(self.workspace, "tag", "-a", "local-only", "-m", "local only")
        self.git(self.workspace, "config", "push.followTags", "true")
        self.git(self.workspace, "config", "push.recurseSubmodules", "on-demand")

        with patch("workspace_setup._run_git", wraps=workspace_setup._run_git) as run:
            result = push_checkpoints(self.workspace)

        push_arguments = [
            call.args[1]
            for call in run.call_args_list
            if call.args[1] and call.args[1][0] == "push"
        ]
        self.assertEqual(len(push_arguments), 1)
        self.assertIn("--no-force", push_arguments[0])
        self.assertIn("--no-follow-tags", push_arguments[0])
        self.assertIn("--recurse-submodules=no", push_arguments[0])
        self.assertTrue(result["ok"])
        remote_tag = self.git(
            self.origin,
            "show-ref",
            "--verify",
            "refs/tags/local-only",
            check=False,
        )
        self.assertNotEqual(remote_tag.returncode, 0)

    def test_non_fast_forward_is_rejected_without_losing_local_commit(self) -> None:
        self.configure_push()
        rival = self.root / "rival"
        self.git(self.root, "clone", "--branch", "dev", str(self.origin), str(rival))
        self.git(rival, "config", "user.name", "Rival")
        self.git(rival, "config", "user.email", "rival@example.invalid")
        (rival / "rival.txt").write_text("rival\n", encoding="utf-8")
        self.git(rival, "add", "rival.txt")
        self.git(rival, "commit", "-m", "rival")
        self.git(rival, "push", "origin", "dev")
        remote_head = self.head(self.origin, "refs/heads/dev")

        local_head = self.commit_file("local.txt", "local\n", "local")
        self.assertEqual(self.head(self.workspace), local_head)
        self.assertEqual(self.head(self.origin, "refs/heads/dev"), remote_head)
        self.assertNotEqual(local_head, remote_head)
        status = json.loads(
            (self.workspace / PUSH_STATUS_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertFalse(status["ok"])
        self.assertFalse(status["targets"][0]["ok"])

    def test_unmanaged_hook_is_never_overwritten(self) -> None:
        hook_text = "#!/bin/sh\necho owner\n"
        hook_raw = self.git(
            self.workspace, "rev-parse", "--git-path", "hooks/post-commit"
        ).stdout.strip()
        hook = Path(hook_raw)
        if not hook.is_absolute():
            hook = self.workspace / hook
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(hook_text, encoding="utf-8")

        with self.assertRaisesRegex(SetupError, "unmanaged hook"):
            self.configure_push()
        self.assertEqual(hook.read_text(encoding="utf-8"), hook_text)

    def test_managed_marker_does_not_authorize_overwriting_extra_commands(self) -> None:
        result = self.configure_push()
        hook = Path(str(result["hook"]))
        modified = hook.read_text(encoding="utf-8") + "echo user-owned\n"
        hook.write_text(modified, encoding="utf-8")

        with self.assertRaisesRegex(SetupError, "modified managed hook"):
            self.configure_push()
        self.assertEqual(hook.read_text(encoding="utf-8"), modified)

    def test_phase_two_setup_binds_clock_after_frozen_dfs(self) -> None:
        (self.workspace / ".de67").mkdir()
        (self.workspace / ".de67/DFS.md").write_text(
            "# Feature DFS\n\nStatus: Refrozen against inspected source baseline\n",
            encoding="utf-8",
        )
        result = configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            lineage="feature-lineage",
            worker_capabilities=VERIFIED_WORKERS,
        )

        self.assertEqual(result["clock"]["lineage"], "feature-lineage")
        config = json.loads(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(config["clock"]["lineage"], "feature-lineage")
        connection = sqlite3.connect(config["clock"]["state"])
        try:
            bound = connection.execute(
                "SELECT lineage_id FROM lineage_binding WHERE singleton = 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(bound, ("feature-lineage",))

    def test_phase_two_records_only_successfully_probed_worker_pairs(self) -> None:
        self.freeze_dfs()
        passed = (("gpt-5.6-luna", "high"), ("gpt-5.6-terra", "low"))

        configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            worker_capabilities=passed,
        )

        config = json.loads(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["worker_capabilities"],
            [
                {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
                {"model": "gpt-5.6-terra", "reasoning_effort": "low"},
            ],
        )

    def test_phase_two_requires_luna_terra_and_distinct_efforts(self) -> None:
        self.freeze_dfs()

        invalid_rosters = (
            (),
            (("gpt-5.6-luna", "high"),),
            (("gpt-5.6-luna", "high"), ("gpt-5.6-terra", "high")),
        )
        for roster in invalid_rosters:
            with self.subTest(roster=roster), self.assertRaises(SetupError):
                configure(
                    self.workspace,
                    [("origin", "dev")],
                    bind_clock=True,
                    worker_capabilities=roster,
                )

        self.assertFalse((self.workspace / CONFIG_RELATIVE_PATH).exists())

    def test_repeated_phase_two_setup_replaces_the_roster_with_fresh_probe_results(self) -> None:
        self.freeze_dfs()
        configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            worker_capabilities=VERIFIED_WORKERS,
        )

        replacement = (
            ("gpt-5.6-luna", "low"),
            ("gpt-5.6-terra", "medium"),
        )
        configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            worker_capabilities=replacement,
        )

        config = json.loads(
            (self.workspace / CONFIG_RELATIVE_PATH).read_text(encoding="utf-8")
        )
        self.assertEqual(
            config["worker_capabilities"],
            [
                {"model": "gpt-5.6-luna", "reasoning_effort": "low"},
                {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
            ],
        )

    def test_phase_two_setup_initializes_an_empty_sqlite_state_file(self) -> None:
        self.freeze_dfs()
        state_path = self.workspace / DEADLINE_STATE_RELATIVE_PATH
        state_path.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(state_path).close()

        result = configure(
            self.workspace,
            [("origin", "dev")],
            bind_clock=True,
            lineage="empty-state-lineage",
            worker_capabilities=VERIFIED_WORKERS,
        )

        self.assertEqual(result["clock"]["lineage"], "empty-state-lineage")
        connection = sqlite3.connect(state_path)
        try:
            bound = connection.execute(
                "SELECT lineage_id FROM lineage_binding WHERE singleton = 1"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(bound, ("empty-state-lineage",))

    def test_default_lineage_uses_primary_upstream_when_origin_is_absent(self) -> None:
        self.git(self.workspace, "remote", "rename", "origin", "primary")
        (self.workspace / ".de67").mkdir()
        (self.workspace / ".de67/DFS.md").write_text(
            "# Feature DFS\n\nStatus: Frozen against inspected source baseline\n",
            encoding="utf-8",
        )

        result = configure(
            self.workspace,
            [("primary", "dev")],
            bind_clock=True,
            worker_capabilities=VERIFIED_WORKERS,
        )

        self.assertEqual(result["clock"]["lineage"], "origin:dev")


if __name__ == "__main__":
    unittest.main()
