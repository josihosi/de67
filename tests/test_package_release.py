from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location(
    "package_release", Path(__file__).resolve().parents[1] / "scripts/package_release.py")
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class ReleasePackageTests(unittest.TestCase):
    def test_clean_tree_packages_are_separate_reproducible_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            for key, value in (("user.name", "Release test"), ("user.email", "test@example.invalid"),
                               ("core.autocrlf", "false")):
                subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
            tracked = {
                "LICENSE": "license\n", "SKILL.md": "core\n", "de-67-3/scripts/runner.py": "core code\n",
                "integrations/dashboard/README.md": "dashboard setup\n",
                "integrations/dashboard/de67_dashboard.py": "dashboard code\n",
                "integrations/direct_input/de67_agent_relay.py": "relay code\n",
                "integrations/openclaw_discord/SETUP.md": "discord setup\n",
                "docs/verification/history.md": "local development evidence\n",
            }
            for path, text in tracked.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-m", "fixture"],
                           check=True, capture_output=True)
            (root / "SKILL.md").write_text("uncommitted changes must not ship")
            (root / "private.log").write_text("untracked state must not ship")
            first = Path(directory) / "first"
            report = packaging.build(root, "HEAD", "3.0.0", first)
            second = Path(directory) / "second"
            self.assertEqual(report, packaging.build(root, "HEAD", "3.0.0", second))
            for artifact in report["artifacts"]:
                self.assertEqual((first / artifact["name"]).read_bytes(),
                                 (second / artifact["name"]).read_bytes())
                with zipfile.ZipFile(first / artifact["name"]) as archive:
                    names = set(archive.namelist())
                    self.assertNotIn("de67/private.log", names)
                    self.assertNotIn("de67/docs/verification/history.md", names)
                    manifest_path = next(p for p in names if p.startswith("de67/package-manifests/"))
                    manifest = json.loads(archive.read(manifest_path))
                    self.assertEqual(manifest["source_commit"], report["source_commit"])
                    for path, digest in manifest["files"].items():
                        self.assertEqual(hashlib.sha256(archive.read("de67/" + path)).hexdigest(), digest)
                    if manifest["package"] == "core":
                        self.assertEqual(archive.read("de67/SKILL.md"), b"core\n")
                        self.assertIn("de67/integrations/dashboard/README.md", names)
                        self.assertNotIn("de67/integrations/dashboard/de67_dashboard.py", names)
                        self.assertNotIn("de67/integrations/direct_input/de67_agent_relay.py", names)
                    else:
                        self.assertEqual(manifest["requires_core"], "3.0.0")
                        self.assertNotIn("de67/de-67-3/scripts/runner.py", names)
            with zipfile.ZipFile(first / "de67-3.0.0-dashboard.zip") as archive:
                self.assertIn("de67/integrations/dashboard/de67_dashboard.py", archive.namelist())
            with zipfile.ZipFile(first / "de67-3.0.0-discord.zip") as archive:
                self.assertIn("de67/integrations/direct_input/de67_agent_relay.py", archive.namelist())

    def test_unclassified_and_runtime_paths_fail_instead_of_shipping(self):
        for path in (".de67/state/clock.sqlite3", "de-67-3/private.log", "secrets.json",
                     "integrations/new-plugin/code.py", "scripts/__pycache__/x.pyc"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                packaging.package_for(path)


if __name__ == "__main__":
    unittest.main()
