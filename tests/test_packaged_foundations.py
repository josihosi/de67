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
                actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
                self.assertEqual(actual, expected_hash)

    def test_phases_route_to_the_shared_foundations(self) -> None:
        phase_one = (ROOT / "de-67-1/SKILL.md").read_text(encoding="utf-8")
        phase_two = (ROOT / "de-67-2/SKILL.md").read_text(encoding="utf-8")
        phase_three = (ROOT / "de-67-3/SKILL.md").read_text(encoding="utf-8")

        self.assertIn("../references/imagination-round.md", phase_one)
        self.assertIn("../references/msw-kernel.md", phase_one)
        self.assertIn("../references/msw-kernel.md", phase_two)
        self.assertIn("../references/msw-kernel.md", phase_three)


if __name__ == "__main__":
    unittest.main()
