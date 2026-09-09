import hashlib
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from specification import SpecificationError, compatibility_pointer, render_functional_specification, resolve


class SpecificationMigrationTests(unittest.TestCase):
    def test_hash_bound_pointer_resolves_fs_and_rejects_stale_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fs = root / "FS.md"
            fs.write_text("# Functional\n<!-- DE67:DFS-SLICE:BEGIN claim=R-X -->\nImplementation status:\n- [ ] stale\n<!-- DE67:DFS-SLICE:END claim=R-X -->\n", encoding="utf-8")
            (root / "DFS.md").write_text(compatibility_pointer(fs), encoding="utf-8")
            self.assertFalse(resolve(root).legacy)
            fs.write_text(fs.read_text(encoding="utf-8") + "x", encoding="utf-8")
            with self.assertRaises(SpecificationError):
                resolve(root)

    def test_dual_mutable_content_and_missing_pointer_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "FS.md").write_text("# FS\n", encoding="utf-8")
            (root / "DFS.md").write_text("# DFS\n", encoding="utf-8")
            with self.assertRaises(SpecificationError):
                resolve(root)

    def test_functional_render_removes_delivery_status_only(self):
        text = "# FS\nImplementation status:\n- [x] delivered\n<!-- DE67:DFS-SLICE:END claim=R-X -->\n"
        rendered = render_functional_specification(text)
        self.assertNotIn("Implementation status:", rendered)
        self.assertIn("# FS", rendered)

    def test_functional_render_preserves_contract_before_status_tracking(self):
        text = (
            "<!-- DE67:DFS-SLICE:BEGIN id=R-X-S001 claim=R-X -->\n"
            "The adapter binds sender, workspace, and revision before delivery.\n\n"
            "Implementation status:\n"
            "- [x] R-X — historical delivery projection\n"
            "<!-- DE67:DFS-SLICE:END id=R-X-S001 claim=R-X -->\n"
        )
        rendered = render_functional_specification(text)
        self.assertIn("The adapter binds sender, workspace, and revision", rendered)
        self.assertNotIn("Implementation status:", rendered)
        self.assertNotIn("historical delivery projection", rendered)


if __name__ == "__main__":
    unittest.main()
