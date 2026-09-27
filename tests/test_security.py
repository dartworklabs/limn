"""Security hardening through the real handler: dot-named files and a state folder placed inside the manuscript stay
out of every route that reads a named manuscript file, an unusable people.json fails closed, and every response forbids
framing.

Each class drives the request handler over a socketpair as a tailnet person or the agent (helpers_access.AccessBase),
so what is pinned is what a client sees: status, reason and body, the response headers, and the bytes left on disk.
The module rules underneath are pinned on their own in test_web_parse.py (FileInTree), test_locate.py (DotPaths,
StateFolderPaths), test_build_copy.py (StateFolderCopy), test_startup.py (StatePlacement), test_people.py (Unreadable)
and test_access_module.py (UnreadableRoles).

Run: uv run pytest -q tests/test_security.py
"""

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from limn import access
from limn.cli import cli_audit

from helpers import DEFAULT_ACCESS, ps, req, set_config, split_resp
from helpers_access import ALICE, BOB, CAROL, AccessBase, talk_to

SECRET = "url = https://alice:hunter2@example.com/repo.git"


class DotPaths(AccessBase):
    """GET /api/snippet, GET /api/overlaps, POST /api/pin, an edit's loc and a close's changes refuse a file under a
    dot-named part of the manuscript tree with the reason they already give for a file outside it, and never quote it."""

    def setUp(self):
        """A manuscript holding .git/config, a nested sub/.git/config and .env (each with SECRET), a normal-looking
        link into .git, and a link out of the tree; Bob is a viewer, Alice the default editor."""
        super().setUp()
        for rel in (".git/config", "sub/.git/config", ".env"):
            p = self.src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("[remote]\n" + SECRET + "\n", encoding="utf-8")
        (self.src / "notes.tex").symlink_to(self.src / ".git" / "config")
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text(SECRET + "\n", encoding="utf-8")
        (self.src / "away.tex").symlink_to(outside)
        self.names = (".git/config", "sub/.git/config", ".env", "notes.tex", "away.tex", str(self.src / ".env"))
        self.set_people([{"login": "bob@example.com", "name": "Bob Park", "role": "viewer"}])

    def refused(self, code, d, reason, name):
        """The answer is a 400 with reason and never carries the secret."""
        self.assertEqual((code, d.get("reason")), (400, reason), name)
        self.assertNotIn("hunter2", json.dumps(d), name)

    def test_a_viewer_cannot_read_a_dot_file_through_snippet_or_overlaps(self):
        """Both GET routes answer 400 file_outside_manuscript for every dot path and link; main.tex still reads."""
        for route in ("/api/snippet", "/api/overlaps"):
            for name in self.names:
                code, d = self.call("GET", "%s?file=%s&lo=1&hi=2" % (route, quote(name)), headers=BOB)
                self.refused(code, d, "file_outside_manuscript", (route, name))
            code, _ = self.call("GET", "%s?file=main.tex&lo=1&hi=2" % route, headers=BOB)
            self.assertEqual(code, 200, route)

    def test_a_new_pin_cannot_name_a_dot_file(self):
        """POST /api/pin answers 400 file_outside_manuscript and stores nothing, so pins.md never quotes the file."""
        for name in self.names:
            code, d = self.call("POST", "/api/pin", {"file": name, "lo": 1, "hi": 2, "page": 1, "note": "n"}, ALICE)
            self.refused(code, d, "file_outside_manuscript", name)
        self.assertEqual(ps.snapshot_pins(), [])
        self.assertFalse(ps.C.pins_md.exists() and "hunter2" in ps.C.pins_md.read_text(encoding="utf-8"))

    def test_an_edit_cannot_move_a_pin_onto_a_dot_file(self):
        """An edit's loc naming a dot file is 400 file_outside_manuscript; the pin keeps its place."""
        pid = self.pin_id(ALICE)
        for name in self.names:
            code, d = self.call(
                "POST",
                "/api/pins/%d/edit" % pid,
                {"loc": {"file": name, "lo": 1, "hi": 2}, "base_rev": self.pin(pid)["rev"]},
                ALICE,
            )
            self.refused(code, d, "file_outside_manuscript", name)
        self.assertEqual(Path(self.pin(pid)["file"]).name, "main.tex")

    def test_a_close_cannot_record_a_dot_file_as_a_change(self):
        """A close whose changes name .env or a nested .git is 400 change_outside_manuscript and leaves the pin open."""
        pid = self.pin_id(ALICE)
        for name in (".env", "sub/.git/config"):
            code, d = self.call("POST", "/api/pins/%d/close" % pid, {"changes": [{"file": name, "lo": 1, "hi": 1}]})
            self.refused(code, d, "change_outside_manuscript", name)
        self.assertFalse(self.pin(pid).get("done"))


STATE_FILES = ("people.json", "tokens.json", "audit.jsonl", "events.jsonl", "pins.jsonl", "pins.md")


class StateFolderInManuscript(AccessBase):
    """--state-dir inside the manuscript under a normal (non-dot) name: every route that reads a named manuscript file
    refuses the state files (people.json, tokens.json's hashes, audit.jsonl, events.jsonl, the pin store) with the
    reason it gives for a file outside the tree, and never quotes them; the manuscript's own files still read."""

    def setUp(self):
        """The state folder is <manuscript>/limn-state and holds every state file: people.json (Bob a viewer), a token
        (tokens.json and its audit line), a pin by Alice (pins.jsonl, pins.md) and events.jsonl. notes.tex is a
        normal-looking link into it."""
        super().setUp()
        set_config(state=self.src / "limn-state")
        ps.C.state.mkdir()
        ps.init_seq()
        self.set_people([{"login": "bob@example.com", "name": "Bob Park", "role": "viewer"}])
        access.token_create(ps.C.state, "ci", cli_audit(ps.C.state))
        self.pid = self.pin_id(ALICE)
        if not ps.C.events_file.exists():
            ps.C.events_file.write_text('{"id": 1, "kind": "mention"}\n', encoding="utf-8")
        for name in STATE_FILES:
            self.assertTrue((ps.C.state / name).is_file(), name)
        (self.src / "notes.tex").symlink_to(ps.C.state / "people.json")
        self.names = tuple("limn-state/" + n for n in STATE_FILES) + (
            str(ps.C.state / "tokens.json"),
            "limn-state/../limn-state/audit.jsonl",
            "notes.tex",
        )

    def refused(self, code, d, reason, name):
        """The answer is a 400 with reason and quotes nothing of a state file (no token hash, no audit line)."""
        self.assertEqual((code, d.get("reason")), (400, reason), name)
        self.assertNotIn("sha256:", json.dumps(d), name)
        self.assertNotIn("token_created", json.dumps(d), name)

    def test_a_viewer_cannot_read_a_state_file_through_snippet_or_overlaps(self):
        """Both GET routes answer 400 file_outside_manuscript for every state file, by relative or absolute name or
        through a link; main.tex still reads."""
        for route in ("/api/snippet", "/api/overlaps"):
            for name in self.names:
                code, d = self.call("GET", "%s?file=%s&lo=1&hi=2" % (route, quote(name)), headers=BOB)
                self.refused(code, d, "file_outside_manuscript", (route, name))
            code, _ = self.call("GET", "%s?file=main.tex&lo=1&hi=2" % route, headers=BOB)
            self.assertEqual(code, 200, route)

    def test_a_new_pin_or_an_edit_cannot_name_a_state_file(self):
        """POST /api/pin and an edit's loc answer 400 file_outside_manuscript; no pin is added and Alice's pin keeps
        its place on main.tex."""
        for name in self.names:
            code, d = self.call("POST", "/api/pin", {"file": name, "lo": 1, "hi": 1, "page": 1, "note": "n"}, ALICE)
            self.refused(code, d, "file_outside_manuscript", name)
            code, d = self.call(
                "POST",
                "/api/pins/%d/edit" % self.pid,
                {"loc": {"file": name, "lo": 1, "hi": 1}, "base_rev": self.pin(self.pid)["rev"]},
                ALICE,
            )
            self.refused(code, d, "file_outside_manuscript", name)
        self.assertEqual([r["id"] for r in ps.snapshot_pins()], [self.pid])
        self.assertEqual(Path(self.pin(self.pid)["file"]).name, "main.tex")

    def test_a_close_cannot_record_a_state_file_as_a_change(self):
        """A close whose changes name a state file is 400 change_outside_manuscript and leaves the pin open."""
        for name in self.names:
            code, d = self.call(
                "POST", "/api/pins/%d/close" % self.pid, {"changes": [{"file": name, "lo": 1, "hi": 1}]}
            )
            self.refused(code, d, "change_outside_manuscript", name)
        self.assertFalse(self.pin(self.pid).get("done"))

    def test_startup_warns_about_the_folder_and_refuses_one_holding_the_document(self):
        """configure_run with --state-dir inside the manuscript starts and prints the one warning on stderr; with the
        manuscript folder itself as --state-dir it refuses before creating or using anything. It answers a value and
        binds nothing (start() binds C)."""
        src = self.src.resolve()

        def configure(state):
            """configure_run for `limn serve --manuscript <src> --state-dir <state>` -> (answer, stderr)."""
            a = ps.build_arg_parser().parse_args(["--manuscript", str(src), "--state-dir", str(state), "--no-build"])
            with mock.patch("sys.stderr", io.StringIO()) as err:
                return ps.configure_run(a, DEFAULT_ACCESS), err.getvalue()

        before = ps.C
        got, err = configure(src / "st2")
        self.assertIsInstance(got, ps.RunStart)
        self.assertEqual((got.config.state, got.config.build, got.docs), (src / "st2", src / "st2" / "build", None))
        self.assertEqual(err.count("warning:"), 1, err)
        self.assertIn("warning: the state folder %s is inside the manuscript %s" % (src / "st2", src), err)
        got, err = configure(src)
        self.assertIsInstance(got, ps.StartupRefused)
        self.assertIn("holds %s, a document this run serves" % (src / "main.tex"), got.message)
        self.assertIs(ps.C, before)  # configure_run changed nothing
        got, err = configure(src.parent / "beside")
        self.assertIsInstance(got, ps.RunStart)
        self.assertEqual(err, "")


GOOD = [
    {"login": "alice@example.com", "name": "Alice Kim", "role": "viewer"},
    {"login": "bob@example.com", "name": "Bob Park", "role": "owner"},
]
BROKEN = {
    "truncated": lambda good: good[: len(good) // 2],
    "invalid JSON": lambda good: b"{not json\n",
    "wrong shape": lambda good: json.dumps(GOOD).encode(),  # a bare list, not {"people": [...]}
    "not UTF-8": lambda good: b"\xff\xfe" + good,
    "empty": lambda good: b"",
}


class UnreadablePeople(AccessBase):
    """A people.json that exists but cannot be used fails closed: nobody gains a role, members-only admits nobody
    from it, no visit rewrites it, and the server recovers on its own once the file is fixed."""

    def setUp(self):
        """people.json lists Alice as viewer and Bob as owner; Carol is not listed. Bob has made a pin, so he is an
        @-tag candidate of GET /api/people whatever people.json holds."""
        super().setUp()
        self.set_people(GOOD)
        self.pin_id(BOB)
        self.set_people(GOOD)
        self.good = ps.C.people_file.read_bytes()

    def visit_all(self):
        """Alice, Bob and Carol each open the viewer and read meta (both record a visit) -> {login: role shown}."""
        roles = {}
        for h in (ALICE, BOB, CAROL):
            self.assertEqual(self.call("GET", "/", headers=h)[0], 200)
            code, d = self.call("GET", "/api/meta", headers=h)
            self.assertEqual(code, 200, d)
            roles[d["me"]["login"]] = d["me"]["role"]
        return roles

    def assert_fails_closed(self, case):
        """Everyone a header names is a viewer (no escalation: Alice stays viewer, Carol is no editor, Bob no owner),
        a change is refused, the file keeps its bytes, and one warning is printed however many requests come."""
        broken = ps.C.people_file.read_bytes() if os.access(ps.C.people_file, os.R_OK) else None
        with mock.patch("sys.stderr", io.StringIO()) as err:
            roles = self.visit_all()
            self.visit_all()
            code, d = self.call("POST", "/api/pin", {"file": "main.tex", "lo": 1, "hi": 1, "page": 1}, BOB)
            code_people, people = self.call("GET", "/api/people", headers=ALICE)
        if broken is not None:
            self.assertEqual(ps.C.people_file.read_bytes(), broken, case)
        self.assertEqual(
            roles, {"alice@example.com": "viewer", "bob@example.com": "viewer", "carol@example.com": "viewer"}, case
        )
        self.assertEqual((code, d.get("reason")), (403, "viewer_only"), case)
        self.assertEqual(code_people, 200, case)
        self.assertEqual([(p["login"], p["role"]) for p in people["people"]], [("bob@example.com", "viewer")], case)
        self.assertEqual(err.getvalue().count("warning:"), 1, (case, err.getvalue()))
        self.assertIn(str(ps.C.people_file), err.getvalue(), case)

    def assert_recovers(self, case):
        """Once the good file is back, roles come from it again (Carol, unlisted, is the default editor) and her
        visit is recorded next to the listed people."""
        roles = self.visit_all()
        self.assertEqual(
            roles, {"alice@example.com": "viewer", "bob@example.com": "owner", "carol@example.com": "editor"}, case
        )
        self.assertEqual(
            sorted((p["login"], p.get("role")) for p in self.people_file()),
            [("alice@example.com", "viewer"), ("bob@example.com", "owner"), ("carol@example.com", None)],
            case,
        )

    def test_a_broken_file_fails_closed_and_recovers_when_rewritten(self):
        """Truncated, invalid JSON, a wrong shape, bytes that are not UTF-8 and an empty file each fail closed; writing
        the good file back restores the roles without a restart."""
        for case, make in BROKEN.items():
            with self.subTest(case):
                self.setUp_case()
                ps.C.people_file.write_bytes(make(self.good))
                self.assert_fails_closed(case)
                ps.C.people_file.write_bytes(self.good)
                self.assert_recovers(case)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a file of any mode")
    def test_a_file_this_process_may_not_read_fails_closed_and_recovers_on_chmod(self):
        """people.json with mode 000 fails closed; a chmod alone (no content change) is noticed and restores it."""
        os.chmod(ps.C.people_file, 0o000)
        self.addCleanup(lambda: ps.C.people_file.exists() and os.chmod(ps.C.people_file, 0o600))
        self.assert_fails_closed("mode 000")
        os.chmod(ps.C.people_file, 0o600)
        self.assertEqual(ps.C.people_file.read_bytes(), self.good)
        self.assert_recovers("mode 000")

    def test_members_only_admits_nobody_from_an_unreadable_file(self):
        """Under --members-only, listed people are refused 403 not_member while the file is broken; a login given
        with --allow does not depend on the file and is still admitted, as a viewer; fixed, Alice is back in."""
        set_config(members_only=True)
        ps.C.people_file.write_bytes(b"{not json\n")
        with mock.patch("sys.stderr", io.StringIO()):
            for h in (ALICE, BOB, CAROL):
                code, d = self.call("GET", "/api/meta?light=1", headers=h)
                self.assertEqual((code, d.get("reason")), (403, "not_member"), h)
            set_config(allow=frozenset({"carol@example.com"}))
            code, d = self.call("GET", "/api/meta?light=1", headers=CAROL)
        self.assertEqual((code, d["me"]["role"]), (200, "viewer"))
        self.assertEqual(ps.C.people_file.read_bytes(), b"{not json\n")
        ps.C.people_file.write_bytes(self.good)
        code, d = self.call("GET", "/api/meta?light=1", headers=ALICE)
        self.assertEqual((code, d["me"]["role"]), (200, "viewer"))

    def setUp_case(self):
        """Start one subTest from the good file with nobody memoised as recently recorded."""
        ps.C.people_file.write_bytes(self.good)
        ps._PEOPLE_SEEN.clear()


class FramingHeaders(AccessBase):
    """Every response forbids being framed by another page (clickjacking): X-Frame-Options DENY and a CSP whose only
    directive is frame-ancestors 'none'. Page images are cached privately, like the PDFs."""

    FRAMING = {"x-frame-options": "DENY", "content-security-policy": "frame-ancestors 'none'"}

    def framing(self):
        """The two anti-framing headers of the last response."""
        return {k: self.last_headers.get(k) for k in self.FRAMING}

    def test_html_json_errors_and_images_forbid_framing(self):
        """The viewer page, a JSON answer, a 404, a 401 and a 403 refusal page all carry both headers."""
        pages = ps.DOCS[0].dir / "pages"
        pages.mkdir()
        (pages / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        self.set_people([{"login": "bob@example.com", "name": "Bob Park", "role": "viewer"}])
        for method, path, headers, peer, status in (
            ("GET", "/", ALICE, "127.0.0.1", 200),
            ("GET", "/api/meta?light=1", ALICE, "127.0.0.1", 200),
            ("GET", "/pages/page-1.png", ALICE, "127.0.0.1", 200),
            ("GET", "/nope", ALICE, "127.0.0.1", 404),
            ("GET", "/api/meta", ALICE, "10.0.0.5", 401),
            ("POST", "/api/pin", BOB, "127.0.0.1", 403),
        ):
            code, _ = self.call(method, path, {} if method == "POST" else None, headers, peer)
            self.assertEqual(code, status, path)
            self.assertEqual(self.framing(), self.FRAMING, (method, path))

    def test_the_base_class_error_pages_forbid_framing_too(self):
        """A method the server does not serve (PUT) is answered by http.server itself with 501; that page carries
        both headers as well."""
        code, hdrs, _ = split_resp(talk_to(ps, req("PUT", "/")))
        self.assertEqual(code, 501)
        self.assertEqual({k: hdrs.get(k) for k in self.FRAMING}, self.FRAMING)

    def test_page_images_are_cached_privately(self):
        """GET /pages/page-N.png is Cache-Control: private, max-age=600 - a shared cache must not keep manuscript
        pages - while the instance's favicon stays public."""
        pages = ps.DOCS[0].dir / "pages"
        pages.mkdir()
        (pages / "page-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        code, _ = self.call("GET", "/pages/page-1.png", headers=ALICE)
        self.assertEqual((code, self.last_headers["cache-control"]), (200, "private, max-age=600"))
        code, _ = self.call("GET", "/favicon-32.png", headers=ALICE)
        self.assertEqual((code, self.last_headers["cache-control"]), (200, "public, max-age=86400"))


if __name__ == "__main__":
    unittest.main()
