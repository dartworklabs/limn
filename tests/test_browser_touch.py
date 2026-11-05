"""Pin that a synthesized touch drag (helpers_browser.Finger, touch_drag) leaves no fling behind: the tap that follows it at
once is a click, on the touch screens the viewer's tests drag on, even when the moves arrive at once as on a busy runner."""

import time

from helpers_browser import VIEWPORTS, ChromiumTestCase, touch_drag, touch_line

# A scroller far taller than its box above a field: a drag up the scroller scrolls it, and a fling would go on scrolling.
PAGE = """<!doctype html><meta name=viewport content="width=device-width">
<style>body{margin:0} #s{height:60vh;overflow:auto} #s div{height:400vh;background:linear-gradient(#eee,#999)}
input{display:block;width:90%;height:60px;margin:10px;font-size:20px}</style>
<div id=s><div></div></div><input id=f>"""
# The control's scroller is far taller still, so its fling cannot reach the end and stop before the tap comes.
TALL = PAGE.replace("height:400vh", "height:4000vh")
SCREENS = ("fold inner 841x673", "tablet 1024x768")


class TouchDragThenTap(ChromiumTestCase):
    """A drag up the scroller with its moves sent at once, then at once a tap on the field and keys: the keys land in it."""

    def drag_then_type(self, screen, drag, content=PAGE):
        """On screen, drag(cdp, points) up the scroller, then tap the field and type: (focused id, field value, scrollTop)."""
        context = self.browser.new_context(**VIEWPORTS[screen])
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_content(content)
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
        field, so the keys are its value."""
        for screen in SCREENS:
            with self.subTest(screen=screen):
                focused, value, top = self.drag_then_type(screen, lambda cdp, pts: touch_drag(cdp, pts, pace=0))
                self.assertGreater(top, 100, "the drag did not scroll")
                self.assertEqual((focused, value), ("f", "ok"))

    def test_a_drag_lifted_at_speed_leaves_the_tap_no_click(self):
        """The control: the same drag lifted while moving fast - its moves 4 ms apart by their own times, lifted 1 ms
        after the last, as a burst without times reads on a busy runner - flings, and the tap that stops the fling takes
        no focus. So the page reproduces the race the first test is about. The times fix the release speed whatever the
        runner's delays (without them Chrome reads the speed from arrival, and a late lift would read as a still one),
        and the scroller is tall enough that the fling is still running when the tap comes."""

        def lifted_at_speed(cdp, points):
            """The defect this control reproduces, made deterministic: a fast release by the events' own times."""
            t0 = time.time()

            def send(kind, pts, at):
                cdp.send(
                    "Input.dispatchTouchEvent",
                    {"type": kind, "touchPoints": [{"x": x, "y": y, "id": 0} for x, y in pts], "timestamp": at},
                )

            send("touchStart", points[:1], t0)
            for i, point in enumerate(points[1:], 1):
                send("touchMove", [point], t0 + 0.004 * i)
            send("touchEnd", [], t0 + 0.004 * (len(points) - 1) + 0.001)

        for screen in SCREENS:
            with self.subTest(screen=screen):
                focused, value, _ = self.drag_then_type(screen, lifted_at_speed, TALL)
                self.assertEqual((focused, value), ("", ""))
