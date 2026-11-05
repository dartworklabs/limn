"""Every Markdown pin kind the viewer stores is taught where agents and readers look for it.

The viewer saves a Markdown block pin as kind `md:<block>`, the block kinds being md-surface.js's MD_BLOCK_KINDS
(docs/adr/0025-html-document-surface.md D3; `front` and `math` from docs/adr/0032-markdown-front-matter.md D4, D9), and a
section pin as `md:section`. The server takes any string, so nothing else stops a new block kind from reaching agents
unexplained: this test keeps the agent contract (docs/handbook/api.md: the Markdown pins' value list and the record
schema's kind row), the viewer topic and both SKILLs naming every one of them.

Run: uv run pytest -q tests/architecture/test_markdown_kinds.py
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SURFACE = ROOT / "src" / "limn" / "viewer" / "js" / "md-surface.js"
API = ROOT / "docs" / "handbook" / "api.md"
TAUGHT = (
    ROOT / "docs" / "handbook" / "viewer.md",
    ROOT / "skill" / "SKILL.md",
    ROOT / "skill" / "SKILL.ko.md",
)


def stored_kinds() -> list[str]:
    """md:<block> for every block kind of MD_BLOCK_KINDS in md-surface.js, then md:section."""
    m = re.search(r"^const MD_BLOCK_KINDS=\[([^\]]*)\];$", SURFACE.read_text(encoding="utf-8"), re.M)
    assert m is not None, "md-surface.js has no MD_BLOCK_KINDS line"
    return ["md:" + k for k in re.findall(r"'([a-z]+)'", m.group(1))] + ["md:section"]


class MarkdownKinds(unittest.TestCase):
    """The kinds the viewer stores against the documents that list them."""

    def test_the_viewer_stores_the_kinds_adr_0032_adds(self):
        """The block kinds include front matter and display math besides ADR-0025's six."""
        self.assertEqual(
            stored_kinds(),
            [
                "md:paragraph",
                "md:item",
                "md:table",
                "md:code",
                "md:quote",
                "md:html",
                "md:front",
                "md:math",
                "md:section",
            ],
        )

    def test_api_md_lists_every_kind_in_the_value_list_and_the_record_schema(self):
        """api.md §Markdown 문서의 핀's value list and the record schema's kind row each name every stored kind."""
        api = API.read_text(encoding="utf-8")
        values = api[api.index("## Markdown 문서의 핀") : api.index("## 텍스트 문서의 핀")]
        row = next(line for line in api.splitlines() if line.startswith("| `kind` | ") and "md:paragraph" in line)
        for kind in stored_kinds():
            with self.subTest(kind=kind):
                self.assertIn("`%s`" % kind, values)
                self.assertIn(kind, row)

    def test_the_viewer_topic_and_both_skills_name_every_kind(self):
        """viewer.md, SKILL.md and SKILL.ko.md each name every stored kind."""
        for path in TAUGHT:
            text = path.read_text(encoding="utf-8")
            for kind in stored_kinds():
                with self.subTest(path=path.name, kind=kind):
                    self.assertIn("`%s`" % kind, text)
