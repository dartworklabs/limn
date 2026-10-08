"""Real review controls respect server identity; native PDF badges support keyboard navigation."""

import subprocess
from urllib.parse import urlparse

from limn.pins.lifecycle.rules import CloseRequest
from limn.security.access import LOCAL_ACTOR

from helpers import add_pin, find_record, ps, records
from helpers_access import ALICE, actor, member_add
from helpers_authority import post_authority
from helpers_browser import BrowserBase, settle


class ReviewRoleAndKeyboard(BrowserBase):
    """Observe role-specific controls and keyboard navigation against the real handler and store."""

    def setUp(self):
        """Use a fresh viewer and opt into headerless forwarding only for the local-agent scenario."""
        super().setUp()
        self.headerless = False

    def forward(self, route):
        """Forward local-agent requests without identity headers; other scenarios use the usual person adapter."""
        if not self.headerless:
            return super().forward(route)
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

    def reviewed_pin(self):
        """Seed a real Git change and agent close so the changes guide resolves an actual commit and diff."""
        root = self.main.parent

        def git(*args):
            """Run Git in the temporary manuscript, independently of user signing settings."""
            return subprocess.check_output(["git", "-c", "commit.gpgsign=false", *args], cwd=root, text=True).strip()

        git("init", "-q")
        git("config", "user.name", "Example Author")
        git("config", "user.email", "author@example.com")
        git("add", "main.tex")
        git("commit", "-qm", "Initial manuscript")
        pid = add_pin(
            {
                "file": str(self.main),
                "lo": 5,
                "hi": 5,
                "page": 1,
                "note": "Review this result",
                "frac": [0.1, 0.2, 0.4, 0.03],
            },
            actor(ALICE),
        ).record["id"]
        self.main.write_text(self.main.read_text(encoding="utf-8") + "\n% Reviewed change\n", encoding="utf-8")
        git("add", "main.tex")
        git("commit", "-qm", "Address the pin")
        ref = git("rev-parse", "HEAD")
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="Changed the manuscript", ref=ref),
        )
        return pid

    def assert_read_only_review(self, role, headerless=False):
        """Neither review surface offers a refused confirmation; the unchanged server still refuses direct attempts."""
        pid = self.reviewed_pin()
        self.headerless = headerless
        if not headerless:
            member_add(ps.APP.C.state, "alice@example.com", role=role, name="Alice Kim")
        page = self.open(0, lang="en")
        self.assertEqual(page.evaluate("META.me.role"), role)
        self.assertEqual(page.locator("#review-pins [data-act=confirm]").count(), 0)
        self.assertTrue(page.locator("#review-pins .review-access").is_visible())
        page.locator("#review-pins [data-act=change]").click()
        page.wait_for_selector("#revision-pin:not([hidden])")
        settle(page)
        self.assertEqual(page.locator("#revision-pin [data-act=confirm],#revision-acts [data-act=confirm]").count(), 0)
        self.assertTrue(page.locator("#revision-pin .review-access").is_visible())
        result = page.evaluate("async id=>await api('/api/pins/'+id+'/confirm',{method:'POST',expect:[403]})", pid)
        self.assertEqual(result["status"], 403)
        self.assertTrue(find_record(ps.APP.snapshot_pins(), pid)["review"])

    def test_headerless_local_agent_has_guidance_instead_of_confirmation(self):
        """The default localhost identity receives a human-access explanation and cannot confirm."""
        self.assert_read_only_review("agent", headerless=True)

    def test_agent_role_person_has_guidance_instead_of_confirmation(self):
        """A named person assigned the agent role still cannot approve a result."""
        self.assert_read_only_review("agent")

    def test_viewer_has_guidance_instead_of_confirmation(self):
        """A viewer can inspect the actual change without receiving a write control."""
        self.assert_read_only_review("viewer")

    def test_human_editor_can_confirm_the_result_from_the_changes_guide(self):
        """The person-only guide action completes the reviewed pin in the real store."""
        pid = self.reviewed_pin()
        page = self.open(0, lang="en")
        self.assertTrue(page.locator("#review-pins [data-act=confirm]").is_visible())
        page.locator("#review-pins [data-act=change]").click()
        page.wait_for_selector("#revision-pin [data-act=confirm]")
        page.locator("#revision-pin [data-act=confirm]").click()
        page.wait_for_function("!document.body.classList.contains('revision-open')")
        page.wait_for_function("!CONFIRMING.size", timeout=10000)
        pin = find_record(ps.APP.snapshot_pins(), pid)
        self.assertFalse(pin.get("review", False))
        self.assertEqual(pin["confirmed_by"]["login"], "alice@example.com")

    def test_keyboard_reaches_and_activates_pdf_badges_without_creating_a_selection(self):
        """Tab reaches a named badge, and Enter and Space reveal its card while leaving persisted pins unchanged."""
        pid = add_pin(
            {
                "file": str(self.main),
                "lo": 5,
                "hi": 5,
                "page": 1,
                "note": "Keyboard target",
                "frac": [0.1, 0.2, 0.4, 0.03],
            },
            actor(ALICE),
        ).record["id"]
        page = self.open(1, lang="en")
        before = records(ps.APP.snapshot_pins())
        for _ in range(60):
            page.keyboard.press("Tab")
            if page.evaluate("document.activeElement.dataset.act==='mark-jump'"):
                break
        self.assertEqual(page.evaluate("document.activeElement.dataset.act"), "mark-jump")
        badge = page.get_by_role("button", name=f"Go to pin #{pid}")
        self.assertTrue(badge.is_visible())
        self.assertEqual(badge.evaluate("e=>e.getBoundingClientRect().width"), 22)
        for key in ("Enter", "Space"):
            page.locator("#open-toggle").click()
            badge.focus()
            page.keyboard.press(key)
            page.wait_for_selector(f'.pin[data-id="{pid}"].cur')
            self.assertEqual(page.locator("#open-toggle").get_attribute("aria-expanded"), "true")
            self.assertTrue(page.locator("#composer").is_hidden())
            self.assertEqual(records(ps.APP.snapshot_pins()), before)
