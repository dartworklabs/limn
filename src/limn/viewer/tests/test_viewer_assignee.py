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
import statistics
import unittest
from urllib.parse import urlparse

from helpers import add_pin, extract_js_fn, find_record, ps, run_node
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_browser import (
    MISSES_24,
    MISSES_44,
    ROW_INK,
    SEGMENTS,
    VIEWPORTS,
    BrowserBase,
    booted,
    fonts_ready,
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
OUTCOME_FNS = (
    "mentionTokens",
    "mentionAfterWord",
    "mentionScan",
    "meLogin",
    "assignPeople",
    "defaultAssignee",
    "assignOutcome",
)


class AssigneeOutcomeRule(unittest.TestCase):
    """assignOutcome(text, hints, pick): the assignee a new pin is saved with and who is only notified."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 (CI), where a missing node is a failure."""
        if shutil.which("node"):
            return
        if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
            self.fail("node is required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
        self.skipTest("node is not installed")

    def outcomes(self, cases):
        """assignOutcome() for every (text, hints, pick) case, as Alice among TEAM, in one node process."""
        js = "\n".join(
            [
                "const PEOPLE=%s,META={me:%s};" % (json.dumps(TEAM), json.dumps(TEAM[0])),
                *(extract_js_fn(name) for name in OUTCOME_FNS),
                "const CASES=%s;" % json.dumps(cases, ensure_ascii=False),
                "console.log(JSON.stringify(CASES.map(([text,hints,pick])=>assignOutcome(text,new Set(hints),pick))));",
            ]
        )
        return json.loads(run_node(js))

    def test_the_first_resolved_colleague_is_the_assignee_and_later_ones_are_only_notified(self):
        """Every case of the rule: where the tag sits does not matter, the first colleague wins, the author, an
        unresolved word and a removed tag assign nobody, and a pick stands only while its person is still tagged."""
        got = self.outcomes([[text, hints, pick] for _, text, hints, pick, *_ in OUTCOMES])
        for (label, _, _, _, assignee, fyi, kept), out in zip(OUTCOMES, got, strict=True):
            with self.subTest(label):
                self.assertEqual((out["assignee"], out["fyi"], out["kept"]), (assignee, fyi, kept), out)

    def test_the_default_does_not_read_the_pin_kind(self):
        """defaultAssignee(text, hints) takes no kind: a fix request with a mid-sentence tag is handed over as a
        question is (it used to stay with the agent unless the note started with the tag)."""
        js = "\n".join(
            [
                "const PEOPLE=%s,META={me:%s};" % (json.dumps(TEAM), json.dumps(TEAM[0])),
                *(extract_js_fn(name) for name in OUTCOME_FNS),
                "console.log(JSON.stringify([defaultAssignee.length,"
                " defaultAssignee('수치를 @Bob Park 확인 부탁',new Set()),defaultAssignee('@홍길동 확인',new Set())]));",
            ]
        )
        self.assertEqual(json.loads(run_node(js)), [2, B, AGENT])


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

    def route(self, route):
        """The fixture's routes, keeping the JSON body of each new-pin request as it left the viewer."""
        request = route.request
        if request.method == "POST" and urlparse(request.url).path == "/api/pin":
            self.sent.append(request.post_data_json)
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

    def compose(self, page, note, kind="fix"):
        """Select a region as a finger does (no popover by the box), write note in the panel's field, set the kind and
        leave the field - so the @-list is closed and a word that does not resolve is flagged, as when the author moves
        on to [핀 저장]."""
        page.evaluate("()=>{LAST_PTR='touch'; pick({page:1,x0:10,y0:10,x1:200,y1:60});}")
        page.wait_for_function("COMPOSE.current&&!COMPOSE.picking")
        page.locator("#note").fill(note)
        if kind != "fix":
            page.evaluate("kind=>setKind(kind)", kind)
        page.evaluate("document.querySelector('#note').blur()")
        settle(page)
        page.wait_for_function("document.querySelector('#mention-pop').hidden")

    def save(self, page):
        """Press [핀 저장], wait for the composer to close and return (the request's body, the stored record)."""
        before = len(self.sent)
        page.evaluate("document.querySelector('#btn-save').click()")
        page.wait_for_function("!COMPOSE.saving&&document.querySelector('#composer').hidden")
        settle(page)
        self.assertEqual(len(self.sent), before + 1)
        pid = max(pin.record["id"] for pin in ps.APP.snapshot_pins())
        return self.sent[-1], find_record(ps.APP.snapshot_pins(), pid)

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
        page.locator("#note").fill("@Bob Park 그리고 @Carol Lee 확인 부탁합니다")
        settle(page)
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [AGENT])
        self.assertEqual(
            page.evaluate(PREVIEW)["groups"], [["담당", ["에이전트"]], ["알림", ["Bob Park", "Carol Lee"]]]
        )
        page.locator('#c-assign [data-v="%s"]' % C).click()
        settle(page)
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], [C])
        self.assertEqual(page.evaluate(PREVIEW)["groups"], [["담당", ["Carol Lee"]], ["알림", ["Bob Park"]]])
        page.locator("#note").fill("@Bob Park 확인 부탁합니다")
        settle(page)
        self.assertEqual(page.evaluate(ASSIGN_ROW), {"options": [AGENT, B], "checked": [B]})
        page.locator("#note").fill("@Bob Park 그리고 @Carol Lee 확인 부탁합니다")
        settle(page)
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


LONG = [
    {"Tailscale-User-Login": "alexandria@example.com", "Tailscale-User-Name": "Alexandria Montgomery-Smythe"},
    {"Tailscale-User-Login": "bartholomew@example.com", "Tailscale-User-Name": "Bartholomew Fitzgerald-Jones"},
    {"Tailscale-User-Login": "seojun@example.com", "Tailscale-User-Name": "김서준 박사후연구원 2026"},
]
LONG_NOTE = "@Alexandria Montgomery-Smythe 와 @Bartholomew Fitzgerald-Jones 그리고 @김서준 박사후연구원 2026 확인"
# Fallback interface fonts: a system Korean family, and a Latin family whose metrics differ from Pretendard's.
FALLBACK_FONTS = ("'Noto Sans CJK KR','WenQuanYi Zen Hei',sans-serif", "'DejaVu Sans','WenQuanYi Zen Hei',sans-serif")
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
    ink, fonts: getComputedStyle(q('#note-mentions')).fontFamily};}"""


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

    def assert_one_centre(self, got, prefix, bundled):
        """The measured items whose key starts with prefix share one ink centre: in the bundled Pretendard every pair
        is within 0.5px; in a fallback family each is within 0.5px of the row's common centre (their median) - there a
        Hangul label and a mixed-case Latin name differ by their glyphs' reach past the cap height, which no layout
        removes."""
        mids = {key: mid for key, mid in got["mid"].items() if key.startswith(prefix)}
        self.assertGreaterEqual(len(mids), 4, got["mid"])
        self.assertNotIn(None, mids.values(), mids)
        if bundled:
            self.assertLessEqual(max(mids.values()) - min(mids.values()), 0.5, mids)
        centre = statistics.median(mids.values())
        self.assertLessEqual(max(abs(mid - centre) for mid in mids.values()), 0.5, mids)

    def test_the_rows_keep_the_grid_and_the_standard_track_on_every_band(self):
        """Each viewport of the list, a note tagging Bob and Carol: the preview line, the assignee row and the kind
        share the note's edges and stand 8px apart; the track is 36px round 28px segments 4px in, its thumb's radius the
        track's less 4; every segment answers 44px on touch and 24px with a mouse; nothing is wider than the composer."""
        for name, device in VIEWPORTS.items():
            with self.subTest(name):
                page = self.view(device)
                self.compose(page, "@Bob Park 확인 부탁, @Carol Lee 참고")
                got = self.rows(page, device)
                self.assert_grid(got)
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

    def test_each_row_has_one_ink_centre_in_latin_digits_and_hangul(self):
        """Phone 390 and the desktop, in the bundled Pretendard and in two fallback families, light and dark: the preview
        line's labels, icon and names - Latin, digits and Hangul - share one ink centre within 0.5px, and so do the
        assignee row's label and segment labels."""
        ps.APP.people_directory.record(
            actor({"Tailscale-User-Login": "r2@example.com", "Tailscale-User-Name": "R2 4096"})
        )
        ps.APP.people_directory.record(
            actor({"Tailscale-User-Login": "jiwoo@example.com", "Tailscale-User-Name": "한지우"})
        )
        note = "@Bob Park 확인, @R2 4096 참고 @한지우"
        for name, device in (("phone 390x844", PHONE), ("desktop 1440x900", DESKTOP)):
            for font in (None, *FALLBACK_FONTS):
                for theme in ("light", "dark"):
                    with self.subTest(name, font=font, theme=theme):
                        page = self.view(device, theme=theme, font=font)
                        self.compose(page, note)
                        got = self.rows(page, device)
                        self.assertEqual("Pretendard" in got["fonts"], not font)
                        self.assert_one_centre(got, "preview", not font)
                        self.assert_one_centre(got, "assign", not font)

    def test_three_long_names_at_320_scroll_inside_the_row(self):
        """320x720, three long names: the track is longer than the row and scrolls sideways inside it, as the range
        ladder does - the composer and the sheet stay 320 wide, the checked segment is in view with the fade on the
        cut side, the track keeps its 36px geometry, and after a pick the new thumb scrolls into view and every segment
        in view answers 44px. Names are not shortened, so the option a person presses reads in full."""
        device = VIEWPORTS["phone 320x720"]
        page = self.view(device)
        self.compose(page, LONG_NOTE)
        got = self.rows(page, device)
        self.assert_grid(got)
        self.assertGreater(got["overflow"]["seg"], 0)
        (track,) = page.evaluate(SEGMENTS, "#c-assign")
        self.assertEqual([track[key] for key in ("h", "top", "bottom", "left")], [36, 4, 4, 4], track)
        in_view = """() => {const seg = document.querySelector('#c-assign .as-seg'), S = seg.getBoundingClientRect();
          const on = seg.querySelector('button.on').getBoundingClientRect();
          return {whole: on.left >= S.left - 0.5 && on.right <= S.right + 0.5, fade: [...seg.classList].filter(c => c.startsWith('fade')).sort(),
            names: [...seg.querySelectorAll('button')].map(b => b.textContent.trim())};}"""
        first = page.evaluate(in_view)
        self.assertTrue(first["whole"], first)
        self.assertIn("fade-r", first["fade"])
        self.assertEqual(first["names"], ["에이전트"] + ["@" + person["Tailscale-User-Name"] for person in LONG])
        page.locator('#c-assign [data-v="seojun@example.com"]').click()
        settle(page)
        last = page.evaluate(in_view)
        self.assertIn("fade-l", last["fade"])
        visible = page.evaluate(
            """() => {const seg = document.querySelector('#c-assign .as-seg'), S = seg.getBoundingClientRect(), on = seg.querySelector('button.on').getBoundingClientRect();
              return Math.min(on.right, S.right) - Math.max(on.left, S.left);}"""
        )
        self.assertGreaterEqual(visible, 44)
        self.assertEqual(page.evaluate(ASSIGN_ROW)["checked"], ["seojun@example.com"])
        self.assertEqual(page.evaluate(COMPOSER_ROWS)["overflow"]["composer"], 0)

    def test_a_long_name_wraps_the_preview_line_inside_the_composer(self):
        """320x720 and three long names: the preview line breaks between names and stays inside the composer; no name
        is cut by a clipping box (each chip is as wide as its text)."""
        device = VIEWPORTS["phone 320x720"]
        page = self.view(device)
        self.compose(page, LONG_NOTE)
        got = page.evaluate(
            """() => {const box = document.querySelector('#note-mentions'), B = box.getBoundingClientRect();
              return [...box.querySelectorAll('.mention')].map(e => {const r = e.getBoundingClientRect();
                return {text: e.textContent, inside: r.left >= B.left - 0.5 && r.right <= B.right + 0.5, cut: e.scrollWidth > e.clientWidth + 1};});}"""
        )
        self.assertEqual(len(got), 3)
        self.assertEqual([item for item in got if not item["inside"] or item["cut"]], [])


if __name__ == "__main__":
    unittest.main()
