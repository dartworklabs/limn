"""A new pin's assignee comes from the note's inline @-tags (docs/handbook/viewer.md §담당).

The owner's rule: tagging a colleague anywhere in the note hands them the pin; with no colleague tag the agent keeps it.
The first resolved colleague who is not the author is the assignee, whichever kind the pin is; colleagues tagged after
them are only notified. Tags that do not resolve, tags taken out of the text and a tag of oneself assign nobody. The
segmented control under the note (`#c-assign`) is the one override, and the line under the note says the outcome
before saving, from the calculation the save sends.

Three kinds of test:

- ``AssigneeOutcomeRule`` runs the pure decision (``assignOutcome``) under node on the served source.
- ``NewPinAssignee`` drives the real composer against the in-process server and reads what was sent, stored and
  notified.
- ``AssigneeRowGeometry`` measures the preview line and the assignee row on every layout band.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_assignee.py
"""

import base64
import json
import os
import shutil
import time
import unittest
from urllib.parse import urlparse

from limn.administration import serve_documents as startup_documents

from helpers import add_pin, blank_png, extract_js_fn, find_record, ps, run_node
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_browser import (
    FALLBACK_FONTS,
    MEASURE,
    MISSES_24,
    MISSES_44,
    ROW_INK,
    SEGMENTS,
    VIEWPORTS,
    BrowserBase,
    booted,
    drawn_faces,
    fonts_ready,
    hangul_ink_holds,
    off_centre,
    settle,
)

A, B, C = (person["Tailscale-User-Login"] for person in (ALICE, BOB, CAROL))
AGENT = "agent"
TEAM = [
    {"login": A, "name": "Alice Kim"},
    {"login": B, "name": "Bob Park"},
    {"login": C, "name": "Carol Lee"},
    {"login": "bob.lee@example.com", "name": "Bob Lee"},
]
UNTOUCHED = {"v": AGENT, "touched": False}

# (label, note, autocomplete hints, the author's pick, the assignee, who is only notified, whether the pick stands).
# The author is Alice Kim.
OUTCOMES = [
    ("mid-sentence tag", "이 문단 수치를 @Bob Park 확인 부탁합니다", [], UNTOUCHED, B, [], False),
    ("leading tag", "@Bob Park 확인 부탁합니다", [], UNTOUCHED, B, [], False),
    ("several colleagues: the first one", "@Carol Lee 봐 주세요, @Bob Park 참고", [], UNTOUCHED, C, [B], False),
    ("the same colleague twice", "@Bob Park 확인, 다시 @Bob Park", [], UNTOUCHED, B, [], False),
    ("only a tag of oneself", "@Alice Kim 나중에 다시 보기", [], UNTOUCHED, AGENT, [], False),
    ("oneself first, then a colleague", "@Alice Kim 그리고 @Bob Park", [], UNTOUCHED, B, [], False),
    ("a tag that does not resolve", "@홍길동 확인 부탁합니다", [], UNTOUCHED, AGENT, [], False),
    ("no tag", "문장을 줄여 주세요", [], UNTOUCHED, AGENT, [], False),
    ("a tag taken out of the text keeps only its hint", "확인 부탁합니다", [B], UNTOUCHED, AGENT, [], False),
    ("a shared first name without a hint", "@Bob 확인", [], UNTOUCHED, AGENT, [], False),
    (
        "a shared first name with its hint",
        "@Bob 확인",
        ["bob.lee@example.com"],
        UNTOUCHED,
        "bob.lee@example.com",
        [],
        False,
    ),
    (
        "the agent picked over two tags",
        "@Bob Park 와 @Carol Lee",
        [],
        {"v": AGENT, "touched": True},
        AGENT,
        [B, C],
        True,
    ),
    ("the second colleague picked", "@Bob Park 와 @Carol Lee", [], {"v": C, "touched": True}, C, [B], True),
    ("a picked colleague who left the note", "@Bob Park 확인", [], {"v": C, "touched": True}, B, [], False),
    ("the agent picked, then every tag removed", "확인", [], {"v": AGENT, "touched": True}, AGENT, [], True),
]
OUTCOME_FNS = ("mentionTokens", "mentionAfterWord", "mentionResolve", "assignPeople", "assignOutcome")
SAMS = [{"login": "sam1@example.com", "name": "Sam Jung"}, {"login": "sam2@example.com", "name": "Sam Jung"}]


class AssigneeOutcomeRule(unittest.TestCase):
    """assignOutcome(q): what a save of the composer's note does - the assignee a new pin is saved with and who is only
    notified, or, when the note joins an existing pin, that pin's assignee kept and everyone told. The harness defines
    none of the page's globals (PEOPLE, META, ASSIGN_NEW, the DOM), so the function answers from its arguments alone."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node is a failure."""
        if shutil.which("node"):
            return
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            self.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        self.skipTest("node is not installed")

    def outcomes(self, asks, people=TEAM, me=A):
        """assignOutcome() for every ask - a dict of the inputs that differ from a new fix request by me among people
        with an untouched pick - in one node process that has the rule's functions and nothing else."""
        base = {"text": "", "kind": "fix", "hints": [], "people": people, "me": me, "mode": "new", "pick": UNTOUCHED}
        js = "\n".join(
            [
                *(extract_js_fn(name) for name in OUTCOME_FNS),
                "const ASKS=%s;" % json.dumps([dict(base, **ask) for ask in asks], ensure_ascii=False),
                "console.log(JSON.stringify(ASKS.map(q=>assignOutcome(q))));",
            ]
        )
        return json.loads(run_node(js))

    def test_the_first_resolved_colleague_is_the_assignee_and_later_ones_are_only_notified(self):
        """Every case of the rule: where the tag sits does not matter, the first colleague wins, the author, an
        unresolved word and a removed tag assign nobody, and a pick stands only while its person is still tagged."""
        got = self.outcomes([{"text": text, "hints": hints, "pick": pick} for _, text, hints, pick, *_ in OUTCOMES])
        for (label, _, _, _, assignee, told, kept), out in zip(OUTCOMES, got, strict=True):
            with self.subTest(label):
                self.assertEqual(
                    (out["assignee"], out["told"], out["kept"], out["mode"]), (assignee, told, kept, "new")
                )

    def test_the_kind_goes_into_the_request_and_does_not_change_the_assignee(self):
        """A fix request with a mid-sentence tag is handed over as a question is (it used to stay with the agent unless
        the note started with the tag), and the answer carries the kind the request is saved with."""
        fix, question = self.outcomes(
            [{"text": "수치를 @Bob Park 확인 부탁", "kind": kind} for kind in ("fix", "question")]
        )
        self.assertEqual((fix["assignee"], fix["kind"]), (B, "fix"))
        self.assertEqual((question["assignee"], question["kind"]), (B, "question"))

    def test_an_append_keeps_the_stored_assignee_and_tells_everyone_the_note_tags(self):
        """mode append: the pin the note joins keeps its assignee - the agent, a person, none - whatever the note tags
        and whatever was picked; nobody is offered, no kind is sent, and every colleague the note tags is told (the
        author never)."""
        text = "@Carol Lee 답해 주세요, @Bob Park 참고 @Alice Kim"
        picked = {"v": C, "touched": True}
        got = self.outcomes(
            [{"text": text, "mode": "append", "stored": stored, "pick": picked} for stored in (AGENT, B, None)]
        )
        for stored, out in zip((AGENT, B, None), got, strict=True):
            with self.subTest(stored=stored):
                want = {"mode": "append", "kind": None, "people": [], "assignee": stored, "told": [C, B], "kept": False}
                self.assertEqual(out, want)

    def test_of_two_people_with_one_name_the_one_tagged_first_is_the_assignee(self):
        """Two people named Sam Jung, both picked from the @-list: the hints are in the order the text names them, and
        the first of them is the assignee whichever login sorts first (it was always sam1); one hint tags that one
        alone, and no hint tags nobody."""
        people = TEAM + SAMS
        text = "@Sam Jung 먼저, 그리고 @Sam Jung"
        second_first, first_first, one, none = self.outcomes(
            [
                {"text": text, "hints": ["sam2@example.com", "sam1@example.com"], "people": people},
                {"text": text, "hints": ["sam1@example.com", "sam2@example.com"], "people": people},
                {"text": "@Sam Jung 확인", "hints": ["sam2@example.com"], "people": people},
                {"text": "@Sam Jung 확인", "people": people},
            ]
        )
        self.assertEqual((second_first["assignee"], second_first["told"]), ("sam2@example.com", ["sam1@example.com"]))
        self.assertEqual((first_first["assignee"], first_first["told"]), ("sam1@example.com", ["sam2@example.com"]))
        self.assertEqual((one["assignee"], one["people"]), ("sam2@example.com", ["sam2@example.com"]))
        self.assertEqual((none["assignee"], none["people"]), (AGENT, []))

    def test_the_identity_less_screen_has_no_author_to_leave_out(self):
        """me null (the local screen): a tag of anyone is a colleague's."""
        (out,) = self.outcomes([{"text": "@Alice Kim 그리고 @Bob Park", "me": None}])
        self.assertEqual((out["assignee"], out["told"]), (A, [B]))


DESKTOP, PHONE = VIEWPORTS["desktop 1440x900"], VIEWPORTS["phone 390x844"]
# The preview line under the note as drawn: each label with the names after it, and the words that will not resolve.
PREVIEW = """() => {const box = document.querySelector('#note-mentions'), out = {hidden: box.hidden, groups: [], bad: []};
  for (const e of box.children) {
    if (e.classList.contains('m-lab')) out.groups.push([e.textContent.trim(), []]);
    else if (e.classList.contains('mention') || e.classList.contains('m-who')) out.groups[out.groups.length - 1][1].push(e.textContent.trim());
    else if (e.classList.contains('mention-bad')) out.bad.push(e.textContent.trim());}
  return out;}"""
# The assignee row as drawn: its options in order and the one checked, or null while the row is hidden.
ASSIGN_ROW = """() => {const box = document.querySelector('#c-assign'); if (box.hidden) return null;
  const bs = [...box.querySelectorAll('button[role=radio]')];
  return {options: bs.map(b => b.dataset.v), checked: bs.filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.dataset.v)};}"""


class ComposerBase(BrowserBase):
    """The real composer as Alice, with Bob and Carol known to the instance, recording every POST /api/pin body."""

    WHO = ALICE

    def setUp(self):
        """Register the three people and start with no saved request."""
        super().setUp()
        for person in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(person))
        self.sent = []
        self.people_down = False

    def route(self, route):
        """The fixture's routes, keeping the JSON body of each new-pin request as it left the viewer."""
        request = route.request
        if request.method == "POST" and urlparse(request.url).path == "/api/pin":
            self.sent.append(request.post_data_json)
        if self.people_down and urlparse(request.url).path == "/api/people":
            return route.fulfill(status=503, body="{}")  # the list does not arrive while a test keeps it down
        return super().route(route)

    def view(self, device, n_open=0, theme="light", font=None):
        """Open the viewer on device with the hints seen and the theme set; font replaces the interface font stack."""
        prefs = {"theme": theme, "coach": {"touch": 1, "mouse": 1, "sel": 1}}
        init = "try{localStorage.setItem('pinPrefs',%s);}catch(e){}" % json.dumps(json.dumps(prefs))
        if font:
            init += (
                "document.addEventListener('DOMContentLoaded',()=>"
                "document.documentElement.style.setProperty('--font-sans',%s));" % json.dumps(font)
            )
        return self.open(n_open, init=init, **device)

    def select(self, page, device):
        """Select a region of page 1 as the device's person does - a mouse drags over it, a finger turns [선택] on and
        drags - and wait for the pick. The fixture answers every pick with the manuscript's one paragraph, so a
        selection made after a pin was saved overlaps that pin and the composer offers [덧붙이기]."""
        if device.get("has_touch"):
            page.tap("#btn-select")
            settle(page)
        box = page.locator("#p1").bounding_box()  # read once [선택] is on: its hint moves the page down
        x0, y0, x1, y1 = box["x"] + box["width"] * 0.2, box["y"] + 40, box["x"] + box["width"] * 0.6, box["y"] + 64
        if device.get("has_touch"):
            cdp = page.context.new_cdp_session(page)  # left attached: detaching resets the page's touch emulation

            def touch(kind, points):
                """One CDP touch event of the finger."""
                cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [dict(p, id=0) for p in points]})

            touch("touchStart", [{"x": x0, "y": y0}])
            for i in range(1, 9):
                touch("touchMove", [{"x": x0 + (x1 - x0) * i / 8, "y": y0 + (y1 - y0) * i / 8}])
                time.sleep(0.016)  # the finger's speed, not a wait for the page
            touch("touchEnd", [])
        else:
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=5)
            page.mouse.up()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo&&!COMPOSE.picking", timeout=8000)
        settle(page)
        if device.get("has_touch"):
            time.sleep(0.5)  # the finger's pause before its next tap, past the window that swallows a drag's own click

    def press(self, page, device, selector):
        """Press the control as the device's person does: a tap, or a mouse click."""
        if device.get("has_touch"):
            page.tap(selector)
        else:
            page.click(selector)
        settle(page)

    def write(self, page, device, text, selector="#note"):
        """Put the caret in the field with a press and type text key by key - the @-list opens and closes as it does
        for a person - then leave the field with a press on the range caption under it (after Esc, if the list is
        still open over a tag the text ends with), so the list is closed and a word that does not resolve is
        flagged, as when the author moves on."""
        self.press(page, device, selector)
        page.keyboard.type(text)
        settle(page)
        self.leave(page, device)

    def leave(self, page, device):
        """Take the caret out of the note: Esc closes an open @-list, then a press on the range caption."""
        if page.evaluate("!document.querySelector('#mention-pop').hidden"):
            page.keyboard.press("Escape")
        self.press(page, device, "#c-cap .rg-l")
        page.wait_for_function("document.querySelector('#mention-pop').hidden")

    def compose(self, page, note, kind="fix", device=DESKTOP, separate=True):
        """Select a region, write note in the panel's field and set the kind, all with the device's own input. A
        selection that overlaps a saved pin is taken as a pin of its own ([따로 저장]) unless separate is false, where
        the composer keeps offering [덧붙이기]."""
        self.select(page, device)
        if separate:
            self.separate(page, device)
        self.write(page, device, note)
        if kind != "fix":
            self.press(page, device, '#c-kind [data-kind="%s"]' % kind)

    def separate(self, page, device=DESKTOP):
        """Choose [따로 저장] where the composer offers [덧붙이기] for an overlapped pin."""
        if page.is_visible("#c-overlap [data-act=overlap-separate]"):
            self.press(page, device, "#c-overlap [data-act=overlap-separate]")

    def save(self, page, device=DESKTOP):
        """Press [핀 저장], wait for the composer to close and return (the request's body, the stored record)."""
        before = len(self.sent)
        self.press(page, device, "#btn-save")
        page.wait_for_function("!COMPOSE.saving&&document.querySelector('#composer').hidden")
        settle(page)
        self.assertEqual(len(self.sent), before + 1)
        pid = max(pin.record["id"] for pin in ps.APP.snapshot_pins())
        return self.sent[-1], find_record(ps.APP.snapshot_pins(), pid)

    def rewrite(self, page, text, device=DESKTOP):
        """Replace the note with text from the keyboard: select all of it, type over it, and leave the field."""
        self.press(page, device, "#note")
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Delete")
        self.write(page, device, text)

    def events(self, pid):
        """The notices events.jsonl holds for pin pid, as {type: recipients}."""
        path = ps.APP.C.events_file
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return {row["type"]: row["to"] for row in rows if row.get("pin") == pid}


# (label, note, the assignee, the preview's groups, the notices).
SAVED = [
    (
        "mid-sentence tag",
        "이 문단 수치를 @Bob Park 확인 부탁합니다",
        B,
        [["담당", ["Bob Park"]]],
        {"mention": [B], "assigned": [B]},
    ),
    ("leading tag", "@Bob Park 확인 부탁합니다", B, [["담당", ["Bob Park"]]], {"mention": [B], "assigned": [B]}),
    (
        "several colleagues",
        "@Carol Lee 봐 주세요, @Bob Park 참고",
        C,
        [["담당", ["Carol Lee"]], ["알림", ["Bob Park"]]],
        {"mention": [C, B], "assigned": [C]},
    ),
    (
        "only a tag of oneself",
        "@Alice Kim 나중에 다시 보기",
        AGENT,
        [["담당", ["에이전트"]], ["알림", ["Alice Kim (나 — 알림 없음)"]]],
        {},
    ),
    ("a tag that does not resolve", "@홍길동 확인 부탁합니다", AGENT, [["담당", ["에이전트"]]], {}),
    ("no tag", "문장을 줄여 주세요", AGENT, [], {}),
]


class NewPinAssignee(ComposerBase):
    """What the composer shows, sends and stores for a new pin, and who is told."""

    def test_the_default_is_the_first_tagged_colleague_for_both_kinds(self):
        """A fix request and a question alike: the row checks the first tagged colleague, the request carries them as
        `assignee`, the record stores them, they get `assigned` and every tagged colleague `mention`; a note that tags
        no colleague is the agent's and offers no row."""
        for kind in ("fix", "question"):
            page = self.view(DESKTOP)
            for label, note, assignee, _, notices in SAVED:
                with self.subTest(label, kind=kind):
                    self.compose(page, note, kind)
                    row = page.evaluate(ASSIGN_ROW)
                    if assignee == AGENT:
                        self.assertIsNone(row)
                    else:
                        self.assertEqual(row["checked"], [assignee])
                        self.assertEqual(row["options"][0], AGENT)
                    body, record = self.save(page)
                    self.assertEqual((body["kind_req"], body["assignee"]), (kind, assignee))
                    self.assertEqual(record["assignee"], assignee)
                    self.assertEqual(self.events(record["id"]), notices)

    def test_the_preview_line_says_the_saved_outcome(self):
        """Before saving, the line under the note names the assignee ('담당') and who is only notified ('알림') - the
        same people the request then assigns and the server then tells; with no tag at all there is no line."""
        page = self.view(DESKTOP)
        for label, note, assignee, groups, notices in SAVED:
            with self.subTest(label):
                self.compose(page, note)
                shown = page.evaluate(PREVIEW)
                self.assertEqual((shown["hidden"], shown["groups"]), (not groups, groups))
                body, record = self.save(page)
                named = dict(shown["groups"]).get("담당", ["에이전트"])
                self.assertEqual(
                    named, ["에이전트" if assignee == AGENT else page.evaluate("peopleName(%r)" % assignee)]
                )
                self.assertEqual(body["assignee"], assignee)
                told = [name for name in dict(shown["groups"]).get("알림", []) if "알림 없음" not in name]
                only_mentioned = [
                    login for login in notices.get("mention", []) if login not in notices.get("assigned", [])
                ]
                self.assertEqual(told, [page.evaluate("peopleName(%r)" % login) for login in only_mentioned])
                self.assertEqual(self.events(record["id"]), notices)

    def test_an_unresolved_word_is_named_beside_the_agent(self):
        """'@홍길동 확인': the line says the agent handles the pin and that the word is no registered person."""
        page = self.view(DESKTOP)
        self.compose(page, "@홍길동 확인 부탁합니다")
        shown = page.evaluate(PREVIEW)
        self.assertEqual((shown["groups"], shown["bad"]), ([["담당", ["에이전트"]]], ["@홍길동"]))
        self.assertIn("등록된 사람이 아님", page.locator("#note-mentions").inner_text())

    def test_the_row_overrides_the_default_and_a_pick_stands_until_its_person_leaves(self):
        """With Bob then Carol tagged: 에이전트 turns both into notifications and stays through further typing; Carol
        takes the pin from Bob; once Carol leaves the note the default (Bob) is back, and writing her in again does not
        bring the old pick back."""
        page = self.view(DESKTOP)
        self.compose(page, "@Bob Park 그리고 @Carol Lee 확인")
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B, C], "checked": [B]})
        page.locator('#c-assign [data-v="agent"]').click()
        self.rewrite(page, "@Bob Park 그리고 @Carol Lee 확인 부탁합니다")
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [AGENT])
        self.assertEqual(
            page.evaluate(PREVIEW)["groups"], [["담당", ["에이전트"]], ["알림", ["Bob Park", "Carol Lee"]]]
        )
        page.locator('#c-assign [data-v="%s"]' % C).click()
        settle(page)
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [C])
        self.assertEqual(page.evaluate(PREVIEW)["groups"], [["담당", ["Carol Lee"]], ["알림", ["Bob Park"]]])
        self.rewrite(page, "@Bob Park 확인 부탁합니다")
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B], "checked": [B]})
        self.rewrite(page, "@Bob Park 그리고 @Carol Lee 확인 부탁합니다")
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [B])

    def test_an_override_is_what_gets_saved_and_notified(self):
        """에이전트 picked over two tags: the request says `agent`, nobody is `assigned` and both get `mention`; Carol
        picked over Bob: she is `assigned` and Bob is only mentioned."""
        page = self.view(DESKTOP)
        for pick, notices in ((AGENT, {"mention": [B, C]}), (C, {"mention": [B, C], "assigned": [C]})):
            with self.subTest(pick=pick):
                self.compose(page, "@Bob Park 그리고 @Carol Lee 확인")
                page.locator('#c-assign [data-v="%s"]' % pick).click()
                body, record = self.save(page)
                self.assertEqual((body["assignee"], record["assignee"]), (pick, pick))
                self.assertEqual(self.events(record["id"]), notices)

    def test_a_restored_draft_keeps_its_explicit_choice(self):
        """Carol picked over Bob, then the page reloads: the restored draft still hands the pin to Carol, on the row
        and on the line, and saves her; an untouched draft comes back with the default."""
        for pick, assignee in ((C, C), (None, B)):
            with self.subTest(pick=pick):
                page = self.view(DESKTOP)
                self.compose(page, "@Bob Park 그리고 @Carol Lee 확인")
                if pick:
                    page.locator('#c-assign [data-v="%s"]' % pick).click()
                settle(page)  # the debounced draft write
                page.reload()
                page.wait_for_function(booted(0), timeout=20000)
                page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
                settle(page)
                self.separate(page)  # a reload offers [덧붙이기] again for a pin an earlier case saved
                page.wait_for_function("COMPOSE.current&&!document.querySelector('#composer').hidden")
                settle(page)
                self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [assignee])
                self.assertEqual(
                    page.evaluate(PREVIEW)["groups"][0], ["담당", [page.evaluate("peopleName(%r)" % assignee)]]
                )
                self.assertEqual(self.save(page)[0]["assignee"], assignee)

    def test_editing_a_stored_pin_keeps_its_assignee(self):
        """A stored agent pin whose note tags Bob mid-sentence: its edit card still checks 에이전트, and saving a note
        change sends no `assignee` - the new default is for new pins only."""
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "수치를 @Bob Park 확인", "assignee": AGENT},
            actor(ALICE),
        ).record["id"]
        page = self.view(DESKTOP, n_open=1)
        edits = []
        page.on(
            "request",
            lambda request: (
                edits.append(request.post_data_json) if request.url.endswith("/api/pins/%d/edit" % pid) else None
            ),
        )
        page.evaluate("id=>openEdit(id)", pid)
        page.wait_for_function("EDITOR.current&&EDITOR.current.levels.length>0")
        settle(page)
        checked = page.locator('.e-assign [aria-checked="true"]')
        self.assertEqual(checked.get_attribute("data-v"), AGENT)
        page.locator(".e-note").fill("수치를 @Bob Park 확인 부탁합니다")
        page.locator(".b-esave").click()
        page.wait_for_function("!EDITOR.current")
        settle(page)
        self.assertEqual(len(edits), 1)
        self.assertNotIn("assignee", edits[0])
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["assignee"], AGENT)


class PickLifetime(ComposerBase):
    """The author's pick belongs to one selection: it does not reach the next pin, another document, or a save made
    before its person can be looked up - and typing in the popover by the box redraws what the panel says."""

    TWO = "@Bob Park 그리고 @Carol Lee 확인"

    def test_a_pick_does_not_leak_into_the_next_pin(self):
        """에이전트 picked over two tags, then the pin saved - and, the second time, the selection cancelled with Esc:
        the next selection tagging Bob starts from the default (Bob), on the row and in the request. The pick used to
        stay 'touched', so the next pin went to the agent although its note handed it to Bob."""
        page = self.view(DESKTOP)
        for end in ("save", "cancel"):
            with self.subTest(end=end):
                self.compose(page, self.TWO)
                page.locator('#c-assign [data-v="agent"]').click()
                settle(page)
                self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [AGENT])
                if end == "save":
                    self.assertEqual(self.save(page)[0]["assignee"], AGENT)
                else:
                    page.click("#btn-cancel")
                    page.wait_for_function("document.querySelector('#composer').hidden")
                    settle(page)
                self.compose(page, "@Bob Park 확인 부탁합니다")
                self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B], "checked": [B]})
                self.assertEqual(page.evaluate(PREVIEW)["groups"], [["담당", ["Bob Park"]]])
                self.assertEqual(self.save(page)[0]["assignee"], B)

    def test_typing_in_the_popover_by_the_box_redraws_the_row_and_the_line(self):
        """A mouse drag opens the note popover by the box with the focus in it; a note typed there tagging Bob and
        Carol is the panel's note, and the panel's assignee row and preview line follow every key: Bob checked,
        '담당 Bob Park · 알림 Carol Lee'. The popover's [저장] then sends Bob."""
        page = self.view(DESKTOP)
        self.select(page, DESKTOP)
        self.assertTrue(page.is_visible("#sel-pop"))
        page.keyboard.type("@Bob Park 그리고 @Carol Lee")
        settle(page)
        self.assertEqual(page.input_value("#note"), "@Bob Park 그리고 @Carol Lee")
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B, C], "checked": [B]})
        self.assertEqual(page.evaluate(PREVIEW)["groups"], [["담당", ["Bob Park"]], ["알림", ["Carol Lee"]]])
        page.click('#sel-pop [data-act="pop-save"]')
        page.wait_for_function("!COMPOSE.saving&&!COMPOSE.current")
        settle(page)
        self.assertEqual(self.sent[-1]["assignee"], B)

    def test_a_save_before_the_people_list_arrives_sends_what_the_line_says(self):
        """Carol picked over Bob, then the page reloads while GET /api/people fails: nobody can be looked up, so the
        line says the agent has the pin and names both words as no registered person, no row is drawn - and the
        request carries the agent, the outcome on screen, not the restored pick (it sent Carol, who then got
        `assigned` for a pin whose screen never named her). The same once the note is rewritten without a tag."""
        for rewritten in (False, True):
            with self.subTest(rewritten=rewritten):
                page = self.reloaded_without_people()
                if rewritten:
                    self.rewrite(page, "태그 없는 메모")
                    self.assertTrue(page.evaluate(PREVIEW)["hidden"])
                else:
                    self.press(page, DESKTOP, "#note")
                    self.leave(page, DESKTOP)  # the caret has been in the note and left it: both words are flagged
                    shown = page.evaluate(PREVIEW)
                    self.assertEqual((shown["groups"], shown["bad"]), ([["담당", ["에이전트"]]], ["@Bob", "@Carol"]))
                self.assertIsNone(page.evaluate(ASSIGN_ROW))
                body, record = self.save(page)
                self.assertEqual((body["assignee"], record["assignee"]), (AGENT, AGENT))
                self.assertNotIn("assigned", self.events(record["id"]))
                self.people_down = False

    def test_a_restored_pick_is_back_once_the_people_list_arrives(self):
        """The same reload, then the list arrives with the next reading of the pins ([핀 다시 읽기]): Carol's segment is
        pressed again and the save sends her - the pick was kept, not settled away while nobody could be looked up."""
        page = self.reloaded_without_people()
        self.people_down = False
        page.click("#btn-reload")
        page.wait_for_function("PEOPLE_KNOWN")
        settle(page)
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [C])
        self.assertEqual(self.save(page)[0]["assignee"], C)

    def reloaded_without_people(self):
        """A draft tagging Bob and Carol with Carol picked, restored by a reload during which /api/people fails; a
        selection that overlaps an earlier case's pin is taken as a pin of its own. Returns the page."""
        page = self.view(DESKTOP)
        self.compose(page, self.TWO)
        page.locator('#c-assign [data-v="%s"]' % C).click()
        settle(page)  # the debounced draft write
        self.people_down = True
        page.reload()
        page.wait_for_function(booted(0), timeout=20000)
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        settle(page)
        self.assertFalse(page.evaluate("PEOPLE_KNOWN"))
        self.separate(page)
        return page


# The preview line as drawn while [덧붙이기] is on offer: its words, its separators' boxes, and for each group between
# separators the tops of the items in it; a pill's height (one line, so no name breaks inside).
APPEND_LINE = """() => {const box = document.querySelector('#note-mentions'), top = e => Math.round(e.getBoundingClientRect().top);
  const kids = [...box.children], groups = kids.filter(e => e.classList.contains('m-grp'));
  return {words: box.innerText.replace(/\\s+/g, ' ').trim(), hidden: box.hidden, groups: groups.map(g => [...g.children].map(top)),
    seps: kids.filter(e => e.classList.contains('m-sep')).map(top), lineTops: [...new Set(kids.map(top))],
    pills: [...box.querySelectorAll('.mention')].map(e => e.getBoundingClientRect().height)};}"""


class AppendToAnOverlappedPin(ComposerBase):
    """While the composer offers [덧붙이기] for the pin its selection overlaps, the line under the note says only what
    each action changes - whom appending tells, and whom a separate save makes the assignee - and no assignee row is
    drawn; each button then does what the line said."""

    def start(self, stored, note="@Carol Lee 답해 주세요", device=DESKTOP):
        """An open pin of mine assigned to stored on the fixture's paragraph, then a selection over it with note;
        returns (the page, the pin's id)."""
        body = {"file": str(self.main), "lo": 5, "hi": 5, "page": 1, "note": "먼저 쓴 메모", "assignee": stored}
        pid = add_pin(body, actor(ALICE)).record["id"]
        page = self.view(device, 1)
        self.compose(page, note, separate=False, device=device)
        self.assertTrue(page.is_visible('#c-overlap [data-act="overlap-append"]'))
        return page, pid

    def test_the_line_says_what_each_action_changes_and_no_row_is_offered(self):
        """Over an agent pin and over a pin of Bob's alike: '@ 알림 Carol Lee · 따로 저장하면 담당 Carol Lee'. Appending
        changes nothing about the pin's assignee, so the line names neither the agent nor Bob (it said '덧붙이면 담당
        에이전트 그대로' and wrapped). No assignee row: it would choose nothing for an append (it showed '담당 Carol
        Lee' with her segment pressed)."""
        for stored in (AGENT, B):
            with self.subTest(stored=stored):
                page, _ = self.start(stored)
                line = page.evaluate(APPEND_LINE)
                self.assertEqual(
                    line["words"].split(), ["알림", "Carol", "Lee", "·", "따로", "저장하면", "담당", "Carol", "Lee"]
                )
                self.assertIsNone(page.evaluate(ASSIGN_ROW))

    def test_the_line_is_one_line_at_390_and_breaks_only_at_its_separator_at_320(self):
        """Phone 390 and the desktop: the line is one line. Phone 320: it may wrap, only after the separator - each
        group ('@ 알림 Carol Lee', '따로 저장하면 담당 Carol Lee') stays on one line and no pill breaks."""
        for name in ("phone 390x844", "desktop 1440x900", "phone 320x720"):
            device = VIEWPORTS[name]
            with self.subTest(name):
                page, _ = self.start(AGENT, device=device)
                line = page.evaluate(APPEND_LINE)
                self.assertEqual(len(line["groups"]), 2, line)
                self.assertEqual([len(set(tops)) for tops in line["groups"]], [1, 1], line)
                self.assertEqual(set(line["pills"]), {18}, line)
                if name != "phone 320x720":
                    self.assertEqual(len(line["lineTops"]), 1, line)
                else:
                    self.assertLessEqual(len(line["lineTops"]), 2, line)
                    self.assertEqual(line["seps"], [line["groups"][0][0]], line)  # the separator ends the first line

    def test_without_a_colleague_the_line_is_the_usual_one(self):
        """A note that tags only me says whom it tells as a new pin's line does ('@ 알림 Alice Kim (나 — 알림 없음)'),
        with nothing about a separate save; a note without a tag has no line."""
        page, _ = self.start(AGENT, note="@Alice Kim 나중에 다시 보기")
        line = page.evaluate(APPEND_LINE)
        self.assertEqual(line["words"].split(), ["알림", "Alice", "Kim", "(나", "—", "알림", "없음)"])
        self.assertEqual(line["groups"], [])
        self.rewrite(page, "태그 없는 메모")
        self.assertTrue(page.evaluate(APPEND_LINE)["hidden"])

    def test_the_append_keeps_the_pins_assignee_and_tells_the_tagged_colleague(self):
        """[덧붙이기]: one edit request carrying the note and no assignee; the pin stays the agent's, Carol gets
        `mention` and nobody `assigned`."""
        page, pid = self.start(AGENT)
        edits = []
        page.on("request", lambda r: edits.append(r.post_data_json) if "/api/pins/%d/edit" % pid in r.url else None)
        page.click('#c-overlap [data-act="overlap-append"]')
        page.wait_for_function("!COMPOSE.saving&&document.querySelector('#composer').hidden")
        settle(page)
        self.assertEqual(edits, [{"note_append": "@Carol Lee 답해 주세요", "base_rev": edits[0]["base_rev"]}])
        self.assertEqual(self.sent, [])
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["assignee"], AGENT)
        self.assertEqual(self.events(pid), {"mention": [C]})

    def test_a_new_pin_instead_goes_to_whom_the_line_named(self):
        """[핀 저장] with the notice still up saves the new pin the line named - Carol's; and after [따로 저장] the
        notice is gone, the line reads '담당 Carol Lee' alone and the row is back with her segment pressed."""
        page, pid = self.start(AGENT)
        body, record = self.save(page)
        self.assertEqual((body["assignee"], record["assignee"]), (C, C))
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["assignee"], AGENT)
        self.compose(page, "@Carol Lee 한 번 더", separate=False)
        self.assertIsNone(page.evaluate(ASSIGN_ROW))
        page.click('#c-overlap [data-act="overlap-separate"]')
        settle(page)
        self.assertFalse(page.is_visible("#c-overlap"))
        self.assertEqual(page.evaluate(PREVIEW)["groups"], [["담당", ["Carol Lee"]]])
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, C], "checked": [C]})


SAM1 = {"Tailscale-User-Login": "sam1@example.com", "Tailscale-User-Name": "Sam Jung"}
SAM2 = {"Tailscale-User-Login": "sam2@example.com", "Tailscale-User-Name": "Sam Jung"}


class TwoPeopleWithOneName(ComposerBase):
    """Two people named Sam Jung, picked from the @-list: the one the text names first has the pin, and the row and
    the line tell them apart with the login the @-list shows."""

    def setUp(self):
        """Register the two."""
        super().setUp()
        for person in (SAM1, SAM2):
            ps.APP.people_directory.record(actor(person))

    def pick_sam(self, page, login):
        """Type '@Sam' at the caret and click login's row of the @-list."""
        page.keyboard.type("@Sam")
        page.wait_for_selector("#mention-pop:not([hidden]) button[role=option]")
        index = page.evaluate("login => MENTION.items.findIndex(p => p.login === login)", login)
        page.click('#mention-pop button[data-i="%d"]' % index)
        settle(page)

    def test_the_one_tagged_first_in_the_text_has_the_pin_and_the_two_read_apart(self):
        """sam2 picked first and sam1 after it - and, the second time, sam1 picked first and sam2 then put before it
        at the start of the note: sam2, whom the text names first, is the assignee on the row, on the line and in the
        request (it was sam1, the login that sorts first), and each segment and pill carries its login."""
        for sam2_typed_first in (True, False):
            with self.subTest(sam2_typed_first=sam2_typed_first):
                page = self.view(DESKTOP)
                self.select(page, DESKTOP)
                self.separate(page)
                page.click("#note")
                if sam2_typed_first:
                    self.pick_sam(page, "sam2@example.com")
                    page.keyboard.type("먼저, 그리고 ")
                    self.pick_sam(page, "sam1@example.com")
                else:
                    self.pick_sam(page, "sam1@example.com")
                    page.keyboard.press("ControlOrMeta+Home")
                    self.pick_sam(page, "sam2@example.com")
                self.leave(page, DESKTOP)
                row = page.evaluate(ASSIGN_ROW)
                self.assertEqual(
                    (row["options"], row["checked"]),
                    ([AGENT, "sam2@example.com", "sam1@example.com"], ["sam2@example.com"]),
                )
                cells = page.locator("#c-assign button[role=radio]").all_inner_texts()
                self.assertEqual(
                    [" ".join(cell.split()) for cell in cells],
                    ["에이전트", "@Sam Jung sam2@example.com", "@Sam Jung sam1@example.com"],
                )
                self.assertEqual(
                    page.locator("#note-mentions").inner_text().split(),
                    ["담당", "Sam", "Jung", "sam2@example.com", "알림", "Sam", "Jung", "sam1@example.com"],
                )
                body, record = self.save(page)
                self.assertEqual((body["assignee"], record["assignee"]), ("sam2@example.com", "sam2@example.com"))
                self.assertEqual(self.events(record["id"])["assigned"], ["sam2@example.com"])


class PickAcrossDocuments(ComposerBase):
    """A pick made on one document does not follow the author to another."""

    def setUp(self):
        """A second document beside the manuscript, with its finished build."""
        super().setUp()
        src = ps.APP.C.src
        (src / "reply.tex").write_text((src / "main.tex").read_text(encoding="utf-8"), encoding="utf-8")
        ps.APP.set_docs(startup_documents.make_docs(["ms=본문:main.tex", "rr=답변서:reply.tex"], src, ps.APP.C.paths))
        for doc in ps.APP.docs:
            pages = doc.dir / "pages-20260925100000"
            pages.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (pages / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
            (doc.dir / "pages.cur").write_text(pages.name)
            (doc.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
            (doc.dir / "head.txt").write_text("abc1234")

    def test_switching_documents_starts_the_other_one_from_the_default(self):
        """에이전트 picked over two tags on the manuscript, then the other document's link pressed: a selection there
        tagging Bob has Bob pressed and saves him - the pick stayed behind with the manuscript's draft (it came along
        as 'touched' and the pin went to the agent)."""
        page = self.view(DESKTOP)
        self.compose(page, "@Bob Park 그리고 @Carol Lee 확인")
        page.locator('#c-assign [data-v="agent"]').click()
        settle(page)
        page.click('#doc-links button[data-doc="rr"]')
        page.wait_for_function("DOC==='rr'&&META&&META.doc==='rr'")
        settle(page)
        self.compose(page, "@Bob Park 답변서 확인")
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B], "checked": [B]})
        self.assertEqual(self.save(page)[0]["assignee"], B)


LONG = [
    {"Tailscale-User-Login": "alexandria@example.com", "Tailscale-User-Name": "Alexandria Montgomery-Smythe"},
    {"Tailscale-User-Login": "bartholomew@example.com", "Tailscale-User-Name": "Bartholomew Fitzgerald-Jones"},
    {"Tailscale-User-Login": "seojun@example.com", "Tailscale-User-Name": "김서준 박사후연구원 2026"},
]
LONG_NOTE = "@Alexandria Montgomery-Smythe 와 @Bartholomew Fitzgerald-Jones 그리고 @김서준 박사후연구원 2026 확인"
# The composer's stacked blocks from the note to the kind, as drawn (CSS px): each block's box, the assignee track's box,
# whether anything is wider than its container, and - for the ink measure - the boxes of the preview line's items (a label's
# icon and its word apart) and of the assignee row's label and each segment's name (without its '@', whose tail hangs under
# the baseline), every text read by its own range; a segment under the scroll box's 32px edge fade is left out.
COMPOSER_ROWS = """() => {const q = s => document.querySelector(s), R = e => {const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];};
  const text = (e, from) => {const n = [...e.childNodes].find(x => x.nodeType === 3 && x.nodeValue.trim()), g = document.createRange();
    g.setStart(n, from || 0); g.setEnd(n, n.nodeValue.length); return R(g);};
  const seg = q('#c-assign .as-seg'), S = R(seg), track = seg.querySelector('.lad-t') || seg, wide = e => e.scrollWidth - e.clientWidth;
  const ink = [];
  [...q('#note-mentions').children].forEach((e, i) => {const svg = e.querySelector('svg');
    if (svg) ink.push({k: 'preview' + i + ':icon', box: R(svg), ix: 0});
    ink.push({k: 'preview' + i + ':' + e.textContent.trim(), box: text(e), ix: 0});});
  ink.push({k: 'assign:' + q('#c-assign .as-lab').textContent, box: text(q('#c-assign .as-lab')), ix: 0});
  [...track.querySelectorAll('button')].forEach((b, i) => {const t = b.querySelector('.as-t') || b, name = t.textContent.trim(), r = text(t, name.startsWith('@') ? 1 : 0);
    const lo = S[0] + (seg.classList.contains('fade-l') ? 32 : 0), hi = S[2] - (seg.classList.contains('fade-r') ? 32 : 0);
    if (r[0] >= lo && r[2] <= hi) ink.push({k: 'assign' + i + ':' + name, box: r, ix: 0});});
  return {note: R(q('#note')), preview: R(q('#note-mentions')), assign: R(q('#c-assign')), seg: S, track: R(track), kind: R(q('#c-kind')),
    composer: R(q('#composer')), overflow: {page: wide(document.documentElement), panel: wide(q('#right')), composer: wide(q('#composer')), seg: wide(seg)},
    ink};}"""
# The two rows' words against the ink reference (MEASURE's label(), docs/handbook/viewer.md §글자 가운데): each item of the
# preview line against its own box - with the items' box centres and heights (one flex line shares a centre) and how far each
# label icon's centre lies under its label's - the assignee row's label against the track, and each segment's words against
# the segment.
COMPOSER_LABELS = """() => {const q = s => document.querySelector(s), mid = e => {const r = e.getBoundingClientRect(); return r.top + r.height / 2;};
  const read = (row, box) => e => Object.assign(__m.label(e, box), {row, el: e.className});
  const items = [...q('#note-mentions').children], seg = q('#c-assign .as-seg'), track = seg.querySelector('.lad-t') || seg;
  return {labels: items.map(e => read('preview')(e)).concat([read('assign', track)(q('#c-assign .as-lab'))],
      [...track.querySelectorAll('button')].map(b => read('assign', b)(b.querySelector('.as-t')))),
    mids: items.map(mid), heights: items.map(e => e.getBoundingClientRect().height),
    icons: items.filter(e => e.querySelector('svg')).map(e => mid(e.querySelector('svg')) - mid(e))};}"""


class AssigneeRowGeometry(ComposerBase):
    """The preview line and the assignee row keep the composer's grid on every band (docs/handbook/viewer.md
    §컴포넌트 규격): one left and one right edge with the note, 8px between blocks, the standard segmented track, one ink
    centre per row, 44px (touch) or 24px (mouse) hits, and nothing wider than the composer."""

    def setUp(self):
        """Add the three long-named colleagues."""
        super().setUp()
        for person in LONG:
            ps.APP.people_directory.record(actor(person))

    def rows(self, page, device):
        """COMPOSER_ROWS with each ink item's measured centre (CSS px), read from a screenshot once the fonts are in."""
        self.assertEqual(fonts_ready(page), "loaded")
        got = page.evaluate(COMPOSER_ROWS)
        x0, y0 = got["composer"][0], got["note"][3]
        clip = {"x": x0, "y": y0, "width": got["composer"][2] - x0, "height": got["kind"][1] - y0}
        items = [
            dict(i, box=[i["box"][0] - x0, i["box"][1] - y0, i["box"][2] - x0, i["box"][3] - y0]) for i in got["ink"]
        ]
        shot = base64.b64encode(page.screenshot(clip=clip)).decode()
        ink = page.evaluate(ROW_INK, [shot, device["device_scale_factor"], items])
        got["mid"] = {key: None if value is None else round(value["mid"] + y0, 2) for key, value in ink.items()}
        return got

    def assert_grid(self, got):
        """One left edge and one right edge with the note, 8px between the blocks, and nothing wider than its box."""
        lefts = [got[key][0] for key in ("note", "preview", "assign", "kind")]
        rights = [got[key][2] for key in ("note", "seg", "kind")]
        self.assertLessEqual(max(lefts) - min(lefts), 0.5, got)
        self.assertLessEqual(max(rights) - min(rights), 0.5, got)
        gaps = [
            got["preview"][1] - got["note"][3],
            got["track"][1] - got["preview"][3],
            got["kind"][1] - got["track"][3],
        ]
        self.assertEqual([round(gap, 1) for gap in gaps], [8, 8, 8], got)
        self.assertEqual(
            {key: got["overflow"][key] for key in ("page", "panel", "composer")}, {"page": 0, "panel": 0, "composer": 0}
        )

    def assert_one_centre(self, got, prefix):
        """The measured items whose key starts with prefix are painted on one ink centre: every pair is within 0.5px.
        For the bundled Pretendard only - a painted centre is the ink of the very strings, and in another font a Hangul
        label and a mixed-case Latin name differ by their glyphs' reach past the cap height, which no layout removes."""
        mids = {key: mid for key, mid in got["mid"].items() if key.startswith(prefix)}
        self.assertGreaterEqual(len(mids), 4, got["mid"])
        self.assertNotIn(None, mids.values(), mids)
        self.assertLessEqual(max(mids.values()) - min(mids.values()), 0.5, mids)

    def assert_on_the_cap_centre(self, page, hangul):
        """The ink reference, by layout (COMPOSER_LABELS): every word of the preview line and the assignee row has its
        cap-height centre and its digits' centre within 0.5px of its box's centre - and its Hangul ink centre, when
        hangul is true; the preview line's items are whole px tall on one centre, with each label's icon on its label's."""
        self.assertEqual(fonts_ready(page), "loaded")
        page.evaluate(MEASURE)
        got = page.evaluate(COMPOSER_LABELS)
        self.assertLessEqual({"preview", "assign"}, {label["row"] for label in got["labels"]}, got)
        self.assertEqual(off_centre(got["labels"], hangul), [])
        self.assertEqual({height % 1 for height in got["heights"]}, {0}, got)
        self.assertLessEqual(max(got["mids"]) - min(got["mids"]), 0.5, got)
        self.assertTrue(got["icons"], got)
        self.assertLessEqual(max(abs(under) for under in got["icons"]), 0.5, got)

    def test_the_rows_keep_the_grid_and_the_standard_track_on_every_band(self):
        """Each viewport of the list, a note tagging Bob and Carol: the preview line, the assignee row and the kind
        share the note's edges and stand 8px apart; the preview line is a whole number of px tall (as line boxes of the
        body's 1.55 it was 18.6px and what followed it began between pixels); the track is 36px round 28px segments 4px
        in, its thumb's radius the track's less 4; every segment answers 44px on touch and 24px with a mouse; nothing
        is wider than the composer."""
        for name, device in VIEWPORTS.items():
            with self.subTest(name):
                page = self.view(device)
                self.compose(page, "@Bob Park 확인 부탁, @Carol Lee 참고", device=device)
                got = self.rows(page, device)
                self.assert_grid(got)
                self.assertEqual(got["preview"][3] - got["preview"][1], 18, got)
                (track,) = page.evaluate(SEGMENTS, "#c-assign")
                self.assertEqual(
                    [track[key] for key in ("h", "top", "bottom", "left")] + [track["rTrack"] - track["rThumb"]],
                    [36, 4, 4, 4, 4],
                    track,
                )
                if device.get("has_touch"):
                    self.assertEqual(page.evaluate(MISSES_44, "#c-assign button"), [])
                else:
                    self.assertEqual(page.evaluate(MISSES_24, "#c-assign button"), [])

    def tag_three(self):
        """Register a digit and a Hangul name beside Bob's Latin one and return a note tagging the three."""
        for login, name in (("r2@example.com", "R2 4096"), ("jiwoo@example.com", "한지우")):
            ps.APP.people_directory.record(actor({"Tailscale-User-Login": login, "Tailscale-User-Name": name}))
        return "@Bob Park 확인, @R2 4096 참고 @한지우"

    def test_the_rows_stand_on_the_cap_height_centre_whichever_font_draws_them(self):
        """Phone 390 and the desktop, with a Latin, a digit and a Hangul name, in the bundled Pretendard and in two
        fallback stacks: every label, pill and plain word of the preview line, the assignee row's label and each
        segment's words have their cap-height centre, and so their digits and capitals, within 0.5px of their box's
        centre, whichever face the machine draws the stack with (as line boxes the preview line's words stood 0.6px
        over its middle in Pretendard). The Hangul ink is held to 0.5px only where the face that drew it (drawn_faces)
        is one the handbook gives a tolerance for."""
        note = self.tag_three()
        for name, device in (("phone 390x844", PHONE), ("desktop 1440x900", DESKTOP)):
            for font in (None, *FALLBACK_FONTS):
                with self.subTest(name, font=font):
                    page = self.view(device, font=font)
                    self.compose(page, note, device=device)
                    latin = drawn_faces(page, "#note-mentions", "Bob Park R2 4096")
                    hangul = drawn_faces(page, "#note-mentions", "담당알림에이전트한지우")
                    self.assertTrue(latin and hangul, (latin, hangul))
                    self.assertEqual(
                        {face.startswith("Pretendard") for face in latin | hangul}, {not font}, (latin, hangul)
                    )
                    self.assert_on_the_cap_centre(page, hangul_ink_holds(hangul))

    def test_each_row_is_painted_on_one_ink_centre_in_light_and_dark(self):
        """Phone 390 and the desktop in the bundled Pretendard, light and dark: the preview line's labels, icon and
        names - Latin, digits and Hangul - are painted on one ink centre within 0.5px, and so are the assignee row's
        label and segment labels. On touch the label is as large as the segments' words: at 12px beside their 13px its
        baseline lay a third of a pixel higher and was painted 0.8px over them."""
        note = self.tag_three()
        for name, device in (("phone 390x844", PHONE), ("desktop 1440x900", DESKTOP)):
            for theme in ("light", "dark"):
                with self.subTest(name, theme=theme):
                    page = self.view(device, theme=theme)
                    self.compose(page, note, device=device)
                    faces = drawn_faces(page, "#note-mentions", "담당알림한지우")
                    self.assertEqual({face.startswith("Pretendard") for face in faces}, {True}, faces)
                    got = self.rows(page, device)
                    self.assert_one_centre(got, "preview")
                    self.assert_one_centre(got, "assign")
                    sizes = page.evaluate(
                        "['#c-assign .as-lab', '#c-assign .as-t'].map(s => getComputedStyle(document.querySelector(s)).fontSize)"
                    )
                    self.assertEqual(len(set(sizes)), 1, sizes)

    def test_three_long_names_at_320_scroll_inside_the_row(self):
        """320x720, three long names: the track is longer than the row and scrolls sideways inside it, as the range
        ladder does - the composer and the sheet stay 320 wide and the track keeps its 36px geometry. The checked
        segment is whole and clear of the edge fades, each fade is only as wide as the room beside it and is drawn only
        on a side that has more to scroll to (the checked name's ends lay under 32px fades and 에이전트 was scrolled out
        with nothing to say so). The same after each other segment is picked, back to 에이전트, whose side then has no
        fade. Names are not shortened, so the option a person presses reads in full."""
        device = VIEWPORTS["phone 320x720"]
        page = self.view(device)
        self.compose(page, LONG_NOTE, device=device)
        got = self.rows(page, device)
        self.assert_grid(got)
        self.assertGreater(got["overflow"]["seg"], 0)
        (track,) = page.evaluate(SEGMENTS, "#c-assign")
        self.assertEqual([track[key] for key in ("h", "top", "bottom", "left")], [36, 4, 4, 4], track)
        in_view = """() => {const seg = document.querySelector('#c-assign .as-seg'), S = seg.getBoundingClientRect(), cs = getComputedStyle(seg);
          const on = seg.querySelector('button.on').getBoundingClientRect(), has = c => seg.classList.contains(c);
          const fade = [has('fade-l') ? parseFloat(cs.getPropertyValue('--fade-l')) : 0, has('fade-r') ? parseFloat(cs.getPropertyValue('--fade-r')) : 0];
          return {whole: on.left >= S.left - 0.5 && on.right <= S.right + 0.5, fade, drawn: [has('fade-l'), has('fade-r')],
            clear: on.left >= S.left + fade[0] - 0.5 && on.right <= S.right - fade[1] + 0.5,
            more: [seg.scrollLeft > 1, seg.scrollWidth - seg.clientWidth - seg.scrollLeft > 1],
            names: [...seg.querySelectorAll('button')].map(b => b.textContent.trim())};}"""
        logins = [person["Tailscale-User-Login"] for person in LONG]
        first = page.evaluate(in_view)
        self.assertEqual(first["names"], ["에이전트"] + ["@" + person["Tailscale-User-Name"] for person in LONG])
        for login in (logins[0], logins[2], logins[1], AGENT):
            with self.subTest(checked=login):
                if page.evaluate(ASSIGN_ROW)["checked"] != [login]:
                    page.tap('#c-assign [data-v="%s"]' % login)
                    settle(page)
                seen = page.evaluate(in_view)
                self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [login])
                self.assertTrue(seen["whole"] and seen["clear"], seen)
                self.assertEqual(seen["drawn"], seen["more"], seen)
                self.assertLessEqual(max(seen["fade"]), 32, seen)
                self.assertEqual(page.evaluate(MISSES_44, "#c-assign button.on"), [])
        self.assertEqual(seen["drawn"], [False, True], seen)
        self.assertEqual(page.evaluate(COMPOSER_ROWS)["overflow"]["composer"], 0)

    def test_a_preview_of_two_lines_leaves_the_rows_under_it_on_whole_pixels(self):
        """768x1024 and 673x841 (the tablet sheet), three long names and two short ones: the preview line wraps, and it and every row
        under it - the assignee row, the kind - still stand on whole pixels, 8px apart (each line of the preview was
        18.6px, so the rows under a two-line preview began between pixels)."""
        for name in ("tablet 768x1024", "fold inner 673x841"):
            device = VIEWPORTS[name]
            with self.subTest(name):
                page = self.view(device)
                self.compose(page, LONG_NOTE + ", @Bob Park 와 @Carol Lee 도", device=device)
                got = page.evaluate(COMPOSER_ROWS)
                lines = page.evaluate(
                    "() => new Set([...document.querySelector('#note-mentions').children].map(e => Math.round(e.getBoundingClientRect().top))).size"
                )
                self.assertGreaterEqual(lines, 2)
                for key in ("preview", "assign", "kind"):
                    self.assertEqual([got[key][1] % 1, got[key][3] % 1], [0, 0], (key, got[key]))
                self.assert_grid(got)

    def test_a_long_name_wraps_the_preview_line_inside_the_composer(self):
        """320x720 and three long names: the preview line breaks between names and stays inside the composer; no name
        is cut by a clipping box (each chip is as wide as its text)."""
        device = VIEWPORTS["phone 320x720"]
        page = self.view(device)
        self.compose(page, LONG_NOTE, device=device)
        got = page.evaluate(
            """() => {const box = document.querySelector('#note-mentions'), B = box.getBoundingClientRect();
              return [...box.querySelectorAll('.mention')].map(e => {const r = e.getBoundingClientRect();
                return {text: e.textContent, inside: r.left >= B.left - 0.5 && r.right <= B.right + 0.5, cut: e.scrollWidth > e.clientWidth + 1};});}"""
        )
        self.assertEqual(len(got), 3)
        self.assertEqual([item for item in got if not item["inside"] or item["cut"]], [])


if __name__ == "__main__":
    unittest.main()
