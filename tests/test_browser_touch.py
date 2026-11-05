"""Pin that a synthesized touch drag (helpers_browser.Finger, touch_drag) leaves no fling behind: the tap that follows it at
once is a click, on the touch screens the viewer's tests drag on, even when the moves arrive at once as on a busy runner."""

from helpers_browser import VIEWPORTS, ChromiumTestCase, touch_drag, touch_line

# A scroller far taller than its box above a field: a drag up the scroller scrolls it, and a fling would go on scrolling.
PAGE = """<!doctype html><meta name=viewport content="width=device-width">
<style>body{margin:0} #s{height:60vh;overflow:auto} #s div{height:400vh;background:linear-gradient(#eee,#999)}
input{display:block;width:90%;height:60px;margin:10px;font-size:20px}</style>
<div id=s><div></div></div><input id=f>"""
SCREENS = ("fold inner 841x673", "tablet 1024x768")


class TouchDragThenTap(ChromiumTestCase):
    """A drag up the scroller with its moves sent at once, then at once a tap on the field and keys: the keys land in it."""

    def drag_then_type(self, screen, drag):
        """On screen, drag(cdp, points) up the scroller, then tap the field and type: (focused id, field value, scrollTop)."""
        context = self.browser.new_context(**VIEWPORTS[screen])
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_content(PAGE)
        cdp = context.new_cdp_session(page)
        s = page.locator("#s").bounding_box()
        x = s["x"] + s["width"] / 2
        drag(cdp, touch_line(x, s["y"] + s["height"] * 0.9, x, s["y"] + s["height"] * 0.1))
        page.tap("#f")
        page.keyboard.type("ok")
        return page.evaluate(
            "[document.activeElement.id, document.querySelector('#f').value, document.querySelector('#s').scrollTop]"
        )

    def test_a_tap_right_after_a_burst_drag_focuses_the_field(self):
        """touch_drag with pace 0 (a busy runner's delivery): the drag scrolled the scroller, and the tap focused the
        field, so the keys are its value. This fails on the defect it guards: with Finger.up()'s still move before the
        lift removed (or the events' own timestamps removed), the burst's release reads as fast, the drag flings, and
        the tap only stops the fling - ('', '') on both screens. A separate control that drags the old way and expects
        the tap to be swallowed was dropped: whether a fling is still running when the tap comes depends on the
        runner's delays, so such a control is itself a flake."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                focused, value, top = self.drag_then_type(screen, lambda cdp, pts: touch_drag(cdp, pts, pace=0))
                self.assertGreater(top, 100, "the drag did not scroll")
                self.assertEqual((focused, value), ("f", "ok"))
