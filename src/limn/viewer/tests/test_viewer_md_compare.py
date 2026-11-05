"""The rendered compare of a Markdown document in the browser ([그린 비교], docs/superpowers/specs/2026-11-05-markdown-
rendered-compare.md): both sides of a commit or a range drawn and compared block by block, a pin's blocks ringed, one
column everywhere and two only where they fit, never sideways.

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

    def test_a_range_keeps_the_rendered_compare_and_paints_its_commits(self):
        """From the rewrite to now: every kind at once, and the list paints the range's commits (the source diff's answer
        read beside the compare)."""
        page = self.open_compare()
        page.evaluate("setRevisionRange(RANGE_MODE.FROM)")
        page.locator("#revision-commits .rc-row").nth(3).click()
        until(page, COMPARED + "&&!!REV.base&&REV.rangeIds!==null", 15)
        settle(page)
        kinds = sorted({k for k, _, _ in self.marks(page)})
        self.assertEqual(kinds, ["del", "ins", "mod", "move"])
        self.assertEqual(page.evaluate("document.querySelectorAll('#revision-commits .rc-row.in').length"), 4)
        self.assertEqual(page.evaluate("REV.format"), "rendered")

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


class PinBlocks(CompareBase):
    """A pin closed with the table's commit: its [변경 보기] opens that commit's rendered compare with its blocks ringed."""

    def test_a_pins_change_view_rings_its_changed_blocks(self):
        lo = next(
            i for i, ln in enumerate(self.md.read_text(encoding="utf-8").splitlines(), 1) if ln.startswith("| 전이")
        )
        body = json.dumps({"doc": "nt", "file": str(self.md), "lo": lo, "hi": lo + 1, "note": "n"}).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        pid = json.loads(out)["id"]
        close = json.dumps(
            {"ref": "(%s)" % self.c[2][:7], "changes": [{"file": "note.md", "lo": lo, "hi": lo + 1}]}
        ).encode()
        code, _, out = self.talk(req("POST", "/api/pins/%d/close" % pid, close, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        page = self.open(0)
        until(page, DRAWN, 20)
        until(page, "REVIEW_ALL.some(p=>p.id===%d)" % pid, 10)
        page.evaluate("showChange(%d)" % pid)
        until(page, COMPARED + "&&!!document.querySelector('#revision-rendered .mdc-pin')", 15)
        settle(page)
        self.assertEqual(page.evaluate("REV.commit"), self.c[2])
        rows = page.evaluate(
            "[...document.querySelectorAll('#revision-rendered .mdc-pin')].map(e=>[e.tagName,e.dataset.mdc])"
        )
        self.assertEqual(rows, [["TR", "mod"], ["TR", "ins"]])
        self.assertIn("보라 테두리", page.evaluate("document.getElementById('revision-pin').textContent"))


class Layout(CompareBase):
    """One column on every band, never wider than the screen; two columns only where asked for and wide enough."""

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

    def test_two_columns_align_their_shared_blocks_and_stack_when_narrow(self):
        """?cmp=split: on a wide pane the old and the new side stand side by side, each shared heading at the same height;
        with the pin panel and outline open the pane is too narrow and the compare is one column that says so."""
        init = "history.replaceState(null,'',location.pathname+'?lang=ko&cmp=split')"
        page = self.open_compare(viewport={"width": 1440, "height": 900}, init=init)
        self.assertEqual(page.evaluate("document.querySelectorAll('.mdc-cols').length"), 0)
        self.assertIn("한 단으로", page.evaluate("document.getElementById('revision-rendered').textContent"))
        page.evaluate("setSide(false)")
        page.set_viewport_size({"width": 1700, "height": 900})
        self.show(page, self.c[4], self.c[0])
        self.assertEqual(page.evaluate("document.querySelectorAll('.mdc-cols .mdc-doc').length"), 2)
        page.wait_for_timeout(300)
        offs = page.evaluate(
            "(()=>{const r=[...document.querySelectorAll('.mdc-cols .mdc-doc')],t=r.map(x=>x.getBoundingClientRect().top);"
            "const at=(k,s)=>[...r[k].querySelectorAll('h2')].find(h=>h.textContent.includes(s));"
            "return ['방법','결과'].map(s=>Math.abs((at(0,s).getBoundingClientRect().top-t[0])-(at(1,s).getBoundingClientRect().top-t[1])));})()"
        )
        self.assertTrue(all(d <= 2 for d in offs), offs)


STRUCT = "# 구조\n\n{warn}\n\n{quote}인용한 문장이다.\n\n{n}. 첫 항목\n{m}. 둘째 항목\n\n![{alt}](figs/v1.png)\n\n끝 문단이다.\n"
FF = "# 줄 끝\n\nA 문단이다.\x0c이어지는 A.\n\nB 첫 줄이다.\u2028B 둘째 줄.\n\nC 문단이다.\n\n{d}\n"


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
        """A pin on D closed with that commit: its [변경 보기] rings D (changed), not C two lines above in git's numbering."""
        lines = self.md.read_text(encoding="utf-8").splitlines()
        lo = next(i for i, ln in enumerate(lines, 1) if ln.startswith("D "))
        body = json.dumps({"doc": "nt", "file": str(self.md), "lo": lo, "hi": lo, "note": "n"}).encode()
        code, _, out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        pid = json.loads(out)["id"]
        close = json.dumps(
            {"ref": "(%s)" % self.c[1][:7], "changes": [{"file": "note.md", "lo": lo, "hi": lo}]}
        ).encode()
        code, _, out = self.talk(req("POST", "/api/pins/%d/close" % pid, close, {"Content-Type": "application/json"}))
        self.assertEqual(code, 200, out)
        page = self.open(0)
        until(page, DRAWN, 20)
        until(page, "REVIEW_ALL.some(p=>p.id===%d)" % pid, 10)
        page.evaluate("showChange(%d)" % pid)
        until(page, COMPARED + "&&!!document.querySelector('#revision-rendered .mdc-pin')", 15)
        settle(page)
        rows = page.evaluate(
            "[...document.querySelectorAll('#revision-rendered .mdc-pin')].map(e=>{const c=e.cloneNode(true);"
            "c.querySelectorAll('.sr-only,del').forEach(x=>x.remove());return [e.dataset.mdc||'',c.textContent.trim()];})"
        )
        self.assertEqual(rows, [["mod", "D 문단을 고쳤다."]])


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
