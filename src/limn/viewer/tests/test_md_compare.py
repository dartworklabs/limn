"""The rendered compare's pure rules (docs/superpowers/specs/2026-11-05-markdown-rendered-compare.md §결정 2): the
common subsequence of two block lists, which blocks are one block changed in place, which moved, and the format a
document's changes open in.

The production part js/md-compare.js runs under node whole, as the page serves it, so every constant the rules read is
the served one. Units are plain objects with the fields mdcUnits gives (tag, key, text, pics, lo, hi). The browser
behaviour - drawing both sides, the marks, the layouts, a pin's blocks - is test_viewer_md_compare.py.

Run: uv run pytest -q src/limn/viewer/tests/test_md_compare.py
"""

import json
import shutil
import unittest

from helpers import HTML, VIEWER, extract_js_fn, run_node


def served() -> str:
    """js/md-compare.js exactly as the page serves it, after revisionFormatFor (revisions.js)."""
    part = (VIEWER / "js/md-compare.js").read_text(encoding="utf-8")
    assert part in HTML  # the page joins its parts byte for byte (parts.txt)
    return extract_js_fn("revisionFormatFor") + "\n" + part


def unit(tag, text, pics="", refs=""):
    """A unit as mdcUnits makes it, for a block of tag showing text (and pictures, link targets)."""
    return {"tag": tag, "text": text, "pics": pics, "key": "\u0001".join([tag, text, pics, refs]), "lo": 0, "hi": 0}


INTRO = "이 노트는 부하 예측 모델을 새 건물로 옮길 때 무엇을 먼저 확인할지 정리한다."
INTRO2 = "이 노트는 부하 예측 모델을 새 건물로 옮길 때 먼저 확인할 것을 정리한다."
TERMS = "체크포인트는 대상 데이터가 한 달 늘 때마다 다시 학습한 모델이다."


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CompareRules(unittest.TestCase):
    """mdcLcs, mdcOps and revisionFormatFor under node."""

    def run_js(self, body: str):
        """Evaluate body (an expression) with the served part; its JSON value."""
        return json.loads(run_node(served() + "\nconsole.log(JSON.stringify(%s));" % body))

    def ops(self, old, new):
        """mdcOps of two unit lists as [t, a, b] rows."""
        return self.run_js("mdcOps(%s,%s).map(o=>[o.t,o.a,o.b])" % (json.dumps(old), json.dumps(new)))

    def test_the_common_subsequence_takes_its_ends_first_and_deletes_before_it_adds(self):
        """Equal ends are matched first; inside a gap the deletions come before the insertions."""
        got = self.run_js("mdcLcs(['a','b','c','d'],['a','x','c','y','d'],(x,y)=>x===y).map(o=>o.t+o.a+':'+o.b)")
        self.assertEqual(got, ["eq0:0", "del1:-1", "ins-1:1", "eq2:2", "ins-1:3", "eq3:4"])

    def test_a_rewritten_paragraph_is_changed_in_place_and_an_added_item_is_added(self):
        """A paragraph whose words mostly stay is one block changed (mod); a new list item between kept ones is added."""
        old = [unit("H1", "노트"), unit("P", INTRO), unit("LI", "Reference"), unit("LI", "전이")]
        new = [
            unit("H1", "노트"),
            unit("P", INTRO2),
            unit("LI", "Reference"),
            unit("LI", "전이"),
            unit("LI", "유사도 가중"),
        ]
        self.assertEqual(self.ops(old, new), [["eq", 0, 0], ["mod", 1, 1], ["eq", 2, 2], ["eq", 3, 3], ["ins", -1, 4]])

    def test_an_unlike_paragraph_or_another_kind_is_taken_out_and_added(self):
        """Below the likeness threshold, or a heading where a paragraph was, the old block is taken out and the new one
        added: never a word diff of two unrelated blocks."""
        old = [unit("P", "완전히 다른 첫 문단이다"), unit("P", "끝")]
        new = [unit("P", "새로 쓴 문장은 공통 낱말이 없음"), unit("P", "끝")]
        self.assertEqual(self.ops(old, new), [["del", 0, -1], ["ins", -1, 0], ["eq", 1, 1]])
        old = [unit("P", "결과"), unit("P", "끝")]
        new = [unit("H2", "결과"), unit("P", "끝")]
        self.assertEqual(self.ops(old, new), [["del", 0, -1], ["ins", -1, 0], ["eq", 1, 1]])

    def test_a_changed_picture_shows_the_old_one_taken_out_and_the_new_one_added(self):
        """Two image paragraphs with the same words but other pictures are not one block changed in place: the old picture
        is taken out and the new one added, so both show."""
        old = [unit("P", "", "../figures/arch-v1.png"), unit("P", "끝")]
        new = [unit("P", "", "../figures/arch-v2.png"), unit("P", "끝")]
        self.assertEqual(self.ops(old, new), [["del", 0, -1], ["ins", -1, 0], ["eq", 1, 1]])

    def test_a_moved_section_is_moved_where_it_was_and_where_it_is(self):
        """Two sections that swap places: one is kept and the other moved - each of its blocks once where it was (from) and
        once where it is (to), naming the same pair - and nothing is taken out or added. Which of two equally long sections
        stays is the subsequence's choice. A short block that moves is taken out and added, not moved."""
        h, p = unit("H2", "부록: 용어"), unit("P", TERMS)
        a, b = unit("H2", "배경"), unit("P", "배경 문단이다.")
        got = self.ops([a, b, h, p], [h, p, a, b])
        kinds = sorted(t for t, _, _ in got)
        self.assertEqual(kinds, ["eq", "eq", "from", "from", "to", "to"])
        self.assertEqual(
            sorted((x, y) for t, x, y in got if t == "from"), sorted((x, y) for t, x, y in got if t == "to")
        )
        short = unit("P", "끝")
        got = self.ops([short, a, b], [a, b, short])
        self.assertNotIn("from", [t for t, _, _ in got])

    def test_a_markdown_document_opens_its_rendered_compare_unless_the_source_diff_is_asked(self):
        """drawn (a document drawn from Markdown) opens the rendered compare for any format but the source diff; a figure
        keeps its overlay; without drawn the formats are as before."""
        got = self.run_js(
            "[['pdf','source','overlay','rendered'].map(f=>revisionFormatFor(f,false,true,true)),"
            "['pdf','rendered'].map(f=>revisionFormatFor(f,false,true,false)),revisionFormatFor('pdf',true,false,true)]"
        )
        self.assertEqual(got, [["rendered", "source", "rendered", "rendered"], ["source", "source"], "overlay"])


if __name__ == "__main__":
    unittest.main()
