from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


class PackagedFoundationTests(unittest.TestCase):
    def test_authoring_and_audit_links_resolve(self) -> None:
        # Prose may evolve; a routed reference must remain reachable.
        documents = [ROOT / "SKILL.md"]
        for directory in ("references", "de-67-1", "de-67-2", "alignment-audit"):
            documents.extend((ROOT / directory).rglob("*.md"))
        for document in documents:
            text = re.sub(r"```.*?```", "", document.read_text(encoding="utf-8"), flags=re.S)
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                if "://" in target or target.startswith("#"):
                    continue
                relative = unquote(target.strip("<>").split("#", 1)[0])
                with self.subTest(document=document.relative_to(ROOT), target=target):
                    self.assertTrue((document.parent / relative).is_file())

    def test_phase_handoff_templates_remain_available(self) -> None:
        for phase, artifact in (("de-67-1", "WEC.md"), ("de-67-2", "DFS.md")):
            with self.subTest(phase=phase):
                self.assertTrue((ROOT / phase / "SKILL.md").is_file())
                self.assertTrue((ROOT / phase / "assets" / artifact).is_file())


if __name__ == "__main__":
    unittest.main()
