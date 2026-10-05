"""The viewer's warning when a deferred [확인] answers 409 conflict (docs/handbook/api.md §검토 대기).

The confirm names the close the card showed; a 409 conflict means the pin's close is another one now, and the 409 body
carries the pin as it stands. confirmConflictText chooses the warning from that pin: still awaiting review means it was
closed again and the person should look at the new result and confirm; any other state (a person closed it straight
to done) leaves nothing to confirm. Run under node with the real confirmConflictText, pinState and message functions.

Run: uv run pytest -q src/limn/viewer/tests/test_confirm_conflict.py
"""

import json
import os
import shutil
import unittest

from helpers import UI_EN, extract_js_fn, js_i18n, run_node

CLOSED_AGAIN = "핀 #{id} 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요"
ALREADY_DONE = "핀 #{id} 은 이미 완료로 닫혔습니다 — 확인할 것이 없습니다"


class ConfirmConflictText(unittest.TestCase):
    """confirmConflictText(id, pin) for each state the 409 conflict's pin can be in, in Korean and English."""

    def setUp(self):
        """Skip without node, unless LIMN_TEST_REQUIRE_NODE=1 makes that a failure."""
        if not shutil.which("node"):
            if os.environ.get("LIMN_TEST_REQUIRE_NODE") == "1":
                self.fail("node required (LIMN_TEST_REQUIRE_NODE=1) but not installed")
            self.skipTest("node not available")

    def texts(self, lang: str, pins: list) -> list:
        """The warning the real confirmConflictText gives pin #7 for each 409 pin in pins, in lang."""
        js = "\n".join(
            [
                js_i18n(lang),
                extract_js_fn("pinState"),
                extract_js_fn("confirmConflictText"),
                "console.log(JSON.stringify(%s.map(p=>confirmConflictText(7,p))));" % json.dumps(pins),
            ]
        )
        return json.loads(run_node(js))

    def test_a_pin_still_awaiting_review_was_closed_again(self):
        """The 409 pin awaits review (an agent reopened and closed it again): the closed-again warning, which asks the
        person to look at the new result and confirm."""
        want = {"ko": CLOSED_AGAIN, "en": UI_EN[CLOSED_AGAIN]}
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                got = self.texts(lang, [{"id": 7, "state": "review"}, {"id": 7, "done": True, "review": True}])
                self.assertEqual(got, [want[lang].replace("{id}", "7")] * 2)

    def test_a_pin_a_person_closed_to_done_has_nothing_to_confirm(self):
        """The 409 pin is done (a person closed it straight to done meanwhile): it says the pin is already closed and
        there is nothing to confirm - not the closed-again warning, whose [확인] the pin no longer has."""
        want = {"ko": ALREADY_DONE, "en": UI_EN[ALREADY_DONE]}
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                got = self.texts(lang, [{"id": 7, "state": "done"}, {"id": 7, "done": True}])
                self.assertEqual(got, [want[lang].replace("{id}", "7")] * 2)
                self.assertNotIn("다시 닫혔습니다", got[0])

    def test_a_conflict_without_a_pin_keeps_the_closed_again_warning(self):
        """A 409 body without the pin (an older server) cannot tell the state, so the warning stays today's."""
        self.assertEqual(self.texts("ko", [None]), [CLOSED_AGAIN.replace("{id}", "7")])


if __name__ == "__main__":
    unittest.main()
