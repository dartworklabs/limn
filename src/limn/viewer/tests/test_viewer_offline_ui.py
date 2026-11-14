"""The queued pins on screen (js/offline-ui.js, docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기).

A pin made while cut off waits in this browser's queue (IndexedDB limnOffline). The person has to see where they already
pinned, which pins are held back and why, and be able to drop one or pin it again. The pure parts - which records draw a
mark, how a record's place and reason are said - run under node on the served source. The screen is read in the real
viewer with records seeded through the shipped queue functions (offAdd, offlineSync): the marks on the page and their
filters (document, build, page, line pins), the panel's section and its rows, [버리기] and its undo in the row's place,
[다시 찍기] putting the note in the composer for the next drag, the desktop status line, and the harsh records the contract
names (an empty quote, a 3,000-character note, a page past the document, another build, a held record with no reason,
another document's record).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_offline_ui.py
"""

import json
import shutil
import unittest

from helpers import extract_js_fn, run_node
from helpers_browser import BrowserBase, settle

DESKTOP = {"viewport": {"width": 1440, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
BUILD = "pages-20260925100000"  # BrowserBase's build

# Seeds the queue with records (each merged over a whole record of the build on screen) through the shipped functions.
SEED = """async recs=>{for(const r of recs){const rec=Object.assign({v:1,label:'Demo',doc:DEFAULT_DOC,build:META.pages_build,
  pt:{w:612,h:792},rect:null,quote:'q',note:'n',kind_req:'fix',assignee:'agent',mentions:[],at:new Date().toISOString(),
  held:false,why:'',sent:false,place:null},r); await offAdd(rec);} await offlineSync(); return OFF.n;}"""
QUEUE = "async()=>(await offAll()).map(r=>r.note)"
MARKS = """()=>[...document.querySelectorAll('.qmark')].map(m=>({page:Number(m.parentElement.dataset.page),held:m.classList.contains('held'),
  left:m.style.left,top:m.style.top,label:m.querySelector('button').getAttribute('aria-label')}))"""
ROWS = """()=>[...document.querySelectorAll('#queue-rows>.qrow')].map(r=>({label:r.getAttribute('aria-label'),held:r.classList.contains('held'),
  why:(r.querySelector('.q-why')||{}).textContent||null,old:!!r.querySelector('.q-old'),go:!!r.querySelector('.q-go'),
  at:(r.querySelector('.q-go,.q-at')||{}).textContent||'',h:Math.round(r.getBoundingClientRect().height),note:r.querySelector('.q-note').textContent}))"""


def node_json(test, js):
    """Run js under node and return what it printed as JSON; skip the calling test when node is missing."""
    if not shutil.which("node"):
        test.skipTest("node not available")
    return json.loads(run_node(js))


STUBS = """
function tr(s){return s;}
function tl(s,p){return s.replace(/\\{(\\w+)\\}/g,function(_,k){return String(p[k]);});}
"""


class QueueRowsLogic(unittest.TestCase):
    """offUiRows, offUiWhy, offUiPlace, offUiFrac and statusShown, on the served source."""

    def run_js(self, body, *names):
        return node_json(self, STUBS + "\n".join(extract_js_fn(n) for n in names) + "\n" + body)

    def test_a_mark_is_drawn_only_on_this_document_and_build_and_a_page_it_has(self):
        """Of seven records only this document's, drawn on the build on screen, on a page the document has, with a box on
        the page, draw a mark; another document's rows come after this document's, each in the order they were kept."""
        got = self.run_js(
            """
            const B='b1',f=[0.1,0.2,0.3,0.05];
            const all=[{id:1,doc:'cl',build:B,page:1,frac:f},{id:2,doc:'ms',build:B,page:1,frac:f},
              {id:3,doc:'ms',build:'b0',page:1,frac:f},{id:4,doc:'ms',build:B,page:9,frac:f},
              {id:5,doc:'ms',build:B,page:null,frac:null,lines:{file:'a.md',lo:1,hi:2}},{id:6,build:B,page:2,frac:[0.9,0.1,0.3,0.1]},
              {id:7,build:B,page:2,frac:f,held:true},null,'junk'];
            console.log(JSON.stringify(offUiRows(all,'ms','ms',B,2).map(r=>[r.rec.id,r.here,r.mark,r.old,r.lines,r.held])));
            """,
            "offUiFrac",
            "offUiRows",
        )
        self.assertEqual(
            got,
            [
                [2, True, True, False, False, False],
                [3, True, False, True, False, False],  # another build: listed, said, not drawn
                [4, True, False, False, False, False],  # page 9 of 2
                [5, True, False, False, True, False],  # a line pin has no page
                [6, True, False, False, False, False],  # a box past the page's right edge
                [7, True, True, False, False, True],  # no document: the default one, which is on screen
                [1, False, False, False, False, False],  # another document's, last
            ],
        )

    def test_a_held_record_always_says_why_and_a_place_reads_as_a_page_or_lines(self):
        """A held record with an empty reason says the reason held records have; a waiting one says none. A place is
        '3쪽', a line pin's 'intro.md 12–14줄' or '12줄', and nothing when the record says neither."""
        got = self.run_js(
            """
            console.log(JSON.stringify([offUiWhy({held:true,why:''}),offUiWhy({held:true,why:'  '}),offUiWhy({held:true,why:'빌드 없음'}),
              offUiWhy({held:false,why:'x'}),offUiPlace({page:3}),offUiPlace({page:null,lines:{file:'notes/intro.md',lo:12,hi:14}}),
              offUiPlace({page:null,lines:{file:'a.md',lo:12,hi:12}}),offUiPlace({page:0}),offUiPlace({}),
              offUiClip('  a\\n b  ',10),offUiClip('x'.repeat(30),10).length]));
            """,
            "offUiWhy",
            "offUiPlace",
            "offUiClip",
        )
        self.assertEqual(
            got,
            [
                "위치를 찾지 못했습니다",
                "위치를 찾지 못했습니다",
                "빌드 없음",
                "",
                "3쪽",
                "intro.md 12–14줄",
                "a.md 12줄",
                "",
                "",
                "a b",
                10,
            ],
        )

    def test_a_box_must_lie_on_the_page(self):
        got = self.run_js(
            "console.log(JSON.stringify([[0,0,1,1],[0.1,0.2,0.3,0.4],[0,0,0,0.1],[0.8,0,0.3,0.1],[-0.1,0,0.2,0.2],"
            "[0.1,0.1,NaN,0.1],[0.1,0.1,0.1],'x',null].map(offUiFrac)));",
            "offUiFrac",
        )
        self.assertEqual(got, [True, True, False, False, False, False, False, False, False])

    def test_the_desktop_line_shows_the_kept_pins(self):
        """On the desktop the line keeps the kept pins' item (no chip counts them) and still drops what its chips say."""
        got = self.run_js(
            """
            const K=STATUS_KIND,list=[{kind:K.OFFLINE},{kind:K.QUEUED},{kind:K.STALE},{kind:K.NOTICE}];
            console.log(JSON.stringify([statusShown(list,true).map(i=>i.kind),statusShown(list,false).length]));
            """,
            "statusShown",
        )
        self.assertEqual(got, [["queued", "notice"], 4])


class QueuedPinsScreen(BrowserBase):
    """The real viewer (two pages, build pages-20260925100000) with records seeded into its queue."""

    def view(self, recs=None, lang="ko", **device):
        page = self.open(0, lang=lang, init=NO_COACH, **(device or DESKTOP))
        if recs:
            page.evaluate(SEED, recs)
            settle(page)
        return page

    def three(self):
        return [
            {"page": 1, "frac": [0.2, 0.2, 0.5, 0.05], "note": "첫째", "quote": "Line 5"},
            {"page": 1, "frac": [0.2, 0.4, 0.5, 0.05], "note": "둘째"},
            {"page": 1, "frac": [0.2, 0.6, 0.5, 0.05], "note": "셋째", "held": True, "why": "빌드가 없어졌습니다"},
        ]

    def test_with_no_queue_nothing_is_drawn(self):
        """No record: no mark, no section, and the status line says nothing of kept pins."""
        page = self.view()
        self.assertEqual(page.evaluate(MARKS), [])
        self.assertTrue(page.is_hidden("#sec-queue"))
        self.assertEqual(
            page.evaluate("statusShown(statusList(statusInput()),true).filter(i=>i.kind==='queued').length"), 0
        )

    def test_three_on_one_page_with_one_held(self):
        """Three marks on page 1 at their boxes, the held one apart by its class and its name; the section lists the three
        with their state in words, the held one with its reason; the desktop status line counts them."""
        page = self.view(self.three())
        marks = page.evaluate(MARKS)
        self.assertEqual(
            [(m["page"], m["held"], m["top"]) for m in marks], [(1, False, "20%"), (1, False, "40%"), (1, True, "60%")]
        )
        self.assertEqual(marks[2]["label"], "보류된 핀 — 목록에서 보기")
        self.assertEqual(marks[0]["label"], "쌓인 핀 — 목록에서 보기")
        self.assertTrue(page.is_visible("#sec-queue"))
        self.assertEqual(page.inner_text("#queue-toggle .sec-n"), "3")
        self.assertEqual(page.inner_text("#queue-toggle .q-held-n"), "보류 1")
        rows = page.evaluate(ROWS)
        self.assertEqual(
            [r["label"] for r in rows], ["쌓인 핀: 대기 · 1쪽", "쌓인 핀: 대기 · 1쪽", "쌓인 핀: 보류 · 1쪽"]
        )
        self.assertEqual([r["why"] for r in rows], [None, None, "빌드가 없어졌습니다"])
        self.assertTrue(page.is_visible("#status-wide #status"))
        self.assertEqual(page.inner_text("#status .st-tx"), "오프라인 핀 3개 · 1개는 자리를 다시 골라야 합니다")
        # the frames let every press through to the page; only their badges take one
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.qmark')).pointerEvents"), "none")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.qmark')).borderRadius"), "0px")
        # a badge answers 24px round its centre with a mouse, as a saved one does
        self.assertEqual(
            page.evaluate("getComputedStyle(document.querySelector('.qmark-jump'),'::after').width"), "24px"
        )

    def test_harsh_records_do_not_break_the_screen(self):
        """An empty quote, a 3,000-character note, page 9 of 2, another build, a held record with no reason, another
        document's record and a line pin: three marks (the ones drawn on this build and page), seven rows, the long note
        folded, the reasons and the other build said, and the panel not wider than itself."""
        page = self.view(
            [
                {"page": 1, "frac": [0.1, 0.1, 0.3, 0.05], "quote": "", "note": "인용 없음"},
                {"page": 1, "frac": [0.5, 0.1, 0.3, 0.05], "note": "가" * 3000},
                {"page": 9, "frac": [0.1, 0.1, 0.3, 0.05], "note": "뒤 쪽"},
                {"page": 1, "frac": [0.1, 0.5, 0.3, 0.05], "note": "다른 빌드", "build": "pages-20200101000000"},
                {"page": 2, "frac": [0.1, 0.5, 0.3, 0.05], "note": "사유 없음", "held": True, "why": ""},
                {"page": 1, "frac": [0.1, 0.5, 0.3, 0.05], "note": "다른 문서", "doc": "other"},
                {"page": None, "frac": None, "lines": {"file": "notes/intro.md", "lo": 12, "hi": 14}, "note": "줄 핀"},
            ]
        )
        self.assertEqual([(m["page"], m["held"]) for m in page.evaluate(MARKS)], [(1, False), (1, False), (2, True)])
        rows = page.evaluate(ROWS)
        self.assertEqual(
            [r["note"][:5] for r in rows],
            ["인용 없음", "가가가가가", "뒤 쪽", "다른 빌드", "사유 없음", "줄 핀", "다른 문서"],
        )
        self.assertLess(rows[1]["h"], 220)  # three lines of note, not a wall of text
        self.assertEqual(rows[4]["why"], "위치를 찾지 못했습니다")
        self.assertTrue(rows[3]["old"])
        self.assertEqual((rows[2]["at"], rows[2]["go"]), ("9쪽", False))  # no page 9 to go to
        self.assertEqual((rows[5]["at"], rows[5]["go"]), ("intro.md 12–14줄", False))
        self.assertEqual((rows[6]["at"], rows[6]["go"]), ("other1쪽", False))  # an unknown document: named, not a link
        self.assertEqual(page.evaluate("document.querySelectorAll('#queue-rows .q-quote').length"), 6)
        self.assertEqual(
            page.evaluate("(()=>{const l=document.getElementById('list');return l.scrollWidth<=l.clientWidth;})()"),
            True,
        )

    def test_drop_leaves_its_undo_in_place_and_undo_puts_it_back(self):
        """[버리기] takes the record out of the queue and its mark off the page; an undo row stands in its place, its
        [되돌리기] puts the same record back (same id, same note) where it was. Its window ends by itself."""
        page = self.view(self.three())
        page.click("#queue-rows>.qrow:nth-child(2) [data-q=drop]")
        page.wait_for_function("OFF.n===2")
        settle(page)
        self.assertEqual(page.evaluate(QUEUE), ["첫째", "셋째"])
        self.assertEqual(len(page.evaluate(MARKS)), 2)
        kids = page.evaluate(
            "[...document.querySelectorAll('#queue-rows>*')].map(e=>e.dataset.undo?'undo':e.dataset.qid)"
        )
        self.assertEqual(kids[1], "undo")
        self.assertEqual(
            page.evaluate("document.activeElement.dataset.q"), "undo"
        )  # the focus stays where it was pressed
        page.click("#queue-rows [data-q=undo]")
        page.wait_for_function("OFF.n===3")
        settle(page)
        self.assertEqual(page.evaluate(QUEUE), ["첫째", "둘째", "셋째"])
        self.assertEqual(page.evaluate("document.querySelectorAll('#queue-rows>[data-undo]').length"), 0)
        self.assertEqual(len(page.evaluate(MARKS)), 3)
        page.click("#queue-rows>.qrow:nth-child(3) [data-q=drop]")
        page.wait_for_function("OFF.n===2")
        page.wait_for_function("!document.querySelector('#queue-rows>[data-undo]')", timeout=12000)
        self.assertEqual(page.evaluate(QUEUE), ["첫째", "둘째"])

    def test_the_last_drop_keeps_the_section_for_its_undo(self):
        page = self.view([self.three()[0]])
        page.click("#queue-rows [data-q=drop]")
        page.wait_for_function("OFF.n===0")
        settle(page)
        self.assertTrue(page.is_visible("#sec-queue"))
        self.assertTrue(page.is_visible("#queue-rows [data-q=undo]"))
        page.click("#queue-rows [data-q=undo-x]")
        settle(page)
        self.assertTrue(page.is_hidden("#sec-queue"))

    def test_redo_puts_the_note_in_the_composer_for_the_next_drag(self):
        """[다시 찍기] takes the record out and puts its note (and its kind) in the hidden composer; the next drag opens the
        composer with that note. A note already being written is not overwritten."""
        page = self.view(
            [
                {"page": 1, "frac": [0.2, 0.2, 0.5, 0.05], "note": "다시 찍을 메모", "kind_req": "question"},
                {"page": 1, "frac": [0.2, 0.4, 0.5, 0.05], "note": "남는 메모"},
            ]
        )
        page.click("#queue-rows>.qrow:nth-child(1) [data-q=redo]")
        page.wait_for_function("OFF.n===1")
        settle(page)
        self.assertEqual(page.input_value("#note"), "다시 찍을 메모")
        self.assertEqual(page.evaluate("KIND_NEW"), "question")
        self.assertTrue(page.is_hidden("#composer"))
        self.assertEqual(page.evaluate(QUEUE), ["남는 메모"])
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect();return [r.left,r.top,r.width,r.height];})()"
        )
        x, y = box[0] + box[2] * 0.25, box[1] + box[3] * 0.75
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + box[2] * 0.3, y + box[3] * 0.05, steps=6)
        page.mouse.up()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        self.assertEqual(page.input_value("#note"), "다시 찍을 메모")
        # a note being written now: the other record is not taken back over it
        page.fill("#note", "쓰는 중")
        page.click("#queue-rows>.qrow [data-q=redo]")
        settle(page)
        self.assertEqual(page.evaluate(QUEUE), ["남는 메모"])
        self.assertEqual(page.input_value("#note"), "쓰는 중")
        self.assertIn("작성 중인 메모가 있습니다", page.evaluate("LINE.map(n=>n.title).join('|')"))

    def test_redo_undo_takes_the_note_back_out(self):
        page = self.view([{"page": 1, "frac": [0.2, 0.2, 0.5, 0.05], "note": "되돌릴 메모"}])
        page.click("#queue-rows [data-q=redo]")
        page.wait_for_function("OFF.n===0")
        settle(page)
        page.click("#queue-rows [data-q=undo]")
        page.wait_for_function("OFF.n===1")
        settle(page)
        self.assertEqual(page.input_value("#note"), "")
        self.assertEqual(page.evaluate(QUEUE), ["되돌릴 메모"])

    def test_redo_undo_on_another_document_leaves_that_documents_note(self):
        """A take-back's undo pressed after the document changed: the note field is that document's draft, so it is not
        cleared (even holding the same words) and the record is not put back; the line says why."""
        page = self.view([{"page": 1, "frac": [0.2, 0.2, 0.5, 0.05], "note": "같은 글"}])
        page.click("#queue-rows [data-q=redo]")
        page.wait_for_function("OFF.n===0")
        settle(page)
        page.evaluate("DOC='other'")  # as after a switch: the field now holds the other document's draft
        page.click("#queue-rows [data-q=undo]")
        settle(page)
        self.assertEqual(page.input_value("#note"), "같은 글")
        self.assertEqual(page.evaluate(QUEUE), [])
        self.assertIn("다른 문서로 옮겨 되돌리지 않았습니다", page.evaluate("LINE.map(n=>n.title).join('|')"))
        self.assertEqual(page.evaluate("document.querySelectorAll('#queue-rows>[data-undo]').length"), 0)
        page.evaluate("DOC=DEFAULT_DOC")

    def test_a_marks_badge_shows_its_row_and_starts_no_selection(self):
        """A mouse press on a mark's badge never starts a box on the page; its click brings the row into view, flashed."""
        page = self.view(self.three())
        page.click(".qmark.held .qmark-jump")
        page.wait_for_function("document.querySelector('.qrow.held').classList.contains('flash')", timeout=4000)
        self.assertEqual(page.evaluate("!!COMPOSE.current||!!document.querySelector('.sel')"), False)

    def test_a_rows_page_link_goes_to_that_page(self):
        page = self.view([{"page": 2, "frac": [0.2, 0.5, 0.5, 0.05], "note": "둘째 쪽"}])
        page.click("#queue-rows .q-go")
        page.wait_for_function("document.getElementById('left').scrollTop>100", timeout=5000)

    def test_pages_drawn_again_get_their_marks_again(self):
        """The page boxes are made anew (a new build, another document, a zoom that rebuilds them): the marks, which went
        with the old boxes, are drawn on the new ones."""
        page = self.view(self.three())
        old = page.evaluate(
            "(()=>{window._p1=document.getElementById('p1'); return document.querySelectorAll('.qmark').length;})()"
        )
        page.evaluate("buildDoc()")
        page.wait_for_function(
            "document.getElementById('p1')!==window._p1&&document.querySelectorAll('#p1 .qmark').length===3",
            timeout=5000,
        )
        self.assertEqual(old, 3)

    def test_phone_lists_them_in_the_sheet_with_touch_sized_actions(self):
        """On a phone the status line already counts the kept pins; the sheet lists them and each action answers 44px."""
        page = self.view(self.three(), **PHONE)
        self.assertIn("오프라인 핀 3", page.inner_text("#status .st-tx"))
        page.evaluate("setSide(true)")
        settle(page)
        self.assertTrue(page.is_visible("#sec-queue"))
        sizes = page.evaluate(
            "[...document.querySelectorAll('#queue-rows .q-acts button')].map(b=>Math.round(b.getBoundingClientRect().height))"
        )
        self.assertEqual(set(sizes), {44})
        hit = page.evaluate("getComputedStyle(document.querySelector('#queue-rows .q-go'),'::after').height")
        self.assertEqual(hit, "44px")
        badge = page.evaluate("getComputedStyle(document.querySelector('.qmark-jump'),'::after').height")
        self.assertEqual(badge, "44px")

    def test_english_screen_reads_english_outside_what_the_person_wrote(self):
        page = self.view(
            [
                {"page": 1, "frac": [0.2, 0.2, 0.5, 0.05], "note": "a note", "quote": "Line 5"},
                {"page": 1, "frac": [0.2, 0.4, 0.5, 0.05], "note": "held", "held": True, "why": ""},
            ],
            lang="en",
        )
        text = page.inner_text("#sec-queue")
        self.assertNotRegex(text, "[가-힣]")
        self.assertIn("Kept pins", text)
        self.assertIn("Held", text)


if __name__ == "__main__":
    unittest.main()
