from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import policy_kernel as kernel
from deadline_harness import DeadlineHarness

CLAIM = "multi-machine-parallel-play-roadmap"
TASK = "multi-machine-source-sync-candidate-001"
LEDGER = (f"- [ ] {CLAIM} — One coordinator, source-sync readiness.\n"
          "  - Method candidate: Stage source-sync code and disposable controls in .de67/task-logs/sync/.\n"
          f"  - Assignment {TASK}: Prove selected commits replace source only; preserve saved state.\n")

class MethodCandidateRouteTests(unittest.TestCase):
    def workspace(self, root, ledger=LEDGER):
        d = root / ".de67"
        d.mkdir()
        (d / "work-ledger.md").write_text(ledger)
        (d / "FS.md").write_text("# Frozen product FS\nNo gameplay claim belongs to this method assignment.\n")
        (d / "WEC.md").write_text("<!-- DE67:OWNER-CONTRACT:BEGIN -->\nMac authoritative; preserve runtime saves.\n<!-- DE67:OWNER-CONTRACT:END -->")
        return d

    def test_start_decide_real_packet_no_product_slice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace(root)
            state = root / "state.sqlite3"
            with DeadlineHarness(state) as h:
                h.start_task("project", TASK, CLAIM, 100000, now=100)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/policy_kernel.py"),
                "decide", "--policy", str(ROOT / "assets/environment/phase3-policy.d67"),
                "--workspace", str(root), "--state", str(state), "--lineage", "project", "--now", "101"],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = json.loads(result.stdout)["worker_spawns"]
            self.assertEqual(len(calls), 1)
            call = calls[0]
            self.assertEqual(call["task_id"], TASK)
            packet = Path(call["dispatch_packet"]["path"]).read_text()
            for text in ("Prove selected commits", "Staged method candidate:", "Do not edit installed",
                         "supervisor activation remain separate", "Mac authoritative"):
                self.assertIn(text, packet)
            self.assertNotIn(".de67/FS.md slice for " + CLAIM, packet)
            self.assertNotIn(".agents/skills/caol-harness/SKILL.md", packet)
            import sqlite3
            with sqlite3.connect(state) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_claims").fetchone()[0], 0)

    def test_markers_cannot_escape_owning_item_or_fence(self):
        cases = [LEDGER.replace("- [ ]", "- [x]", 1),
                 "```\n" + LEDGER + "```\n",
                 LEDGER.replace("  - Method candidate:", "  - Historical candidate:"),
                 LEDGER.split("  - Assignment")[0] + "## Other\n" + LEDGER[LEDGER.index("  - Assignment"):],
                 LEDGER.replace("  - Assignment", "```\n  - Assignment") + "```\n"]
        for ledger in cases:
            with self.subTest(ledger=ledger):
                self.assertIsNone(kernel._method_candidate_route(ledger, CLAIM, TASK))
        with self.assertRaises(kernel.PolicyError):
            kernel._method_candidate_route(LEDGER + LEDGER, CLAIM, TASK)
        with self.assertRaises(kernel.PolicyError):
            kernel._method_candidate_route(LEDGER.replace("Stage source-sync code and disposable controls in .de67/task-logs/sync/.", ""), CLAIM, TASK)

    def test_product_route_still_requires_real_fs_slice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace(root, LEDGER.replace(CLAIM, "R-PRODUCT"))
            with self.assertRaises(kernel.PolicyError):
                kernel._exploration_route(root, "R-PRODUCT", TASK)

    def test_method_only_ledger_exposes_executable_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.workspace(root)
            state = root / "state.sqlite3"
            with DeadlineHarness(state) as h:
                h.start_task("project", TASK, CLAIM, 100000, now=100)
            facts = kernel.workspace_facts(root, state, "project", now=101)
            self.assertIn("executable_route", facts)
            self.assertIn("red_dfs_work", facts)

if __name__ == "__main__":
    unittest.main()
