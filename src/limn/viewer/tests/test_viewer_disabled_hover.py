"""A control that cannot be pressed answers no mouse (docs/handbook/viewer.md §뜻과 모양, issue #416).

A disabled button and one that waits (aria-disabled, a page line's verdict words) keep the look they have at rest when the
mouse is over them: the hover fill said "press me" on a control that a press does nothing to - [더보기]'s disabled
[브라우저 알림] row filled with --accent. Each scene is read in Chromium and Firefox: hover is the browser's to set, and the
transition that eases a hover's fill in is waited out (settle) before the look is read. An enabled control beside it is
read the same way and does change, so a hover that never reached the page cannot pass for a guard.

The touch press wash (components.css, button:active) skips the same controls; it is held by the stylesheet check in
test_viewer.py (FrontendHoverForMouse) only: a finger held through the DevTools input domain never sets :active in headless
Chromium, so no press can be read here.
"""

import json

from helpers import ps
from helpers_access import member_add
from helpers_browser import BrowserBase, booted, settle, until, watch_idle
from helpers_figure import viewer_docs

# The look a hover may change: fills, text, border, inset wash, underline.
LOOK = """sel => {const e = document.querySelector(sel), c = getComputedStyle(e);
  return {background: c.backgroundColor, color: c.color, border: [c.borderTopColor, c.borderRightColor, c.borderBottomColor,
    c.borderLeftColor].join(' '), shadow: c.boxShadow, underline: c.textDecorationLine};}"""
# Resolves once sel has no transition running, two frames after the call - a hover's fill eases in over .12s. Not settle():
# the waiting verdict words are read while the pin list is held, and settle() waits for that fetch.
EASED = """async sel => {const e = document.querySelector(sel), frame = () => new Promise(r => requestAnimationFrame(r));
  await frame(); await frame(); while (e.getAnimations().some(a => a.playState === 'running')) await frame(); return true;}"""
WORDS = {"format": "limn-verdicts/1", "verdicts": [{"key": "채택"}, {"key": "보류"}, {"key": "삭제", "confirm": True}]}
# The components' button variants (components.css), each planted twice as a page's own control would carry it.
VARIANTS = ("", "btn-default", "btn-secondary", "btn-ghost", "btn-soft", "btn-destructive", "badge")
PLANT = """variants => {const box = document.createElement('div'); box.id = 'hover-probe';
  box.style.cssText = 'position:fixed;left:16px;top:120px;z-index:99;display:flex;flex-direction:column;gap:8px;background:var(--background)';
  for (const v of variants) for (const how of ['live', 'disabled', 'aria']) {const b = document.createElement('button');
    b.type = 'button'; b.className = v; b.textContent = (v || 'plain') + ' ' + how; b.dataset.probe = (v || 'plain') + '-' + how;
    if (how === 'disabled') b.disabled = true; if (how === 'aria') b.setAttribute('aria-disabled', 'true'); box.append(b);}
  document.body.append(box);}"""


# Page 1's [보류] on the figure document's page verdict line.
WORD = '#doc .pv[data-page="1"] button.vd-b[data-key="보류"]'


def waiting_page_line(case, **device):
    """The figure document open in a new context of case's browser (device: its new_context options) with its first pin
    list held, so page 1's verdict words wait (aria-disabled); returns the page and release(), which answers the held
    list and returns once the viewer has booted and settled."""
    fig = viewer_docs(ps.APP, ps.APP.C.src)[1]
    (fig.main.parent / "figures.limnverdicts.json").write_text(
        json.dumps({**WORDS, "page": True}, ensure_ascii=False), encoding="utf-8"
    )
    member_add(ps.APP.C.state, "agentb@example.com", "agent")
    held = []

    def route(r):
        """Hold every pin list read; the rest goes to the handler."""
        if r.request.url.split("?")[0].endswith("/api/pins") and r.request.method == "GET":
            held.append(r)
            return None
        return case.route(r)

    context = case.browser.new_context(**device)
    case.addCleanup(context.close)
    watch_idle(context)
    page = context.new_page()
    page.route("**/*", route)
    page.goto("http://viewer.test/?lang=ko#doc=fig")
    until(page, "!!document.querySelector('%s')" % WORD.replace("'", "\\'"), timeout=20)

    def release():
        """Answer the held list reads and route the next ones straight to the handler; wait for the boot to end."""
        page.route("**/*", case.route)
        for r in held:
            case.route(r)
        page.wait_for_function(booted(0), timeout=20000)
        settle(page)

    return page, release


class DisabledHover(BrowserBase):
    """In Chromium: the disabled and the waiting controls of real screens, and every button variant, under the mouse."""

    def look_at_rest_and_under_mouse(self, page, sel):
        """sel's look with the mouse off it and then on it, each read once its transition has ended (EASED)."""
        page.mouse.move(2, 2)
        page.evaluate(EASED, sel)
        rest = page.evaluate(LOOK, sel)
        box = page.locator(sel).bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.evaluate(EASED, sel)
        self.assertTrue(page.evaluate("s=>document.querySelector(s).matches(':hover')", sel), sel)
        return rest, page.evaluate(LOOK, sel)

    def test_the_disabled_notifications_row_keeps_its_resting_look_under_the_mouse(self):
        """[더보기]'s [브라우저 알림] cannot turn on over http://viewer.test (disabled, the reason under it): under the mouse
        it keeps its resting look, while the [휴지통] row under it fills with --accent."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.locator("#btn-more").click()
        page.wait_for_selector("#more[open]")
        settle(page)
        self.assertTrue(page.evaluate("document.querySelector('#m-notify').disabled"))
        rest, hovered = self.look_at_rest_and_under_mouse(page, "#m-notify")
        self.assertEqual(hovered, rest)
        rest, hovered = self.look_at_rest_and_under_mouse(page, "#m-trash")
        self.assertNotEqual(hovered["background"], rest["background"])

    def test_a_waiting_verdict_word_keeps_its_resting_look_until_it_can_be_pressed(self):
        """The figure's page line while the first pin list is on its way: its words wait (aria-disabled) and keep their
        resting look under the mouse; once the list is in, the same word fills under the mouse."""
        page, release = waiting_page_line(self, viewport={"width": 1440, "height": 900})
        self.assertEqual(page.get_attribute(WORD, "aria-disabled"), "true")
        rest, hovered = self.look_at_rest_and_under_mouse(page, WORD)
        self.assertEqual(hovered, rest)
        self.assertNotEqual(rest["background"], "rgba(0, 0, 0, 0)")  # a drawn word, not an empty box
        release()
        self.assertIsNone(page.get_attribute(WORD, "aria-disabled"))
        rest, hovered = self.look_at_rest_and_under_mouse(page, WORD)
        self.assertNotEqual(hovered["background"], rest["background"])

    def test_every_button_variant_keeps_its_resting_look_when_it_cannot_be_pressed(self):
        """Each of the components' button variants, disabled or aria-disabled, looks the same at rest and under the mouse;
        the same variant that can be pressed changes."""
        page = self.open(0, viewport={"width": 1440, "height": 900})
        page.evaluate(PLANT, list(VARIANTS))
        for v in VARIANTS:
            name = v or "plain"
            for how in ("disabled", "aria"):
                with self.subTest(variant=name, how=how):
                    rest, hovered = self.look_at_rest_and_under_mouse(page, '[data-probe="%s-%s"]' % (name, how))
                    self.assertEqual(hovered, rest)
            with self.subTest(variant=name, how="live"):
                rest, hovered = self.look_at_rest_and_under_mouse(page, '[data-probe="%s-live"]' % name)
                self.assertNotEqual(hovered, rest)


class DisabledHoverFirefox(DisabledHover):
    """The same controls under the mouse in Firefox."""

    BROWSER_ENGINE = "firefox"
