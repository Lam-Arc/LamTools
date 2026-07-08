from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import kbtool


class KbToolTests(unittest.TestCase):
    def make_notes(self) -> tempfile.TemporaryDirectory[str]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "project.md").write_text(
            """---
tags: [python, project]
---
# Project Plan

See [[Research]] and [Local](research.md).

- [ ] Write summary
- [x] Create draft
""",
            encoding="utf-8",
        )
        (root / "research.md").write_text(
            """# Research

#notes #python

Back to [[Project Plan]].
""",
            encoding="utf-8",
        )
        return tmp

    def test_normal_scan(self):
        with self.make_notes() as tmp:
            result = kbtool.scan_notes(Path(tmp))
            self.assertEqual(len(result.notes), 2)
            self.assertEqual(result.todo_count, 2)
            self.assertEqual(result.broken_links, [])

    def test_tag_extraction(self):
        with self.make_notes() as tmp:
            result = kbtool.scan_notes(Path(tmp))
            self.assertEqual(result.tags, {"python", "project", "notes"})

    def test_internal_link_parsing(self):
        with self.make_notes() as tmp:
            result = kbtool.scan_notes(Path(tmp))
            links = [(link.kind, link.target) for note in result.notes for link in note.links]
            self.assertIn(("wiki", "Research"), links)
            self.assertIn(("markdown", "research.md"), links)

    def test_broken_link_detection(self):
        with self.make_notes() as tmp:
            root = Path(tmp)
            (root / "broken.md").write_text(
                """# Broken

[[Missing Page]]
[Missing file](missing.md)
""",
                encoding="utf-8",
            )
            result = kbtool.scan_notes(root)
            broken = {(item.target, item.reason) for item in result.broken_links}
            self.assertIn(("Missing Page", "missing wiki page"), broken)
            self.assertIn(("missing.md", "missing file"), broken)

    def test_index_generation(self):
        with self.make_notes() as tmp:
            root = Path(tmp)
            result = kbtool.scan_notes(root)
            index_path = kbtool.write_index(result)
            text = index_path.read_text(encoding="utf-8")
            self.assertIn("# Knowledge Base Index", text)
            self.assertIn("### #python", text)
            self.assertIn("[Project Plan](project.md)", text)
            self.assertIn("[Research](research.md)", text)


if __name__ == "__main__":
    unittest.main()

