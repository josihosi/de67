"""Changed helper permission must reach a reused worker, preserving its task text."""
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import policy_kernel
from worker_packet import delivery_text, standing_section


class ChaperoneDeliveryTests(unittest.TestCase):
    def test_existing_worker_receives_changed_ownership_section(self):
        context = "Task R051; pending input untouched; run A on host X.\n"
        previous = context + standing_section("worker-ownership", "Use Luna helpers only.")
        current = context + standing_section("worker-ownership", policy_kernel.worker_helper_contract())
        delivered, meta = delivery_text(current, previous)
        self.assertEqual(meta["changed_sections"], ["worker-ownership"])
        self.assertIn(context, delivered)
        self.assertIn('model="gpt-6.1-sol"', delivered)
        self.assertIn("Luna retains game input", delivered)
        repeated, meta = delivery_text(current, current)
        self.assertEqual(meta["omitted_sections"], ["worker-ownership"])
        self.assertIn(context, repeated)


if __name__ == "__main__":
    unittest.main()
