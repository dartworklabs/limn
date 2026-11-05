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


def unit(tag, text, pics="", refs="", shape=None, box="", alts=""):
    """A unit as mdcUnits makes it, for a block of tag showing text (and pictures, link targets), its inline structure
    shape (the text when it has none), the boxes it sits in and its images' alt texts."""
    shape = text if shape is None else shape
    key = "\u0001".join([tag, box, shape, pics, refs])
    return {
        "tag": tag,
        "text": text,
        "pics": pics,
        "shape": shape,
        "box": box,
        "alts": alts,
        "key": key,
        "lo": 0,
        "hi": 0,
    }


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

    def test_the_same_words_with_another_structure_are_one_block_changed_and_say_what_changed(self):
        """Bold where the words were plain, a paragraph out of a quote, a list renumbered, an image's new alt text: the
        keys differ, so each is one block changed in place (not kept as it was), and mdcWhy names what changed."""
        cases = [
            (
                unit("P", "Warning", shape="Warning"),
                unit("P", "Warning", shape="\u0002strong\u0003Warning\u0002/strong\u0003"),
            ),
            (unit("P", "인용한 문장이다.", box="BLOCKQUOTE"), unit("P", "인용한 문장이다.")),
            (unit("LI", "첫 항목", box="OL1"), unit("LI", "첫 항목", box="OL5")),
            (
                unit("P", "", "figs/a.png", shape="\u0002img 옛 설명\u0003", alts="옛 설명"),
                unit("P", "", "figs/a.png", shape="\u0002img 새 설명\u0003", alts="새 설명"),
            ),
        ]
        whys = []
        for old, new in cases:
            with self.subTest(old=old["key"]):
                self.assertEqual(
                    self.ops([old, unit("P", "끝")], [new, unit("P", "끝")]), [["mod", 0, 0], ["eq", 1, 1]]
                )
            whys.append(self.run_js("mdcWhy(%s,%s)" % (json.dumps(old), json.dumps(new))))
        self.assertEqual(
            whys,
            [
                "글자 모양(굵게·기울임·코드·링크)이 바뀜",
                "인용·목록 안팎으로 자리가 바뀜",
                "목록 번호가 바뀜",
                "그림 대체 글이 바뀜",
            ],
        )
        self.assertEqual(
            self.run_js("mdcWhy(%s,%s)" % (json.dumps(unit("P", INTRO)), json.dumps(unit("P", INTRO2)))), ""
        )

    def test_a_code_blocks_key_holds_its_body_and_language(self):
        """mdcShape of a code block (a stand-in PRE with the renderer's .ln lines and data-lang) is its language and its
        lines as they are: return 1; and return 2; in one place are one block changed in place, not the same block; an
        indent or the language alone changes it too, and mdcWhy says which. The same code is the same block."""

        def code(lang, *lines):
            stub = "{tagName:'PRE',dataset:{lang:%s},querySelectorAll:()=>%s.map(t=>({textContent:t+'\\n'}))}" % (
                json.dumps(lang),
                json.dumps(list(lines)),
            )
            shape = self.run_js("mdcShape(%s,'PRE')" % stub)
            return unit("PRE", " ".join(" ".join(lines).split()), shape=shape)

        one, two = code("js", "function f() {", "  return 1;", "}"), code("js", "function f() {", "  return 2;", "}")
        end = unit("P", "끝")
        self.assertNotEqual(one["key"], two["key"])
        self.assertEqual(self.ops([one, end], [two, end]), [["mod", 0, 0], ["eq", 1, 1]])
        self.assertEqual(self.ops([one, end], [dict(one), end]), [["eq", 0, 0], ["eq", 1, 1]])
        flat, py = code("js", "function f() {", "return 1;", "}"), code("python", "function f() {", "  return 1;", "}")
        self.assertEqual(
            [self.run_js("mdcWhy(%s,%s)" % (json.dumps(one), json.dumps(x))) for x in (two, flat, py)],
            ["", "코드의 공백·들여쓰기가 바뀜", "코드 언어가 바뀜"],
        )
        self.assertEqual(self.ops([one, end], [py, end]), [["mod", 0, 0], ["eq", 1, 1]])
        empty, blank = code("py"), code("py", "")  # an empty fence, and the same fence holding one blank line
        self.assertNotEqual(empty["key"], blank["key"])
        self.assertEqual(self.ops([empty, end], [blank, end]), [["mod", 0, 0], ["eq", 1, 1]])
        # A language or a line holding the old separator characters cannot make two blocks read alike.
        a, b = code("py", "x\u00030\u0003"), code("py\u00031\u0003x")
        self.assertNotEqual(a["key"], b["key"])
        self.assertEqual(self.run_js("mdcLang(%s)" % json.dumps(b["shape"])), "py\u00031\u0003x")

    def test_git_lines_are_turned_into_the_sides_screen_lines(self):
        """A side whose line 3 holds a form feed and line 5 a U+2028 ([[1,1],[4,5],[6,8]] from the server): git's lines
        4 and 6-7 are the screen's 5 and 8-9; without a map the numbers are the same."""
        got = self.run_js(
            "[mdcGitRange([[1,1],[4,5],[6,8]],10,[4,4]),mdcGitRange([[1,1],[4,5],[6,8]],10,[3,3]),"
            "mdcGitRange([[1,1],[4,5],[6,8]],10,[6,7]),mdcGitRange([[1,1],[4,5],[6,8]],10,[7,9]),"
            "mdcGitRange(undefined,10,[4,4]),mdcGitRange([[1,1],[4,6]],5,[3,3]),mdcGitRange([[1,1],[2,3]],2,[1,1])]"
        )
        # the last two: the server's end pair (git's count + 1 at the screen's + 1) gives the last git line its every
        # screen line - first/(empty)/A\f\fB is git's 3 lines and the screen's 5; A\u2028B is git's 1 and the screen's 2
        self.assertEqual(got, [[5, 5], [3, 4], [8, 9], [9, 10], [4, 4], [3, 5], [1, 2]])

    def test_a_large_compare_stops_pairing_at_its_budget_and_marks_the_rest_added_and_taken_out(self):
        """8,000 blocks taken out and 8,000 added in one gap, each pair alike: the subsequence gives up past 4 million
        cells, which spends the budget, so none is paired. 2,000 and 2,000, no two alike: the subsequence fits, and
        weighing every pair (4 million of them) would take seconds - the budget stops it. Both end quickly, with every
        block taken out or added."""
        js = (
            "(()=>{const u=(t,i,w)=>({tag:'P',text:w?t+i+' 가'+i+' 나'+i+' 다'+i:t+i+' '+t+'가'+i+' '+t+'나'+i,"
            "pics:'',shape:'',box:'',alts:'',key:t+i,lo:0,hi:0});"
            "const o=[],nn=[]; for(let i=0;i<%d;i++){o.push(u('old',i,%s)); nn.push(u('new',i,%s));}"
            "const t0=Date.now(),b=mdcBudget(),ops=mdcOps(o,nn,b);"
            "return [Date.now()-t0,b.left<=0,[...new Set(ops.map(x=>x.t))].sort(),ops.length];})()"
        )
        for n, alike in ((8000, "true"), (2000, "false")):
            with self.subTest(blocks=n):
                got = self.run_js(js % (n, alike, alike))
                self.assertLess(got[0], 3000, got)
                self.assertEqual(got[1:], [True, ["del", "ins"], 2 * n], got)

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
