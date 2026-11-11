"""Taking the pin marks off the page for a look at what is under them (docs/handbook/viewer.md §핀 표시 숨기기).

A pin's mark lies over what it marks, so a pinned figure is seen through a frame, a tint and a badge. The marks can be
taken off without touching a pin: H switches them, H held flips them only while it is down, and [더보기]'s [핀 표시]
switch does it on a touch screen. Read in the real viewer: what a person sees of the marks (visibility, the tint, the
badge as a Tab stop), what the status line and the switch say, and that the marks come back when one of them has something
to show - a card's [보기], a save's undo chip. The pins themselves are read from the server before and after: hiding sends
nothing.

The key's rule is read as a pure function too (marksKey, marksAfterPress): which key it is on a layout that types no Latin
letter, and where a press stops being a switch and becomes a look.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_marks_hide.py
"""

import json
import shutil
import unittest
from pathlib import Path

from limn.administration import serve_documents as startup_documents

from helpers import add_pin, extract_js_fn, ps, run_node
from helpers_access import ALICE, actor
from helpers_browser import BrowserBase, settle

A = actor(ALICE)
DESKTOP = {"viewport": {"width": 1440, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
# First-visit hints off: their line would stand on the status line the reminder is read from.
NO_COACH = "try{localStorage.setItem('pinPrefs',JSON.stringify({coach:{touch:1,mouse:1,sel:1,side:1}}))}catch(e){}"
# What a person sees of the marks: for each mark its pin, whether it is drawn, its tint's alpha, and whether its badge is a
# Tab stop a screen reader meets (visibility:hidden takes it out of both).
MARKS = """() => [...document.querySelectorAll('.mark')].map(m => {const s = getComputedStyle(m), b = m.querySelector('.mark-jump');
  const c = s.backgroundColor, sl = /\\/\\s*([\\d.]+)\\s*\\)/.exec(c), four = /^rgba\\(([^)]+)\\)/.exec(c);
  const tint = sl ? Number(sl[1]) : four ? Number(four[1].split(',')[3]) : c === 'transparent' ? 0 : 1;
  return {pin: Number(m.dataset.pin), shown: s.visibility === 'visible', tint: Math.round(tint * 100) / 100,
    badge: getComputedStyle(b).visibility === 'visible'};})"""
# The status line's messages as [text, action label].
LINE_SAYS = "LINE.map(n=>[n.title,n.act?n.act.label:null])"
SWITCH = "document.querySelector('#m-marks').getAttribute('aria-checked')"


def node_json(test, js):
    """Run js under node and return what it printed as JSON; skip the calling test when node is missing."""
    if not shutil.which("node"):
        test.skipTest("node not available")
    return json.loads(run_node(js))


def fns(*names):
    """The served source of the named viewer functions, joined."""
    return "\n".join(extract_js_fn(n) for n in names)


def hold_ms():
    """The source line of marks-hide.js that defines MARKS_HOLD_MS."""
    src = (Path(__file__).resolve().parents[1] / "js" / "marks-hide.js").read_text(encoding="utf-8")
    (line,) = [x for x in src.splitlines() if x.startswith("const MARKS_HOLD_MS=")]
    return line


class MarksKeyRule(unittest.TestCase):
    """The marks key's rule, on the served source: which key it is, and what a press of some length does."""

    def test_the_key_is_the_one_that_types_h_or_the_h_key_of_a_layout_without_latin_letters(self):
        """h and H (Caps Lock) are the key, by the letter typed: on Dvorak the key that types h (physical J) is it and the
        physical H key, which types d, is not. With a Korean layout the key types a jamo (or the input method's
        'Process') and the physical H key is taken. With Shift, Ctrl, Cmd or Alt it is another key."""
        keys = [
            {"key": "h", "code": "KeyH"},
            {"key": "H", "code": "KeyH"},
            {"key": "h", "code": "KeyJ"},
            {"key": "d", "code": "KeyH"},
            {"key": "ㅗ", "code": "KeyH"},
            {"key": "Process", "code": "KeyH"},
            {"key": "ㅓ", "code": "KeyJ"},
            {"key": "H", "code": "KeyH", "shiftKey": True},
            {"key": "h", "code": "KeyH", "ctrlKey": True},
            {"key": "h", "code": "KeyH", "metaKey": True},
            {"key": "h", "code": "KeyH", "altKey": True},
        ]
        js = fns("marksKey") + "\nconsole.log(JSON.stringify(%s.map(k=>marksKey(k))));" % json.dumps(keys)
        self.assertEqual(node_json(self, js), [True, True, True, False, True, True, False, False, False, False, False])

    def test_a_short_press_switches_the_marks_and_a_long_one_leaves_them(self):
        """A press shorter than MARKS_HOLD_MS switches the marks - off when they showed, on when they were off - and one
        that long or longer was a look: they are as before it."""
        js = (
            hold_ms()
            + "\n"
            + fns("marksAfterPress")
            + (
                "\nconsole.log(JSON.stringify([MARKS_HOLD_MS,[false,true].map(off=>"
                "[0,MARKS_HOLD_MS-1,MARKS_HOLD_MS,5000].map(ms=>marksAfterPress(off,ms)))]));"
            )
        )
        hold, got = node_json(self, js)
        self.assertEqual(hold, 350)
        self.assertEqual(got, [[True, True, False, False], [False, False, True, True]])


class MarksHide(BrowserBase):
    """The marks of two open pins on the manuscript's first page, taken off and brought back."""

    def setUp(self):
        """Two open pins with boxes on page 1 of the manuscript."""
        super().setUp()
        body = {"file": str(self.main), "page": 1}
        self.one = add_pin(
            {**body, "lo": 4, "hi": 5, "note": "그림 색 고치기", "frac": [0.2, 0.2, 0.4, 0.1]}, A
        ).record["id"]
        self.two = add_pin({**body, "lo": 8, "hi": 9, "note": "범례 옮기기", "frac": [0.2, 0.5, 0.4, 0.1]}, A).record[
            "id"
        ]

    def view(self, **device):
        """The viewer with both marks drawn."""
        page = self.open(2, init=NO_COACH, **(device or DESKTOP))
        page.wait_for_function("document.querySelectorAll('.mark').length===2", timeout=8000)
        settle(page)
        return page

    def shown(self, page):
        """Whether each mark is drawn, by pin."""
        return {m["pin"]: m["shown"] for m in page.evaluate(MARKS)}

    def tap(self, page, ms=40):
        """Press the marks key and let go after ms."""
        page.keyboard.down("h")
        page.wait_for_timeout(ms)
        page.keyboard.up("h")
        settle(page)

    def test_h_takes_the_marks_off_and_h_again_brings_them_back(self):
        """H: no mark is drawn and no badge is a stop, the switch is off, the status line says so and offers [다시
        보이기]; the pins and their cards are as they were, and nothing was written. H again: every mark is back, the
        switch on, the reminder gone."""
        page = self.view()
        before = json.dumps(ps.APP.snapshot_pins(), sort_keys=True, default=str)
        self.assertEqual(
            page.evaluate(MARKS), [{"pin": p, "shown": True, "tint": 0.08, "badge": True} for p in (self.one, self.two)]
        )
        self.tap(page)
        self.assertEqual([(m["shown"], m["badge"]) for m in page.evaluate(MARKS)], [(False, False)] * 2)
        self.assertEqual(page.evaluate(SWITCH), "false")
        self.assertIn(["핀 표시를 숨겼습니다", "다시 보이기"], page.evaluate(LINE_SAYS))
        self.assertEqual(page.evaluate("document.querySelectorAll('.pin.card[data-id]').length"), 2)
        self.tap(page)
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        self.assertEqual(page.evaluate(SWITCH), "true")
        self.assertNotIn("핀 표시를 숨겼습니다", [m for m, _ in page.evaluate(LINE_SAYS)])
        self.assertEqual(json.dumps(ps.APP.snapshot_pins(), sort_keys=True, default=str), before)

    def test_h_held_is_a_look_and_the_marks_are_back_when_it_comes_up(self):
        """Held past MARKS_HOLD_MS the marks are off while the key is down - with no reminder, the switch untouched - and
        back when it comes up. Held while they are off, it shows them for as long, and they are off again after."""
        page = self.view()
        page.keyboard.down("h")
        page.wait_for_timeout(500)
        self.assertEqual(self.shown(page), {self.one: False, self.two: False})
        self.assertEqual((page.evaluate(SWITCH), page.evaluate("LINE.length")), ("true", 0))
        page.keyboard.up("h")
        settle(page)
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        self.assertEqual(page.evaluate("LINE.length"), 0)
        self.tap(page)  # off for good
        page.keyboard.down("h")
        page.wait_for_timeout(500)
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        self.assertEqual(page.evaluate(SWITCH), "false")
        page.keyboard.up("h")
        settle(page)
        self.assertEqual(self.shown(page), {self.one: False, self.two: False})
        self.assertEqual(page.evaluate("LINE.filter(n=>n.title==='핀 표시를 숨겼습니다').length"), 1)

    def test_a_look_ends_when_the_window_loses_the_key(self):
        """The window loses the focus with H down (its keyup goes elsewhere): the marks are as before the press."""
        page = self.view()
        page.keyboard.down("h")
        page.wait_for_timeout(100)
        self.assertEqual(self.shown(page), {self.one: False, self.two: False})
        page.evaluate("window.dispatchEvent(new Event('blur'))")
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        page.keyboard.up("h")
        settle(page)
        self.assertEqual((self.shown(page), page.evaluate(SWITCH)), ({self.one: True, self.two: True}, "true"))

    def test_h_typed_in_a_field_or_under_a_dialog_is_not_the_marks_key(self):
        """An h typed into the page field is a letter, and H under the help dialog does nothing: the marks stay."""
        page = self.view()
        page.click("#jump")
        page.keyboard.type("h")
        self.assertEqual(page.input_value("#jump"), "h")
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        page.fill("#jump", "")
        page.evaluate("document.activeElement.blur()")
        page.evaluate("openHelp()")
        page.wait_for_selector("#help[open]", timeout=5000)
        self.tap(page)
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})

    def test_the_reminders_action_and_a_cards_view_bring_the_marks_back(self):
        """With the marks off, the status line's [다시 보이기] shows them; off again, a card's [보기] - which goes to that
        pin's mark - shows them too."""
        page = self.view()
        self.tap(page)
        page.click("button.nt-act:visible")
        settle(page)
        self.assertEqual((self.shown(page), page.evaluate(SWITCH)), ({self.one: True, self.two: True}, "true"))
        self.tap(page)
        self.assertEqual(self.shown(page), {self.one: False, self.two: False})
        page.evaluate("id=>jumpPin(id)", self.two)
        settle(page)
        self.assertEqual(self.shown(page), {self.one: True, self.two: True})
        self.assertEqual(page.evaluate("LINE.filter(n=>n.title==='핀 표시를 숨겼습니다').length"), 0)

    def test_a_new_pins_undo_chip_brings_the_marks_back(self):
        """With the marks off a pin is saved: its undo chip sits on its mark, so the marks show again and the chip with
        them."""
        page = self.view()
        self.tap(page)
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect();return [r.left,r.top,r.width,r.height];})()"
        )
        x, y = box[0] + box[2] * 0.25, box[1] + box[3] * 0.75
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + box[2] * 0.3, y + box[3] * 0.05, steps=6)
        page.mouse.up()
        page.wait_for_function("!!COMPOSE.current", timeout=8000)
        page.locator("#note").fill("새 핀")
        page.click("#btn-save")
        page.wait_for_function("OPEN_ALL.some(p=>p.note==='새 핀')", timeout=8000)
        settle(page)
        self.assertTrue(all(self.shown(page).values()))
        self.assertEqual(page.evaluate(SWITCH), "true")
        self.assertTrue(page.locator(".mark > .nt-chip").is_visible())

    def test_the_switch_in_more_takes_the_marks_off_on_a_phone(self):
        """On a phone [더보기]'s [핀 표시] switch is on; pressed, the sheet closes, the marks are off and the switch off;
        pressed again they are back."""
        page = self.view(**PHONE)
        page.evaluate("openMore()")
        page.wait_for_selector("#more[open]", timeout=5000)
        self.assertEqual(
            page.evaluate(
                "(()=>{const m=document.querySelector('#m-marks');return [m.getAttribute('role'),m.getAttribute('aria-checked'),m.textContent.trim()];})()"
            ),
            ["switch", "true", "핀 표시"],
        )
        page.tap("#m-marks")
        page.wait_for_function("!document.querySelector('#more').open", timeout=5000)
        settle(page)
        self.assertEqual((self.shown(page), page.evaluate(SWITCH)), ({self.one: False, self.two: False}, "false"))
        page.evaluate("openMore()")
        page.wait_for_selector("#more[open]", timeout=5000)
        page.tap("#m-marks")
        page.wait_for_function("!document.querySelector('#more').open", timeout=5000)
        settle(page)
        self.assertEqual((self.shown(page), page.evaluate(SWITCH)), ({self.one: True, self.two: True}, "true"))

    def test_english_says_the_same(self):
        """In English the switch is 'Pin marks' and the reminder 'Pin marks hidden' with [Show again]."""
        page = self.open(2, lang="en", init=NO_COACH, **DESKTOP)
        page.wait_for_function("document.querySelectorAll('.mark').length===2", timeout=8000)
        settle(page)
        self.tap(page)
        self.assertEqual(page.evaluate("LINE.map(n=>n.title)"), ["Pin marks hidden"])
        self.assertEqual(page.locator("button.nt-act:visible").inner_text().strip(), "Show again")
        self.assertEqual(page.evaluate("document.querySelector('#m-marks .lbl').textContent"), "Pin marks")


class MarksHideMarkdown(BrowserBase):
    """A Markdown document's marks - the tint on a pinned line and the badge in the gutter - go and come back too, and the
    lines being chosen keep their colour."""

    def setUp(self):
        """notes.md first, with a line pin on its third line."""
        super().setUp()
        src = self.main.parent
        (src / "notes.md").write_text("# 제목\n\n첫 문단의 줄이다.\n\n둘째 문단의 줄이다.\n", encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:notes.md", "ms=본문:main.tex"], src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.addCleanup(ps.APP.set_docs, None)
        add_pin({"doc": "nt", "file": str(src / "notes.md"), "lo": 3, "hi": 3, "note": "고치기"}, A)

    def test_the_line_tint_and_the_badge_go_with_h_and_a_chosen_line_keeps_its_colour(self):
        """The pinned line is tinted and its badge shown; with H neither is, and with H again both are. A line chosen
        while the marks are off is still shown as chosen."""
        page = self.open(1, init=NO_COACH, **DESKTOP)
        page.wait_for_selector("#md .md-badge", timeout=20000)
        settle(page)
        read = """() => {const l = document.querySelector('#md .md-pin'), b = document.querySelector('#md .md-badges');
          return [getComputedStyle(l).backgroundColor !== 'rgba(0, 0, 0, 0)', getComputedStyle(b).visibility === 'visible'];}"""
        self.assertEqual(page.evaluate(read), [True, True])
        page.keyboard.press("h")
        settle(page)
        self.assertEqual(page.evaluate(read), [False, False])
        page.locator("#md [data-line='5']").first.click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo===5", timeout=5000)
        self.assertTrue(
            page.evaluate(
                "getComputedStyle(document.querySelector('#md .md-sel')).backgroundColor!=='rgba(0, 0, 0, 0)'"
            )
        )
        page.keyboard.press("Escape")
        page.keyboard.press("h")
        settle(page)
        self.assertEqual(page.evaluate(read), [True, True])
