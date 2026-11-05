"""The rendered compare of a Markdown document in the browser ([그린 비교], docs/handbook/viewer.md §변경 보기, ADR-0031):
both sides of a commit or a range drawn and compared block by block in one column, never sideways; a pin's [변경 보기] on
its source diff with [그린 비교] beside it, where the pin's blocks are ringed.

A Markdown note in a real temporary repository gets four commits after the first: a paragraph rewritten, a list item and
a table row added with a cell changed, the picture changed, and a section moved to the top. The pure rules (pairs, moves)
are test_md_compare.py's.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_md_compare.py
"""

import json
import subprocess

from limn.administration import serve_documents as startup_documents

from helpers import blank_png, ps, req
from helpers_browser import BrowserBase, settle, until
from helpers_figure import BUILD1, viewer_build

INTRO = "이 노트는 부하 예측 모델을 새 건물로 옮길 때 무엇을 먼저 확인할지 정리한다."
INTRO2 = "이 노트는 부하 예측 모델을 새 건물로 옮길 때 먼저 확인할 것을 정리한다."
TERMS = "## 부록: 용어\n\n**체크포인트**는 대상 데이터가 한 달 늘 때마다 다시 학습한 모델이다.\n"
BODY = (
    "## 방법\n\n- Reference — 대상만으로 학습\n- 전이 — 원본으로 사전학습\n{item}\n\n"
    "| 조건 | 미세조정 |\n| --- | --- |\n| Reference | 대상 전체 |\n| 전이 | {cell} |\n{row}\n\n"
    "![구조도](figs/{pic}.png)\n\n## 결과\n\n전이의 이득은 대상 데이터가 늘면서 줄어든다.\n"
)


def note(intro, item="", cell="대상 누적", row="", pic="v1", moved=False):
    """The note: its title and intro, the method (list, table, picture) and the results, with the terms at the end or,
    moved, before the method."""
    body = BODY.format(item=item, cell=cell, row=row, pic=pic)
    return "# 노트\n\n" + intro + "\n\n" + (TERMS + "\n" + body if moved else body + "\n" + TERMS)


DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"
COMPARED = (
    "REV.format===DIFF_FORMAT.RENDERED&&!!document.querySelector('#revision-rendered .mdc-frame')&&MDC.key===revKey()"
)
SOURCED = "REV.format===DIFF_FORMAT.SOURCE&&REV.sourceCommit===revKey()&&!!REV.target"


class CompareBase(BrowserBase):
    """A Markdown document nt (notes/note.md) first and the LaTeX manuscript ms second, in a repository with the five
    commits (self.c, oldest first)."""

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        (self.src / "figs").mkdir()
        (self.src / "figs/v1.png").write_bytes(blank_png(40, 20))
        (self.src / "figs/v2.png").write_bytes(blank_png(60, 20))
        self.md = self.src / "note.md"
        self.md.write_text(note(INTRO), encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:note.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        viewer_build(docs[1], BUILD1)
        self.git("init", "-q")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.c = [self.commit("first")]
        steps = [
            dict(intro=INTRO2),
            dict(
                intro=INTRO2,
                item="- 유사도 가중 — 월 단위 가중",
                cell="대상 최근 2개월",
                row="| 유사도 가중 | 대상 누적 + 가중 |",
            ),
            dict(
                intro=INTRO2,
                item="- 유사도 가중 — 월 단위 가중",
                cell="대상 최근 2개월",
                row="| 유사도 가중 | 대상 누적 + 가중 |",
                pic="v2",
            ),
            dict(
                intro=INTRO2,
                item="- 유사도 가중 — 월 단위 가중",
                cell="대상 최근 2개월",
                row="| 유사도 가중 | 대상 누적 + 가중 |",
                pic="v2",
                moved=True,
            ),
        ]
        for i, kw in enumerate(steps):
            self.md.write_text(note(**kw), encoding="utf-8")
            self.c.append(self.commit("step %d" % (i + 1)))

    def git(self, *args):
        """A fixture git command in the manuscript folder; its stdout, stripped."""
        return subprocess.run(
            ["git", "-C", str(self.src), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, subject):
        """Commit everything as subject; its full id."""
        self.git("add", "-A")
        self.git("commit", "-qm", subject)
        return self.git("rev-parse", "HEAD")

    def open_compare(self, **kw):
        """The viewer on the Markdown document, its changes view open on the newest commit's rendered compare."""
        page = self.open(0, **kw)
        until(page, DRAWN, 20)
        settle(page)
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        until(page, COMPARED, 15)
        settle(page)
        return page

    def show(self, page, commit, base=""):
        """The rendered compare of commit (from base), once it is drawn."""
        page.evaluate("showRevision(%s,DIFF_FORMAT.RENDERED,%s)" % (json.dumps(commit), json.dumps(base)))
        until(page, COMPARED, 15)
        settle(page)

    def pin_on(self, lo, hi, commit):
        """A pin on lines lo..hi of the note, closed with commit as its reference and those lines as its change; its id."""
        body = json.dumps({"doc": "nt", "file": str(self.md), "lo": lo, "hi": hi, "note": "n"}).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        pid = json.loads(out)["id"]
        close = json.dumps({"ref": "(%s)" % commit[:7], "changes": [{"file": "note.md", "lo": lo, "hi": hi}]}).encode()
        code, _, out = self.talk(req("POST", "/api/pins/%d/close" % pid, close, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        return pid

    def pin_view(self, pid, **kw):
        """The viewer on the note with pin pid's [변경 보기] open: its source diff (ADR-0031 D6, C), loaded."""
        page = self.open(0, **kw)
        until(page, DRAWN, 20)
        until(page, "REVIEW_ALL.some(p=>p.id===%d)" % pid, 10)
        page.evaluate("showChange(%d)" % pid)
        until(page, SOURCED, 15)
        settle(page)
        return page

    def pin_rendered(self, pid, **kw):
        """pin_view, then its [그린 비교] tab pressed, once the compare has ringed the pin's blocks."""
        page = self.pin_view(pid, **kw)
        page.click("#revision-rendered-tab")
        until(page, COMPARED + "&&!!document.querySelector('#revision-rendered .mdc-pin')", 15)
        settle(page)
        return page

    def ringed_rows(self, page):
        """The ringed blocks as [kind, text without the screen reader's words and the struck-through words]."""
        return page.evaluate(
            "[...document.querySelectorAll('#revision-rendered .mdc-pin')].map(e=>{const c=e.cloneNode(true);"
            "c.querySelectorAll('.sr-only,del').forEach(x=>x.remove());return [e.dataset.mdc||'',c.textContent.trim()];})"
        )

    def marks(self, page):
        """The marked blocks on screen in order, as [kind, tag, text without the screen-reader prefix]."""
        return page.evaluate(
            "[...document.querySelectorAll('#revision-rendered [data-mdc]')].map(e=>{const c=e.cloneNode(true);"
            "c.querySelectorAll('.sr-only').forEach(x=>x.remove());return [e.dataset.mdc,e.tagName,c.textContent.trim()];})"
        )


class Compare(CompareBase):
    """What each commit's compare marks, and how it reads."""

    def test_the_changes_view_opens_on_the_rendered_compare_of_the_newest_commit(self):
        """The newest commit moved the terms section to the top: its heading and paragraph are moved blocks, their old
        place one slim line, nothing else marked; the tab row has [그린 비교] pressed and no comparison PDF."""
        page = self.open_compare()
        self.assertEqual([k for k, _, _ in self.marks(page)], ["move", "move"], self.marks(page))
        self.assertEqual(page.evaluate("document.querySelectorAll('#revision-rendered .mdc-ghost').length"), 1)
        self.assertIn(
            "블록 2개를", page.evaluate("document.querySelector('#revision-rendered .mdc-ghost').textContent")
        )
        self.assertEqual(
            page.evaluate(
                "[document.getElementById('revision-rendered-tab').getAttribute('aria-pressed'),"
                "document.getElementById('revision-pdf-tab').hidden,document.getElementById('revision-source').hidden]"
            ),
            ["true", True, True],
        )
        self.assertIn("옮김 2", page.evaluate("document.getElementById('revision-status').textContent"))

    def test_a_rewritten_paragraph_marks_its_words_and_added_blocks_are_added(self):
        """The rewrite is one block changed in place with its taken-out and added words; the next commit adds a list item
        and a table row and changes a cell (a row changed in place)."""
        page = self.open_compare()
        self.show(page, self.c[1])
        self.assertEqual([k for k, _, _ in self.marks(page)], ["mod"])
        words = page.evaluate(
            "[[...document.querySelectorAll('#revision-rendered del.mdc-w')].map(e=>e.textContent.trim()),"
            "[...document.querySelectorAll('#revision-rendered ins.mdc-w')].map(e=>e.textContent.trim())]"
        )
        self.assertEqual(words, [["무엇을", "확인할지"], ["확인할 것을"]])
        self.show(page, self.c[2])
        self.assertEqual(
            [(k, t) for k, t, _ in self.marks(page)], [("ins", "LI"), ("mod", "TR"), ("ins", "TR")], self.marks(page)
        )

    def test_a_changed_picture_shows_both_pictures_from_the_tree(self):
        """The picture's commit takes out the old picture and adds the new one; both load from GET /api/asset only."""
        page = self.open_compare()
        self.show(page, self.c[3])
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("del", "P"), ("ins", "P")])
        until(
            page, "[...document.querySelectorAll('#revision-rendered img')].every(i=>i.complete&&i.naturalWidth>0)", 10
        )
        srcs = page.evaluate(
            "[...document.querySelectorAll('#revision-rendered img')].map(i=>new URL(i.src).pathname+new URL(i.src).search)"
        )
        self.assertEqual(srcs, ["/api/asset?doc=nt&path=figs%2Fv1.png", "/api/asset?doc=nt&path=figs%2Fv2.png"])

    def test_the_navigator_steps_through_the_changes(self):
        """[다음 바뀐 곳] goes to the next change group and rings it; at the last one it cannot be pressed."""
        page = self.open_compare()
        self.show(page, self.c[2])
        self.assertEqual(page.evaluate("document.getElementById('mdc-at').textContent"), "바뀐 곳 2곳")
        page.click("#mdc-next")
        self.assertEqual(page.evaluate("document.getElementById('mdc-at').textContent"), "바뀐 곳 1/2")
        page.click("#mdc-next")
        self.assertEqual(
            page.evaluate(
                "[document.getElementById('mdc-at').textContent,document.getElementById('mdc-next').disabled]"
            ),
            ["바뀐 곳 2/2", True],
        )
        self.assertGreater(page.evaluate("document.querySelectorAll('#revision-rendered .mdc-cur').length"), 0)

    def test_links_in_the_compare_do_not_leave_the_view(self):
        """An in-document heading link drawn in the compare is words: no data-act, so a press stays in the changes view."""
        self.md.write_text(note(INTRO2 + " [결과](#결과)로 간다.", pic="v2"), encoding="utf-8")
        last = self.commit("link")
        page = self.open_compare()
        self.show(page, last)
        self.assertEqual(
            page.evaluate("document.querySelectorAll('#revision-rendered [data-act=md-anchor]').length"), 0
        )


class RangeDisplay(CompareBase):
    """A range from the rewrite to now: every kind of change at once in one column."""

    def test_a_range_keeps_the_rendered_compare_and_paints_its_commits(self):
        """Every kind at once; the list paints the range's commits (the source diff's answer read beside the compare) and
        the status line says the range's commits and files with the blocks it changed. Mutation: leave REV.rangeN out of
        mdcStatus (the two ends only) -> the line has no '커밋 4개', fails."""
        page = self.open_compare()
        page.evaluate("setRevisionRange(RANGE_MODE.FROM)")
        page.locator("#revision-commits .rc-row").nth(3).click()
        until(page, COMPARED + "&&!!REV.base&&REV.rangeIds!==null&&!!REV.rangeN", 15)
        settle(page)
        kinds = sorted({k for k, _, _ in self.marks(page)})
        self.assertEqual(kinds, ["del", "ins", "mod", "move"])
        self.assertEqual(page.evaluate("document.querySelectorAll('#revision-commits .rc-row.in').length"), 4)
        self.assertEqual(page.evaluate("REV.format"), "rendered")
        status = page.evaluate("document.getElementById('revision-status').textContent")
        self.assertIn("커밋 4개 · 파일 1개", status)
        self.assertIn("바뀐 블록", status)
        self.assertEqual(
            page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth"), True
        )


class RangeDisplayFirefox(RangeDisplay):
    """The same compare in Firefox."""

    BROWSER_ENGINE = "firefox"


class PinBlocks(CompareBase):
    """A pin closed with the table's commit, which also added a list item: its [변경 보기] opens that commit's source diff
    with the pin's hunks alone (ADR-0005 §4), and [그린 비교] beside it compares the whole commit with the pin's blocks
    ringed (ADR-0031 D6: C until the pin-only side)."""

    def table_pin(self):
        lo = next(
            i for i, ln in enumerate(self.md.read_text(encoding="utf-8").splitlines(), 1) if ln.startswith("| 전이")
        )
        return self.pin_on(lo, lo + 1, self.c[2])

    def test_a_pins_change_view_opens_its_source_diff_with_the_rendered_compare_beside_it(self):
        """The default is the source diff, the pin's own hunks with the rest folded; [그린 비교] is the visible tab next to
        [소스 diff], not pressed, and nothing is drawn for it until pressed. Mutation: open a Markdown pin on
        DIFF_FORMAT.RENDERED in loadRevisions (the PoC's A) -> the format is rendered and the source diff never loads,
        fails."""
        page = self.pin_view(self.table_pin())
        self.assertEqual(page.evaluate("REV.commit"), self.c[2])
        got = page.evaluate(
            "(()=>{const r=document.getElementById('revision-rendered-tab'),s=document.getElementById('revision-source-tab');"
            "return {format:REV.format,mode:REV.scope&&REV.scope.mode,other:!document.getElementById('revision-other-toggle').hidden,"
            "rendered:[r.hidden,r.getAttribute('aria-pressed'),r.nextElementSibling===s],source:s.getAttribute('aria-pressed'),"
            "drawn:!!document.querySelector('#revision-rendered .mdc-frame'),pane:document.getElementById('revision-rendered').hidden};})()"
        )
        self.assertEqual(
            got,
            {
                "format": "source",
                "mode": "pin",
                "other": True,
                "rendered": [False, "false", True],
                "source": "true",
                "drawn": False,
                "pane": True,
            },
        )
        self.assertIn("이 핀의 변경", page.evaluate("document.getElementById('revision-pin').textContent"))

    def test_its_rendered_compare_rings_the_pins_blocks_and_says_it_is_the_whole_commit(self):
        """[그린 비교]: the two table rows (one changed, one added) are ringed, the list item the same commit added is
        marked too (the whole commit), and the guide line says so and points back at [소스 diff]. Mutation: drop the
        whole-commit sentence from mdcTarget -> fails."""
        page = self.pin_rendered(self.table_pin())
        rows = page.evaluate(
            "[...document.querySelectorAll('#revision-rendered .mdc-pin')].map(e=>[e.tagName,e.dataset.mdc])"
        )
        self.assertEqual(rows, [["TR", "mod"], ["TR", "ins"]])
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("ins", "LI"), ("mod", "TR"), ("ins", "TR")])
        guide = page.evaluate("document.getElementById('revision-pin').textContent")
        self.assertIn("보라 테두리", guide)
        self.assertIn("그린 비교는 커밋 전체입니다", guide)
        page.click("#revision-source-tab")
        until(page, "REV.format===DIFF_FORMAT.SOURCE", 5)
        self.assertNotIn("그린 비교는", page.evaluate("document.getElementById('revision-pin').textContent"))


class Layout(CompareBase):
    """One column on every band, never wider than the screen."""

    def test_no_sideways_scroll_on_the_outer_foldable_screen(self):
        """At 344x882 (touch) the page and the compare scroll only down."""
        page = self.open_compare(viewport={"width": 344, "height": 882}, is_mobile=True, has_touch=True)
        page.evaluate("setRevisionRange(RANGE_MODE.FROM)")
        page.locator("#revision-commits .rc-row").nth(3).click()
        until(page, COMPARED + "&&!!REV.base", 15)
        settle(page)
        widths = page.evaluate(
            "[document.documentElement.scrollWidth,document.documentElement.clientWidth,"
            "document.getElementById('revision-body').scrollWidth,document.getElementById('revision-body').clientWidth]"
        )
        self.assertLessEqual(widths[0], widths[1], widths)
        self.assertLessEqual(widths[2], widths[3], widths)


STRUCT = "# 구조\n\n{warn}\n\n{quote}인용한 문장이다.\n\n{n}. 첫 항목\n{m}. 둘째 항목\n\n![{alt}](figs/v1.png)\n\n끝 문단이다.\n"
FF = "# 줄 끝\n\nA 문단이다.\x0c이어지는 A.\n\nB 첫 줄이다.\u2028B 둘째 줄.\n\nC 문단이다.\n\n{d}\n"
CODE = "# 코드\n\n```{lang}\nfunction f() {{\n  return {v};\n}}\n```\n\n끝 문단이다.\n"
TAIL = "# 끝\n\n첫 문단이다.\n\nA 문단이다.\x0c\x0c{b}{end}"


class OneNote(CompareBase):
    """A Markdown document nt (note.md) and the LaTeX manuscript, the note committed in the versions texts() gives, oldest
    first (self.c)."""

    def texts(self):
        """The note's versions, oldest first."""
        raise NotImplementedError

    def setUp(self):
        BrowserBase.setUp(self)
        self.src = self.main.parent
        (self.src / "figs").mkdir()
        (self.src / "figs/v1.png").write_bytes(blank_png(40, 20))
        self.md = self.src / "note.md"
        versions = self.texts()
        self.md.write_text(versions[0], encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:note.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        viewer_build(docs[1], BUILD1)
        self.git("init", "-q")
        self.git("config", "user.email", "alice@example.com")
        self.git("config", "user.name", "Alice")
        self.c = [self.commit("first")]
        for i, text in enumerate(versions[1:]):
            self.md.write_text(text, encoding="utf-8")
            self.c.append(self.commit("step %d" % (i + 1)))


class SameWordsOtherStructure(OneNote):
    """The same words in bold, out of a quote, in a list renumbered from 5, and an image with a new alt text."""

    def texts(self):
        return [
            STRUCT.format(warn="Warning", quote="> ", n=1, m=2, alt="옛 설명"),
            STRUCT.format(warn="**Warning**", quote="", n=5, m=6, alt="새 설명"),
        ]

    def test_each_structural_change_is_a_block_changed_that_says_what_changed(self):
        """Each of the five blocks is changed in place (none kept as it was, the commit is not 'the same drawn'), its tip
        and its screen-reader words say what changed, and the bold word is marked where it became bold."""
        page = self.open_compare()
        marks = self.marks(page)
        self.assertEqual(
            [(k, t) for k, t, _ in marks], [("mod", "P"), ("mod", "P"), ("mod", "LI"), ("mod", "LI"), ("mod", "P")]
        )
        whys = page.evaluate(
            "[...document.querySelectorAll('#revision-rendered [data-mdc]')].map(e=>e.dataset.mdcWhy||'')"
        )
        self.assertEqual(
            whys,
            [
                "글자 모양(굵게·기울임·코드·링크)이 바뀜",
                "인용·목록 안팎으로 자리가 바뀜",
                "목록 번호가 바뀜",
                "목록 번호가 바뀜",
                "그림 대체 글이 바뀜",
            ],
        )
        self.assertIn(
            "고친 블록 (글자 모양",
            page.evaluate("document.querySelector('#revision-rendered [data-mdc] .sr-only').textContent"),
        )
        self.assertEqual(
            page.evaluate(
                "[...document.querySelectorAll('#revision-rendered strong ins.mdc-w')].map(e=>e.textContent)"
            ),
            ["Warning"],
        )
        self.assertIn("고침 5", page.evaluate("document.getElementById('revision-status').textContent"))


class PinPastOtherLineEnds(OneNote):
    """A note with a form feed in its first paragraph and a U+2028 in its second, whose last paragraph D the commit
    rewrites: git's line of D is the screen's minus two."""

    def texts(self):
        return [FF.format(d="D 문단이다."), FF.format(d="D 문단을 고쳤다.")]

    def test_a_pins_hunk_rings_the_block_it_changed_past_a_form_feed(self):
        """A pin on D closed with that commit: its [그린 비교] rings D (changed), not C two lines above in git's numbering."""
        lines = self.md.read_text(encoding="utf-8").splitlines()
        lo = next(i for i, ln in enumerate(lines, 1) if ln.startswith("D "))
        page = self.pin_rendered(self.pin_on(lo, lo, self.c[1]))
        self.assertEqual(self.ringed_rows(page), [["mod", "D 문단을 고쳤다."]])


class CodeBody(OneNote):
    """A code block whose body changes (return 1; to return 2;), then whose fence language alone changes (js to python)."""

    def texts(self):
        return [CODE.format(lang="js", v=1), CODE.format(lang="js", v=2), CODE.format(lang="python", v=2)]

    def code_marks(self, page):
        """The code block's taken-out and added lines on screen: (del lines, ins lines)."""
        return page.evaluate(
            "[[...document.querySelectorAll('#revision-rendered pre del.mdc-w')].map(e=>e.textContent),"
            "[...document.querySelectorAll('#revision-rendered pre ins.mdc-w')].map(e=>e.textContent)]"
        )

    def test_a_code_blocks_changed_body_is_a_block_changed_with_its_lines_marked(self):
        """The body edit: the code block is changed in place (not "the same drawn", not "no changed block"), its old line
        put back as a line of its own and struck through, its new line marked; the status counts one changed block. The
        language edit: changed in place, its tip saying the language changed."""
        page = self.open_compare()
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("mod", "PRE")])
        self.assertEqual(
            page.evaluate("document.querySelector('#revision-rendered pre[data-mdc]').dataset.mdcWhy"),
            "코드 언어가 바뀜",
        )
        self.show(page, self.c[1])
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("mod", "PRE")])
        self.assertEqual(self.code_marks(page), [["  return 1;\n"], ["  return 2;"]])
        lines = page.evaluate(
            "(()=>{const c=document.querySelector('#revision-rendered pre').cloneNode(true);"
            "c.querySelectorAll('.sr-only').forEach(x=>x.remove());return c.textContent.split('\\n');})()"
        )
        self.assertEqual(lines, ["function f() {", "  return 1;", "  return 2;", "}", ""])
        status = page.evaluate("document.getElementById('revision-status').textContent")
        self.assertIn("고침 1", status)
        self.assertNotIn("바뀐 블록 없음", status)
        self.assertFalse(
            page.evaluate(
                "document.querySelector('#revision-rendered').textContent.includes('두 판의 그린 문서가 같습니다')"
            )
        )


class EmptyFence(OneNote):
    """An empty python fence that gains one blank line: the fence's lines go from none to one empty line."""

    def texts(self):
        return ["# 메모\n\n```py\n```\n\n끝\n", "# 메모\n\n```py\n\n```\n\n끝\n"]

    def test_a_blank_line_added_to_an_empty_fence_is_a_change(self):
        """The commit adds a blank line inside an empty fence: the code block is changed in place, not "no changed
        block" - its key keeps the number of lines, so [] and [''] differ though both join to ''."""
        page = self.open_compare()
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("mod", "PRE")])
        self.assertNotIn("바뀐 블록 없음", page.evaluate("document.getElementById('revision-status').textContent"))


class PinInTheLastGitLine(OneNote):
    """A note whose last git line holds two form feeds, so its paragraph B is the screen's line 7 and git's line 5, with no
    git line after it: the commit rewrites B, with and without a final newline."""

    def texts(self):
        return [
            TAIL.format(b="B 문단이다.", end="\n"),
            TAIL.format(b="B 문단을 고쳤다.", end="\n"),
            TAIL.format(b="B 문단을 또 고쳤다.", end=""),
        ]

    def ringed(self, commit):
        """The blocks a pin on B closed with commit rings in its [그린 비교], as [kind, text]."""
        self.md.write_text(self.texts()[self.c.index(commit)], encoding="utf-8")
        lines = self.md.read_text(encoding="utf-8").splitlines()
        lo = next(i for i, ln in enumerate(lines, 1) if ln.startswith("B "))
        self.assertEqual(lo, 7)
        page = self.pin_rendered(self.pin_on(lo, lo, commit))
        rows = self.ringed_rows(page)
        page.close()
        return rows

    def test_a_pins_hunk_in_the_last_git_line_rings_the_block_it_changed(self):
        """git's hunk [5,5] is the screen's lines 5-7 (A to B), so the pin rings B, changed - not A alone, unchanged."""
        self.assertEqual(self.ringed(self.c[1]), [["mod", "B 문단을 고쳤다."]])

    def test_the_same_without_a_final_newline(self):
        self.assertEqual(self.ringed(self.c[2]), [["mod", "B 문단을 또 고쳤다."]])


class ImageNotice(CompareBase):
    """The note draws an image from the tree: the compare says, where it is read and seen, that both sides' images are the
    tree's files of now."""

    def test_the_image_notice_is_in_the_accessibility_tree_and_visible(self):
        page = self.open_compare()
        notice = "그림은 두 판 모두 지금 원고 트리의 파일입니다"
        self.assertIn(notice, page.locator("#revision-rendered").aria_snapshot())
        found = page.get_by_text(notice)
        self.assertTrue(found.is_visible())
        self.assertFalse(found.evaluate("e=>!!e.closest('[aria-hidden=true]')"))
        self.assertNotIn(notice, page.evaluate("document.querySelector('#revision-rendered .mdc-legend').textContent"))


ZWSP, WJ = "​", "⁠"
HFM = "---\ntitle: {title}\nauthor: a\n---\n\n# 문서\n\nA{cc}B 문단이다.\n\n$$\nx = {x}\n$$\n\n인라인 {inl} 수식이다.\n\n끝 문단이다.\n"


class HiddenFrontMath(OneNote):
    """The front matter's title changes, a paragraph's hidden character changes (U+200B to U+2060, nothing else), display
    math changes, and an inline formula becomes inline code of the same text: the compare draws the same blocks the
    document view does (ADR-0029 D5, ADR-0032), so each of the four is a block changed in place."""

    def texts(self):
        return [
            HFM.format(title="옛 제목", cc=ZWSP, x=1, inl="$a+b$"),
            HFM.format(title="새 제목", cc=WJ, x=2, inl="`$a+b$`"),
        ]

    def test_hidden_characters_front_matter_and_math_compare_as_blocks(self):
        """Marks in order: the front matter (its title line taken out and added), the paragraph (the old character's box
        put back struck through, the new one's added), the display math (its line), the paragraph whose formula became
        code (the formatting changed); the hidden-character notice counts the two boxes. Mutations: leave the box out of
        mdcShape and mdcToks (as the screen reader's words) -> the paragraph is the same block, fails; take .md-front out
        of MDC_UNIT -> the front matter is not marked, fails; name code by its tag alone in mdcInl -> the last paragraph is
        the same block, fails."""
        page = self.open_compare()
        self.assertEqual(
            [(k, t) for k, t, _ in self.marks(page)], [("mod", "DIV"), ("mod", "P"), ("mod", "PRE"), ("mod", "P")]
        )
        got = page.evaluate(
            "(()=>{const q=s=>[...document.querySelectorAll('#revision-rendered '+s)];"
            "const words=s=>q(s).map(e=>{const c=e.cloneNode(true);c.querySelectorAll('.sr-only').forEach(x=>x.remove());return c.textContent;});"
            "return {front:[q('.md-front[data-mdc=mod]').length,words('.md-front del.mdc-w'),words('.md-front ins.mdc-w')],"
            "boxes:[q('p del.mdc-w .cc').map(e=>e.dataset.cc),q('p ins.mdc-w .cc').map(e=>e.dataset.cc)],"
            "names:[ccName(0x200b),ccName(0x2060)],"
            "math:[q('pre.md-math-block[data-mdc=mod]').length,words('pre.md-math-block del.mdc-w'),words('pre.md-math-block ins.mdc-w')],"
            "code:q('[data-mdc]').map(e=>e.dataset.mdcWhy||'')[3],"
            "notice:q('.mdc-info').map(e=>e.textContent).join('|')};})()"
        )
        self.assertEqual(got["front"], [1, ["title: 옛 제목\n"], ["title: 새 제목"]])
        self.assertEqual(got["boxes"], [[got["names"][0]], [got["names"][1]]])
        self.assertEqual(got["math"], [1, ["x = 1\n"], ["x = 2"]])
        self.assertEqual(got["code"], "글자 모양(굵게·기울임·코드·링크)이 바뀜")
        self.assertIn("문자 2개를 이름으로 표시했습니다", got["notice"])
        # the box put back holds the old character itself, for a copy and the screen reader, as a drawn box does
        self.assertEqual(
            page.evaluate("document.querySelector('#revision-rendered p del.mdc-w .cc .sr-only').textContent"), ZWSP
        )


class HiddenFrontMathFirefox(HiddenFrontMath):
    """The same in Firefox."""

    BROWSER_ENGINE = "firefox"


BIG = "# 큰 문서\n\n" + ("이 문단은 한도를 넘기려고 되풀이한 문장이다. " * 40 + "\n\n") * 460


class SidePastLimit(OneNote):
    """The commit makes the note larger than 1 MiB: its new side is not drawn, and the compare's place says so with the
    way to the source diff."""

    def texts(self):
        assert len(BIG.encode("utf-8")) > 1_048_576
        return ["# 큰 문서\n\n짧은 문단이다.\n", BIG]

    def test_a_side_past_one_mebibyte_sends_the_reader_to_the_source_diff(self):
        """The new side is source_too_large: the pane holds a status note naming its size and the limit, and its [소스 diff
        보기] opens the source diff. Mutation: let mdcShow draw a side without lines as an empty document (skip its
        reason) -> no note, fails."""
        page = self.open(0)
        until(page, "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')", 20)
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        until(page, "REV.format===DIFF_FORMAT.RENDERED&&!!document.querySelector('#revision-rendered .mdc-note')", 15)
        note = page.locator("#revision-rendered .mdc-note")
        self.assertEqual(note.get_attribute("role"), "status")
        text = note.text_content()
        self.assertIn("새 판이", text)
        self.assertIn("한도 1 MiB", text)
        self.assertIn("그려 비교하지 않습니다", page.locator("#revision-rendered").aria_snapshot())
        note.get_by_role("button", name="소스 diff 보기").click()
        until(page, "REV.format===DIFF_FORMAT.SOURCE&&REV.sourceCommit===revKey()", 15)
        self.assertEqual(
            page.evaluate("document.getElementById('revision-source-tab').getAttribute('aria-pressed')"), "true"
        )


class TabsAndFocus(CompareBase):
    """What a screen reader and a keyboard meet: the tabs are named buttons with their pressed state, a marked block is read
    with its kind, the notices are read, and the focus stays on the tab a key pressed."""

    def test_the_tabs_are_named_and_pressed_and_keep_the_focus(self):
        """[그린 비교] and [소스 diff] are buttons by those names, one pressed; the navigator is a named group of two
        named buttons; the moved blocks are read as moved and the legend's chips are not read. Enter on [소스 diff] and
        then on [그린 비교] switches the view and leaves the focus on the key's tab. Mutation: blur the active element in
        setRevisionFormat -> the focus falls to the body, fails."""
        page = self.open_compare()
        rendered = page.get_by_role("button", name="그린 비교", exact=True)
        source = page.get_by_role("button", name="소스 diff", exact=True)
        self.assertEqual(
            [rendered.get_attribute("aria-pressed"), source.get_attribute("aria-pressed")], ["true", "false"]
        )
        nav = page.get_by_role("group", name="바뀐 곳 이동")
        self.assertTrue(nav.get_by_role("button", name="이전 바뀐 곳").is_visible())
        self.assertTrue(nav.get_by_role("button", name="다음 바뀐 곳").is_visible())
        tree = page.locator("#revision-rendered").aria_snapshot()
        self.assertIn("옮긴 블록:", tree)
        self.assertNotIn("더함", tree)  # the legend and the gutter chips are aria-hidden: each block says its own kind
        self.assertIn("옮김 2", page.locator("#revision-status").text_content())
        self.assertEqual(page.locator("#revision-status").get_attribute("role"), "status")
        source.focus()
        page.keyboard.press("Enter")
        until(page, "REV.format===DIFF_FORMAT.SOURCE&&REV.sourceCommit===revKey()", 15)
        self.assertEqual(page.evaluate("document.activeElement&&document.activeElement.id"), "revision-source-tab")
        rendered.focus()
        page.keyboard.press("Enter")
        until(page, COMPARED, 15)
        self.assertEqual(page.evaluate("document.activeElement&&document.activeElement.id"), "revision-rendered-tab")
        self.assertEqual(rendered.get_attribute("aria-pressed"), "true")


LONG = "# 긴 문서\n\n" + "".join("문단 %d은 짧은 문장이다.\n\n" % i for i in range(3000))


class BuildPauses(OneNote):
    """A note of 3,000 paragraphs whose commit changes one of them."""

    def texts(self):
        return [LONG, LONG.replace("문단 1500은", "문단 1500을 고쳤고")]

    def test_the_compare_builds_with_its_own_context_and_pauses_like_the_document_view(self):
        """Both sides are built with a render context of their own: the document view's lines, element count, headings
        and marked count are what they were, and the build yields to the browser every MD_LIMITS.chunk units of work
        (thousands of units per side, so several pauses). Mutations: build the sides with MD as their context in
        mdcBuild -> MD's headings and count change, fails; drain mdRender without a yield -> no pause, fails."""
        page = self.open(0)
        until(page, DRAWN, 20)
        settle(page)
        before = page.evaluate(
            "(()=>{window.__keep={lines:MD.lines,heads:MD.heads,head:MD.heads[0].el};"
            "return [MD.lines.length,MD.els,MD.marked,MD.heads.length,MD.bom];})()"
        )
        page.evaluate("(()=>{const y=mdYield;window.__n=0;window.mdYield=()=>{window.__n++;return y();};})()")
        page.evaluate("setViewMode(VIEW_MODE.REVISIONS)")
        until(page, COMPARED, 30)
        self.assertEqual([(k, t) for k, t, _ in self.marks(page)], [("mod", "P")])
        self.assertGreaterEqual(page.evaluate("window.__n"), 6)
        self.assertEqual(page.evaluate("[MD.lines.length,MD.els,MD.marked,MD.heads.length,MD.bom]"), before)
        # the very arrays and heading the document view drew, still in article#md - not a side's like them
        self.assertEqual(
            page.evaluate(
                "[MD.lines===__keep.lines,MD.heads===__keep.heads,MD.heads[0].el===__keep.head,!!MD.heads[0].el.closest('#md')]"
            ),
            [True, True, True, True],
        )
