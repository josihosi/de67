from __future__ import annotations

from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate  # noqa: E402


class PitCrewEvaluationTests(unittest.TestCase):
    def test_controlled_stub_labels_and_negative_results_are_retained(self) -> None:
        value = evaluate.run()
        self.assertFalse(value["provider_requested"])
        self.assertEqual(value["provider_transport"], "controlled_local_stub")
        self.assertEqual(value["totals"]["useful"], 2)
        self.assertEqual(value["totals"]["missed"], 1)
        self.assertEqual(value["totals"]["irrelevant"], 1)
        self.assertEqual(value["totals"]["stub_calls"], 4)
        self.assertTrue(any(row["missed"] for row in value["cases"]))
        self.assertTrue(any(row["irrelevant"] for row in value["cases"]))
        self.assertTrue(all(row["observed_outcome"]["mode"] == "shadow" for row in value["cases"]))
        self.assertTrue(all(row["observed_outcome"]["mailbox_notices"] == 0 for row in value["cases"]))


if __name__ == "__main__":
    unittest.main()
