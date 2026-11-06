"""When a comment was written, a card's timeline and the pin list's order (docs/handbook/viewer.md §뜻과 모양, §패널 정리,
§스레드와 검토, §목록 순서).

- ``StampWords`` and ``PinOrder`` run the pure decisions under node against a fixed clock: the time's words at the seven-day
  and the year edge, the day lines' names, the three orders.
- ``CommentCards`` drives the real viewer: the first comment's head on open and review cards, the author out of the card's
  head, a folded card, an edited note, a pin with no recorded author, the words ticking.
- ``TimelineRail`` reads the line as painted: unbroken through what can stand in it, ending at the last node, absent without
  a thread, in both themes; and how a state record is laid out.
- ``OrderControl`` drives the control: the default and the remembered order, day lines, both sections, the filters, keyboard
  walking, jumps and far cards in the order drawn, and the fit at four sizes.

The browser classes run at a fixed time of day (NOON), the page and the server alike, not at the hour the suite runs.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_timeline.py
"""

import base64
import json
import random
import shutil
import time
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

import helpers_figure
from helpers import add_pin, edit_pin, edit_stored, extract_js_fn, find_record, js_i18n, ps, record_of, run_node
from helpers_access import ALICE, BOB, actor
from helpers_authority import post_authority
from helpers_browser import VIEWPORTS, BrowserBase, booted, settle

DESKTOP = {"viewport": {"width": 1440, "height": 900}}
TABLET = VIEWPORTS["tablet 1024x768"]
FOLD = VIEWPORTS["fold inner 841x673"]
PHONE = VIEWPORTS["phone 390x844"]
FOUR_SIZES = {"desktop": DESKTOP, "foldable": FOLD, "tablet": TABLET, "phone": PHONE}
# 2026-11-02 12:00 in Seoul, where StampWords runs node. In a zone that keeps daylight saving time the week before it can
# be 169 hours (the US left it on 11-01), and the seven-day cut, which counts hours, would fall an hour from the tests' edge.
NOW = "new Date(2026,10,2,12,0).getTime()"
# The browser tests' time: noon on the 15th of this month in Seoul. The page runs in that zone with its clock started there
# (TimelineFixture.show), the server stamps what it records with it, and ago() counts back from it, so a day line, a relative
# word, the year and the seven-day cut read the same whenever the suite runs. By the real clock an hour ago was yesterday from
# 00:00 to 01:00 on the runner (UTC on CI), a day ago was last year on January 1st, and eight days on was next year from
# December 24th. Mid-month, what the tests reach (two days back, eight days on) stays in the month; this month rather than
# a fixed date keeps it within 30 days of the server's own clock, by which it still counts the Trash's days.
NOON = datetime.fromtimestamp(time.time(), ZoneInfo("Asia/Seoul")).replace(
    day=15, hour=12, minute=0, second=0, microsecond=0
)
# A time stored moments ago, as a comment says it: relTime counts from the start of the stored minute and the page's clock
# runs on from NOON, so a test that crosses a minute's end reads '1분 전' (or more on a loaded machine), not '방금'.
JUST = r"(?:방금|\d+분 전)"
# A person whose name is 60 letters with no space to break at (the longest a head has to hold on one line).
LONG = {"Tailscale-User-Login": "long@example.com", "Tailscale-User-Name": ("Wolfeschlegelsteinhausen" * 3)[:60]}


def ago(**delta):
    """The stored string of a time this far (days=, hours=) before NOON, as the server writes it in Seoul."""
    return (NOON - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def stamp_js(lang="ko"):
    """The served time functions, with the viewer's message functions for lang, for a node harness."""
    return "\n".join(
        [js_i18n(lang)]
        + [extract_js_fn(n) for n in ("relTime", "timeParts", "timeAbs", "timeAgo", "stampText", "dayName")]
    )


class StampWords(unittest.TestCase):
    """stampText and dayName: what a comment's time says, against a fixed clock."""

    def setUp(self):
        """The decisions run the served functions under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def words(self, script, lang="ko"):
        """The JSON script prints, run with the time functions, now (the fixed clock) and BOTH, SHORT and EDITED."""
        prelude = "const now=%s,BOTH=STAMP_FORM.BOTH,SHORT=STAMP_FORM.SHORT,EDITED=STAMP_FORM.EDITED;" % NOW
        return json.loads(run_node("\n".join([stamp_js(lang), prelude, script]), tz="Asia/Seoul"))

    def test_a_time_says_both_under_seven_days_and_only_the_absolute_from_then_on(self):
        """Relative and absolute together up to the last minute of the seventh day, the absolute alone from that minute."""
        got = self.words("""console.log(JSON.stringify([
          '2026-11-02 12:00:10','2026-11-02 11:59:00','2026-11-01 20:41:00','2026-10-26 12:01:00','2026-10-26 12:00:00','2026-10-26 11:59:00',
        ].map(s=>stampText(s,BOTH,now))));""")
        self.assertEqual(
            got,
            [
                "방금 · 11-02 12:00",
                "1분 전 · 11-02 11:59",
                "15시간 전 · 11-01 20:41",
                "6일 전 · 10-26 12:01",
                "10-26 12:00",
                "10-26 11:59",
            ],
        )

    def test_the_year_shows_only_when_it_is_not_the_current_one(self):
        """On New Year's day last night's comment names its year beside its relative time, and this year's does not."""
        got = self.words("""const ny=new Date(2026,0,1,0,30).getTime(); console.log(JSON.stringify([
          stampText('2025-12-31 23:50:00',BOTH,ny),stampText('2025-09-25 00:01:00',BOTH,ny),stampText('2026-01-01 00:10:00',BOTH,ny),
          stampText('2025-09-25 00:01:00',SHORT,ny),timeAbs('2027-02-03 04:05:00',ny)]));""")
        self.assertEqual(
            got,
            [
                "40분 전 · 2025-12-31 23:50",
                "2025-09-25 00:01",
                "20분 전 · 01-01 00:10",
                "2025-09-25 00:01",
                "2027-02-03 04:05",
            ],
        )

    def test_the_short_form_is_the_relative_part_else_the_absolute(self):
        """A folded card's preview: the relative part under seven days, the absolute from then on."""
        got = self.words(
            "console.log(JSON.stringify(['2026-11-01 20:41:00','2026-10-26 12:01:00','2026-10-26 12:00:00'].map(s=>stampText(s,SHORT,now))));"
        )
        self.assertEqual(got, ["15시간 전", "6일 전", "10-26 12:00"])

    def test_an_edit_says_so_before_the_same_words(self):
        """The edited form is '수정' and the time's words, in either age."""
        got = self.words(
            "console.log(JSON.stringify(['2026-11-01 20:41:00','2025-09-25 00:01:00'].map(s=>stampText(s,EDITED,now))));"
        )
        self.assertEqual(got, ["수정 15시간 전 · 11-01 20:41", "수정 2025-09-25 00:01"])

    def test_a_string_that_is_no_time_comes_back_as_it_is(self):
        """A stored value the viewer cannot read is shown, not guessed at; nothing at all says nothing."""
        got = self.words(
            "console.log(JSON.stringify([stampText('언젠가',BOTH,now),stampText('',BOTH,now),dayName('언젠가',now)]));"
        )
        self.assertEqual(got, ["언젠가", "", ""])

    def test_the_archive_words_are_not_the_comment_words(self):
        """relTime, which the archive and the verdict line say, still gives 'M-D' past a week."""
        self.assertEqual(self.words("console.log(JSON.stringify(relTime('2026-09-01 10:00:00',now)));"), "9-1")

    def test_a_day_line_says_today_yesterday_the_date_and_the_year_when_it_differs(self):
        """Calendar days, not spans of 24 hours: a minute before midnight on New Year's Eve is yesterday, in another year."""
        got = self.words("""const ny=new Date(2026,0,1,0,10).getTime(); console.log(JSON.stringify([
          dayName('2026-11-02 00:01:00',now),dayName('2026-11-01 23:59:00',now),dayName('2026-10-31 12:00:00',now),dayName('2025-09-25 00:01:00',now),
          dayName('2025-12-31 23:59:00',ny),dayName('2025-12-30 23:59:00',ny),dayName('2026-11-03 00:10:00',now)]));""")
        self.assertEqual(got, ["오늘", "어제", "10월 31일", "2025년 9월 25일", "어제", "2025년 12월 30일", "오늘"])

    def test_in_english_the_words_are_english(self):
        """The time's words, '수정' and the day names through the message table."""
        got = self.words(
            """console.log(JSON.stringify([stampText('2026-11-01 20:41:00',BOTH,now),stampText('2026-11-01 20:41:00',EDITED,now),
              dayName('2026-11-02 01:00:00',now),dayName('2026-11-01 01:00:00',now),dayName('2026-10-31 01:00:00',now),dayName('2025-09-25 01:00:00',now)]));""",
            "en",
        )
        self.assertEqual(
            got,
            [
                "15 hr ago · 11-01 20:41",
                "Edited 15 hr ago · 11-01 20:41",
                "Today",
                "Yesterday",
                "Oct 31",
                "Sep 25, 2025",
            ],
        )


class PinOrder(unittest.TestCase):
    """orderPins and listOrderOf: which card goes where in each order."""

    def setUp(self):
        """The decision runs the served function under node."""
        if not shutil.which("node"):
            self.skipTest("node not available")

    def ordered(self, script):
        """The JSON script prints, run with orderPins, its helpers, two known documents and LIST_ORDER in scope."""
        js = "\n".join(
            [
                "var DOCS=[{key:'a'},{key:'b'}],DEFAULT_DOC='a';",
                *(
                    extract_js_fn(n)
                    for n in ("pdoc", "isFrac", "hasMark", "pinPlace", "timeParts", "orderPins", "listOrderOf")
                ),
                script,
            ]
        )
        return json.loads(run_node(js))

    def test_newest_first_breaks_a_tie_by_number_and_leaves_an_unread_time_last(self):
        """Two pins of one minute: the later one, which has the larger number, first. The list given stays as it was."""
        got = self.ordered("""const L=[{id:1,at:'2026-11-01 09:00:00'},{id:2,at:'2026-11-02 09:00:10'},{id:3,at:'2026-11-02 09:00:50'},{id:4},{id:5,at:'x'},{id:6,at:'2025-01-01 09:00:00'}];
          const ids=l=>l.map(p=>p.id); console.log(JSON.stringify([ids(orderPins(L,LIST_ORDER.NEW)),ids(L)]));""")
        self.assertEqual(got, [[3, 2, 1, 6, 5, 4], [1, 2, 3, 4, 5, 6]])

    def test_by_page_goes_by_page_then_line_and_a_region_by_its_height_after_the_lines(self):
        """The page is where the mark stands now (a figure pin's element can move), a region has no line."""
        got = self.ordered("""const f=[.1,.5,.1,.1]; console.log(JSON.stringify(orderPins([
          {id:1,page:2,lo:30},{id:2,page:1,lo:40},{id:3,page:1,lo:12},{id:4,page:1,frac:[.1,.8,.1,.1]},{id:5,page:1,frac:f},
          {id:6,page:5,lo:1,mark_page:1,mark:[.1,.2,.1,.1]},{id:7,page:1,lo:12},
        ],LIST_ORDER.PAGE).map(p=>p.id)));""")
        self.assertEqual(got, [6, 3, 7, 2, 5, 4, 1])

    def test_by_page_keeps_each_document_together(self):
        """Page numbers mean nothing across documents: all of the first document's pins, then the next's, then unknown ones."""
        got = self.ordered("""console.log(JSON.stringify(orderPins([
          {id:1,doc:'b',page:1,lo:1},{id:2,doc:'gone',page:1,lo:1},{id:3,page:9,lo:1},{id:4,doc:'a',page:2,lo:1},{id:5,doc:'b',page:0,lo:1},
        ],LIST_ORDER.PAGE).map(p=>p.id)));""")
        self.assertEqual(got, [4, 3, 5, 1, 2])

    def test_by_number_is_the_list_as_given(self):
        """Today's order: nothing is sorted, whatever the numbers."""
        self.assertEqual(
            self.ordered("console.log(JSON.stringify(orderPins([{id:3},{id:1},{id:2}],LIST_ORDER.ID).map(p=>p.id)));"),
            [3, 1, 2],
        )

    def test_an_order_does_not_depend_on_the_order_the_server_gives(self):
        """For random pins and every shuffle of them each sorted order is one list holding the same pins (seed printed on failure)."""
        for seed in range(20):
            rnd = random.Random(seed)
            pins = [
                {
                    "id": i,
                    "doc": rnd.choice("ab"),
                    "page": rnd.randint(1, 3),
                    **({"lo": rnd.randint(1, 9)} if rnd.random() < 0.7 else {"frac": [0.1, rnd.random(), 0.1, 0.1]}),
                    **(
                        {"at": "2026-11-0%d 09:%02d:00" % (rnd.randint(1, 3), rnd.randint(0, 59))}
                        if rnd.random() < 0.9
                        else {}
                    ),
                }
                for i in range(1, 13)
            ]
            shuffles = [rnd.sample(pins, len(pins)) for _ in range(5)]
            got = self.ordered(
                "const S=%s; console.log(JSON.stringify([LIST_ORDER.NEW,LIST_ORDER.PAGE].map(o=>S.map(l=>orderPins(l,o).map(p=>p.id)))));"
                % json.dumps(shuffles)
            )
            for runs in got:
                self.assertEqual([runs[0]] * len(shuffles), runs, "seed %d" % seed)
                self.assertEqual(sorted(runs[0]), list(range(1, 13)), "seed %d" % seed)

    def test_a_saved_value_that_names_no_order_is_the_default(self):
        """Newest first until something else is chosen; a stale or foreign value counts as nothing saved."""
        got = self.ordered("console.log(JSON.stringify(['page','id','new',undefined,'x',3].map(listOrderOf)));")
        self.assertEqual(got, ["page", "id", "new", "new", "new", "new"])


class TimelineFixture(BrowserBase):
    """Real pins, threads and permissions, as Alice with Bob known. Holds no test, so the classes built on it share it."""

    WHO = ALICE

    def setUp(self):
        """Give each test its own manuscript, its two people and a fresh line for each pin. The server stamps what the
        test makes (a pin, a reply, an edit, a close) at NOON, the time the page starts at."""
        super().setUp()
        ps.APP.assembly.pins.commands.now_str = ago
        self.next_line = 4
        for person in (ALICE, BOB):
            ps.APP.people_directory.record(actor(person))

    def pin(self, note="문장을 줄여 주세요", author=ALICE, **body):
        """Save a pin on its own lines through the real service; returns its id."""
        line = self.next_line
        self.next_line += 2
        fields = {"file": str(self.main), "lo": line, "hi": line, "page": 1, "note": note}
        return add_pin({**fields, **body}, actor(author)).record["id"]

    def reply(self, pid, text="그렇게 하겠습니다", who=BOB):
        """Add a reply through the real service."""
        ps.APP.pin_lifecycle.reply_pin(
            pid, text, post_authority(ps.APP.pin_lifecycle.context().store, actor(who), "reply", pid)
        )

    def close(self, pid, ref="PR #373", reply="고쳤습니다"):
        """Close the pin as the agent: it waits for review, with a close record in its thread."""
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply=reply, ref=ref)
        )

    def reopen(self, pid, who=ALICE):
        """Reopen the pin as who (Alice): a reopen record in its thread."""
        ps.APP.pin_lifecycle.reopen_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, actor(who), "reopen", pid)
        )

    def edit_note(self, pid, note, who=ALICE):
        """Edit the pin's note as who (Alice) through the real service, against the revision stored now; the stored note."""
        rev = find_record(ps.APP.snapshot_pins(), pid)["rev"]
        return record_of(edit_pin(pid, {"note": note, "base_rev": rev}, actor(who)))["note"]

    def age(self, **ats):
        """Rewrite stored `at` of pins by 'p<id>'=value."""

        def step(rows):
            """The stored records with their times."""
            for r in rows:
                key = "p%d" % r["id"]
                if key in ats:
                    r["at"] = ats[key]

        edit_stored(step)

    def show(self, n_open, device=DESKTOP, theme="light", lang="ko", prefs=None):
        """The list on device at NOON in Seoul with the hints seen and the panel or sheet open; prefs adds to the saved
        preferences."""
        saved = {"theme": theme, "coach": {"touch": 1, "mouse": 1, "sel": 1}, **(prefs or {})}
        # set on the context's first page only: a reload keeps what the page saved meanwhile
        init = "try{if(!localStorage.getItem('pinPrefs'))localStorage.setItem('pinPrefs',%s);}catch(e){}" % json.dumps(
            json.dumps(saved)
        )
        page = self.open(n_open, lang=lang, init=init, clock=NOON, **device)
        page.evaluate("setSide(true)")
        settle(page)
        return page

    def card(self, page, pid):
        """One drawn card, by its pin."""
        return page.locator('#right .pin[data-id="%d"]' % pid)


class CommentCards(TimelineFixture):
    """A card's first comment: a reply's head on its own line, the author out of the card's head."""

    SHAPE = """c => {const R = s => {const e = c.querySelector(s); return e && e.getClientRects().length ? e.getBoundingClientRect() : null;};
      const box = s => {const r = R(s); return r && {top: r.top, bottom: r.bottom, left: r.left};};
      const time = c.querySelector('.note-h .rt');
      return {head: box('.note-h'), note: box('.note'), reply: box('.msg-t'), avatar: box('.cmt>.av'), name: (c.querySelector('.note-h b') || {}).textContent,
        time: time && time.textContent, tip: time && time.dataset.tip, inHead: c.querySelectorAll('.head .au').length, msgs: c.querySelectorAll('.msg').length};}"""

    def test_the_first_comment_has_a_replys_head_over_the_note_on_open_and_review_cards(self):
        """Avatar, name and time on a line of their own above the note, the note on the reply text's edge, no author in the
        card's head - on an open card and on a card awaiting review."""
        opened, closed = self.pin(), self.pin()
        self.reply(opened)
        self.close(closed)
        stamp = ago(hours=14)
        self.age(**{"p%d" % opened: stamp, "p%d" % closed: stamp})
        page = self.show(1)
        for pid in (opened, closed):
            with self.subTest(pid=pid):
                got = self.card(page, pid).evaluate(self.SHAPE)
                self.assertEqual(got["name"], "Alice Kim (나)")
                self.assertTrue(got["time"].startswith("14시간 전 · "), got["time"])
                self.assertEqual(got["tip"], stamp)
                self.assertEqual(got["inHead"], 0)
                self.assertLessEqual(got["head"]["bottom"], got["note"]["top"] + 0.5)
                self.assertEqual(got["note"]["left"], got["reply"]["left"])
                self.assertEqual(got["avatar"]["left"] + 28, got["note"]["left"])

    def test_an_edited_note_says_so_in_its_head(self):
        """After an edit the head says when it was edited, and the hover the whole stored string; an unedited note does not."""
        edited, plain = self.pin(), self.pin()
        self.assertEqual(self.edit_note(edited, "고쳐 쓴 메모"), "고쳐 쓴 메모")
        page = self.show(2)
        row = self.card(page, edited).locator(".note-h .rt[data-form=edited]")
        self.assertRegex(row.inner_text(), r"^수정 %s · \d\d-\d\d \d\d:\d\d$" % JUST)
        self.assertRegex(row.get_attribute("data-tip"), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual(self.card(page, plain).locator(".rt[data-form=edited]").count(), 0)

    def test_a_folded_card_keeps_its_avatar_in_its_head_and_starts_its_preview_with_the_short_time(self):
        """Folded on a compact band there is no comment head: the card's head has the avatar and the preview the time.
        Unfolded the avatar is the comment's again."""
        recent, old = self.pin(note="요즘 메모"), self.pin(note="옛 메모")
        self.age(**{"p%d" % recent: ago(hours=14), "p%d" % old: "2025-09-25 00:01:00"})
        page = self.show(2, TABLET)
        for pid, preview in ((recent, "14시간 전"), (old, "2025-09-25 00:01")):
            with self.subTest(pid=pid):
                card = self.card(page, pid)
                self.assertEqual(card.locator(".sum .rt").inner_text(), preview)
                self.assertTrue(card.locator(".sum").inner_text().startswith(preview))
                self.assertTrue(card.locator(".head .au .av").is_visible())
                self.assertEqual(card.locator(".head .au").get_attribute("aria-label"), "Alice Kim")
                self.assertFalse(card.locator(".note-h").is_visible())
                self.assertFalse(card.locator(".cmt>.av").is_visible())
        page.evaluate("id => {OPEN_CARDS.add(id); drawPins();}", recent)
        card = self.card(page, recent)
        self.assertEqual(card.locator(".head .au").count(), 0)
        self.assertTrue(card.locator(".note-h").is_visible())
        self.assertTrue(card.locator(".cmt>.av").is_visible())

    def test_the_facts_line_of_a_folded_card_stands_on_the_cards_edge(self):
        """The column the comment keeps in an open card takes no room in a folded one: the facts line is where the preview is."""
        pid = self.pin(assignee=BOB["Tailscale-User-Login"])
        page = self.show(1, TABLET)
        got = self.card(page, pid).evaluate(
            "c => [c.querySelector('.sum').getBoundingClientRect().left, c.querySelector('.card-meta').getBoundingClientRect().left]"
        )
        self.assertEqual(got[0], got[1])

    def test_a_pin_with_no_recorded_author_keeps_the_column_and_says_so(self):
        """'기록 전' stands where the name does, with an empty circle as the node, so the note holds its edge; folded it has no avatar."""
        pid = self.pin()
        self.reply(pid)

        def forget(rows):
            """The stored record as one from before authors were recorded."""
            rows[0].pop("author", None)

        edit_stored(forget)
        page = self.show(1)
        got = self.card(page, pid).evaluate(self.SHAPE)
        self.assertEqual(got["name"], "기록 전")
        self.assertEqual(got["avatar"]["left"] + 28, got["note"]["left"])
        phone = self.show(1, PHONE)
        self.assertEqual(self.card(phone, pid).locator(".head .au").count(), 0)

    def test_the_edit_card_keeps_the_comments_head_with_no_thread_and_no_line(self):
        """While the note is edited the head says who wrote it and when, under no line: the thread is not drawn meanwhile."""
        pid = self.pin()
        self.reply(pid)
        page = self.show(1)
        page.evaluate("id => openEdit(id)", pid)
        page.wait_for_selector("#pins .edit .e-note")
        card = self.card(page, pid)
        self.assertEqual(card.locator(".note-h b").text_content(), "Alice Kim (나)")
        self.assertEqual(card.locator(".tl-on").count(), 0)
        self.assertEqual(card.locator(".thread").count(), 0)
        self.assertLess(card.locator(".note-h").bounding_box()["y"], card.locator(".edit").bounding_box()["y"])

    HEADS = """c => {const R = e => e.getBoundingClientRect(), C = R(c), L = document.querySelector('#list');
      return {doc: document.documentElement.scrollWidth - innerWidth, list: L.scrollWidth - L.clientWidth, heads: [...c.querySelectorAll('.tl .msg-h')].map(h => {
        const n = h.querySelector('.nm'), t = h.querySelector('.who .rt'), N = R(n), T = R(t);
        return {name: n.textContent, tip: n.closest('b').dataset.tip, cut: n.scrollWidth > n.clientWidth, shown: N.width,
          time: t.textContent, visible: t.checkVisibility(), inside: T.right <= C.right - 12.5 + 0.5, beside: T.left >= N.right && Math.abs(T.bottom - N.bottom) < 2};})};}"""

    def test_a_long_name_ends_in_an_ellipsis_and_its_time_stays_beside_it(self):
        """A 60-letter name with no space, on the note, a reply, a reopen and with an edit, at 1440, 841, 1024 and 390: no
        band scrolls sideways, each head's name is cut with an ellipsis yet holds its whole text and description, and its
        time is drawn whole beside it inside the card."""
        pid = self.pin(author=LONG)
        self.reply(pid, "답글", who=LONG)
        self.close(pid)
        self.reopen(pid, who=LONG)
        self.assertEqual(self.edit_note(pid, "고친 메모", who=LONG), "고친 메모")
        name = LONG["Tailscale-User-Name"]
        for size, device in FOUR_SIZES.items():
            with self.subTest(size=size):
                page = self.show(1, device)
                page.evaluate("id => {OPEN_CARDS.add(id); THREAD_OPEN.add(id); drawPins();}", pid)
                settle(page)
                got = self.card(page, pid).evaluate(self.HEADS)
                self.assertLessEqual(got["doc"], 0)
                self.assertLessEqual(got["list"], 0)
                heads = got["heads"]
                self.assertEqual([h["name"] for h in heads], [name, name, "로컬/에이전트", name])
                for h in heads:
                    self.assertTrue(h["visible"] and h["inside"] and h["beside"], h)
                    self.assertRegex(h["time"], r"^%s · \d\d-\d\d \d\d:\d\d$" % JUST)
                for h in (heads[0], heads[1], heads[3]):
                    self.assertTrue(h["cut"], h)
                    self.assertGreater(h["shown"], 20, h)
                    self.assertIn(name, h["tip"])

    def test_the_drawn_words_follow_the_clock(self):
        """tickRel moves every comment's words: the head's, a reply's and the preview's, into the absolute form at seven days."""
        pid = self.pin()
        self.reply(pid)
        page = self.show(1, TABLET)
        page.evaluate("id => {OPEN_CARDS.add(id); drawPins();}", pid)
        card = self.card(page, pid)
        self.assertRegex(card.locator(".note-h .rt").inner_text(), r"^%s · " % JUST)
        page.evaluate("() => {const t = Date.now() + 2 * 3600000; Date.now = () => t; tickRel();}")
        self.assertTrue(card.locator(".note-h .rt").inner_text().startswith("2시간 전 · "))
        self.assertTrue(card.locator(".msg .rt").inner_text().startswith("2시간 전 · "))
        self.assertEqual(card.locator(".sum .rt").text_content(), "2시간 전")
        page.evaluate("() => {const t = Date.now() + 8 * 86400000; Date.now = () => t; tickRel();}")
        self.assertRegex(card.locator(".note-h .rt").inner_text(), r"^\d\d-\d\d \d\d:\d\d$")
        self.assertRegex(card.locator(".sum .rt").text_content(), r"^\d\d-\d\d \d\d:\d\d$")


# The stretch of the rail's column one card paints, from under its first node to the last node, as (r, g, b) by device pixel
# row: the card's screenshot is decoded on a canvas, and the column read at the avatar column's middle.
RAIL_PIXELS = """async ([b64, scale, x, y0, y1]) => {const im = await createImageBitmap(new Blob([Uint8Array.from(atob(b64), ch => ch.charCodeAt(0))], {type: 'image/png'}));
  const cv = document.createElement('canvas'); cv.width = im.width; cv.height = im.height; const g = cv.getContext('2d', {willReadFrequently: true}); g.drawImage(im, 0, 0);
  const out = []; for (let v = Math.ceil(y0 * scale); v < Math.floor(y1 * scale); v++) out.push([...g.getImageData(Math.floor(x * scale), v, 1, 1).data].slice(0, 3));
  return out;}"""
# The nodes on one card's rail, top to bottom (each its box in the page), with the card's box, the tokens' colours and the
# boxes the line must not run beside.
RAIL_NODES = """c => {const box = e => {const r = e.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right};};
  const nodes = [...c.querySelectorAll('.cmt>.av,.msg>.av,.msg>.ev-dot')].map(box);
  const probe = document.createElement('div'); probe.style.background = 'var(--border)'; c.append(probe);
  const line = getComputedStyle(probe).backgroundColor; probe.style.background = 'var(--card)'; const card = getComputedStyle(probe).backgroundColor; probe.remove();
  const rgb = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number), reply = c.querySelector('.reply-box');
  return {nodes, card: box(c), line: rgb(line), face: rgb(card), reply: reply && box(reply), last: box([...c.querySelectorAll('.tl .thread>.msg')].pop())};}"""


class TimelineRail(TimelineFixture):
    """The line through a card's comment and thread, read from the pixels: it can be broken only where it is painted."""

    def rail(self, page, pid):
        """RAIL_NODES of pin pid's card in view (a scale factor of 1), with the painted column between each two nodes, past
        the rings they wear, as a list of (r, g, b) per pixel row; and the card's screenshot and the column's x in it."""
        card = self.card(page, pid)
        card.evaluate("c => c.scrollIntoView({block: 'start'})")
        settle(page)
        got = card.evaluate(RAIL_NODES)
        c = got["card"]
        clip = {"x": c["left"], "y": c["top"], "width": c["right"] - c["left"], "height": c["bottom"] - c["top"]}
        shot = base64.b64encode(page.screenshot(clip=clip)).decode()
        x = (got["nodes"][0]["left"] + got["nodes"][0]["right"]) / 2 - c["left"]
        gaps = []
        for upper, lower in zip(got["nodes"], got["nodes"][1:], strict=False):
            # past the rings the nodes wear (3px): the stretch between them is all line
            y0, y1 = upper["bottom"] + 4 - c["top"], lower["top"] - 4 - c["top"]
            gaps.append(page.evaluate(RAIL_PIXELS, [shot, 1, x, y0, y1]))
        got["gaps"] = gaps
        got["shot"], got["x"] = shot, x
        return got

    def assert_unbroken(self, got):
        """Every painted pixel between every two nodes on the rail is the line's colour."""
        self.assertGreaterEqual(len(got["nodes"]), 2)
        for gap in got["gaps"]:
            self.assertGreater(len(gap), 0)
            self.assertEqual({tuple(p) for p in gap}, {tuple(got["line"])})

    def test_the_line_runs_unbroken_through_all_that_can_stand_in_it_in_both_themes(self):
        """[이전 N건 보기], a suggested edit, a verdict-less plain note and a long reply between the nodes, light and dark."""
        folded = self.pin()
        for i in range(5):
            self.reply(folded, "답글 %d" % i)
        long_reply = self.pin()
        self.reply(long_reply, "긴 답글입니다. " * 40)
        self.reply(long_reply, "마지막")
        suggested = self.pin(
            note="", suggest={"base": "Line 8 of the demo manuscript.", "text": "Line eight."}, lo=8, hi=8
        )
        self.reply(suggested)
        for theme in ("light", "dark"):
            page = self.show(3, theme=theme)
            for pid in (folded, long_reply, suggested):
                with self.subTest(theme=theme, pid=pid):
                    self.assert_unbroken(self.rail(page, pid))

    def test_the_line_holds_over_a_pin_with_no_recorded_author_and_a_verdict_pin_without_a_note(self):
        """The empty circle is a node like an avatar; a verdict pin with no note goes straight from its head to its thread."""
        (self.main.parent / "main.limnverdicts.json").write_text(
            json.dumps({"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        unknown, bare = self.pin(), self.pin(note="", verdict="채택")
        self.reply(unknown)
        self.reply(bare)

        def forget(rows):
            """One record from before authors were recorded."""
            for r in rows:
                if r["id"] == unknown:
                    r.pop("author", None)

        edit_stored(forget)
        page = self.show(2)
        self.assertEqual(self.card(page, bare).locator(".note").count(), 0)
        self.assertEqual(self.card(page, bare).locator(".tags .badge-verdict").count(), 1)
        for pid in (unknown, bare):
            with self.subTest(pid=pid):
                self.assert_unbroken(self.rail(page, pid))

    def test_the_line_ends_at_the_last_node_with_the_reply_box_open(self):
        """Under the last node the column is the card's face, beside that entry's text and the reply box; above it is the line."""
        pid = self.pin()
        self.reply(pid, "마지막 답글입니다. " * 30)
        page = self.show(1)
        page.evaluate("id => openReply(id)", pid)
        page.wait_for_selector(".reply-box textarea")
        got = self.rail(page, pid)
        self.assert_unbroken(got)
        node, box, c = got["nodes"][-1], got["reply"], got["card"]
        under = page.evaluate(
            RAIL_PIXELS, [got["shot"], 1, got["x"], node["bottom"] + 4 - c["top"], got["last"]["bottom"] - c["top"]]
        )
        self.assertEqual({tuple(p) for p in under}, {tuple(got["face"])})
        self.assertGreaterEqual(box["top"], got["last"]["bottom"])

    def test_a_card_without_a_thread_has_no_line_and_no_divider(self):
        """No entries, no timeline, also with the reply box open; with entries no divider stands over the thread."""
        lone, threaded = self.pin(), self.pin()
        self.reply(threaded)
        page = self.show(2)
        self.assertEqual(self.card(page, lone).locator(".tl-on").count(), 0)
        page.evaluate("id => openReply(id)", lone)
        page.wait_for_selector(".reply-box textarea")
        self.assertEqual(self.card(page, lone).locator(".tl-on").count(), 0)
        got = self.card(page, threaded).evaluate(
            """c => {const t = c.querySelector('.thread'), s = getComputedStyle(t), l = getComputedStyle(c.querySelector('.cmt'), '::before');
              return [s.borderTopStyle, s.paddingTop, l.content];}"""
        )
        self.assertEqual(got, ["none", "0px", '""'])

    def test_the_timeline_is_a_cards_only(self):
        """An archive row's expanded thread keeps the words and the shape it had: relative time, the record on one line, no line."""
        pid = self.pin()
        self.reply(pid)
        self.close(pid)
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.confirm_pin(pid, post_authority(store, actor(ALICE), "confirm", pid))
        page = self.show(0, prefs={"sec": {"open": True, "review": True, "done": True}})
        page.evaluate("id => {ARC_OPEN.add('t:' + id); drawPins();}", pid)
        settle(page)
        row = page.locator('#done-list .arc-row[data-id="%d"]' % pid)
        self.assertEqual(row.locator(".ev-dot").count(), 0)
        self.assertEqual(row.locator(".rt.ts").count(), 0)
        self.assertEqual(row.locator(".msg.ev .msg-h span").first.inner_text(), "닫음 · PR #373")

    def test_a_state_record_has_a_dot_its_time_beside_the_name_and_its_words_under_them(self):
        """A close and a reopen: a dot and no avatar, name and time on one line, the label on the next, the note under it."""
        pid = self.pin()
        self.close(pid)
        self.reopen(pid)
        page = self.show(1)
        got = self.card(page, pid).evaluate(
            """c => [...c.querySelectorAll('.msg.ev')].map(m => {const R = s => m.querySelector(s).getBoundingClientRect(), n = R('.msg-h b'), t = R('.msg-h .rt'), l = R('.ev-l');
              return {cls: m.className, avatars: m.querySelectorAll('.av').length, sameLine: Math.abs(n.bottom - t.bottom) < 2 && t.left > n.left, below: l.top >= n.bottom - 1,
                label: m.querySelector('.ev-l').textContent, edge: l.left - m.getBoundingClientRect().left};})"""
        )
        self.assertEqual([g["cls"] for g in got], ["msg ev ev-close", "msg ev ev-reopen"])
        self.assertEqual(got[0]["label"], "닫음 · PR #373")
        self.assertEqual(got[1]["label"], "다시 엶")
        for g in got:
            self.assertEqual(g["avatars"], 0)
            self.assertTrue(g["sameLine"])
            self.assertTrue(g["below"])
            self.assertEqual(g["edge"], 28)

    def test_each_kind_of_record_has_the_colour_of_its_meaning_in_both_themes(self):
        """The dots take the state tokens: close green, reopen the warning colour, confirm the review's, assign the primary, and an
        unknown record the muted one."""
        pid = self.pin()
        page = self.show(1)
        for theme in ("light", "dark"):
            page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
            got = page.evaluate(
                """id => {const c = document.querySelector('.pin[data-id="' + id + '"] .tl'), out = {}, token = v => {const e = document.createElement('i'); e.style.color = 'var(' + v + ')'; c.append(e); const w = getComputedStyle(e).color; e.remove(); return w;};
                  for (const [ev, v] of [['close', '--status-closed'], ['reopen', '--status-warning'], ['confirm', '--status-review'], ['assign', '--primary'], ['later', '--muted-foreground']]) {
                    const m = document.createElement('div'); m.className = 'msg ev ev-' + ev; m.innerHTML = '<span class="ev-dot"></span>'; c.append(m);
                    out[ev] = [getComputedStyle(m.firstChild, '::before').backgroundColor, token(v)]; m.remove();}
                  return out;}""",
                pid,
            )
            for ev, (dot, token) in got.items():
                with self.subTest(theme=theme, ev=ev):
                    self.assertEqual(dot, token)


class OrderControl(TimelineFixture):
    """[최신순 | 위치순 | 번호순] over the list: what it does to both sections and what follows the order drawn."""

    ROWS = """box => [...document.querySelector(box).children].map(e => e.matches('.pin') ? Number(e.dataset.id)
      : e.matches('.nt-row') ? 'row' + (e.textContent.match(/#(\\d+)/) || ['', ''])[1] : e.matches('.day-line') ? e.textContent : e.className)"""

    def rows(self, page, box="#pins"):
        """The list's rows top to bottom: a card's pin id, a day line's words."""
        return page.evaluate(self.ROWS, box)

    def three(self):
        """Three pins whose number, age and place on the pages all disagree: (a, b, c) with b newest and c on the first line."""
        a = self.pin(note="가", lo=20, hi=20, page=2)
        b = self.pin(note="나", lo=30, hi=30, page=2)
        c = self.pin(note="다", lo=4, hi=4, page=1)
        self.age(**{"p%d" % a: ago(days=1), "p%d" % b: ago(hours=0), "p%d" % c: "2025-09-25 00:01:00"})
        return a, b, c

    def press(self, page, name):
        """Press the control's word (a radio) by its words."""
        page.get_by_role("radio", name=name, exact=True).click()

    def test_the_list_starts_newest_first_with_a_line_per_day(self):
        """Nothing saved: 최신순 pressed, the newest first, a line over each day's first card."""
        a, b, c = self.three()
        page = self.show(3)
        self.assertEqual(self.rows(page), ["오늘", b, "어제", a, "2025년 9월 25일", c])
        self.assertEqual(page.locator("#list-order button[aria-checked=true]").inner_text(), "최신순")

    def test_by_page_and_by_number_have_no_day_lines(self):
        """위치순 goes by page then line, 번호순 back to the list as the server gives it, neither with a day line."""
        a, b, c = self.three()
        page = self.show(3)
        self.press(page, "위치순")
        self.assertEqual(self.rows(page), [c, a, b])
        self.press(page, "번호순")
        self.assertEqual(self.rows(page), [a, b, c])

    def test_the_review_section_goes_in_the_same_order(self):
        """The order is the list's: awaiting review follows it, with its own day lines newest first."""
        a, b, c = self.three()
        for pid in (a, b, c):
            self.close(pid)
        self.pin()
        page = self.show(1)
        self.assertEqual(self.rows(page, "#review-pins"), ["오늘", b, "어제", a, "2025년 9월 25일", c])
        self.press(page, "위치순")
        self.assertEqual(self.rows(page, "#review-pins"), [c, a, b])

    def test_the_choice_is_remembered_in_this_browser(self):
        """A press is saved in pinPrefs and comes back with the page; a stale saved value is the default."""
        a, b, c = self.three()
        page = self.show(3)
        self.press(page, "위치순")
        self.assertEqual(page.evaluate("JSON.parse(localStorage.getItem('pinPrefs')).order"), "page")
        page.reload()
        page.wait_for_function(booted(3))
        settle(page)
        self.assertEqual(self.rows(page), [c, a, b])
        self.assertEqual(page.locator("#list-order button[aria-checked=true]").inner_text(), "위치순")
        stale = self.show(3, prefs={"order": "sideways"})
        self.assertEqual(stale.locator("#list-order button[aria-checked=true]").inner_text(), "최신순")

    def test_the_order_holds_across_documents_and_with_all_documents_on(self):
        """One choice for every document; with [모든 문서] 위치순 keeps each document together, and the filter still filters."""
        ms, _fig, rv = helpers_figure.viewer_docs(ps.APP, ps.APP.C.src)
        self.addCleanup(lambda: ps.APP.set_docs(None))
        late = add_pin(
            {"file": str(ms.main), "lo": 20, "hi": 20, "page": 2, "note": "본문 둘째 쪽"}, actor(ALICE), doc=ms
        )
        early = add_pin({"page": 1, "frac": [0.1, 0.1, 0.3, 0.1], "note": "리뷰어 첫 쪽"}, actor(ALICE), doc=rv)
        first, second = late.record["id"], early.record["id"]
        page = self.show(2, prefs={"order": "page"})
        self.assertEqual(self.rows(page), [first])
        page.evaluate("k => switchDoc(k)", rv.key)
        page.wait_for_function(
            "id => DOC==='rv' && !!document.querySelector('#pins .pin[data-id=\"' + id + '\"]')", arg=second
        )
        self.assertEqual(self.rows(page), [second])
        self.assertEqual(page.locator("#list-order button[aria-checked=true]").inner_text(), "위치순")
        page.locator("#all-docs").click()
        self.assertEqual(self.rows(page), [first, second])

    def test_the_mention_filter_keeps_its_pins_in_the_order(self):
        """[나를 부른 핀] lists only those pins, in the order chosen, and takes the list back when released."""
        people = [ALICE["Tailscale-User-Login"]]
        older = self.pin(note="@Alice Kim 봐 주세요?", kind_req="question", author=BOB, mentions=people)
        other = self.pin(note="다른 핀")
        newer = self.pin(note="@Alice Kim 이것도요?", kind_req="question", author=BOB, mentions=people)
        self.age(**{"p%d" % older: ago(days=2), "p%d" % other: ago(hours=2), "p%d" % newer: ago(days=1)})
        page = self.show(3)
        page.locator("#mention-filter").click()
        self.assertEqual([r for r in self.rows(page) if isinstance(r, int)], [newer, older])
        page.locator("#mention-filter").click()
        self.assertEqual([r for r in self.rows(page) if isinstance(r, int)], [other, newer, older])

    def test_day_lines_are_worked_out_when_the_list_is_drawn(self):
        """A list left open over midnight says yesterday from its next draw."""
        pid = self.pin()
        page = self.show(1)
        self.assertEqual(self.rows(page), ["오늘", pid])
        page.evaluate("() => {const t = Date.now() + 86400000; Date.now = () => t; drawPins();}")
        self.assertEqual(self.rows(page), ["어제", pid])

    def test_the_control_is_a_labelled_radio_group_the_keyboard_reaches(self):
        """A named radio group of native buttons with aria-checked (issue #438); Tab reaches the chosen word, → chooses the
        next one with the focus on it, and the next Tab leaves the group. The walk itself: test_viewer_segment_keys.py."""
        self.three()
        page = self.show(3)
        group = page.locator("#list-order")
        self.assertEqual(group.get_attribute("role"), "radiogroup")
        self.assertEqual(group.get_attribute("aria-label"), "목록 순서")
        self.assertEqual(
            group.locator("button[role=radio]").evaluate_all("b => b.map(x => x.textContent)"),
            ["최신순", "위치순", "번호순"],
        )
        page.locator("#open-toggle").focus()
        for _ in range(12):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.dataset.order==='new'"):
                break
        self.assertEqual(page.evaluate("document.activeElement.dataset.order"), "new")
        page.keyboard.press("ArrowRight")
        self.assertEqual(group.locator("[aria-checked=true]").inner_text(), "위치순")
        self.assertEqual(page.evaluate("document.activeElement.dataset.order"), "page")
        self.assertEqual(group.locator("[aria-checked=false]").count(), 2)
        page.keyboard.press("Tab")
        self.assertIsNone(page.evaluate("document.activeElement.closest('#list-order')"))

    def test_the_control_shows_while_a_section_it_orders_has_a_card(self):
        """No card in the open or review sections, nothing to order; a collapsed open section keeps the control for the other."""
        pid = self.pin()
        self.close(pid)
        page = self.show(0)
        self.assertTrue(page.locator("#list-order").is_visible())
        page.evaluate("toggleSec('open',false)")
        self.assertTrue(page.locator("#list-order").is_visible())
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.confirm_pin(pid, post_authority(store, actor(ALICE), "confirm", pid))
        page.evaluate("loadPins()")
        page.wait_for_function("!REVIEW_ALL.length")
        self.assertFalse(page.locator("#list-order").is_visible())

    def test_tab_walks_the_cards_in_the_order_drawn_both_ways(self):
        """Tab from the control meets the cards as drawn in each order, and Shift+Tab meets them backwards."""
        a, b, c = self.three()
        page = self.show(3)
        self.press(page, "위치순")
        page.locator("#list-order [data-order=id]").focus()

        def walk(key, want):
            """The cards the focus passes pressing key, in order, until it has met want of them."""
            seen = []
            for _ in range(60):
                page.keyboard.press(key)
                pid = page.evaluate("(document.activeElement.closest('#pins .pin[data-id]')||{dataset:{}}).dataset.id")
                if pid and (not seen or seen[-1] != int(pid)):
                    seen.append(int(pid))
                if len(seen) == want:
                    break
            return seen

        self.assertEqual(walk("Tab", 3), [c, a, b])
        self.assertEqual(walk("Shift+Tab", 2), [a, c])  # from b's first control, back over a to c

    def test_a_delete_by_keyboard_gives_the_focus_to_the_card_drawn_next_past_a_day_line(self):
        """The next card as drawn, over the line between them, not the next by number."""
        a, b, c = self.three()
        page = self.show(3)
        self.assertEqual(self.rows(page), ["오늘", b, "어제", a, "2025년 9월 25일", c])
        self.card(page, a).locator("[data-act=drop]").focus()
        page.keyboard.press("Enter")
        page.wait_for_function("id => document.activeElement.closest('.pin[data-id=\"' + id + '\"]')", arg=c)

    def four(self):
        """three() and a fourth pin, d, from today but older than b: today holds b then d, yesterday a alone, then c."""
        a, b, c = self.three()
        d = self.pin(note="라", lo=24, hi=24, page=2)
        self.age(**{"p%d" % d: ago(hours=1)})
        return a, b, c, d

    def test_an_undo_row_takes_its_cards_place_under_its_day_line(self):
        """Deleting or completing the first card of a day: the row stands under that day's line, where the card was, at 1440
        and 1920 wide; [되돌리기] brings the card back to its place and the row goes."""
        for width, height in ((1440, 900), (1920, 1080)):
            for act in ("drop", "close"):
                with self.subTest(width=width, act=act):
                    self.tearDown()
                    self.setUp()
                    a, b, c, d = self.four()
                    page = self.show(4, {"viewport": {"width": width, "height": height}})
                    full = ["오늘", b, d, "어제", a, "2025년 9월 25일", c]
                    self.assertEqual(self.rows(page), full)
                    line = page.locator("#pins > .day-line").first.bounding_box()["y"]
                    self.card(page, b).locator("[data-act=%s]" % act).click()
                    page.wait_for_selector("#pins > .nt-row")
                    settle(page)
                    self.assertEqual(self.rows(page), ["오늘", "row%d" % b, d, "어제", a, "2025년 9월 25일", c])
                    self.assertEqual(page.locator("#pins > .day-line").first.bounding_box()["y"], line)
                    page.locator("#pins > .nt-row [data-act=notice-act]").click()
                    page.wait_for_function(
                        "id => document.querySelector('#pins > .pin[data-id=\"' + id + '\"]')", arg=b
                    )
                    settle(page)
                    self.assertEqual(self.rows(page), full)

    def test_a_days_only_card_leaves_its_line_with_the_row_until_the_row_goes(self):
        """Yesterday's only card deleted: its line stays over the row (the row belongs to that day), and goes with it when [x]
        takes the row; undone instead, the card comes back under it."""
        a, b, c, d = self.four()
        page = self.show(4)
        self.card(page, a).locator("[data-act=drop]").click()
        page.wait_for_selector("#pins > .nt-row")
        settle(page)
        self.assertEqual(self.rows(page), ["오늘", b, d, "어제", "row%d" % a, "2025년 9월 25일", c])
        page.locator("#pins > .nt-row [data-act=notice-act]").click()
        page.wait_for_function("id => document.querySelector('#pins > .pin[data-id=\"' + id + '\"]')", arg=a)
        settle(page)
        self.assertEqual(self.rows(page), ["오늘", b, d, "어제", a, "2025년 9월 25일", c])
        self.card(page, a).locator("[data-act=drop]").click()
        page.wait_for_selector("#pins > .nt-row")
        page.locator("#pins > .nt-row [data-act=notice-x]").click()
        page.wait_for_function("!document.querySelector('#pins > .nt-row')")
        self.assertEqual(self.rows(page), ["오늘", b, d, "2025년 9월 25일", c])

    UNDO_TOPS = """() => [...document.querySelectorAll('#pins > .nt-row [data-act=notice-act]')].map(b => b.getBoundingClientRect().top)"""

    def test_rows_of_two_deletes_in_a_row_stand_as_the_next_draw_puts_them(self):
        """Today's two cards deleted one after the other, both rows standing: newest first, the rows read as their cards did,
        and a redraw of the list moves neither row nor its [되돌리기] (rows placed when made and slots drawn after agree);
        so for yesterday's only card and the card after it in the page order."""
        a, b, c, d = self.four()
        for order, first, second, want in (
            ("new", b, d, lambda: ["오늘", "row%d" % b, "row%d" % d, "어제", a, "2025년 9월 25일", c]),
            ("page", c, a, lambda: ["row%d" % c, "row%d" % a, d, b]),  # page 1 line 4, then page 2 lines 20, 24, 30
        ):
            with self.subTest(order=order):
                page = self.show(4, prefs={"order": order})
                for pid in (first, second):
                    self.card(page, pid).locator("[data-act=drop]").click()
                    page.wait_for_function(
                        "id => [...document.querySelectorAll('#pins > .nt-row')].some(r => r.textContent.includes('#' + id + ' '))",
                        arg=pid,
                    )
                    settle(page)
                self.assertEqual(self.rows(page), want())
                tops = page.evaluate(self.UNDO_TOPS)
                page.evaluate("drawPins()")
                self.assertEqual(self.rows(page), want())
                self.assertEqual(page.evaluate(self.UNDO_TOPS), tops)
                page.evaluate(
                    "NOTICES.forEach(n => {if (n.place === 'row') endNotice(n, false);})"
                )  # the next subtest's pins
                for pid in (first, second):
                    ps.APP.pin_trash.restore_pin(
                        pid, post_authority(ps.APP.pin_trash.context().store, actor(ALICE), "restore", pid)
                    )

    def test_the_review_sections_row_takes_its_cards_place_too(self):
        """[확인] on the first review card of a day: its row stands under that day's line in the review section."""
        a, b, c, d = self.four()
        for pid in (a, b, c, d):
            self.close(pid)
        self.pin(note="열린 핀")
        page = self.show(1)
        self.card(page, b).locator("[data-act=confirm]").click()
        page.wait_for_selector("#review-pins > .nt-row")
        self.assertEqual(self.rows(page, "#review-pins"), ["오늘", "row%d" % b, d, "어제", a, "2025년 9월 25일", c])

    def test_a_row_left_in_a_cards_place_stands_after_the_card_drawn_before_it(self):
        """[완료]'s undo row goes where the card was in the order drawn, past a day line, and takes the card's place in the walk."""
        a, b, c = self.three()
        page = self.show(3)
        self.card(page, a).locator("[data-act=close]").click()
        page.wait_for_selector("#pins .nt-row")
        got = page.evaluate(
            "() => {const r = document.querySelector('#pins .nt-row'); let p = r.previousElementSibling; while (p && !p.matches('.pin')) p = p.previousElementSibling; return Number(p.dataset.id);}"
        )
        self.assertEqual(got, b)

    def test_a_focus_on_a_card_comes_back_to_it_after_the_order_changes_under_it(self):
        """A redraw in another order leaves the focus on the same control of the same card (cardFocusBack finds it by pin)."""
        a, b, c = self.three()
        page = self.show(3)
        self.card(page, c).locator(".n.go").focus()
        page.evaluate("() => {ORDER = LIST_ORDER.PAGE; drawPins();}")
        self.assertEqual(self.rows(page), [c, a, b])
        self.assertEqual(page.evaluate("document.activeElement.closest('.pin').dataset.id"), str(c))

    def test_jumps_reach_a_card_wherever_the_order_put_it_and_far_cards_are_skipped_as_drawn(self):
        """Forty pins by page: the cards skipped for being far from the view are those far down the drawn list, the first
        drawn is not, and a jump to the last drawn brings it into the list's view."""
        lines = {}
        for i in range(40):
            line = 4 + (i * 7) % 30  # their lines out of step with their numbers
            lines[self.pin(note="메모 %d" % i, lo=line, hi=line)] = line
        page = self.show(40, prefs={"order": "page"})
        drawn = [r for r in self.rows(page) if isinstance(r, int)]
        self.assertEqual(drawn, sorted(lines, key=lambda pid: (lines[pid], pid)))
        far, near = drawn[-1], drawn[0]
        lazy = "id => document.querySelector('#pins .pin[data-id=\"' + id + '\"]').classList.contains('lazy')"
        page.wait_for_function(lazy, arg=far)
        self.assertFalse(page.evaluate(lazy, near))
        page.evaluate("id => jumpToCard(id)", far)
        page.wait_for_function(
            """id => {const r = document.querySelector('#pins .pin[data-id="' + id + '"]').getBoundingClientRect(), L = listScroller().getBoundingClientRect();
              return r.top >= L.top - 1 && r.bottom <= L.bottom + 1;}""",
            arg=far,
        )

    def test_the_control_stays_under_the_pointer_when_the_order_changes(self):
        """Pressing it with the list a little scrolled keeps it where it stood: a card kept in place would carry it away."""
        for i in range(12):
            self.pin(note="메모 %d" % i)
        page = self.show(12)
        page.evaluate("listScroller().scrollTop = 20")
        before = page.locator("#list-order").bounding_box()["y"]
        self.press(page, "위치순")
        self.assertAlmostEqual(page.locator("#list-order").bounding_box()["y"], before, delta=0.5)

    def test_it_fits_at_the_four_sizes_in_either_language_with_touch_targets_of_44px(self):
        """No band scrolls sideways, the track stays in the panel and every segment answers 44px on touch; the cards too."""
        a, b, c = self.three()
        self.reply(a, "답글")
        self.close(b, ref="paper PR #236; code PR #412")
        self.assertEqual(self.edit_note(c, "고친 메모"), "고친 메모")
        for name, device in FOUR_SIZES.items():
            for lang in ("ko", "en"):
                with self.subTest(size=name, lang=lang):
                    page = self.show(2, device, lang=lang)
                    page.evaluate("ids => {ids.forEach(i => OPEN_CARDS.add(i)); drawPins();}", [a, b, c])
                    settle(page)
                    got = page.evaluate(
                        """() => {const L = document.querySelector('#list'), t = document.querySelector('#list-order'), T = t.getBoundingClientRect(), R = L.getBoundingClientRect();
                          const clipped = e => {for (let a = e.parentElement; a && !a.matches('.pin'); a = a.parentElement) if (getComputedStyle(a).overflowX !== 'visible') return true; return false;};
                          const overflow = [...document.querySelectorAll('#list .pin')].flatMap(c => {const C = c.getBoundingClientRect();
                            return [...c.querySelectorAll('*')].filter(e => e.getClientRects().length && !clipped(e) && e.getBoundingClientRect().right > C.right + 0.5).map(e => c.dataset.id + ' ' + e.className);});
                          const bs = [...t.querySelectorAll('button')].map(b => {const r = b.getBoundingClientRect(), mid = r.left + r.width / 2, y = r.top + r.height / 2;
                            const at = d => document.elementFromPoint(mid, y + d), hit = d => at(d) === b; return {right: r.right, h: r.height, up: hit(-21), down: hit(21), over: String((at(-21) || {}).className || (at(-21) || {}).id)};});
                          return {doc: document.documentElement.scrollWidth - innerWidth, list: L.scrollWidth - L.clientWidth, track: [T.left - R.left, R.right - T.right], last: Math.max(...bs.map(b => b.right)) - T.right, bs, overflow};}"""
                    )
                    self.assertLessEqual(got["doc"], 0)
                    self.assertLessEqual(got["list"], 0)
                    self.assertGreaterEqual(min(got["track"]), 0)
                    self.assertLessEqual(got["last"], 0)
                    self.assertEqual(got["overflow"], [])
                    if device.get("has_touch"):
                        for b in got["bs"]:
                            self.assertTrue(b["up"] and b["down"], b)

    def test_a_person_named_like_a_ui_word_is_named_as_written_in_english(self):
        """A person named '완료' ('Done'): in English the first comment's, a reply's and a reopen's heads show '완료' and their
        descriptions say '완료', and a close whose reference is '완료' reads 'Closed · 완료' - user text is not translated."""
        done = {"Tailscale-User-Login": "done@example.com", "Tailscale-User-Name": "완료"}
        pid = self.pin(author=done)
        self.reply(pid, "답글", who=done)
        self.close(pid, ref="완료")
        self.reopen(pid, who=done)
        page = self.show(1, lang="en")
        page.evaluate("id => {THREAD_OPEN.add(id); drawPins();}", pid)
        settle(page)
        got = self.card(page, pid).evaluate(
            """c => ({heads: [...c.querySelectorAll('.tl .msg-h .who b')].map(b => [b.querySelector('.nm').textContent, b.dataset.tip]),
              label: c.querySelector('.msg.ev-close .ev-l').textContent})"""
        )
        self.assertEqual([h[0] for h in got["heads"]], ["완료", "완료", "Local/agent", "완료"])
        for name, tip in got["heads"]:
            if name == "완료":
                self.assertIn("완료", tip)
                self.assertNotIn("Done", tip)
        self.assertEqual(got["label"], "Closed · 완료")

    def test_nothing_of_it_is_left_in_korean_in_english(self):
        """The control, the day lines and the comment heads through the message table."""
        a, b, c = self.three()
        self.reply(a, "reply")
        page = self.show(3, lang="en")
        self.assertEqual(
            page.locator("#list-order button").evaluate_all("b => b.map(x => x.textContent)"),
            ["Newest", "Position", "Number"],
        )
        self.assertEqual(page.locator("#list-order").get_attribute("aria-label"), "List order")
        self.assertEqual(
            page.locator("#pins .day-line").evaluate_all("l => l.map(x => x.textContent)"),
            ["Today", "Yesterday", "Sep 25, 2025"],
        )
        self.assertRegex(self.card(page, a).locator(".note-h .rt").inner_text(), r"^1 day ago · \d\d-\d\d \d\d:\d\d$")
        self.assertIsNone(page.evaluate("document.querySelector('#list-order').textContent.match(/[가-힣]/)"))


if __name__ == "__main__":
    unittest.main()
