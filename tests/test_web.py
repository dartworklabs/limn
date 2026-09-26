"""limn.web - the HTTP layer on its own: how the handler is bound to server.py, and the answers and error pages.

Every route's statuses, headers and bodies are pinned end to end through the handler in test_server.py, test_access.py
and the version suites. Here: the binding contract (server.py provides everything limn.web.app.App names, and the
handler sees a name rebound on the server module), the import direction (limn.web never imports server.py), the
package name (server.py still runs as a file), and the answers and error pages as plain functions.

Run: uv run pytest -q tests/test_web.py
"""
import subprocess
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

from limn.pins.edit import StaleEdit
from limn.pins.lifecycle import AgentCannotConfirm, ClaimedByOther, PinStillOpen, ThreadFull
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin
from limn.web import answers
from limn.web.app import App
from limn.web.errors import HTTPError, InputRejected, error_page_html, page_lang, ui_text
from test_server import ps

SRC = Path(__file__).resolve().parent.parent / "src"


def app_members() -> list:
    """The names limn.web.app.App declares: its settings and texts (annotations) and its services (methods)."""
    methods = [n for n, v in vars(App).items() if callable(v) and not n.startswith("_")]
    return sorted(set(App.__annotations__) | set(methods))


def show(record):
    """A stand-in for server.py's public(): the record as a plain dict, so a body shows what was passed through."""
    return dict(record)


class Binding(unittest.TestCase):
    """server.Handler is limn.web.handler.Handler bound to the live globals of its own server module."""

    def test_server_module_provides_every_app_member(self):
        """A service the handler calls through App but server.py no longer defines would fail only when a request
        reaches it; this catches a rename or a move (for example into store.py) at once."""
        missing = [n for n in app_members() if not hasattr(ps.Handler.app, n)]
        self.assertEqual(missing, [])
        not_callable = [n for n, v in vars(App).items()
                        if callable(v) and not n.startswith("_") and not callable(getattr(ps.Handler.app, n))]
        self.assertEqual(not_callable, [])

    def test_handler_sees_a_name_rebound_on_the_server_module(self):
        """main() rebinds HTML after startup and tests patch services on their copy of server.py; the handler must
        call what the module holds now, not what it held at import."""
        with mock.patch.object(ps, "build_async", return_value={"sentinel": 1}) as fake:
            self.assertIs(ps.Handler.app.build_async, fake)
        self.assertIs(ps.Handler.app.build_async, ps.build_async)
        with mock.patch.object(ps, "HTML", "<p>rebound</p>"):
            self.assertEqual(ps.Handler.app.HTML, "<p>rebound</p>")

    def test_an_unknown_name_is_an_attribute_error(self):
        """The view answers like a module: a missing global is AttributeError, not KeyError."""
        with self.assertRaises(AttributeError):
            ps.Handler.app.no_such_service  # noqa: B018 - the lookup is the behaviour under test

    def test_server_reexports_the_error_types_it_raises(self):
        """server.py's services raise and return the HTTP layer's own types, so except/match in the handler sees them."""
        self.assertIs(ps.HTTPError, HTTPError)
        self.assertIs(ps.InputRejected, InputRejected)


class ImportDirection(unittest.TestCase):
    """limn.web depends on the pin domain and never on server.py (docs/handbook/architecture.md §목표 구조)."""

    def test_web_package_loads_without_server(self):
        """Importing the handler must not import server.py: the composition root binds it, not the other way round."""
        code = ("import sys, limn.web.handler, limn.web.answers, limn.web.app, limn.web.errors; "
                "print(sorted(m for m in sys.modules if m.startswith('limn') and 'server' in m))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False,
                           cwd=str(SRC))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_server_still_runs_as_a_file(self):
        """Instances start python .../limn/server.py, which puts limn/ first on sys.path; a package named like a
        standard module (limn/http) would shadow it there and the server would not start."""
        r = subprocess.run([sys.executable, str(SRC / "limn" / "server.py"), "--version"], capture_output=True,
                           text=True, timeout=60, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("limn "), r.stdout)


class Answers(unittest.TestCase):
    """Each outcome becomes one body or one HTTPError with the contract's status and message."""

    def assert_refused(self, call, code, body):
        """call() raises HTTPError with exactly this status and JSON body."""
        with self.assertRaises(HTTPError) as e:
            call()
        self.assertEqual((e.exception.code, e.exception.body), (code, body))

    def test_confirm_answers_every_outcome(self):
        """done (also when already done) -> ok; unknown id -> ok:false; an agent -> 403; an open pin -> 409 open."""
        done = {"id": 3, "done": True}
        self.assertEqual(answers.confirm_answer(DonePin(done), show), {"ok": True, "pin": done, "state": "done"})
        self.assertEqual(answers.confirm_answer(PinNotFound(3), show), {"ok": False, "pin": None, "state": None})
        self.assert_refused(lambda: answers.confirm_answer(AgentCannotConfirm(), show), 403,
                            {"error": answers.CONFIRM_BY_HUMAN})
        self.assert_refused(lambda: answers.confirm_answer(PinStillOpen(OpenPin({"id": 3})), show), 409,
                            {"error": "open", "pin": {"id": 3}, "detail": answers.CONFIRM_OPEN_DETAIL})

    def test_claim_reports_the_applied_eta_only_when_sent(self):
        """The applied (clamped) eta is added only for a claim that sent one; a held claim is 409 claimed."""
        pin = OpenPin({"id": 5})
        self.assertEqual(answers.claim_answer(pin, 30, None, show), {"ok": True, "pin": {"id": 5}, "ttl_min_applied": 30})
        self.assertEqual(answers.claim_answer(pin, 30, 240, show)["eta_min_applied"], 240)
        self.assert_refused(lambda: answers.claim_answer(ClaimedByOther("bob", 1.0, None), 30, None, show), 409,
                            {"error": "claimed", "claimed_by": "bob", "claim_until": 1.0, "eta_ts": None})

    def test_reply_says_whether_it_reopened_and_refuses_a_full_thread(self):
        """reopened follows the new thread entry's ev; a full thread is 409 full with the limit in the detail."""
        record = {"id": 2, "thread": [{"text": "again", "ev": "reopen"}]}
        body = answers.reply_answer(OpenPin(record), show, lambda r: "open")
        self.assertEqual((body["msg"], body["state"], body["reopened"]), (record["thread"][-1], "open", True))
        self.assert_refused(lambda: answers.reply_answer(ThreadFull(200), show, lambda r: "open"), 409,
                            {"error": "full", "detail": "스레드가 가득 찼습니다(답글 200건). 새 핀으로 이어 가세요."})

    def test_add_and_edit_answer_a_rejected_field_with_its_message(self):
        """A parser's InputRejected is a 400 whose error is the message, word for word; a stale edit is 409 conflict."""
        self.assertEqual(answers.add_answer(OpenPin({"id": 9})), {"id": 9})
        self.assert_refused(lambda: answers.add_answer(InputRejected("lo 는 정수여야 합니다.")), 400,
                            {"error": "lo 는 정수여야 합니다."})
        self.assert_refused(lambda: answers.edit_answer(PinNotFound(4), show), 404, {"error": "핀 #4 이 없습니다."})
        self.assert_refused(lambda: answers.edit_answer(StaleEdit(ReviewPin({"id": 4})), show), 409,
                            {"error": "conflict", "pin": {"id": 4}})


class ErrorPages(unittest.TestCase):
    """The page a browser gets when GET / is refused: the viewer's language rule and message table."""

    def headers(self, accept_language):
        """Request headers with one Accept-Language value."""
        h = Message()
        h["Accept-Language"] = accept_language
        return h

    def test_language_follows_the_query_then_accept_language(self):
        """?lang= wins; otherwise a first ko* tag gives ko and anything else en."""
        self.assertEqual(page_lang(self.headers("en-US"), {"lang": ["ko"]}), "ko")
        self.assertEqual(page_lang(self.headers("ko-KR,en;q=0.8"), {}), "ko")
        self.assertEqual(page_lang(self.headers("en-US,ko;q=0.8"), {}), "en")

    def test_ui_text_uses_the_table_in_english_and_the_key_in_korean(self):
        """In en the table's entry (its "other" plural form) with placeholders filled; in ko the Korean key itself."""
        table = {"안녕 {name}": "Hello {name}", "핀 {n}개": {"one": "{n} pin", "other": "{n} pins"}}
        self.assertEqual(ui_text("안녕 {name}", "en", table, name="Alice"), "Hello Alice")
        self.assertEqual(ui_text("안녕 {name}", "ko", table, name="Alice"), "안녕 Alice")
        self.assertEqual(ui_text("핀 {n}개", "en", table, n=3), "3 pins")
        self.assertEqual(ui_text("없는 문장", "en", table), "없는 문장")

    def test_page_escapes_the_login_and_links_the_other_language(self):
        """A named page kind fills its heading with the escaped login and links to /?lang=<other>."""
        page = error_page_html(HTTPError(403, "x", page=("not-member", {"login": "<b>eve</b>"})), "ko", {})
        self.assertIn("이 뷰어의 멤버가 아닙니다: &lt;b&gt;eve&lt;/b&gt;", page)
        self.assertIn('<a href="/?lang=en">English</a>', page)
        self.assertNotIn("<b>eve</b>", page)


if __name__ == "__main__":
    unittest.main()
