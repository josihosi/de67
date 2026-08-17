from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagedFoundationTests(unittest.TestCase):
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
        self.assertIn("references/kernel.md", phase_three)
        self.assertIn("../../references/msw-kernel.md", phase_three_kernel)

    def test_authoring_roles_route_to_controlled_english(self) -> None:
        guideline = (ROOT / "references/controlled-english.md").read_text(encoding="utf-8")
        self.assertIn("apply the MSW deletion test", guideline)
        self.assertIn("Write DE67 work ledgers as current operational state", guideline)
        self.assertIn("Write blocker messages as owner decisions", guideline)

        ledger_profile = (
            ROOT / "references/controlled-english-ledger.md"
        ).read_text(encoding="utf-8")
        message_profile = (
            ROOT / "references/controlled-english-message.md"
        ).read_text(encoding="utf-8")
        self.assertIn("current frontier, not the full event history", ledger_profile)
        self.assertIn("Ask for one decision or action", message_profile)

        for relative_path in (
            "de-67-3/references/roles/dfs-steward.md",
            "de-67-3/references/roles/worker.md",
        ):
            with self.subTest(relative_path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("../../../references/controlled-english.md", text)

        coordinator = (
            ROOT / "de-67-3/references/roles/coordinator.md"
        ).read_text(encoding="utf-8")
        supervisor = (
            ROOT / "de-67-3/references/roles/supervisor.md"
        ).read_text(encoding="utf-8")
        self.assertIn("../../../references/controlled-english-ledger.md", coordinator)
        self.assertIn("../../../references/controlled-english-message.md", coordinator)
        self.assertIn("../../../references/controlled-english-message.md", supervisor)

        phase_one = (ROOT / "de-67-1/SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Write owner questions and choices in Simplified Technical English", phase_one)


if __name__ == "__main__":
    unittest.main()
