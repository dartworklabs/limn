"""The owner's access screen in Chromium, against the real handler and stores (helpers_browser.BrowserBase).

docs/superpowers/plans/2026-11-22-viewer-access-management.md Task 8; the rules are docs/handbook/viewer.md §접근 관리.
The screen is drawn for an owner only, and what a row may not use is not drawn at all: a hidden button would stay in
the document (the same rule as ViewerTrashControls in test_viewer_browser.py). The tailnet's people come from a stubbed
directory (ps.read_tailnet_directory), the real handler answers everything else.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_access.py
"""

import dataclasses
import json
from unittest import mock
from urllib.parse import urlparse

from limn.platform.tailnet import TailnetDirectory, TailnetUser, unavailable
from limn.security.access_store import write_access

from helpers import DEFAULT_ACCESS, ps, set_config
from helpers_access import ALICE, BOB, CAROL
from helpers_browser import BrowserBase, settle

OWNER = {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}
EDITOR = {"login": "bob@example.com", "name": "Bob Park", "role": "editor"}
VIEWER = {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"}
SECOND_OWNER = {"login": "frank@example.com", "name": "Frank Oh", "role": "owner"}
NEW_EDITOR = {"login": "gina@example.com", "name": "Gina Yoo", "role": "editor"}
LATE_EDITOR = {"login": "helen@example.com", "name": "Helen Suh", "role": "editor"}
# Holds the answer to GET /api/access until the test lets it go, so a read that lands late is a fact of the test
# rather than a matter of timing. Installed with evaluate (not a <script>), which the page's CSP allows.
HOLD_ACCESS_READ = """
window.__heldAccess = [];
const realFetch = window.fetch;
window.fetch = function (input, init) {
  const url = typeof input === 'string' ? input : input && input.url ? String(input.url) : '';
  if (window.__holdAccess && url.includes('/api/access')) {
    return new Promise((resolve, reject) => {
      window.__heldAccess.push(() => realFetch(input, init).then(resolve, reject));
    });
  }
  return realFetch(input, init);
};
"""
AGENT = {"login": "dave@example.com", "name": "Dave Choi", "role": "agent"}
CANDIDATES = TailnetDirectory(
    (TailnetUser("erin@example.com", "Erin Han", None), TailnetUser("gina@example.com", "Gina Yoo", None)), True, None
)
# The device classes a screen change is shown on (docs/handbook/workflow.md §화면 변경은 PoC를 먼저 보인다): a mouse on
# the desktop, touch everywhere else.
DEVICES = {
    "desktop 1440x900": {"viewport": {"width": 1440, "height": 900}},
    "phone 390x844": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True},
    "phone 320x720": {"viewport": {"width": 320, "height": 720}, "is_mobile": True, "has_touch": True},
    "tablet 768x1024": {"viewport": {"width": 768, "height": 1024}, "is_mobile": True, "has_touch": True},
    "tablet 1024x768": {"viewport": {"width": 1024, "height": 768}, "is_mobile": True, "has_touch": True},
    "fold outer 344x882": {"viewport": {"width": 344, "height": 882}, "is_mobile": True, "has_touch": True},
    "fold inner 673x841": {"viewport": {"width": 673, "height": 841}, "is_mobile": True, "has_touch": True},
    "fold inner 841x673": {"viewport": {"width": 841, "height": 673}, "is_mobile": True, "has_touch": True},
}
ROW_MOUSE, ROW_TOUCH = 48, 56  # a two-line row's height (tokens --row-h, --row-h-touch)


class AccessScreenBase(BrowserBase):
    """A run whose people.json holds ROWS and whose tailnet shows TAILNET; the viewer is WHO (the owner by default)."""

    WHO = ALICE
    ROWS = (OWNER, EDITOR, VIEWER)
    TAILNET = CANDIDATES
    MANAGED = False

    def setUp(self):
        """people.json, the access flag and the stubbed tailnet directory, all undone with the test."""
        super().setUp()
        self.write_people(self.ROWS)
        if self.MANAGED:
            write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
        patch = mock.patch.object(ps, "read_tailnet_directory", side_effect=lambda *_: self.TAILNET)
        patch.start()
        self.addCleanup(patch.stop)

    def write_people(self, rows):
        """people.json with exactly these rows."""
        ps.APP.C.people_file.write_text(json.dumps({"version": 1, "people": list(rows)}), encoding="utf-8")

    def open_screen(self, **device):
        """The viewer opened for the owner, [⋯] -> [접근 관리] pressed, and the dialog open with its body drawn."""
        page = self.open(0, **device)
        page.wait_for_selector("#m-access-host #m-access", state="attached")
        page.click("#btn-more")
        page.click("#m-access")
        page.wait_for_selector("#access[open] #access-body .acc-sec")
        settle(page)
        return page

    def count(self, page, selector):
        """How many elements of the document match selector, drawn or not."""
        return page.evaluate("s => document.querySelectorAll(s).length", selector)

    def row(self, login):
        """The selector of the member or candidate row of login."""
        return '#access-body .acc-row[data-login="%s"]' % login


class AccessAbsentForNonOwners(AccessScreenBase):
    """Anyone who does not own the instance has no entry, no dialog contents and no request for the screen."""

    def test_entry_point_absent_for_non_owner(self):
        """An editor and a viewer get no [접근 관리]: nothing is in the document to unhide, and /api/access is not asked."""
        for who in (BOB, CAROL):
            with self.subTest(who=who["Tailscale-User-Login"]):
                self.WHO = who
                asked = []
                page = self.open(0)
                page.on("request", lambda request, seen=asked: seen.append(request.url))
                page.reload()
                page.wait_for_function("typeof META!=='undefined' && META && META.me")
                settle(page)
                self.assertEqual(self.count(page, "#m-access, #m-access-n"), 0)
                self.assertEqual(page.evaluate("document.getElementById('m-access-host').childElementCount"), 0)
                self.assertFalse(page.evaluate("document.body.classList.contains('role-owner')"))
                self.assertEqual([url for url in asked if "/api/access" in url], [])

    def test_panel_controls_absent_for_non_owner(self):
        """The dialog is an empty shell for a non-owner: no heading, no row, no role control, no button, no field."""
        for who in (BOB, CAROL):
            with self.subTest(who=who["Tailscale-User-Login"]):
                self.WHO = who
                page = self.open(0)
                self.assertEqual(page.evaluate("document.getElementById('access').childElementCount"), 0)
                self.assertEqual(self.count(page, "#access *"), 0)
                self.assertEqual(self.count(page, '[data-act^="access"]'), 0)
                self.assertEqual(self.count(page, "#access-body, #acc-login, .acc-row, .acc-roles"), 0)

    def test_the_owner_has_the_entry_and_the_class(self):
        """The owner gets the entry (with the member count) and body.role-owner, as a viewer gets body.role-viewer."""
        page = self.open(0)
        page.wait_for_selector("#m-access", state="attached")
        self.assertTrue(page.evaluate("document.body.classList.contains('role-owner')"))
        self.assertFalse(page.evaluate("document.body.classList.contains('role-viewer')"))
        self.assertEqual(page.text_content("#m-access-n"), "3")


class AccessMembers(AccessScreenBase):
    """The members section: who has a role control and [빼기], and who has neither."""

    ROWS = (OWNER, EDITOR, VIEWER, SECOND_OWNER, AGENT)
    MANAGED = True

    def test_self_row_has_no_remove_control(self):
        """The owner's own row names the role as a word and draws no role control and no [빼기] - there is no element."""
        page = self.open_screen()
        own = self.row(OWNER["login"])
        self.assertEqual(self.count(page, own), 1)
        self.assertEqual(self.count(page, own + " .acc-roles, " + own + " button, " + own + " [data-act]"), 0)
        self.assertIn("소유자", page.inner_text(own))

    def test_last_owner_row_has_no_role_or_remove_control(self):
        """Every owner row and every agent row draws no control; a viewer and an editor row draw both."""
        page = self.open_screen()
        for member in (OWNER, SECOND_OWNER, AGENT):
            with self.subTest(member=member["login"]):
                row = self.row(member["login"])
                self.assertEqual(self.count(page, row + " button, " + row + " [role=radio], " + row + " [data-act]"), 0)
        for member in (EDITOR, VIEWER):
            with self.subTest(member=member["login"]):
                row = self.row(member["login"])
                self.assertEqual(self.count(page, row + ' [data-act="access-role"]'), 2)
                self.assertEqual(self.count(page, row + ' [data-act="access-remove"]'), 1)

    def test_the_sole_owner_has_no_controls_either(self):
        """With one owner and nobody else of that role, the only owner row is the reader's own, and it has none."""
        self.write_people((OWNER, EDITOR))
        page = self.open_screen()
        self.assertEqual(self.count(page, self.row(OWNER["login"]) + " button"), 0)
        self.assertEqual(self.count(page, self.row(EDITOR["login"]) + " button"), 3)

    def test_a_role_press_changes_the_member_on_a_managed_instance(self):
        """[편집] on a viewer's row asks the server, and the row is drawn again with that role chosen."""
        write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
        page = self.open_screen()
        row = self.row(VIEWER["login"])
        page.click(row + ' [data-act="access-role"][data-role="editor"]')
        page.wait_for_selector(row + ' [data-role="editor"][aria-checked="true"]')
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual({x["login"]: x["role"] for x in stored}[VIEWER["login"]], "editor")

    def test_remove_takes_the_row_away(self):
        """[빼기] removes the member from people.json and the row from the screen."""
        write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
        page = self.open_screen()
        page.click(self.row(EDITOR["login"]) + ' [data-act="access-remove"]')
        page.wait_for_selector(self.row(EDITOR["login"]), state="detached")
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertNotIn(EDITOR["login"], [x["login"] for x in stored])


class AccessTailnet(AccessScreenBase):
    """The tailnet section: who could be let in, and that the list is only part of the people."""

    MANAGED = True

    def test_tailnet_section_says_the_list_is_partial(self):
        """The section carries a line saying the list holds only people this server can see, above the candidates."""
        page = self.open_screen()
        section = page.locator("#access-body .acc-sec").nth(1)
        self.assertIn("테일넷에서 들이기", section.inner_text())
        self.assertIn("이 서버가 볼 수 있는 사람만", section.locator(".acc-note").first.inner_text())
        self.assertEqual(self.count(page, self.row("erin@example.com")), 1)
        self.assertEqual(self.count(page, self.row("gina@example.com")), 1)

    def test_login_input_is_shown_when_the_list_is_empty(self):
        """With nobody to list (and with a daemon that could not be read), the login field is there, with the reason."""
        for directory, words in (
            (TailnetDirectory((), True, None), "들일 사람이 없습니다"),
            (unavailable("tailscaled_not_found"), "읽지 못했습니다"),
        ):
            with self.subTest(reason=directory.reason):
                self.TAILNET = directory
                page = self.open_screen()
                self.assertEqual(self.count(page, "#acc-login"), 1)
                self.assertEqual(self.count(page, '#access-body .acc-sec:nth-of-type(2) [data-act="access-admit"]'), 0)
                self.assertIn(words, page.inner_text("#access-body"))
                self.assertIn(
                    "이 서버가 볼 수 있는" if not directory.reason else "tailscaled_not_found",
                    page.inner_text("#access-body"),
                )

    def test_admitting_a_candidate_makes_a_member_with_the_chosen_role(self):
        """A candidate's own role chooser decides the role [들이기] sends; the screen then shows a member row."""
        page = self.open_screen()
        row = self.row("erin@example.com")
        page.click(row + ' [data-act="access-pick"][data-role="editor"]')
        page.click(row + ' [data-act="access-admit"]')
        page.wait_for_selector(row + ' [data-act="access-remove"]')
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual(
            {x["login"]: (x["role"], x["name"]) for x in stored}["erin@example.com"], ("editor", "Erin Han")
        )

    def test_a_typed_login_is_admitted_and_survives_a_role_press(self):
        """A role pressed beside the typed login does not erase it; [들이기] sends it, and the field is emptied."""
        page = self.open_screen()
        page.fill("#acc-login", "hana@example.com")
        page.click('#access-body .acc-add [data-act="access-typed-role"][data-role="editor"]')
        self.assertEqual(page.input_value("#acc-login"), "hana@example.com")
        page.click('#access-body .acc-add [data-act="access-add"]')
        page.wait_for_selector(self.row("hana@example.com"))
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual({x["login"]: x["role"] for x in stored}["hana@example.com"], "editor")
        self.assertEqual(page.input_value("#acc-login"), "")


class AccessUnmanaged(AccessScreenBase):
    """An instance that still runs on --allow: the band, the transition's two columns, and the refusals."""

    def test_the_band_offers_the_switch_and_a_managed_instance_says_its_mode(self):
        """Unmanaged: the band with [화면 관리로 전환]. Managed: no band, and the status line says so with the count."""
        page = self.open_screen()
        self.assertEqual(self.count(page, '#access-body .acc-band [data-act="access-manage"]'), 1)
        self.assertEqual(self.count(page, "#access-body .acc-status"), 0)
        write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
        page = self.open_screen()
        self.assertEqual(self.count(page, "#access-body .acc-band, #access-body [data-act=access-manage]"), 0)
        self.assertEqual(page.inner_text("#access-body .acc-status"), "화면에서 관리 중 · 멤버 3명")

    def test_the_transition_shows_both_columns_and_the_summary(self):
        """Two columns, the boxes only in the right one, the owner locked, and a summary that follows the boxes."""
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.wait_for_selector("#access-body .acc-cols")
        left = page.locator("#access-body .acc-col").nth(0)
        right = page.locator("#access-body .acc-col").nth(1)
        self.assertIn("지금 들어오는 사람", left.inner_text())
        self.assertIn("전환 뒤 들어오는 사람", right.inner_text())
        self.assertEqual(left.locator("input").count(), 0)
        self.assertEqual(right.locator("input[type=checkbox]").count(), 2)  # the editor and the viewer
        owner_line = right.locator(".acc-fixed")
        self.assertEqual(owner_line.count(), 1)
        self.assertEqual(owner_line.locator("input, button").count(), 0)  # locked: nothing to check
        self.assertIn("고정", owner_line.inner_text())
        self.assertEqual(page.inner_text(".acc-sum").replace("\n", " "), "3명 유지 · 0명 새로 들어옴")
        page.uncheck('input[data-acc-check="carol@example.com"]')
        self.assertEqual(page.inner_text(".acc-sum").replace("\n", " "), "2명 유지 · 0명 새로 들어옴")

    def test_an_allow_login_with_no_row_is_shown_checked_and_kept(self):
        """The co-author only --allow names has no people.json row, so the server sends a settable row of its own. He
        is in both columns, his box starts checked (seeded from admitted_today), and the default press writes his row
        rather than taking his access away."""
        set_config(allow=frozenset({OWNER["login"], "dana@example.com"}))
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.wait_for_selector("#access-body .acc-cols")
        left = page.locator("#access-body .acc-col").nth(0)
        right = page.locator("#access-body .acc-col").nth(1)
        self.assertIn("dana@example.com", left.inner_text())
        self.assertIn("dana@example.com", right.inner_text())
        self.assertTrue(page.is_checked('input[data-acc-check="dana@example.com"]'))
        self.assertFalse(page.is_checked('input[data-acc-check="%s"]' % EDITOR["login"]))  # --allow leaves him out
        self.assertEqual(page.inner_text(".acc-sum").replace("\n", " "), "2명 유지 · 0명 새로 들어옴")
        page.click('[data-act="access-manage-apply"]')
        page.wait_for_selector("#access-body .acc-status")
        rows = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual(
            sorted((x["login"], x.get("role")) for x in rows),
            [(OWNER["login"], "owner"), ("dana@example.com", "editor")],
        )

    def test_applying_the_transition_manages_the_instance_with_the_checked_people(self):
        """[화면 관리로 전환] sends the checked rows; the screen then reads as a managed instance and the flag is on."""
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.uncheck('input[data-acc-check="carol@example.com"]')
        page.click('[data-act="access-manage-apply"]')
        page.wait_for_selector("#access-body .acc-status")
        self.assertEqual(page.inner_text("#access-body .acc-status"), "화면에서 관리 중 · 멤버 2명")
        logins = [x["login"] for x in json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]]
        self.assertEqual(sorted(logins), sorted([EDITOR["login"], OWNER["login"]]))

    def test_the_result_after_the_press_is_the_servers_count_by_login(self):
        """With --allow naming two people, ticking a third lets her in newly: after the press the screen reads the server's
        added / removed / kept / newly_admitted (by login), not the preview's count."""
        set_config(allow=frozenset({OWNER["login"], EDITOR["login"]}))
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.check('input[data-acc-check="carol@example.com"]')
        self.assertEqual(page.inner_text(".acc-sum").replace("\n", " "), "2명 유지 · 1명 새로 들어옴")
        page.click('[data-act="access-manage-apply"]')
        page.wait_for_selector("#access-body .acc-result")
        result = page.inner_text("#access-body .acc-result")
        self.assertIn("화면 관리로 전환했습니다", result)
        self.assertIn("서버가 새로 들어오게 한 사람: carol@example.com", result.replace("\n", " "))
        self.assertIn("alice@example.com", page.inner_text("#access-body .acc-res li:nth-child(4)"))  # kept
        self.assertEqual(self.count(page, "#access-body .acc-result .acc-new"), 1)  # it matched the preview
        page.click(self.row("carol@example.com") + ' [data-act="access-role"][data-role="editor"]')
        page.wait_for_selector(self.row("carol@example.com") + ' [data-role="editor"][aria-checked="true"]')
        self.assertEqual(self.count(page, "#access-body .acc-result"), 0)  # the next change clears it

    def test_cancel_returns_to_the_lists(self):
        """[취소] leaves the transition and draws the lists again, with the band."""
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.click('[data-act="access-manage-cancel"]')
        page.wait_for_selector("#access-body .acc-band")
        self.assertEqual(self.count(page, "#access-body .acc-cols"), 0)

    def test_the_unmanaged_screen_offers_nothing_the_server_would_refuse(self):
        """While --allow decides, the members are there to read and no control of a row, no candidate, no login field is
        drawn: [data-act] exists only in the band, and the one action is [화면 관리로 전환]."""
        page = self.open_screen()
        self.assertEqual(self.count(page, "#access-body .acc-row [data-act], #access-body .acc-row button"), 0)
        self.assertEqual(self.count(page, "#access-body .acc-roles, #acc-login, .acc-add, .acc-sec + .acc-sec"), 0)
        self.assertEqual(self.count(page, self.row("erin@example.com")), 0)  # no candidate row
        self.assertEqual(self.count(page, self.row(EDITOR["login"])), 1)  # the member is listed
        self.assertIn("편집", page.inner_text(self.row(EDITOR["login"])))
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#access-body [data-act]')].map(e => e.dataset.act)"),
            ["access-manage"],
        )

    def test_the_band_says_only_what_is_true_of_this_instance(self):
        """The headline claims no option: with no list it does not say --allow, and the line under it names the state the
        instance is in - nobody listed (anyone on the tailnet comes in), --allow with its list, or --members-only."""
        cases = (
            ("no list", {}, "지금은 테일넷의 누구나 들어옵니다", False),
            ("--allow", {"allow": frozenset({OWNER["login"]})}, "--allow " + OWNER["login"], True),
            (
                "--members-only",
                {"access": dataclasses.replace(DEFAULT_ACCESS, members_only=True)},
                "--members-only",
                False,
            ),
        )
        for name, config, sub, names_allow in cases:
            with self.subTest(state=name):
                set_config(**config)
                page = self.open_screen()
                head = page.inner_text("#access-body .acc-band-t").split("\n")[0]
                self.assertNotIn("--allow", head)
                self.assertNotIn("--members-only", head)
                self.assertIn(sub, page.inner_text("#access-body .acc-band-s"))
                self.assertEqual("--allow" in page.inner_text("#access-body .acc-band"), names_allow)
                page.click('[data-act="access-manage"]')
                page.wait_for_selector("#access-body .acc-cols")
                everyone = "누구나" in page.inner_text("#access-body .acc-tr")
                self.assertEqual(everyone, name == "no list")  # the transition says it only where it holds
                set_config(access=DEFAULT_ACCESS, allow=frozenset())


class AccessOff(AccessScreenBase):
    """Turning management off: the action the managed screen offers, the comparison it opens (the switch's shape, the
    columns reading the other way), the owner's own loss, and the press."""

    MANAGED = True

    def open_off(self, **device):
        """The screen open on the off comparison."""
        page = self.open_screen(**device)
        page.click('[data-act="access-off"]')
        page.wait_for_selector("#access-body .acc-cols")
        settle(page)
        return page

    def flag(self):
        """What access.json says now, or None when it is not there."""
        if not ps.APP.C.access_file.exists():
            return None
        return json.loads(ps.APP.C.access_file.read_text(encoding="utf-8"))["managed"]

    def test_the_managed_screen_offers_the_action(self):
        """A managed instance says how it decides admission and offers the one change to that: turning it off."""
        page = self.open_screen()
        self.assertEqual(page.inner_text("#access-body .acc-status"), "화면에서 관리 중 · 멤버 3명")
        self.assertEqual(self.count(page, '#access-body .acc-managed [data-act="access-off"]'), 1)
        self.assertEqual(self.count(page, "#access-body .acc-cols"), 0)

    def test_the_comparison_reads_from_the_member_list_to_the_run_arguments(self):
        """Two sections, two columns, as the switch has - the left one the member list that decides now, the right one
        the --allow the run would go back to. No checkbox: turning off changes no row."""
        set_config(allow=frozenset({OWNER["login"], "dana@example.com"}))
        page = self.open_off()
        left = page.locator("#access-body .acc-col").nth(0)
        right = page.locator("#access-body .acc-col").nth(1)
        self.assertIn("지금 들어오는 사람", left.inner_text())
        self.assertIn("끈 뒤 들어오는 사람", right.inner_text())
        self.assertEqual(page.locator("#access-body input").count(), 0)
        self.assertIn(EDITOR["login"], left.inner_text())
        self.assertIn("dana@example.com", right.inner_text())
        self.assertNotIn(EDITOR["login"], right.inner_text())
        body = page.inner_text("#access-body .acc-tr").replace("\n", " ")
        self.assertIn("새로 들어오게 되는 사람: dana@example.com", body)
        self.assertIn("못 들어오게 되는 사람: %s, %s" % (EDITOR["login"], VIEWER["login"]), body)
        self.assertIn("1명 유지 · 1명 새로 들어옴 · 2명 못 들어옴", body)

    def test_an_open_instance_says_after_is_everyone_not_an_empty_column(self):
        """With neither --allow nor --members-only, turning management off reopens the instance to every login the
        tailnet identifies. The column says that in words - it cannot be a list."""
        page = self.open_off()
        right = page.locator("#access-body .acc-col").nth(1)
        self.assertIn("신원 헤더가 확인한 테일넷의 모두", right.inner_text())
        self.assertEqual(right.locator(".acc-check").count(), 0)
        body = page.inner_text("#access-body .acc-tr").replace("\n", " ")
        self.assertIn("이 실행에는 목록이 없어", body)
        self.assertIn("3명 유지 · 그 밖의 모두도 들어옴", body)

    def test_an_allow_list_of_only_unusable_logins_is_not_called_empty(self):
        """--allow is not validated at startup, so a run can hold entries no person could hold. Nobody gets in once the
        flag is off, but the list is not empty, and the screen must not say it is."""
        set_config(allow=frozenset({"has space"}))
        page = self.open_off()
        right = page.locator("#access-body .acc-col").nth(1)
        self.assertIn("아무도 들어오지 못합니다", right.inner_text())
        self.assertNotIn("비어 있습니다", right.inner_text())
        self.assertIn("로그인이 없습니다", right.inner_text())
        self.assertEqual(right.locator(".acc-check").count(), 0)

    def test_the_owners_own_loss_is_said_before_the_press(self):
        """--allow names the editor only: once the flag is off the owner's row grants her nothing. The screen says so
        and does not offer the press, which the server would refuse (409 locks_out_owner)."""
        set_config(allow=frozenset({EDITOR["login"]}))
        page = self.open_off()
        self.assertIn("당신도 들어올 수 없게 됩니다", page.inner_text("#access-body .acc-warn"))
        self.assertEqual(self.count(page, '#access-body [data-act="access-off-apply"]'), 0)
        self.assertEqual(self.count(page, '#access-body [data-act="access-off-cancel"]'), 1)
        self.assertEqual(self.flag(), True)

    def test_the_press_sends_no_member_list_and_reports_what_the_server_said(self):
        """The press turns the flag off, leaves every row standing, and the screen reads the server's own answer."""
        set_config(allow=frozenset({OWNER["login"], "dana@example.com"}))
        page = self.open_off()
        page.click('[data-act="access-off-apply"]')
        page.wait_for_selector("#access-body .acc-result")
        result = page.inner_text("#access-body .acc-result").replace("\n", " ")
        self.assertIn("접근 관리를 껐습니다", result)
        self.assertIn("서버가 새로 들어오게 한 사람: dana@example.com", result)
        self.assertEqual(self.flag(), False)
        rows = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual([x["login"] for x in rows], [x["login"] for x in self.ROWS])
        page.wait_for_selector("#access-body .acc-band")  # the instance runs on --allow again
        self.assertEqual(self.count(page, '#access-body [data-act="access-manage"]'), 1)

    def test_cancel_returns_to_the_lists(self):
        page = self.open_off()
        page.click('[data-act="access-off-cancel"]')
        page.wait_for_selector("#access-body .acc-status")
        self.assertEqual(self.count(page, "#access-body .acc-cols"), 0)
        self.assertEqual(self.flag(), True)

    def test_english_has_no_korean_left(self):
        """Every word of the off comparison has an English pair too."""
        page = self.open(0, lang="en")
        page.wait_for_selector("#m-access", state="attached")
        page.click("#btn-more")
        page.click("#m-access")
        page.wait_for_selector("#access[open] #access-body .acc-sec")
        page.click('[data-act="access-off"]')
        page.wait_for_selector("#access-body .acc-cols")
        self.assertEqual([c for c in page.inner_text("#access") if "가" <= c <= "힣"], [])


class AccessRefusals(AccessScreenBase):
    """What goes wrong after a press is told inside the dialog, and the screen never shows a world the server left."""

    MANAGED = True
    fail = None  # the (method, path) the next request to answers with a 500, or None
    fail_reads = False

    def route(self, route):
        """BrowserBase's routing, except that FAIL's request gets a 500 and, once fail_reads, so does GET /api/access."""
        request = route.request
        path = urlparse(request.url).path
        if (request.method, path) == self.fail:
            return route.fulfill(status=500, content_type="application/json", body='{"error": "boom"}')
        if self.fail_reads and (request.method, path) == ("GET", "/api/access"):
            return route.abort()
        return super().route(route)

    def test_a_refusal_is_drawn_inside_the_dialog(self):
        """The server refuses to add a login that is already a member (409 already_member); the reason is in the dialog,
        where a modal leaves it readable, and not on the pin panel behind it."""
        page = self.open_screen()
        page.fill("#acc-login", EDITOR["login"])
        page.click('#access-body .acc-add [data-act="access-add"]')
        page.wait_for_selector("#access-body .acc-err")
        self.assertIn("멤버 들이기", page.inner_text("#access-body .acc-err"))
        self.assertIn(EDITOR["login"], page.inner_text("#access-body .acc-err"))
        self.assertEqual(self.count(page, "#access #access-body .acc-err[role=alert]"), 1)

    def test_a_server_error_is_drawn_inside_the_dialog_too(self):
        """A 500 is no refusal; it still lands in the dialog (the status line stands under the modal), not as a banner."""
        self.fail = ("POST", "/api/members/remove")
        page = self.open_screen()
        page.click(self.row(EDITOR["login"]) + ' [data-act="access-remove"]')
        page.wait_for_selector("#access-body .acc-err")
        self.assertIn("멤버 빼기", page.inner_text("#access-body .acc-err"))
        self.assertEqual(
            self.count(page, self.row(EDITOR["login"])), 1
        )  # nothing was removed, nothing drawn as removed

    def test_reopening_the_dialog_reads_the_store_again(self):
        """The other door: `limn member` (or another tab) changes people.json while this page sits open. Reopening the
        dialog has to show what the store holds now - a member added meanwhile, and no row for one taken away - without
        a page reload. Nothing failed here, so a reopen that only read again on STALE would draw the boot's lists."""
        page = self.open_screen()
        self.assertEqual(self.count(page, self.row(VIEWER["login"])), 1)
        self.write_people([OWNER, EDITOR, SECOND_OWNER])  # carol gone, frank arrived, as `limn member` would leave it
        page.keyboard.press("Escape")
        page.click("#btn-more")
        page.click("#m-access")
        page.wait_for_selector(self.row(SECOND_OWNER["login"]))
        self.assertEqual(self.count(page, self.row(VIEWER["login"])), 0)
        self.assertEqual(self.count(page, "#access-body .acc-err"), 0)

    def test_a_late_read_leaves_the_owners_choices_alone(self):
        """The read every open sends can land after the owner has gone on to the transition screen and changed a
        check. Their choices are their own: the late answer does not reset them, and a row the screen did not have
        before arrives at the default the no-op rule gives it (checked, because today's admission lets it in)."""
        ps.APP.C.access_file.unlink()  # the transition screen exists only while the instance is unmanaged
        page = self.open_screen()
        page.evaluate(HOLD_ACCESS_READ)
        page.keyboard.press("Escape")
        self.write_people([OWNER, EDITOR, VIEWER, NEW_EDITOR])  # another door adds a member while this one is shut
        page.evaluate("window.__holdAccess = true")
        page.click("#btn-more")
        page.click("#m-access")
        page.click('[data-act="access-manage"]')
        page.uncheck('input[data-acc-check="%s"]' % EDITOR["login"])
        page.evaluate("window.__holdAccess = false; window.__heldAccess.splice(0).forEach((go) => go())")
        page.wait_for_selector('input[data-acc-check="%s"]' % NEW_EDITOR["login"])
        self.assertFalse(page.is_checked('input[data-acc-check="%s"]' % EDITOR["login"]))
        self.assertTrue(page.is_checked('input[data-acc-check="%s"]' % NEW_EDITOR["login"]))
        self.assertTrue(page.is_checked('input[data-acc-check="%s"]' % VIEWER["login"]))

    def test_closing_and_reopening_keeps_what_the_owner_unchecked(self):
        """Escape is not a decision. The owner unchecks a row, closes the dialog without pressing and opens it
        again: the read that every open sends brings the rows up to date, and their uncheck is still theirs.
        Rebuilding every check from admitted_today on each open would put that row back without a word."""
        ps.APP.C.access_file.unlink()
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        page.uncheck('input[data-acc-check="%s"]' % EDITOR["login"])
        page.keyboard.press("Escape")
        self.write_people([OWNER, EDITOR, VIEWER, NEW_EDITOR])  # so the reopen's read is visible when it lands
        page.click("#btn-more")
        page.click("#m-access")
        page.click('[data-act="access-manage"]')
        page.wait_for_selector('input[data-acc-check="%s"]' % NEW_EDITOR["login"])
        self.assertFalse(page.is_checked('input[data-acc-check="%s"]' % EDITOR["login"]))
        self.assertTrue(page.is_checked('input[data-acc-check="%s"]' % VIEWER["login"]))
        self.assertTrue(page.is_checked('input[data-acc-check="%s"]' % NEW_EDITOR["login"]))

    def test_a_kept_check_sends_the_role_the_row_shows_now(self):
        """A check that survives a reopen says "keep this person", not "keep the role I saw". Another door makes
        the member an editor while the dialog is shut; the row then says so, and the press sends that role, which
        leaves the store as it stands. Sending the role remembered from when the box was ticked would quietly
        undo the other door's change."""
        ps.APP.C.access_file.unlink()
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        box = 'input[data-acc-check="%s"]' % VIEWER["login"]
        page.uncheck(box)
        page.check(box)  # a decision of the owner's own now, not the default
        page.keyboard.press("Escape")
        self.write_people([OWNER, EDITOR, dict(VIEWER, role="editor")])  # the other door promotes them
        page.click("#btn-more")
        page.click("#m-access")
        page.click('[data-act="access-manage"]')
        page.wait_for_selector('label.acc-check:has(%s) .acc-seen:text-is("편집")' % box)
        self.assertTrue(page.is_checked(box))
        page.click('[data-act="access-manage-apply"]')
        page.wait_for_selector("#access-body .acc-status")
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertEqual([x["role"] for x in stored if x["login"] == VIEWER["login"]], ["editor"])

    def test_two_reads_in_flight_do_not_hand_back_a_row_the_owner_unchecked(self):
        """An open, a close and another open leave two reads in flight. The first brings in a member another door
        added and the owner unchecks them; the second must not offer that row again as one the screen has not
        seen. Measuring what the screen held when the request went out, instead of when its answer lands, is what
        gets this wrong: the second request went out before the first answer existed."""
        ps.APP.C.access_file.unlink()
        page = self.open_screen()
        page.evaluate(HOLD_ACCESS_READ)
        page.keyboard.press("Escape")
        self.write_people([OWNER, EDITOR, VIEWER, NEW_EDITOR])
        page.evaluate("window.__holdAccess = true")
        page.click("#btn-more")
        page.click("#m-access")  # the first read, held
        page.keyboard.press("Escape")
        page.click("#btn-more")
        page.click("#m-access")  # the second read, held, sent before the first has an answer
        page.click('[data-act="access-manage"]')
        page.evaluate("window.__heldAccess.shift()()")  # the first answer: the new member arrives, checked
        page.wait_for_selector('input[data-acc-check="%s"]' % NEW_EDITOR["login"])
        page.uncheck('input[data-acc-check="%s"]' % NEW_EDITOR["login"])
        self.write_people([OWNER, EDITOR, VIEWER, NEW_EDITOR, LATE_EDITOR])  # so the second answer is visible
        page.evaluate("window.__heldAccess.shift()()")
        page.wait_for_selector('input[data-acc-check="%s"]' % LATE_EDITOR["login"])
        self.assertFalse(page.is_checked('input[data-acc-check="%s"]' % NEW_EDITOR["login"]))
        self.assertTrue(page.is_checked('input[data-acc-check="%s"]' % LATE_EDITOR["login"]))

    def test_a_write_whose_read_back_fails_does_not_draw_the_old_lists(self):
        """The remove went through and the read after it fails: the old rows (and the removed member among them) are not
        drawn, the owner is told the change was made, and a reopen reads again."""
        page = self.open_screen()
        self.fail_reads = True
        page.click(self.row(EDITOR["login"]) + ' [data-act="access-remove"]')
        page.wait_for_selector("#access-body .acc-err")
        self.assertIn("바뀌었지만", page.inner_text("#access-body .acc-err"))
        self.assertEqual(self.count(page, "#access-body .acc-row, #access-body .acc-sec"), 0)
        stored = json.loads(ps.APP.C.people_file.read_text(encoding="utf-8"))["people"]
        self.assertNotIn(EDITOR["login"], [x["login"] for x in stored])
        self.fail_reads = False
        page.keyboard.press("Escape")
        page.click("#btn-more")
        page.click("#m-access")
        page.wait_for_selector("#access-body .acc-sec")
        self.assertEqual(self.count(page, self.row(EDITOR["login"])), 0)
        self.assertEqual(self.count(page, "#access-body .acc-err"), 0)

    def test_a_switch_whose_read_back_fails_does_not_offer_the_switch_again(self):
        """The switch went through; the read after it fails: no transition columns, no band, the server's result shown."""
        ps.APP.C.access_file.unlink()  # this one starts on an instance that still runs on --allow
        page = self.open_screen()
        page.click('[data-act="access-manage"]')
        self.fail_reads = True
        page.click('[data-act="access-manage-apply"]')
        page.wait_for_selector("#access-body .acc-result")
        self.assertEqual(self.count(page, '#access-body [data-act^="access-manage"], #access-body .acc-cols'), 0)
        self.assertIn("바뀌었지만", page.inner_text("#access-body .acc-err"))

    def test_the_focus_stays_in_the_dialog_after_a_draw(self):
        """A press that redraws the screen (a role picked on a candidate) leaves the focus on the same control."""
        page = self.open_screen()
        control = self.row("erin@example.com") + ' [data-act="access-pick"][data-role="editor"]'
        page.focus(control)
        page.keyboard.press("Enter")
        page.wait_for_selector(control + '[aria-checked="true"]')
        self.assertTrue(page.evaluate("s => document.activeElement === document.querySelector(s)", control))


class AccessDialog(AccessScreenBase):
    """The dialog's own behaviour: Escape, a click outside, Tab."""

    def test_escape_and_backdrop_close_the_panel(self):
        """Esc closes it on the desktop; a click on the backdrop closes it on the desktop and on a phone's sheet."""
        for name in ("desktop 1440x900", "phone 390x844"):
            with self.subTest(device=name):
                page = self.open_screen(**DEVICES[name])
                page.keyboard.press("Escape")
                page.wait_for_function("!document.getElementById('access').open")
                page = self.open_screen(**DEVICES[name])
                page.mouse.click(4, 4)  # outside the card (desktop) and above the sheet (phone)
                page.wait_for_function("!document.getElementById('access').open")

    def test_tab_stays_inside_the_panel(self):
        """Tab and Shift+Tab, past the last control and the first, never leave the dialog."""
        page = self.open_screen()
        for key in ["Tab"] * 40 + ["Shift+Tab"] * 40:
            page.keyboard.press(key)
            self.assertTrue(
                page.evaluate("!!document.activeElement && !!document.activeElement.closest('#access')"), key
            )

    def test_the_dialog_is_a_labelled_modal(self):
        """The dialog is named by its heading and takes the focus when it opens."""
        page = self.open_screen()
        self.assertEqual(page.get_attribute("#access", "aria-labelledby"), "access-h")
        self.assertEqual(page.inner_text("#access-h"), "접근 관리")
        self.assertTrue(page.evaluate("document.activeElement === document.getElementById('access')"))

    def test_english_has_no_korean_left(self):
        """In English every word of the screen is the English table's, the transition's too."""
        for managed in (False, True):
            with self.subTest(managed=managed):
                if managed:
                    write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
                page = self.open(0, lang="en")
                page.wait_for_selector("#m-access", state="attached")
                page.click("#btn-more")
                page.click("#m-access")
                page.wait_for_selector("#access[open] #access-body .acc-sec")
                text = page.inner_text("#access") + page.get_attribute("#m-access", "data-tip")
                self.assertEqual([c for c in text if "가" <= c <= "힣"], [])
                if not managed:
                    page.click('[data-act="access-manage"]')
                    page.wait_for_selector("#access-body .acc-cols")
                    self.assertEqual([c for c in page.inner_text("#access") if "가" <= c <= "힣"], [])


class AccessLayout(AccessScreenBase):
    """The screen at the device classes: nothing overflows or is clipped, and a row is as tall as the pointer needs."""

    ROWS = (OWNER, EDITOR, VIEWER, AGENT)

    MEASURE = """() => {
        const dialog = document.getElementById('access'), box = dialog.getBoundingClientRect();
        const outside = [], clipped = [];
        for (const el of dialog.querySelectorAll('*')) {
            const r = el.getBoundingClientRect();
            if (!r.width && !r.height) continue;
            if (r.left < box.left - 0.5 || r.right > box.right + 0.5)
                outside.push((el.className || el.tagName) + ' ' + Math.round(r.left) + '..' + Math.round(r.right));
            if (el.matches('button, label, .acc-seen, .acc-role-fixed, .acc-h, .acc-note') && el.scrollWidth > el.clientWidth + 1)
                clipped.push((el.className || el.tagName) + ' ' + el.scrollWidth + '>' + el.clientWidth);
        }
        const rows = [...dialog.querySelectorAll('.acc-row, .acc-check')].map((e) => e.getBoundingClientRect().height);
        const marks = [...dialog.querySelectorAll('button, input')].map((e) => [e.className || e.type, Math.round(e.getBoundingClientRect().height * 10) / 10, e.getBoundingClientRect().width]);
        return {
            overflowX: dialog.scrollWidth - dialog.clientWidth,
            pageOverflowX: document.documentElement.scrollWidth - window.innerWidth,
            inView: box.left >= -0.5 && box.right <= window.innerWidth + 0.5 && box.top >= -0.5 && box.bottom <= window.innerHeight + 0.5,
            outside, clipped, rows, marks,
            coarse: matchMedia('(pointer: coarse)').matches,
        };
    }"""

    def write_flag(self, managed):
        """The instance managed from the viewer, or not (the flag file there, or not)."""
        if managed:
            write_access(ps.APP.C.access_file, True, "2026-11-23 10:00:00", OWNER["login"])
        elif ps.APP.C.access_file.exists():
            ps.APP.C.access_file.unlink()

    def check(self, page, where):
        """The measurements of the open dialog, held to the rules; where names the device and state for a failure."""
        got = page.evaluate(self.MEASURE)
        self.assertLessEqual(got["overflowX"], 0, where)
        self.assertLessEqual(got["pageOverflowX"], 0, where)
        self.assertTrue(got["inView"], where)
        self.assertEqual(got["outside"], [], where)
        self.assertEqual(got["clipped"], [], where)
        floor = ROW_TOUCH if got["coarse"] else ROW_MOUSE
        self.assertTrue(got["rows"], where)
        for height in got["rows"]:
            self.assertGreaterEqual(round(height, 1), floor, where)
        # a thumb presses every button and field at --hit; the checkboxes are pressed through their 56px row
        pressed = [m for m in got["marks"] if m[0] != "checkbox"]
        self.assertTrue(pressed, where)
        for kind, height, _ in pressed:
            self.assertGreaterEqual(height, 44 if got["coarse"] else 24, "%s: a %s is %s tall" % (where, kind, height))
        if not got["coarse"]:
            self.assertEqual({round(h) for h in got["rows"]} & {ROW_MOUSE}, {ROW_MOUSE}, where)
        return got

    def test_layout_at_four_device_classes(self):
        """The lists, both directions' comparisons, and a managed instance fit and clip nothing on every device class,
        in both languages."""
        for name, device in DEVICES.items():
            for managed in (False, True):
                with self.subTest(device=name, managed=managed):
                    self.write_flag(managed)
                    page = self.open_screen(**device)
                    self.check(page, "%s managed=%s" % (name, managed))
                    page.click('[data-act="%s"]' % ("access-off" if managed else "access-manage"))
                    page.wait_for_selector("#access-body .acc-cols")
                    self.check(page, "%s %s" % (name, "off" if managed else "transition"))
                    page.close()
