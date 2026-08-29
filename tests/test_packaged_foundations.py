from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedFoundationTests(unittest.TestCase):
    def test_optional_alignment_audit_is_routed_and_self_contained(self) -> None:
        router = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        audit_root = ROOT / "alignment-audit"
        entrypoint = (audit_root / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("alignment-audit/SKILL.md", router)
        for reference in (
            "references/alignment-manifest.md",
            "references/reviewer-brief.md",
        ):
            with self.subTest(reference=reference):
                self.assertIn(reference, entrypoint)
                self.assertTrue((audit_root / reference).is_file())

        for phase in ("de-67-1", "de-67-2", "de-67-3"):
            with self.subTest(phase=phase):
                phase_entrypoint = (ROOT / phase / "SKILL.md").read_text(encoding="utf-8")
                self.assertNotIn("alignment-audit", phase_entrypoint)

    def test_reader_facing_brand_is_canonical(self) -> None:
        for path in ROOT.rglob("*.md"):
            if ".git" in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("DE67", path.read_text(encoding="utf-8"))

    def test_verbatim_foundations_are_unchanged(self) -> None:
        expected = {
            "references/imagination-round.md":
                "6276090f543c7ac25a2ccde49975be87ae6b0ed2b4d279adff39f36e6fdb8f09",
            "references/msw-kernel.md":
                "fbf42b98a155a7638c92ca7bc6114b4f2a61726d0e35048ee100bc7db957d95f",
        }

        for relative_path, expected_hash in expected.items():
            with self.subTest(relative_path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                normalized = text.replace("\r\n", "\n").encode("utf-8")
                actual = hashlib.sha256(normalized).hexdigest()
                self.assertEqual(actual, expected_hash)

    def test_phases_route_to_the_shared_foundations(self) -> None:
        phase_one = (ROOT / "de-67-1/SKILL.md").read_text(encoding="utf-8")
        phase_two = (ROOT / "de-67-2/SKILL.md").read_text(encoding="utf-8")
        phase_three = (ROOT / "de-67-3/SKILL.md").read_text(encoding="utf-8")
        phase_three_kernel = (
            ROOT / "de-67-3/references/kernel.md"
        ).read_text(encoding="utf-8")

        self.assertIn("../references/imagination-round.md", phase_one)
        self.assertIn("../references/msw-kernel.md", phase_one)
        self.assertIn("../references/controlled-english.md", phase_one)
        self.assertIn("../references/msw-kernel.md", phase_two)
        self.assertIn("../references/controlled-english.md", phase_two)
        self.assertIn("not packaged or workspace guideline prose", phase_three)
        self.assertIn(".de67/phase3-policy.d67", phase_three)
        self.assertIn("scripts/policy_kernel.py decide", phase_three)
        self.assertIn("../../references/msw-kernel.md", phase_three_kernel)

    def test_authoring_roles_route_to_controlled_english(self) -> None:
        guideline = (ROOT / "references/controlled-english.md").read_text(encoding="utf-8")
        self.assertIn("apply the MSW deletion test", guideline)
        self.assertIn("Write de67 work ledgers as current operational state", guideline)
        self.assertIn("Write blocker messages as owner decisions", guideline)

        ledger_profile = (
            ROOT / "references/controlled-english-ledger.md"
        ).read_text(encoding="utf-8")
        message_profile = (
            ROOT / "references/controlled-english-message.md"
        ).read_text(encoding="utf-8")
        self.assertIn("current frontier, not the full event history", ledger_profile)
        self.assertIn("Ask for one decision or action", message_profile)

        task_guidance = (
            ROOT / "de-67-3/assets/environment/test-and-task-guidelines.md"
        ).read_text(encoding="utf-8")
        self.assertIn("in controlled English with exact identifiers", task_guidance)

        phase_one = (ROOT / "de-67-1/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Write owner questions and choices in Simplified Technical English", phase_one)

    def test_promoted_runtime_guidance_is_general_and_outcome_sized(self) -> None:
        coordinator = (
            ROOT / "de-67-3/assets/environment/orchestrator-guidelines.md"
        ).read_text(encoding="utf-8")
        worker = (
            ROOT / "de-67-3/assets/environment/test-and-task-guidelines.md"
        ).read_text(encoding="utf-8")

        self.assertIn("replaceable snapshot of current truth", coordinator)
        self.assertIn("nonterminal checkpoint", coordinator)
        self.assertIn("projection rebase is part of the", coordinator.lower())
        self.assertIn("highest changed authoritative boundary", worker)
        self.assertNotIn("caol-harness", coordinator + worker)


if __name__ == "__main__":
    unittest.main()
