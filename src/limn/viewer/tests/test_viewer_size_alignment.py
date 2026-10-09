"""Size and alignment of the outline, the small button, the badge, the mark badge and the changes view's guide row,
measured in a real Chromium (docs/handbook/viewer.md §모바일 레이아웃, §글자 가운데, §컴포넌트 규격).

A UX audit measured these on eight viewports and found one cause under most of them: heights that came from a text's
line box (12px x 1.4 = 16.8px) put every box under them between pixels, where one label is painted a pixel higher or
lower depending only on the fraction of its y. The tests hold what replaced that: whole-pixel heights from tokens, one
set of columns and one baseline for the outline's rows, labels centred on their cap height, a mark badge's press area
split with its neighbour, and the guide row's buttons clear of the panel handle's hit.

Every number is layout: a box from getBoundingClientRect, a text's baseline as the top of its first glyph's box (Range)
plus the font's layout ascent - read on a scratch span, never by putting an element into the measured one, because a
button of words alone stops being a block container once it has a child - and ink from the viewer's own inkMetrics().
"""

import json
import os
import unittest

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, ps
from helpers_access import ALICE, actor
from helpers_authority import post_authority
from helpers_browser import BrowserBase, fonts_ready, settle

DESK = {"viewport": {"width": 1440, "height": 900}}
PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2}
TOL = 0.5  # the audit's tolerance for an offset or a spread, in CSS px
WHOLE = 0.01  # a length counts as a whole number of px within this

# First-visit hints are seen and the desktop outline is open, before the viewer boots.
PREFS = "try{localStorage.setItem('pinPrefs',%s);}catch(e){}" % json.dumps(
    json.dumps({"coach": {"touch": 1, "mouse": 1, "sel": 1, "side": 1}, "outlineClosed": False})
)
# Fonts whose Hangul reaches far past the cap height and the baseline, as a phone's system Korean font does; the first one
# this machine has stands in for "the system fallback" (Playwright's own dependencies bring WenQuanYi Zen Hei).
FALLBACKS = ("Noto Sans CJK KR", "WenQuanYi Zen Hei")
# Puts the given families in --font-sans before the viewer lays anything out.
FALLBACK_INIT = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent=':root:root{--font-sans:%s,sans-serif}';document.head.append(s);});"
)
# The first of the given families the browser has, or null: a family it lacks measures as the monospace it falls back to.
FIRST_FONT = """fams => {const c = document.createElement('canvas').getContext('2d'), s = '본문 핀 검토 선택';
  c.font = '16px monospace'; const m = c.measureText(s).width;
  return fams.find(f => {c.font = '16px "' + f + '", monospace'; return c.measureText(s).width !== m;}) || null;}"""
# window.__m: layout readings that leave the measured element alone.
#   label(el, box) - el's first text against box (default el): its first glyph's x, its baseline, and how far the centres of
#   its cap height ('H'), of the digits, of its own ink and of its Hangul letters lie under the box's centre (inkMetrics).
#   hit(el) - how far a press still answers el from its centre to the left, right, top and bottom (elementFromPoint, to
#   0.1px, 60px at most), so an ::after extension and a neighbour that takes part of it both count.
MEASURE = """() => {
  const asc = {};
  const ascent = el => {const c = getComputedStyle(el), key = [c.fontStyle, c.fontWeight, c.fontSize, c.fontFamily].join('|');
    if (!(key in asc)) {const s = document.createElement('span'), k = document.createElement('span'), t = document.createTextNode('H');
      s.style.cssText = 'position:absolute;left:-9999px;top:0;white-space:nowrap;line-height:normal';
      for (const p of ['fontStyle', 'fontWeight', 'fontSize', 'fontFamily']) s.style[p] = c[p];
      k.style.cssText = 'display:inline-block;width:0;height:0'; s.append(t, k); document.body.append(s);
      const r = document.createRange(); r.selectNodeContents(t);
      asc[key] = k.getBoundingClientRect().bottom - r.getClientRects()[0].top; s.remove();}
    return asc[key];};
  const first = el => {const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT); let n;
    while ((n = w.nextNode())) {const s = n.nodeValue, i = s.search(/\\S/); if (i < 0) continue;
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); const box = r.getClientRects()[0];
      if (box && box.width) return {node: n, box, text: s.trim()};}
    return null;};
  const label = (el, box) => {const f = first(el), p = f.node.parentElement, base = f.box.top + ascent(p);
    const R = (box || el).getBoundingClientRect(), mid = R.top + R.height / 2, hangul = hangulOf(f.text);
    const under = s => {const m = inkMetrics(p, s); return base + (m.d - m.a) / 2 - mid;};
    return {text: f.text, x: f.box.left, baseline: base, cap: under('H'), digits: under('0123456789'), ink: under(f.text),
      hangul: hangul ? under(hangul) : null, top: R.top, height: R.height};};
  const hit = el => {const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const own = (x, y) => {const n = document.elementFromPoint(x, y); return !!n && (n === el || el.contains(n));};
    const reach = (dx, dy) => {if (!own(cx, cy)) return 0; let lo = 0, hi = 60; if (own(cx + dx * hi, cy + dy * hi)) return hi;
      while (hi - lo > 0.1) {const m = (lo + hi) / 2; if (own(cx + dx * m, cy + dy * m)) lo = m; else hi = m;} return lo;};
    return {l: reach(-1, 0), r: reach(1, 0), t: reach(0, -1), b: reach(0, 1)};};
  window.__m = {label, hit};}"""
# Card labels as drawn: for each selector's elements that draw a text (a compact card's icon buttons draw none), the label
# reading (MEASURE) with the element's display.
LABELS = """sels => sels.flatMap(s => [...document.querySelectorAll(s)].filter(e => e.getClientRects().length
  && e.innerText.trim()).map(e => Object.assign(__m.label(e), {sel: s, display: getComputedStyle(e).display})))"""
# Each icon badge: its text's cap-height centre and its icon's centre under the badge's centre.
BADGE_ICONS = """() => [...document.querySelectorAll('.pin .tags .badge')].filter(b => b.querySelector('svg')).map(b => {
  const R = b.getBoundingClientRect(), i = b.querySelector('svg').getBoundingClientRect(), t = __m.label(b);
  return {text: t.text, cap: t.cap, icon: i.top + i.height / 2 - (R.top + R.height / 2)};})"""


def whole(v: float) -> bool:
    """Whether v is a whole number of px (within WHOLE)."""
    return abs(v - round(v)) <= WHOLE


class SizeAlignmentBase(BrowserBase):
    """BrowserBase with the hints pre-seen and the layout readings (MEASURE) installed in the page."""

    def view(self, device: dict, init: str = ""):
        """Open the viewer on device and return the page once it has booted, settled and its fonts are loaded; init is a
        script run before the viewer's own, after the saved preferences."""
        page = self.open(0, init=PREFS + init, **device)
        self.assertEqual(fonts_ready(page), "loaded")
        page.evaluate(MEASURE)
        return page


class CardFixture(SizeAlignmentBase):
    """SizeAlignmentBase with three pins on page 1: a fix request, a question (its badge has an icon) and one awaiting
    the viewer's review (an icon badge, [변경 보기] [답글] [확인])."""

    def setUp(self):
        """Add the three pins as Alice and close the third as the agent, so it waits for her review."""
        super().setUp()
        for lo, y, kind in ((4, 0.2, "fix"), (8, 0.4, "question")):
            add_pin(
                {
                    "file": str(self.main),
                    "lo": lo,
                    "hi": lo + 1,
                    "page": 1,
                    "note": "메모 %d" % lo,
                    "kind_req": kind,
                    "frac": [0.2, y, 0.5, 0.04],
                },
                actor(ALICE),
            )
        self.review = add_pin(
            {"file": str(self.main), "lo": 20, "hi": 21, "page": 1, "note": "검토할 핀", "frac": [0.2, 0.6, 0.4, 0.04]},
            actor(ALICE),
        ).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            self.review,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", self.review),
            CloseRequest(reply="고침"),
        )

    def cards(self, device: dict, init: str = ""):
        """The viewer on device with the panel open and every card expanded (a compact layout folds them)."""
        page = self.view(device, init)
        page.evaluate(
            "() => {setSide(true); OPEN_ALL.concat(REVIEW_ALL).forEach(p => OPEN_CARDS.add(p.id)); drawPins();}"
        )
        settle(page)
        self.assertEqual(fonts_ready(page), "loaded")
        return page


class ComponentHeights(CardFixture):
    """Heights the component standard names come from tokens and are whole px (docs/handbook/viewer.md §컴포넌트 규격):
    as 12px x 1.4 + padding a small button was 22.8px, a badge 19.94px (21.39px on touch) and the outline's search
    field 36.6px."""

    def heights(self, device: dict, sels: list[str]) -> dict[str, set[float]]:
        """The distinct heights of the visible elements of each selector on device, cards expanded."""
        page = self.cards(device)
        got: dict[str, list[float]] = page.evaluate(
            "sels => Object.fromEntries(sels.map(s => [s, [...document.querySelectorAll(s)]"
            ".filter(e => e.getClientRects().length).map(e => e.getBoundingClientRect().height)]))",
            sels,
        )
        return {k: set(v) for k, v in got.items()}

    def test_small_buttons_badges_and_the_search_field_are_whole_pixels_with_a_mouse(self):
        """Mouse: every small button of the cards and the list head is 24px (--control-h-sm), every card badge 20px, and
        the outline's search field a whole number of px."""
        got = self.heights(DESK, [".pin .acts button.btn-sm", "#btn-reload", ".pin .tags .badge", "#outline-search"])
        self.assertEqual(got[".pin .acts button.btn-sm"], {24}, got)
        self.assertEqual(got["#btn-reload"], {24}, got)
        self.assertEqual(got[".pin .tags .badge"], {20}, got)
        self.assertTrue(got["#outline-search"] and all(whole(h) for h in got["#outline-search"]), got)

    def test_card_buttons_and_badges_are_whole_pixels_on_touch(self):
        """Touch: a card's action buttons keep their drawn 32px on the phone sheet, and a card badge is 20px - no taller
        than with a mouse."""
        got = self.heights(PHONE, [".pin .acts button.btn-sm", ".pin .tags .badge"])
        self.assertEqual(got[".pin .acts button.btn-sm"], {32}, got)
        self.assertEqual(got[".pin .tags .badge"], {20}, got)


class LabelInkCentre(CardFixture):
    """The ink reference (docs/handbook/viewer.md §글자 가운데): in a small button, a badge and a mark badge the cap
    height's centre - where digits and Latin capitals have their ink - and a Hangul label's ink centre are both within
    0.5px of the box's centre, in the bundled Pretendard and in a system fallback font. As line boxes the labels stood
    0.5-1.0px over the centre in Pretendard, and a badge's icon 0.8-1.0px from its text."""

    SELS = (
        ".pin .acts button.btn-sm",
        ".pin .tags .badge",
        ".mark button.mark-jump",
        "#btn-reload",
    )

    def assert_centred(self, page, hangul: bool, required: tuple[str, ...]):
        """Every drawn label of SELS has its cap-height centre and its digits' centre within 0.5px of its box's centre -
        and, when hangul is true, the ink centre of its Hangul letters; the selectors in required each draw one. A
        badge's icon is within 0.5px of the badge's centre and of its text's cap-height centre."""
        labels = page.evaluate(LABELS, list(self.SELS))
        self.assertLessEqual(set(required), {lb["sel"] for lb in labels}, labels)
        self.assertTrue(any(lb["hangul"] is not None for lb in labels), labels)
        for lb in labels:
            self.assertLessEqual(abs(lb["cap"]), TOL, lb)
            self.assertLessEqual(abs(lb["digits"]), TOL, lb)
            if hangul and lb["hangul"] is not None:
                self.assertLessEqual(abs(lb["hangul"]), TOL, lb)
        icons = page.evaluate(BADGE_ICONS)
        self.assertGreaterEqual(len(icons), 2, icons)
        for b in icons:
            self.assertLessEqual(abs(b["icon"]), TOL, b)
            self.assertLessEqual(abs(b["icon"] - b["cap"]), TOL, b)

    def test_labels_are_centred_on_their_cap_height_in_the_bundled_font(self):
        """Pretendard, with a mouse and on a phone: [보기] [수정] [답글] [삭제] [완료] [변경 보기] [확인], the question
        and review badges with their icons, the mark badges' numbers and [핀 다시 읽기]."""
        for name, device, required in (("mouse", DESK, self.SELS), ("phone", PHONE, self.SELS[:3])):
            with self.subTest(device=name):
                self.assert_centred(self.cards(device), hangul=True, required=required)

    def test_labels_are_centred_on_their_cap_height_in_a_fallback_font(self):
        """The same in the first installed fallback (FALLBACKS): the cap-height centre does not depend on the font's
        line metrics, and the Hangul bound holds in Noto Sans CJK KR, the stack's Korean fallback (another fallback's
        Hangul may be drawn further from its capitals than 0.5px, which no layout can undo). Skips without such a font -
        fails under LIMN_TEST_REQUIRE_BROWSER=1."""
        for name, device, required in (("mouse", DESK, self.SELS), ("phone", PHONE, self.SELS[:3])):
            with self.subTest(device=name):
                init = FALLBACK_INIT % ",".join('"%s"' % f for f in FALLBACKS)
                page = self.cards(device, init)
                font = page.evaluate(FIRST_FONT, list(FALLBACKS))
                if font is None:
                    reason = "no fallback Hangul font (%s): install fonts-noto-cjk or fonts-wqy-zenhei" % ", ".join(
                        FALLBACKS
                    )
                    if os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1":
                        self.fail(reason)
                    self.skipTest(reason)
                family = page.evaluate("getComputedStyle(document.querySelector('.pin .acts button')).fontFamily")
                self.assertTrue(family.startswith('"%s"' % FALLBACKS[0]), family)
                self.assert_centred(page, hangul=font == "Noto Sans CJK KR", required=required)


if __name__ == "__main__":
    unittest.main()
