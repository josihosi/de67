from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "policy_compare.py"
POLICY = ROOT / "assets" / "environment" / "phase3-policy.d67"
CONTRACTS = ROOT / "assets" / "environment" / "phase3-contracts.json"
BASELINE_REF = "backup/pre-lab-lab-20260822"
HAS_REPOSITORY_HISTORY = (ROOT.parent / ".git").exists()
SPEC = importlib.util.spec_from_file_location("de67_policy_compare", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
compare_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = compare_module
SPEC.loader.exec_module(compare_module)


class PolicyComparisonTests(unittest.TestCase):
    def test_contract_manifest_is_machine_canonical_and_named(self) -> None:
        value = json.loads(CONTRACTS.read_text(encoding="utf-8"))
        self.assertEqual(value["format"], "de67.phase3.contracts")
        names = [case["name"] for case in value["decision_cases"] + value["trace_cases"]]
        self.assertEqual(len(names), len(set(names)))

    @unittest.skipUnless(HAS_REPOSITORY_HISTORY, "comparison needs de67 Git history")
    def test_main_and_lab_comparison_has_only_declared_strengthenings(self) -> None:
        report = compare_module.compare(POLICY, CONTRACTS, BASELINE_REF)
        self.assertTrue(report["passed"])
        self.assertLess(report["ratio"], 1)
        divergences = {
            case["name"] for case in report["trace_cases"]
            if case["main"] != case["lab"]
        }
        self.assertEqual(divergences, {
            "late-acceptance-before-review",
            "worker-terminal-without-receipt",
            "mutation-ignores-suggestion",
            "proof-owner-replacement-leaves-stale-projection",
        })

    @unittest.skipUnless(HAS_REPOSITORY_HISTORY, "comparison needs de67 Git history")
    def test_comparison_cli_is_reproducible(self) -> None:
        command = [
            sys.executable, str(SCRIPT), "--policy", str(POLICY),
            "--contracts", str(CONTRACTS), "--baseline-ref", BASELINE_REF,
        ]
        first = subprocess.run(command, text=True, capture_output=True)
        second = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertTrue(json.loads(first.stdout)["passed"])

    def test_missing_baseline_fails_closed(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--policy", str(POLICY),
             "--contracts", str(CONTRACTS), "--baseline-ref", "missing-ref"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)


if __name__ == "__main__":
    unittest.main()
