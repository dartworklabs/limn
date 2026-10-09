"""Native cards say a pin's kind, assignee and status without growing for the default (docs/handbook/viewer.md
§모바일 레이아웃 핀 카드는 아코디언이다, §담당).

A fix request, for the agent, open is the default: its card draws no facts line and is as tall as it was before the
line existed, and its three facts are still read out. What differs - a question, a colleague or me or nobody as the
assignee, being worked on, awaiting review, reopened, location lost - is drawn on one quiet line under the preview or
the note. The pressable assignee answers 44px without padding the line, and the folded card's rows share their edges
and centre lines on every layout band.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_card_context.py
"""

import base64
import json
import os
import re
import time
from urllib.parse import urlparse

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, find_record, ps
from helpers_access import ALICE, BOB, CAROL, actor
from helpers_authority import post_authority
from helpers_browser import (
    FALLBACK_FONTS,
    MEASURE,
    MISSES_24,
    MISSES_44,
    ROW_INK,
    VIEWPORTS,
    BrowserBase,
    drawn_faces,
    fonts_ready,
    hangul_ink_holds,
    off_centre,
    settle,
)

PHONE = {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True}
TABLET = {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True}
DESKTOP = {"viewport": {"width": 1400, "height": 850}}
# What a card's facts line draws and says: `shown` (the line takes room), `words` (its drawn text), `all` (its whole
# text, the screen-reader-only defaults included) and `height` (0 when it takes no room).
FACTS = r"""card => {const m = card.querySelector('.card-meta'), r = m.getBoundingClientRect();
  const shown = r.height > 1 && getComputedStyle(m).position !== 'absolute';
  const drawn = [...m.children].filter(e => !e.classList.contains('sr-only') && e.getClientRects().length);
  return {shown, words: shown ? drawn.map(e => e.innerText).join('').replace(/\s+/g, ' ').trim() : '',
    all: m.textContent.replace(/\s+/g, ' ').trim(), height: shown ? r.height : 0};}"""


# The WCAG contrast ratio of an element's text colour against what it is painted over (its own and its ancestors' backgrounds
# composited from the page's white up).
CONTRAST = """e => {const cv = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  const rgb = v => {cv.clearRect(0, 0, 1, 1); cv.fillStyle = '#000'; cv.fillStyle = v; cv.fillRect(0, 0, 1, 1); return [...cv.getImageData(0, 0, 1, 1).data];};
  const over = (fg, bg) => {const a = fg[3] / 255; return [0, 1, 2].map(i => fg[i] * a + bg[i] * (1 - a));};
  const lum = c => {const f = v => {v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;}; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);};
  let bg = [255, 255, 255]; const chain = []; for (let x = e; x; x = x.parentElement) chain.unshift(x);
  for (const x of chain) {const b = rgb(getComputedStyle(x).backgroundColor); if (b[3]) bg = over(b, bg);}
  const L1 = lum(over(rgb(getComputedStyle(e).color), bg)), L2 = lum(bg); return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);}"""


class CardFixture(BrowserBase):
    """Native assembled cards against real pin storage and server permissions, as Alice with Bob and Carol known. Holds
    no test, so the classes built on it share its fixtures without running one another's tests."""

    WHO = ALICE

    def setUp(self):
        """Give each test its own manuscript, participants, stored pins, and browser contexts."""
        super().setUp()
        self.next_line = 4
        for person in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(person))

    def seed_pin(self, assignee="agent", kind="fix", author=ALICE):
        """Create a real pin with a distinct source range and return its assigned identifier."""
        line = self.next_line
        self.next_line += 3
        return add_pin(
            {
                "file": str(self.main),
                "lo": line,
                "hi": line + 1,
                "page": 1,
                "note": "First request line\nSecond request line",
                "kind_req": kind,
                "assignee": assignee,
            },
            actor(author),
        ).record["id"]

    def show_cards(self, n_open, device=DESKTOP, theme="light"):
        """Open the native list and its panel, waiting for requests, layout, and fonts to settle."""
        page = self.open(
            n_open,
            init="localStorage.setItem('pinPrefs', JSON.stringify({theme:%s}));" % json.dumps(theme),
            **device,
        )
        page.evaluate("setSide(true)")
        settle(page)
        return page

    def card(self, page, pid):
        """Select one rendered card by its persisted identifier, excluding overlay copies."""
        return page.locator('#right .pin[data-id="%d"]' % pid)

    def facts(self, page, pid):
        """FACTS of the card of pin pid."""
        return self.card(page, pid).evaluate(FACTS)


class CardContextBrowser(CardFixture):
    """Exercise native assembled cards against real pin storage and server permissions."""

    def test_compact_card_keeps_one_assignee_after_preview_and_expanded_note(self):
        """Folded, a colleague's open question draws its kind and assignee under the preview; unfolded, the question
        badge says the kind and the line keeps the assignee alone, under the note."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"], "question")
        ps.APP.pin_lifecycle.reply_pin(
            pid, "One reply", post_authority(ps.APP.pin_lifecycle.context().store, actor(ALICE), "reply", pid)
        )
        for device in (PHONE, TABLET):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.show_cards(1, device)
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                row = card.locator(".card-meta")
                self.assertEqual(self.facts(page, pid)["words"], "질문 · 담당 Bob Park")
                self.assertEqual(card.locator(".head .as-chip").count(), 0)
                self.assertEqual(card.locator(".as-chip").count(), 1)
                self.assertEqual(card.locator(".head .th-n").inner_text(), "1")
                self.assertEqual(card.locator(".head .au").count(), 1)
                self.assertFalse(card.locator(".badge-question").is_visible())
                self.assertGreaterEqual(row.bounding_box()["y"], card.locator(".sum").bounding_box()["y"])

                card.locator(".b-fold").click()
                settle(page)
                self.assertTrue(card.locator(".badge-question").is_visible())
                self.assertEqual(self.facts(page, pid)["words"], "담당 Bob Park")
                self.assertEqual(card.locator(".as-chip").count(), 1)
                note = card.locator(".note").bounding_box()
                self.assertGreaterEqual(row.bounding_box()["y"], note["y"] + note["height"])

    def test_metadata_is_plain_regular_12px_with_a_shared_text_baseline(self):
        """Recipient and context share regular 12px ink without the old colored pill in either theme, drawn in the
        muted colour - the card's quietest text, under the note it follows (in the card's foreground it was darker
        than the request) - at AA contrast for small text (4.5:1) against the card in light and dark."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"], "question")
        for device, theme in ((DESKTOP, "light"), (DESKTOP, "dark"), (TABLET, "light"), (PHONE, "light")):
            with self.subTest(width=device["viewport"]["width"], theme=theme):
                page = self.show_cards(1, device, theme)
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                ink = card.locator(".card-meta").evaluate(
                    """row => {
                      const texts=[], walker=document.createTreeWalker(row,NodeFilter.SHOW_TEXT);
                      let node;
                      while ((node=walker.nextNode())) {
                        if (!node.textContent.trim() || node.parentElement.closest('.sr-only')) continue;
                        const range=document.createRange(); range.selectNodeContents(node);
                        const rect=range.getBoundingClientRect();
                        if (!rect.width || !rect.height) continue;
                        const style=getComputedStyle(node.parentElement);
                        texts.push({text:node.textContent.trim(), bottom:rect.bottom,
                          size:style.fontSize, weight:style.fontWeight, color:style.color});
                      }
                      const recipient=row.querySelector('.as-chip'), style=getComputedStyle(recipient);
                      const probe=document.createElement('span'); probe.style.color='var(--muted-foreground)'; row.append(probe);
                      const muted=getComputedStyle(probe).color; probe.remove();
                      return {texts, muted, background:style.backgroundColor, border:style.borderTopWidth,
                        shadow:style.boxShadow, contrast:CONTRAST(row)};
                    }""".replace("CONTRAST(row)", "(%s)(row)" % CONTRAST)
                )
                self.assertGreaterEqual(len(ink["texts"]), 2, ink)
                self.assertEqual({item["size"] for item in ink["texts"]}, {"12px"})
                self.assertEqual({item["weight"] for item in ink["texts"]}, {"400"})
                self.assertEqual({item["color"] for item in ink["texts"]}, {ink["muted"]})
                self.assertGreaterEqual(ink["contrast"], 4.5, ink)
                bottoms = [item["bottom"] for item in ink["texts"]]
                self.assertLessEqual(max(bottoms) - min(bottoms), 1, ink)
                self.assertEqual(ink["background"], "rgba(0, 0, 0, 0)")
                self.assertEqual(ink["border"], "0px")
                self.assertEqual(ink["shadow"], "none")

    def test_own_human_assignee_opens_native_editor_and_saves_assignment(self):
        """Under a mouse, pressing the human recipient opens the author's native edit; while it is open the recipient
        is plain text (the control is in the edit card), and handing the pin to the agent takes the line away."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        page = self.show_cards(1, DESKTOP)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        recipient = card.locator(".card-meta button.as-chip")
        self.assertTrue(recipient.is_visible())
        recipient.click()
        settle(page)
        self.assertEqual(card.locator(".e-note").input_value(), "First request line\nSecond request line")
        self.assertEqual(card.locator(".card-meta").count(), 1)
        self.assertEqual(self.facts(page, pid)["words"], "담당 Bob Park")
        self.assertEqual(card.locator(".card-meta button").count(), 0)
        self.assertEqual(card.locator(".head .as-chip").count(), 0)
        self.assertEqual(card.locator('.e-assign [data-v="bob@example.com"]').get_attribute("aria-checked"), "true")
        card.locator('.e-assign [data-v="agent"]').click()
        card.locator('[data-act="esave"]').click()
        settle(page)
        self.assertEqual(card.locator(".e-note").count(), 0)
        facts = self.facts(page, pid)
        self.assertEqual((facts["shown"], facts["all"]), (False, "수정 요청 담당 에이전트 열림"))
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["assignee"], "agent")

    def test_on_touch_the_recipient_is_text_and_a_tap_on_the_preview_only_unfolds(self):
        """A phone and a tablet, my own pin handed to Bob: folded and unfolded the recipient is text on its 18px line,
        never a button - its 44px hit lay over the lower half of the preview line, where a tap opened the editor and
        raised the keyboard. A real tap on the recipient's words, and one low on the preview line, each unfold the card
        and edit nothing; the recipient is changed through [수정]. The head's link and fold button and the action
        buttons keep their 44px."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        for device in (PHONE, TABLET):
            with self.subTest(width=device["viewport"]["width"]):
                page = self.show_cards(1, device)
                card = self.card(page, pid)
                box = '#right .pin[data-id="%d"]' % pid
                card.evaluate("card => card.scrollIntoView({block: 'center'})")
                settle(page)
                self.assertEqual(card.locator(".card-meta button").count(), 0)
                self.assertEqual(self.facts(page, pid), dict(self.facts(page, pid), words="담당 Bob Park", height=18))
                words = card.locator(".card-meta .as-chip").bounding_box()
                line = card.locator(".sum").bounding_box()
                on_the_words = (words["x"] + words["width"] / 2, words["y"] + words["height"] / 2)
                low_on_the_preview = (line["x"] + line["width"] - 40, line["y"] + line["height"] - 4)
                for point in (on_the_words, low_on_the_preview):
                    page.touchscreen.tap(*point)
                    settle(page)
                    state = page.evaluate("id => ({editing: !!EDITOR.current, open: OPEN_CARDS.has(id)})", pid)
                    self.assertEqual(state, {"editing": False, "open": True}, point)
                    self.assertEqual(card.locator(".e-note").count(), 0)
                    if point is on_the_words:
                        card.locator(".b-fold").tap()  # fold it again for the second tap
                        settle(page)
                        self.assertFalse(page.evaluate("id => OPEN_CARDS.has(id)", pid))
                        time.sleep(0.5)  # the finger's pause before its next tap, past the double-tap window
                self.assertEqual(card.locator(".card-meta button").count(), 0)
                facts = self.facts(page, pid)
                self.assertEqual((facts["words"], facts["height"]), ("담당 Bob Park", 18))
                card.evaluate("card => card.scrollIntoView({block: 'center'})")
                settle(page)
                self.assertEqual(
                    page.evaluate(MISSES_44, "%s .acts button,%s .go-all,%s .b-fold" % (box, box, box)), []
                )
                card.locator("button.b-edit").tap()
                settle(page)
                self.assertEqual(
                    card.locator('.e-assign [data-v="bob@example.com"]').get_attribute("aria-checked"), "true"
                )

    def test_a_recipient_that_can_be_pressed_does_not_look_like_one_that_only_reads(self):
        """Under a mouse my own open pin's recipient is a button that ends in a pencil and answers 24px; a pin of
        Bob's shows the same words as text with no pencil. The two used to be drawn alike."""
        mine = self.seed_pin(BOB["Tailscale-User-Login"])
        other = self.seed_pin(BOB["Tailscale-User-Login"], author=BOB)
        page = self.show_cards(2, DESKTOP)
        pressable = self.card(page, mine).locator(".card-meta .as-chip")
        reading = self.card(page, other).locator(".card-meta .as-chip")
        tags = [chip.evaluate("e => e.tagName") for chip in (pressable, reading)]
        self.assertEqual(tags, ["BUTTON", "SPAN"])
        self.assertEqual((pressable.locator("svg").count(), reading.locator("svg").count()), (1, 0))
        self.assertTrue(pressable.locator("svg").is_visible())
        self.assertEqual([chip.text_content() for chip in (pressable, reading)], ["담당 Bob Park", "담당 Bob Park"])
        self.card(page, mine).evaluate("card => card.scrollIntoView({block: 'center'})")
        settle(page)
        self.assertEqual(page.evaluate(MISSES_24, '#right .pin[data-id="%d"] .card-meta button.as-chip' % mine), [])

    def test_other_author_review_and_agent_recipients_have_no_edit_button(self):
        """Read-only recipients stay visible while expanded question, claim, and review badges retain meaning."""
        other = self.seed_pin(BOB["Tailscale-User-Login"], author=BOB)
        review = self.seed_pin(BOB["Tailscale-User-Login"], "question")
        claimed = self.seed_pin("agent", "question")
        lost = self.seed_pin("agent")
        reopened = self.seed_pin("agent")
        ps.APP.pin_lifecycle.close_pin(
            review,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", review),
            CloseRequest(reply="Ready for review"),
        )
        ps.APP.pin_claims.claim_pin(
            claimed, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", claimed), 30
        )
        store = ps.APP.pin_lifecycle.context().store
        ps.APP.pin_lifecycle.close_pin(
            reopened, post_authority(store, dict(LOCAL_ACTOR), "close", reopened), CloseRequest(reply="Ready")
        )
        ps.APP.pin_lifecycle.reopen_pin(reopened, post_authority(store, actor(ALICE), "reopen", reopened))
        before = self.main.stat()
        lines = self.main.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[12:14] = ["Removed first anchor.\n", "Removed last anchor.\n"]
        self.main.write_text("".join(lines), encoding="utf-8")
        os.utime(self.main, (before.st_atime, before.st_mtime + 1))
        page = self.show_cards(4, PHONE)
        page.evaluate("toggleSec('review', true)")
        settle(page)
        for pid, folded, unfolded in (
            (other, "담당 Bob Park", "담당 Bob Park"),
            (review, "질문 · 담당 Bob Park · 검토 대기", "담당 Bob Park"),
            (claimed, "질문 · 처리 중", ""),
            (lost, "위치 잃음", ""),
            (reopened, "다시 열림", ""),
        ):
            with self.subTest(pid=pid):
                card = self.card(page, pid)
                self.assertEqual(card.locator(".card-meta").count(), 1)
                row = card.locator(".card-meta")
                self.assertEqual(self.facts(page, pid)["words"], folded)
                self.assertEqual(row.locator("button,[role=button],[data-act=edit]").count(), 0)
                card.locator(".b-fold").click()
                settle(page)
                self.assertEqual(self.facts(page, pid)["words"], unfolded)
                if pid == review:
                    self.assertTrue(card.locator(".badge-review").is_visible())
                    self.assertTrue(card.locator(".badge-question").is_visible())
                if pid == claimed:
                    self.assertTrue(card.locator(".badge-claimed").is_visible())
                    self.assertTrue(card.locator(".badge-question").is_visible())
                    self.assertIn("담당 에이전트", self.facts(page, pid)["all"])
                if pid == lost:
                    self.assertTrue(card.locator(".badge-warning").filter(has_text="위치 잃음").is_visible())
                if pid == reopened:
                    self.assertTrue(card.locator(".badge-reopen").is_visible())

    def test_viewer_owns_pin_but_sees_plain_recipient_without_edit_authority(self):
        """A viewer can read their own recipient without a hidden edit button erasing the label."""
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        ps.APP.C.people_file.write_text(
            json.dumps({"version": 1, "people": [dict(actor(ALICE), role="viewer"), actor(BOB), actor(CAROL)]}),
            encoding="utf-8",
        )
        page = self.show_cards(1)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        row = card.locator(".card-meta")
        self.assertTrue(row.is_visible())
        self.assertEqual(self.facts(page, pid)["words"], "담당 Bob Park")
        self.assertEqual(row.locator("button,[role=button],[data-act=edit]").count(), 0)

    def test_long_untrusted_name_stays_text_and_separate_from_author_and_reply_count(self):
        """Untrusted recipient names neither execute markup nor crowd the author's independent header."""
        name = '<img src=x onerror="window.nameAttack=true"> & ' + "LongRecipient" * 16
        ps.APP.C.people_file.write_text(
            json.dumps(
                {"version": 1, "people": [actor(ALICE), {"login": "bob@example.com", "name": name}, actor(CAROL)]}
            ),
            encoding="utf-8",
        )
        pid = self.seed_pin(BOB["Tailscale-User-Login"])
        ps.APP.pin_lifecycle.reply_pin(
            pid, "One reply", post_authority(ps.APP.pin_lifecycle.context().store, actor(ALICE), "reply", pid)
        )
        page = self.show_cards(1)
        card = self.card(page, pid)
        self.assertEqual(card.locator(".card-meta").count(), 1)
        recipient = card.locator(".card-meta .as-n")
        self.assertEqual(recipient.text_content(), name)
        self.assertEqual(recipient.get_attribute("translate"), "no")
        self.assertEqual(card.locator(".card-meta img, .card-meta script").count(), 0)
        self.assertFalse(page.evaluate("Boolean(window.nameAttack)"))
        self.assertIn("Alice Kim", card.locator(".head .au").inner_text())
        self.assertEqual(card.locator(".head .th-n").inner_text(), "1")
        bounds = card.bounding_box()
        recipient_bounds = recipient.bounding_box()
        self.assertLessEqual(recipient_bounds["x"] + recipient_bounds["width"], bounds["x"] + bounds["width"])


FOLD_STATES = ("open", "claimed", "review", "reopened")
STATE_WORD = {"open": "열림", "claimed": "처리 중", "review": "검토 대기", "reopened": "다시 열림"}
KIND_WORD = {"fix": "수정 요청", "question": "질문"}
# Whom a card names as the assignee to Alice: the stored value (None for a record without one) and the words shown.
ASSIGNEES = (("agent", "에이전트"), ("alice@example.com", "나"), ("bob@example.com", "Bob Park"), (None, "미지정"))
COMPACT = {name: device for name, device in VIEWPORTS.items() if device.get("has_touch")}
PHONE_390, PHONE_320 = VIEWPORTS["phone 390x844"], VIEWPORTS["phone 320x720"]
# A mouse window in a mid band: the compact (folding) card under a fine pointer.
MOUSE_MID = {"viewport": {"width": 1000, "height": 800}, "device_scale_factor": 2}
# A folded touch card's heights (CSS px): the default card with a one- and a two-line preview - v0.4.20's 73.5 and 93, on
# whole pixels - and a card with a facts line, which gives it the preview's second line.
DEFAULT_1, DEFAULT_2, WITH_FACTS = 73, 92, 91
# v0.4.20's folded touch card, by the lines its note's preview fills, and what each kind of card is against it now:
# (whether it draws a facts line, those lines) -> the difference. The default card is v0.4.20's on whole pixels; a card
# with facts and a short note is the one that grew (the line's 18px, less the half pixel), and with a longer note it is
# 2px shorter, the line standing where the preview's second line was.
V0420_FOLDED = {1: 73.5, 2: 93}
AGAINST_V0420 = {(False, 1): -0.5, (False, 2): -1, (True, 1): 17.5, (True, 2): -2}
# One card as drawn (CSS px): its box and content box, the head row, the preview and the facts line, what is wider than its
# box, and - for the ink measure - the boxes of the head's dot, link words, reply icon and count and fold chevron and of
# every drawn text run of the facts line (each read by its own range).
CARD_ROWS = r"""id => {const c = document.querySelector('#right .pin[data-id="' + id + '"]'), q = s => c.querySelector(s);
  const R = e => {const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];};
  const text = n => {const g = document.createRange(); g.selectNodeContents(n); return R(g);};
  const first = e => {const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let n; while ((n = w.nextNode())) if (n.nodeValue.trim()) return n; return e;};
  const cs = getComputedStyle(c), C = R(c), pad = k => parseFloat(cs['padding' + k]) + parseFloat(cs['border' + k + 'Width']);
  const meta = q('.card-meta'), head = q('.head'), th = q('.head .th-n'), wide = e => e.scrollWidth - e.clientWidth, ink = [];
  const drawn = e => e.getClientRects().length > 0 && !e.closest('.sr-only');
  ink.push({k: 'head:dot', box: R(q('.st-dot')), ix: 0}, {k: 'head:link', box: text(first(q('.go-all'))), ix: 0});
  if (th) ink.push({k: 'head:reply-icon', box: R(th.querySelector('svg')), ix: 0}, {k: 'head:reply-count', box: text(first(th)), ix: 0});
  ink.push({k: 'head:fold', box: R(q('.b-fold svg')), ix: 0});
  const walk = document.createTreeWalker(meta, NodeFilter.SHOW_TEXT); let n, i = 0;
  while ((n = walk.nextNode())) {const b = text(n), word = n.nodeValue.replace(/[·\s]+/g, ' ').trim();
    if (word && b[2] - b[0] > 0 && drawn(n.parentElement)) ink.push({k: 'meta' + (i++) + ':' + word, box: b, ix: 0});}
  const name = q('.card-meta .as-n'), sum = q('.sum'), parts = [...meta.children].filter(drawn);
  return {card: C, content: [C[0] + pad('Left'), C[1] + pad('Top'), C[2] - pad('Right'), C[3] - pad('Bottom')], head: R(head),
    dot: R(q('.st-dot')), fold: R(q('.b-fold')), sum: sum.getClientRects().length ? R(sum) : null, meta: R(meta),
    metaStyle: {padding: getComputedStyle(meta).padding, marginTop: getComputedStyle(meta).marginTop},
    lines: parts.map(e => R(e)), previewLines: sum.getClientRects().length ? Math.round(R(sum)[3] - R(sum)[1]) / 19 : 0,
    headWraps: new Set([...head.children].filter(e => e.getClientRects().length).map(e => Math.round(R(e)[1] + (R(e)[3] - R(e)[1]) / 2))).size,
    name: name && {cut: name.scrollWidth > name.clientWidth + 1, ellipsis: getComputedStyle(name).textOverflow, right: R(name)[2]},
    overflow: {card: wide(c), panel: wide(document.querySelector('#right')), page: wide(document.documentElement)},
    ink};}"""
# One card's words against the ink reference (MEASURE's label(), docs/handbook/viewer.md §글자 가운데): the head's - the folded
# link and reply count, or with a mouse #N, the line range, N쪽 and the author's name - against the head row, and every drawn
# word of the facts line against the line; how far the centres of the head's dot, reply icon, fold chevron and avatar lie under
# the row's; and, for each name a box clips for its ellipsis, how far its ink reaches over and under that box (positive = cut).
CARD_LABELS = r"""id => {const c = document.querySelector('#right .pin[data-id="' + id + '"]'), head = c.querySelector('.head'), meta = c.querySelector('.card-meta');
  const drawn = e => e.getClientRects().length > 0 && !e.closest('.sr-only'), mid = e => {const r = e.getBoundingClientRect(); return r.top + r.height / 2;};
  const own = e => [...e.childNodes].some(n => n.nodeType === 3 && n.nodeValue.trim());
  const read = (row, box) => e => Object.assign(__m.label(e, box), {row, el: e.className});
  const words = [...head.querySelectorAll('.go-all .lbl, .th-n .lbl, :scope > .n.go, :scope > .loc, :scope > .pg-link, .au-n')].filter(drawn).map(read('head', head));
  const facts = [...meta.querySelectorAll('*')].filter(e => drawn(e) && own(e)).map(read('facts', meta));
  const icons = Object.fromEntries([['dot', '.st-dot'], ['reply', '.th-n svg'], ['fold', '.b-fold svg'], ['avatar', '.au .av']]
    .map(([k, s]) => [k, head.querySelector(s)]).filter(([, e]) => e && drawn(e)).map(([k, e]) => [k, mid(e) - mid(head)]));
  const clips = [...c.querySelectorAll('.card-meta .as-n, .head .au-n')].filter(drawn).map(e => {const lb = __m.label(e), m = inkMetrics(e, e.textContent), R = e.getBoundingClientRect();
    return {el: e.className, text: e.textContent, over: R.top - (lb.baseline - m.a), under: lb.baseline + m.d - R.bottom};});
  return {labels: words.concat(facts), icons, clips};}"""


def drawn_words(kind, who, state):
    """What a folded card draws for a pin: only what differs from a fix request, for the agent, open."""
    parts = ["질문"] if kind == "question" else []
    parts += [] if who == "에이전트" else ["담당 " + who]
    parts += [] if state == "open" else [STATE_WORD[state]]
    return " · ".join(parts)


class FoldedCardBase(CardFixture):
    """Cards in every state a folded card must tell apart, seeded through the real pin services."""

    def seed_state(self, assignee, kind, state, author=None, note="문장을 줄여 주세요"):
        """A pin by author (Bob when Alice is the assignee, else Alice) taken to state: claimed by the agent, closed by
        the agent (awaiting review), or closed and reopened by Alice. assignee None stores no assignee (a legacy or API
        record). Returns its id."""
        who = author or (BOB if assignee == ALICE["Tailscale-User-Login"] else ALICE)
        body = {"file": str(self.main), "lo": 4 + self.next_line % 30, "hi": 4 + self.next_line % 30, "page": 1}
        body.update(note=note, kind_req=kind)
        if assignee is not None:
            body["assignee"] = assignee
        self.next_line += 1
        pid = add_pin(body, actor(who)).record["id"]
        store = ps.APP.pin_lifecycle.context().store
        if state == "claimed":
            ps.APP.pin_claims.claim_pin(
                pid, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid), 30
            )
        if state in ("review", "reopened"):
            ps.APP.pin_lifecycle.close_pin(
                pid, post_authority(store, dict(LOCAL_ACTOR), "close", pid), CloseRequest(reply="고침")
            )
        if state == "reopened":
            ps.APP.pin_lifecycle.reopen_pin(pid, post_authority(store, actor(ALICE), "reopen", pid))
        return pid

    def show(self, n_open, device, theme="light", font=None):
        """The list on device with the hints seen, the panel or sheet open and the review section unfolded; font
        replaces the interface font stack."""
        prefs = {"theme": theme, "coach": {"touch": 1, "mouse": 1, "sel": 1}, "sec": {"open": True, "review": True}}
        init = "try{localStorage.setItem('pinPrefs',%s);}catch(e){}" % json.dumps(json.dumps(prefs))
        if font:
            init += (
                "document.addEventListener('DOMContentLoaded',()=>"
                "document.documentElement.style.setProperty('--font-sans',%s));" % json.dumps(font)
            )
        page = self.open(n_open, init=init, **device)
        page.evaluate("setSide(true)")
        settle(page)
        return page

    def rows(self, page, pid, device):
        """CARD_ROWS for pin pid, scrolled into view, with each ink item's measured centre (CSS px) from a screenshot."""
        self.card(page, pid).evaluate("card => card.scrollIntoView({block: 'center'})")
        settle(page)
        self.assertEqual(fonts_ready(page), "loaded")
        got = page.evaluate(CARD_ROWS, pid)
        x0, y0, x1, y1 = got["card"]
        shot = base64.b64encode(page.screenshot(clip={"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})).decode()
        items = [
            dict(i, box=[i["box"][0] - x0, i["box"][1] - y0, i["box"][2] - x0, i["box"][3] - y0]) for i in got["ink"]
        ]
        ink = page.evaluate(ROW_INK, [shot, device["device_scale_factor"], items])
        got["mid"] = {key: None if value is None else round(value["mid"] + y0, 2) for key, value in ink.items()}
        return got

    def labels(self, page, pid):
        """CARD_LABELS for pin pid, scrolled into view, with the layout readings (MEASURE) installed in the page."""
        self.card(page, pid).evaluate("card => card.scrollIntoView({block: 'center'})")
        settle(page)
        self.assertEqual(fonts_ready(page), "loaded")
        page.evaluate(MEASURE)
        return page.evaluate(CARD_LABELS, pid)

    def assert_on_the_cap_centre(self, got, hangul, rows=("head", "facts")):
        """The ink reference, by layout: each of rows drew a word, every word's cap-height centre and its digits' centre
        are within 0.5px of its row's centre - and its Hangul ink centre, when hangul is true - and the head's dot, icons
        and avatar stand on the row's centre. The facts line's words are trimmed one by one, so their cap-height centre
        is the line's within 0.15px in any font (docs/handbook/viewer.md §글자 가운데: 0.11px); as line boxes on one
        baseline they stood 0.3px over it in Pretendard, inside 0.5 but not on the reference."""
        self.assertLessEqual(set(rows), {label["row"] for label in got["labels"]}, got["labels"])
        self.assertEqual(off_centre(got["labels"], hangul), [])
        self.assertLessEqual(max(abs(under) for under in got["icons"].values()), 0.5, got["icons"])
        facts = [label for label in got["labels"] if label["row"] == "facts"]
        self.assertEqual(off_centre(facts, False, tol=0.15), [])  # trimmed, capitals land within 0.11px in any font

    def assert_one_centre(self, got, prefix):
        """The measured text runs whose key starts with prefix are painted on one ink centre: every pair is within
        0.5px. For the bundled Pretendard only - a painted centre is the ink of the very strings, which another font
        draws elsewhere."""
        mids = {key: mid for key, mid in got["mid"].items() if key.startswith(prefix)}
        self.assertGreaterEqual(len(mids), 3, got["mid"])
        self.assertNotIn(None, mids.values(), mids)
        self.assertLessEqual(max(mids.values()) - min(mids.values()), 0.5, mids)

    def assert_head_on_its_centre_line(self, got):
        """The head row stands on whole pixels and its items - the dot, the link's words, the reply icon and count, the
        fold chevron - are painted on one ink centre: each within 0.5px of the row's centre line, and every pair within
        0.75px of each other - a pair a pixel apart, one over and one under the line, is not one centre. The pair bound
        is the reference's 0.5px and one device pixel (0.5px at scale factor 2): a word's baseline is drawn on a whole
        device pixel, and the link's 14px and the count's 12px put theirs at different fractions of one (with a
        runner's font hinting the two were painted 0.62px apart, their cap-height centres 0.02px apart)."""
        top, bottom = got["head"][1], got["head"][3]
        self.assertEqual((top % 1, bottom % 1), (0, 0), got["head"])
        mids = {key: mid for key, mid in got["mid"].items() if key.startswith("head")}
        self.assertEqual(len(mids), 5, got["mid"])
        self.assertNotIn(None, mids.values(), mids)
        self.assertLessEqual(max(abs(mid - (top + bottom) / 2) for mid in mids.values()), 0.5, mids)
        self.assertLessEqual(max(mids.values()) - min(mids.values()), 0.75, mids)


class FoldedCardFacts(FoldedCardBase):
    """A folded card draws what differs from the default and says all three facts."""

    def test_the_default_card_draws_no_line_and_every_other_state_draws_its_exceptions(self):
        """Agent, me, a colleague and a record without an assignee, as a fix request and as a question, open, being
        worked on, awaiting review and reopened, on the phone sheet and in a tablet panel: the fix request for the agent
        that is open draws no facts line and is as tall as a card was before the line (73px); every other card draws
        exactly what differs, joined by ' · ', on one 18px line ('다시 열림' for a reopened pin, whose dot is the open
        one's); and each card's line still holds all three facts for a screen reader."""
        want, said = {}, {}
        for assignee, who in ASSIGNEES:
            for kind in KIND_WORD:
                for state in FOLD_STATES:
                    pid = self.seed_state(assignee, kind, state)
                    want[pid] = drawn_words(kind, who, state)
                    said[pid] = "%s 담당 %s %s" % (KIND_WORD[kind], who, STATE_WORD[state])
        n_open = sum(1 for text in said.values() if "검토 대기" not in text)
        for name in ("phone 390x844", "fold inner 841x673"):
            with self.subTest(name):
                page = self.show(n_open, VIEWPORTS[name])
                self.assertEqual(page.locator("#right .pin").count(), len(want))
                shown = {pid: self.facts(page, pid) for pid in want}
                self.assertEqual({pid: card["words"] for pid, card in shown.items()}, want)
                self.assertEqual({pid: card["all"].replace(" · ", " ") for pid, card in shown.items()}, said)
                for pid, card in shown.items():
                    drawn = bool(want[pid])
                    box = self.card(page, pid)
                    self.assertNotIn("open", box.get_attribute("class").split())
                    self.assertEqual((card["shown"], card["height"]), (drawn, 18 if drawn else 0), pid)
                    self.assertEqual(box.bounding_box()["height"], WITH_FACTS if drawn else DEFAULT_1, pid)

    def test_each_kind_of_folded_card_is_its_v0420_height_but_for_the_stated_exceptions(self):
        """Every touch viewport of the list, each kind of card against v0.4.20's card for the same note (73.5px with a
        one-line preview, 93px with two): the default card is the same on whole pixels (73, 92), with an empty note
        too; a card that draws a facts line is 91px - 17.5px more with a short note, the one card that grew, and 2px
        less with a longer one, whose second preview line the facts take. Nothing else differs, and no card is over
        v0.4.20's two-line 93."""
        long_note = (
            "이 문단의 86개 건물은 타깃 기간 전체를 뜻하나요, 아니면 일부 체크포인트만 뜻하나요? 본문과 표가 다르게 읽힙니다. "
            * 2
        )
        cases = [
            (False, 1, self.seed_state("agent", "fix", "open")),
            (False, 1, self.seed_state("agent", "fix", "open", note="")),
            (False, 2, self.seed_state("agent", "fix", "open", note=long_note)),
            (True, 1, self.seed_state("agent", "question", "open")),
            (True, 1, self.seed_state("bob@example.com", "fix", "open")),
            (True, 1, self.seed_state("agent", "fix", "reopened")),
            (True, 2, self.seed_state("agent", "question", "claimed", note=long_note)),
            (True, 2, self.seed_state("bob@example.com", "fix", "open", note=long_note)),
        ]
        for name, device in COMPACT.items():
            with self.subTest(name):
                page = self.show(len(cases), device)
                for facts, lines, pid in cases:
                    got = page.evaluate(CARD_ROWS, pid)
                    height = got["card"][3] - got["card"][1]
                    self.assertEqual(self.facts(page, pid)["shown"], facts, pid)
                    self.assertEqual(height, V0420_FOLDED[lines] + AGAINST_V0420[(facts, lines)], (pid, facts, lines))
                    self.assertEqual(got["previewLines"], 1 if facts else lines, pid)
                    self.assertLessEqual(height, V0420_FOLDED[2], pid)

    def test_the_expanded_card_leaves_what_its_badges_say_to_the_badges(self):
        """Unfolded, a reopened question of the agent's shows its 질문 and 다시 열림 badges and no facts line; folded
        again the line draws both."""
        pid = self.seed_state("agent", "question", "reopened")
        page = self.show(1, PHONE_390)
        card = self.card(page, pid)
        self.assertEqual(self.facts(page, pid)["words"], "질문 · 다시 열림")
        card.locator(".b-fold").click()
        settle(page)
        self.assertTrue(card.locator(".badge-reopen").is_visible())
        self.assertTrue(card.locator(".badge-question").is_visible())
        self.assertEqual(self.facts(page, pid)["shown"], False)
        card.locator(".b-fold").click()
        settle(page)
        self.assertEqual(self.facts(page, pid)["words"], "질문 · 다시 열림")

    def test_the_desktop_card_shows_the_assignee_under_the_note_only_when_it_is_not_the_agent(self):
        """The desktop's cards never fold: the agent's fix request has no facts line and is as tall as the same card
        with the line taken out of the page; a colleague's has '담당 Bob Park' 4px under the note."""
        agent = self.seed_state("agent", "fix", "open")
        colleague = self.seed_state("bob@example.com", "fix", "open", author=BOB)
        page = self.show(2, VIEWPORTS["desktop 1440x900"])
        self.assertEqual(self.facts(page, agent)["shown"], False)
        box = self.card(page, agent).bounding_box()
        without = self.card(page, agent).evaluate(
            "card => {card.querySelector('.card-meta').remove(); return card.getBoundingClientRect().height;}"
        )
        self.assertEqual(box["height"], without)
        self.assertEqual(self.facts(page, colleague)["words"], "담당 Bob Park")
        note = self.card(page, colleague).locator(".note").bounding_box()
        line = self.card(page, colleague).locator(".card-meta").bounding_box()
        self.assertEqual(round(line["y"] - (note["y"] + note["height"]), 1), 4)

    def test_a_long_name_ends_in_an_ellipsis_and_is_still_read_whole(self):
        """A 60-character colleague name on 320 and 390px phones and a tablet panel: the facts line stays one line with
        the kind and the status whole, the name ends in an ellipsis inside the card and its ink - the descenders of
        g and y under the trimmed line - stays inside the box that clips it,
        the card is as tall as one with a short name, the head row stays one row, and the whole name is still the
        control's accessible name and tooltip."""
        name = "Bartholomew Maximilian Fitzgerald-Montgomery-Smythe the Third"
        ps.APP.people_directory.record(actor({"Tailscale-User-Login": "bart@example.com", "Tailscale-User-Name": name}))
        long_own = self.seed_state("bart@example.com", "fix", "claimed")
        long_other = self.seed_state("bart@example.com", "question", "claimed", author=BOB)
        short = self.seed_state("bob@example.com", "fix", "claimed")
        for label in ("phone 320x720", "phone 390x844", "fold inner 841x673"):
            with self.subTest(label):
                device = VIEWPORTS[label]
                page = self.show(3, device)
                base = page.evaluate(CARD_ROWS, short)
                for pid in (long_own, long_other):
                    got = page.evaluate(CARD_ROWS, pid)
                    self.assertEqual((got["name"]["cut"], got["name"]["ellipsis"]), (True, "ellipsis"), got)
                    (clip,) = self.labels(page, pid)["clips"]
                    self.assertLessEqual(max(clip["over"], clip["under"]), 0, clip)
                    self.assertEqual(got["meta"][3] - got["meta"][1], 18)
                    self.assertLessEqual(got["lines"][-1][2], got["content"][2] + 0.5, got)
                    self.assertEqual(got["card"][3] - got["card"][1], base["card"][3] - base["card"][1])
                    self.assertEqual(got["headWraps"], 1, got)
                    self.assertEqual(got["overflow"], {"card": 0, "panel": 0, "page": 0})
                    words = self.facts(page, pid)["words"]
                    self.assertIn("담당 " + name, words)
                    self.assertRegex(words, r"^(질문 · )?담당 .* · 처리 중$")
                own = self.card(page, long_own)
                self.assertEqual(own.locator(".card-meta .as-chip").text_content(), "담당 " + name)
                self.assertIn(name, own.locator(".card-meta .as-chip").get_attribute("data-tip"))
                self.assertIn(
                    name, self.card(page, long_other).locator(".card-meta .as-chip").get_attribute("data-tip")
                )
        long_open = self.seed_state("bart@example.com", "fix", "open")
        page = self.show(4, MOUSE_MID)
        button = self.card(page, long_open).get_by_role("button", name=re.compile(re.escape("담당 " + name)))
        self.assertEqual(button.count(), 1)  # under a mouse the pressable assignee's accessible name is the whole name


# The desktop head row's words against the ink reference (MEASURE's label()): #N, the line range, N쪽, the author's name and
# the reply count against the row, the dot's, the avatar's and the reply icon's box centres under the row's, the row's top,
# and - for the painted measure - the boxes of the dot, #N, the line range, N쪽's digits, the avatar and the author's name
# without the '(나)' after it (a bracket is outside the reference, docs/handbook/viewer.md §글자 가운데). Also how far each
# link's box reaches over its ink's top and under its ink's bottom, for the focus ring drawn round the box.
DESK_HEAD = r"""id => {const c = document.querySelector('#right .pin[data-id="' + id + '"]'), h = c.querySelector('.head'), H = h.getBoundingClientRect();
  const R = e => {const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom];}, mid = e => {const r = e.getBoundingClientRect(); return r.top + r.height / 2;};
  const span = (e, n) => {const t = e.firstChild, g = document.createRange(); g.setStart(t, 0); g.setEnd(t, n == null ? t.data.length : n); return R(g);};
  const q = s => h.querySelector(s), words = {}, icons = {}, ink = [], rings = {};
  for (const [k, s] of [['n', ':scope > .n.go'], ['loc', ':scope > .loc'], ['pg', ':scope > .pg-link'], ['author', '.au-n'], ['reply', '.th-n .lbl']]) {
    const e = q(s); if (e && e.getClientRects().length) words[k] = __m.label(e, h);}
  for (const [k, s] of [['dot', '.st-dot'], ['avatar', '.au .av'], ['reply', '.th-n svg']]) {const e = q(s); if (e && e.getClientRects().length) icons[k] = mid(e) - (H.top + H.height / 2);}
  ink.push({k: 'dot', box: R(q('.st-dot')), ix: 0}, {k: 'n', box: span(q(':scope > .n.go')), ix: 0}, {k: 'loc', box: span(q(':scope > .loc')), ix: 0},
    {k: 'pg', box: span(q(':scope > .pg-link'), q(':scope > .pg-link').firstChild.data.length - 1), ix: 0}, {k: 'avatar', box: R(q('.au .av')), ix: 0},
    {k: 'author', box: span(q('.au-n')), ix: 0});
  for (const [k, s] of [['n', ':scope > .n.go'], ['loc', ':scope > .loc'], ['pg', ':scope > .pg-link']]) {const e = q(s), b = e.getBoundingClientRect(), g = span(e);
    const base = __m.label(e, h).baseline, m = inkMetrics(e, e.textContent); rings[k] = {over: base - m.a - b.top, under: b.bottom - (base + m.d)};}
  return {top: H.top, height: H.height, card: R(c), words, icons, ink, rings};}"""


class DesktopHeadRow(FoldedCardBase):
    """The desktop card's head row - dot, #N, line range, N쪽, reply icon and count, avatar, author's name - on one ink
    centre at device scale factors 1 and 2 (docs/handbook/viewer.md §글자 가운데)."""

    def cards(self):
        """Pins of mine and Bob's, one with a reply, one assigned to a colleague, one awaiting review with a thread:
        the head rows of every kind of desktop card, stacked so each later card starts where the earlier ones end."""
        pids = [
            self.seed_state("agent", "fix", "open"),
            self.seed_state("bob@example.com", "question", "claimed", author=BOB),
            self.seed_state("agent", "fix", "review"),
            self.seed_state("bob@example.com", "fix", "open"),
        ]
        ps.APP.pin_lifecycle.reply_pin(
            pids[1], "답글", post_authority(ps.APP.pin_lifecycle.context().store, actor(BOB), "reply", pids[1])
        )
        return pids

    def test_the_head_row_is_on_the_cap_height_reference_at_scale_factors_1_and_2(self):
        """Every card's head row starts on a whole pixel (the note's 21.7px lines and the thread's 19.5px ones put
        the cards under them between pixels). By layout every word's cap-height centre - #N, the line range, N쪽,
        the author's name, the reply count - and the dot's, avatar's and reply icon's centres are within 0.5px of the
        row's centre and of each other (as line boxes #N stood 0.8px, the range 1.9px and the name 0.6px over the
        dot). Painted, each item's ink is within 0.5px plus half a device pixel of the row's centre line: a word's
        baseline is drawn on a whole device pixel, and three sizes (#N 14px bold, the range 13px, N쪽 and the name
        12px) put their baselines at different fractions of one, so a pair can differ by up to a device pixel that no
        layout removes - at scale factor 2 the row's items are within 0.75px of each other."""
        pids = self.cards()
        for dsf in (1, 2):
            device = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": dsf}
            with self.subTest(dsf=dsf):
                page = self.show(3, device)
                page.evaluate(MEASURE)
                for pid in pids:
                    self.card(page, pid).evaluate("card => card.scrollIntoView({block: 'center'})")
                    settle(page)
                    got = page.evaluate(DESK_HEAD, pid)
                    self.assertEqual((got["top"] % 1, got["height"]), (0, 28), got)
                    self.assertGreaterEqual(len(got["words"]), 4, got)
                    layout = [w["cap"] for w in got["words"].values()] + [w["digits"] for w in got["words"].values()]
                    layout += list(got["icons"].values())
                    self.assertLessEqual(max(abs(v) for v in layout), 0.5, got)
                    self.assertLessEqual(max(layout) - min(layout), 0.5, got)
                    x0, y0, x1, y1 = got["card"]
                    clip = {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}
                    shot = base64.b64encode(page.screenshot(clip=clip)).decode()
                    items = [
                        dict(i, box=[i["box"][0] - x0, i["box"][1] - y0, i["box"][2] - x0, i["box"][3] - y0])
                        for i in got["ink"]
                    ]
                    ink = page.evaluate(ROW_INK, [shot, dsf, items])
                    centre = got["top"] + 14
                    painted = {k: v["mid"] + y0 - centre for k, v in ink.items() if v}
                    self.assertEqual(len(painted), 6, ink)
                    self.assertLessEqual(max(abs(v) for v in painted.values()), 0.5 + 0.5 / dsf, (pid, painted))
                    if dsf == 2:
                        self.assertLessEqual(max(painted.values()) - min(painted.values()), 0.75, (pid, painted))

    def test_a_focus_ring_round_a_head_link_clears_its_glyphs_and_holds_its_underline(self):
        """Keyboard focus on #N, the line range and N쪽: the ring is drawn 1px round the link's box, and each box reaches
        2.5px or more past its ink over and under (N쪽's Hangul reaches a pixel under the baseline) - the step over and under the trimmed line - so the ring clears the
        glyphs and holds the underline, drawn a pixel or two under the baseline. Round a box of the cap height alone
        the ring touched the digits and the underline fell outside it."""
        (pid, *_) = self.cards()
        page = self.show(3, VIEWPORTS["desktop 1440x900"])
        page.evaluate(MEASURE)
        got = page.evaluate(DESK_HEAD, pid)
        for name, ring in got["rings"].items():
            with self.subTest(name):
                self.assertGreaterEqual(min(ring["over"], ring["under"]), 2.5, ring)


class SameNameAndEmptyNoteCards(FoldedCardBase):
    """A card names which of two same-named people has the pin, and an empty note does not make a card taller."""

    def test_the_card_names_the_login_beside_a_name_two_people_share(self):
        """Two people named Sam Jung, a pin handed to the second: on the phone and the desktop the facts line reads
        '담당 Sam Jung sam2@example.com', as the composer's row and line do; Bob, whose name nobody shares, is 'Bob Park'
        alone. It read only '담당 Sam Jung'."""
        for login in ("sam1@example.com", "sam2@example.com"):
            ps.APP.people_directory.record(actor({"Tailscale-User-Login": login, "Tailscale-User-Name": "Sam Jung"}))
        sam = self.seed_state("sam2@example.com", "fix", "open")
        bob = self.seed_state("bob@example.com", "fix", "open")
        for name in ("phone 390x844", "desktop 1440x900"):
            with self.subTest(name):
                page = self.show(2, VIEWPORTS[name])
                self.assertEqual(" ".join(self.facts(page, sam)["words"].split()), "담당 Sam Jung sam2@example.com")
                self.assertEqual(self.facts(page, bob)["words"], "담당 Bob Park")
                self.assertIn(
                    "sam2@example.com", self.card(page, sam).locator(".card-meta .as-chip").get_attribute("data-tip")
                )

    def test_an_empty_note_is_as_tall_as_a_one_line_note(self):
        """'(메모 없음)' in its smaller words takes the note's line, not one pixel more: an open card with an empty note
        is as tall as one with a one-line note on the desktop and on the phone (it was 133 against 132, and 165 against
        164), and folded it is the default 73px."""
        empty = self.seed_state("agent", "fix", "open", note="")
        short = self.seed_state("agent", "fix", "open")
        for name in ("desktop 1440x900", "phone 390x844"):
            with self.subTest(name):
                page = self.show(2, VIEWPORTS[name])
                if name.startswith("phone"):
                    folded = [page.evaluate(CARD_ROWS, pid) for pid in (empty, short)]
                    self.assertEqual([c["card"][3] - c["card"][1] for c in folded], [DEFAULT_1, DEFAULT_1])
                    page.evaluate("ids => {ids.forEach(id => OPEN_CARDS.add(id)); drawPins();}", [empty, short])
                    settle(page)
                notes = page.evaluate(
                    "ids => ids.map(id => document.querySelector('#right .pin[data-id=\"' + id + '\"] .note').getBoundingClientRect().height)",
                    [empty, short],
                )
                cards = [page.evaluate(CARD_ROWS, pid) for pid in (empty, short)]
                self.assertEqual(notes[0], notes[1], notes)
                self.assertEqual(cards[0]["card"][3] - cards[0]["card"][1], cards[1]["card"][3] - cards[1]["card"][1])


class AgentIdentityCards(FoldedCardBase):
    """The list as the agent identity - a loopback page with no person signed in."""

    def forward(self, route):
        """Forward every request without the tailnet identity headers, as a loopback browser sends them."""
        request = route.request
        url = urlparse(request.url)
        body = request.post_data_buffer or b""
        headers = {"Host": "127.0.0.1:18999"}
        if request.headers.get("content-type"):
            headers["Content-Type"] = request.headers["content-type"]
        if body:
            headers["Content-Length"] = str(len(body))
        if request.method == "POST":
            headers["Origin"] = "http://127.0.0.1:18999"
        target = url.path + ("?" + url.query if url.query else "")
        raw = (
            f"{request.method} {target} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
        ).encode() + body
        code, returned, data = self.talk(raw)
        route.fulfill(
            status=code, headers={"content-type": returned.get("content-type", "application/octet-stream")}, body=data
        )

    def test_a_folded_review_card_does_not_show_the_access_sentence(self):
        """Every touch viewport: a folded card awaiting review shows its head, preview and facts line only - the
        sentence '에이전트 권한으로 접속 중입니다 …' stayed under it, one or two lines - and is 91px like every card with
        facts; unfolded, the sentence is there."""
        pid = self.seed_state("agent", "fix", "review")
        for name, device in COMPACT.items():
            with self.subTest(name):
                page = self.show(0, device)
                card = self.card(page, pid)
                self.assertEqual(card.locator(".review-access").count(), 1)
                self.assertFalse(card.locator(".review-access").is_visible())
                self.assertEqual(card.bounding_box()["height"], WITH_FACTS)
                card.locator(".b-fold").click()
                settle(page)
                self.assertTrue(card.locator(".review-access").is_visible())


class FoldedCardGeometry(FoldedCardBase):
    """The folded card's size and alignment on every compact band (docs/handbook/viewer.md §컴포넌트 규격)."""

    def test_the_facts_line_is_as_tall_whether_or_not_the_assignee_can_be_pressed(self):
        """Every touch viewport of the list: my own pin's card and another author's are the same 91px with the same
        18px line, 4px under the preview and without padding, folded and unfolded, and neither draws a button (the
        pressable one was 24px taller, the line padded 12px over and under a 44px hit). In a mouse window in a mid
        band, where my own pin's assignee is a button, the two cards are as tall as each other too."""
        mine = self.seed_state("bob@example.com", "fix", "open")
        other = self.seed_state("bob@example.com", "fix", "open", author=BOB)
        for name, device in COMPACT.items():
            with self.subTest(name):
                page = self.show(2, device)
                self.assertEqual(page.locator("#right .pin .card-meta button").count(), 0)
                cards = [page.evaluate(CARD_ROWS, pid) for pid in (mine, other)]
                self.assertEqual({card["card"][3] - card["card"][1] for card in cards}, {WITH_FACTS})
                self.assertEqual({card["meta"][3] - card["meta"][1] for card in cards}, {18})
                style = {(card["metaStyle"]["padding"], card["metaStyle"]["marginTop"]) for card in cards}
                self.assertEqual(style, {("0px", "4px")})
                self.card(page, mine).locator(".b-fold").tap()
                settle(page)
                unfolded = page.evaluate(CARD_ROWS, mine)
                line = (unfolded["meta"][3] - unfolded["meta"][1], unfolded["metaStyle"]["padding"])
                self.assertEqual(line, (18, "0px"))
                self.assertEqual(self.card(page, mine).locator(".card-meta button").count(), 0)
        page = self.show(2, MOUSE_MID)
        self.assertEqual(self.card(page, mine).locator(".card-meta button.as-chip").count(), 1)
        self.assertEqual(self.card(page, other).locator(".card-meta button").count(), 0)
        cards = [page.evaluate(CARD_ROWS, pid) for pid in (mine, other)]
        self.assertEqual(len({card["card"][3] - card["card"][1] for card in cards}), 1, cards)
        self.assertEqual({card["meta"][3] - card["meta"][1] for card in cards}, {18})

    def test_the_rows_share_one_left_edge_and_stand_on_the_grid(self):
        """Every touch viewport: the status dot, the preview and the facts line start on the card's content edge (within
        0.5px), the fold button and the preview end on its right edge, the head row's own box is the 32px it draws with
        the preview starting where it ends (it lay 6px into the preview), the facts line follows the preview by 4px, and
        nothing is wider than the card or the panel."""
        pid = self.seed_state("bob@example.com", "question", "claimed")
        ps.APP.pin_lifecycle.reply_pin(
            pid, "답글", post_authority(ps.APP.pin_lifecycle.context().store, actor(BOB), "reply", pid)
        )
        for name, device in COMPACT.items():
            with self.subTest(name):
                page = self.show(1, device)
                got = page.evaluate(CARD_ROWS, pid)
                lefts = [got["content"][0], got["dot"][0], got["sum"][0], got["meta"][0], got["lines"][0][0]]
                self.assertLessEqual(max(lefts) - min(lefts), 0.5, got)
                rights = [got["content"][2], got["fold"][2], got["sum"][2]]
                self.assertLessEqual(max(rights) - min(rights), 0.5, got)
                self.assertLessEqual(got["lines"][-1][2], got["content"][2] + 0.5)
                self.assertEqual(got["head"][3] - got["head"][1], 32)
                self.assertEqual((got["sum"][1] - got["head"][3], got["meta"][1] - got["sum"][3]), (0, 4))
                self.assertEqual(got["overflow"], {"card": 0, "panel": 0, "page": 0})

    def test_each_row_has_one_ink_centre_on_every_band(self):
        """Every touch viewport and a mouse window in a mid band, in the bundled Pretendard: the head row's dot, link
        words, reply icon and count and fold chevron are painted on the row's centre line within 0.5px (the words stood
        0.3-0.8px over the dot), the facts line's kind, assignee and status are painted on one ink centre, and by layout
        every word's cap-height centre and Hangul ink centre are within 0.5px of its row's centre."""
        pid = self.seed_state("bob@example.com", "question", "claimed", author=BOB)
        ps.APP.pin_lifecycle.reply_pin(
            pid, "답글", post_authority(ps.APP.pin_lifecycle.context().store, actor(BOB), "reply", pid)
        )
        for name, device in dict(COMPACT, **{"mouse 1000x800": MOUSE_MID}).items():
            with self.subTest(name):
                page = self.show(1, device)
                got = self.rows(page, pid, device)
                self.assert_head_on_its_centre_line(got)
                self.assert_one_centre(got, "meta")
                self.assert_on_the_cap_centre(self.labels(page, pid), True)

    def named_pins(self):
        """Three questions by Bob being worked on, each with a reply, assigned to a Latin, a digit and a Hangul name
        (Bob Park, R2 4096, 한지우); returns their ids."""
        for login, name in (("r2@example.com", "R2 4096"), ("jiwoo@example.com", "한지우")):
            ps.APP.people_directory.record(actor({"Tailscale-User-Login": login, "Tailscale-User-Name": name}))
        pins = [
            self.seed_state(login, "question", "claimed", author=BOB)
            for login in ("bob@example.com", "r2@example.com", "jiwoo@example.com")
        ]
        store = ps.APP.pin_lifecycle.context().store
        for pid in pins:
            ps.APP.pin_lifecycle.reply_pin(pid, "답글", post_authority(store, actor(BOB), "reply", pid))
        return pins

    def test_the_rows_stand_on_the_cap_height_centre_whichever_font_draws_them(self):
        """Phone 390 (folded cards) and the desktop, with a Latin, a digit and a Hangul assignee name, in the bundled
        Pretendard and in two fallback stacks: every word of the head row - with a mouse #N, the line range, N쪽 and
        the author's name - and of the facts line has its cap-height centre, and so its digits and capitals, within
        0.5px of its row's centre, and the head's dot, icons and avatar stand on it, whichever face the machine draws
        the stack with (as line boxes the facts line stood 0.3px and the author's name 0.6px over the middle in
        Pretendard, and in DejaVu Sans the link words 2.2px over the dot). The Hangul ink is held to 0.5px only where
        the face that drew it (drawn_faces) is one the handbook gives a tolerance for. The author's name loses no ink
        to the box that clips it."""
        pins = self.named_pins()
        for name, device in (("phone 390x844", PHONE_390), ("desktop 1440x900", VIEWPORTS["desktop 1440x900"])):
            for font in (None, *FALLBACK_FONTS):
                with self.subTest(name, font=font):
                    page = self.show(3, device, font=font)
                    latin = drawn_faces(page, "#right .pin .card-meta", "Bob Park R2 4096")
                    hangul = drawn_faces(page, "#right .pin .card-meta", "질문담당한지우처리중쪽")
                    self.assertTrue(latin and hangul, (latin, hangul))
                    self.assertEqual(
                        {face.startswith("Pretendard") for face in latin | hangul}, {not font}, (latin, hangul)
                    )
                    for pid in pins:
                        got = self.labels(page, pid)
                        self.assert_on_the_cap_centre(got, hangul_ink_holds(hangul))
                        self.assertLessEqual(max(max(c["over"], c["under"]) for c in got["clips"]), 0, got["clips"])

    def test_the_painted_ink_holds_for_latin_digit_and_hangul_names_in_light_and_dark(self):
        """Phone 390 in the bundled Pretendard, light and dark: with a Latin, a digit and a Hangul assignee name the
        head row's items are painted within 0.5px of the row's centre line and the facts line's words within 0.5px of
        one another."""
        pins = self.named_pins()
        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                page = self.show(3, PHONE_390, theme=theme)
                faces = drawn_faces(page, "#right .pin .card-meta", "질문담당한지우")
                self.assertEqual({face.startswith("Pretendard") for face in faces}, {True}, faces)
                for pid in pins:
                    got = self.rows(page, pid, PHONE_390)
                    self.assert_head_on_its_centre_line(got)
                    self.assert_one_centre(got, "meta")

    def test_the_folded_cards_controls_answer_44px_on_touch_and_24px_with_a_mouse(self):
        """Every touch viewport: the head link, the reply count and the fold button answer a 44x44 tap at their drawn
        size, and the facts line holds nothing to press; in a mouse window in a mid band and on the desktop the reply
        count, the fold button and the pressable assignee answer 24x24."""
        pid = self.seed_state("bob@example.com", "fix", "open")
        ps.APP.pin_lifecycle.reply_pin(
            pid, "답글", post_authority(ps.APP.pin_lifecycle.context().store, actor(BOB), "reply", pid)
        )
        self.seed_state("agent", "fix", "open")  # a neighbour under the card
        sel = '#right .pin[data-id="%d"] :is(.head [data-act], .card-meta button)' % pid
        for name, device in COMPACT.items():
            with self.subTest(name):
                page = self.show(2, device)
                self.card(page, pid).evaluate("card => card.scrollIntoView({block: 'center'})")
                settle(page)
                drawn = "sel=>[...document.querySelectorAll(sel)].filter(e=>e.getClientRects().length).length"
                self.assertEqual(page.evaluate(drawn, sel), 3)  # the link, the reply count, the fold button
                self.assertEqual(page.evaluate(MISSES_44, sel), [])
        for name, device in (("mouse 1000x800", MOUSE_MID), ("desktop 1440x900", VIEWPORTS["desktop 1440x900"])):
            with self.subTest(name):
                page = self.show(2, device)
                mouse = '#right .pin[data-id="%d"] :is(.th-n, .b-fold, .card-meta button)' % pid
                self.assertEqual(self.card(page, pid).locator(".card-meta button").count(), 1)
                self.assertEqual(page.evaluate(MISSES_24, mouse), [])

    def test_the_dragged_text_line_leaves_the_head_its_44px(self):
        """Phone 390 and a tablet panel, a card unfolded with its dragged-text line right under the head: the head's link
        and fold button answer 44px (the line's hit took the 6px they reach under their row, leaving 38) and so does the
        line, which stands 16px under the head; with a badge between them the line keeps its 8px."""
        body = {"file": str(self.main), "page": 1, "assignee": "agent"}
        plain = add_pin(dict(body, lo=20, hi=20, note="단위를 맞춰 주세요", quote="Line 20 of the demo"), actor(ALICE))
        asked = add_pin(
            dict(body, lo=22, hi=22, note="맞나요?", quote="Line 22 of the demo", kind_req="question"), actor(ALICE)
        )
        for name in ("phone 390x844", "tablet 1024x768"):
            with self.subTest(name):
                page = self.show(2, VIEWPORTS[name])
                for pin, above, gap in ((plain, ".head", 16), (asked, ".tags", 8)):
                    pid = pin.record["id"]
                    card = self.card(page, pid)
                    card.locator(".b-fold").click()
                    card.evaluate("card => card.scrollIntoView({block: 'center'})")
                    settle(page)
                    box = '#right .pin[data-id="%d"]' % pid
                    self.assertEqual(page.evaluate(MISSES_44, "%s .go-all,%s .b-fold,%s .quote" % (box, box, box)), [])
                    quote = card.locator(".quote").bounding_box()
                    over = card.locator(above).bounding_box()
                    self.assertEqual(round(quote["y"] - (over["y"] + over["height"]), 1), gap)
