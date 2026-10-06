"""limn.web - the HTTP layer on its own: how the handler is bound to server.py, and the answers and error pages.

Every route's statuses, headers and bodies are pinned end to end through the handler in test_server.py, test_access.py
and the feature files. Here: the binding contract (server.py provides everything limn.web.app.App names, and the
handler sees a route table replaced on its bound application), the import direction (limn.web never imports server.py), the
package name (server.py still runs as a file), the handler's shape read from its source (no route reads the body or
query itself; it raises only its own transport refusals), the order of the guard checks on every route, and the answers
and error pages as plain functions.

Run: uv run pytest -q src/limn/web/tests/test_web.py
"""

import ast
import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
import types
import typing
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

from limn.builds import http as builds_http
from limn.pins.claims import http as claims_http
from limn.pins.claims.rules import ClaimedByOther
from limn.pins.editing import http as editing_http
from limn.pins.editing.rules import StaleEdit
from limn.pins.lifecycle import http as lifecycle_http
from limn.pins.lifecycle.rules import AgentCannotConfirm, PinStillOpen, ThreadFull
from limn.pins.listing import http as listing_http
from limn.pins.location import http as location_http, mapping, resolve as pick_resolve
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin, TrashedPin
from limn.pins.trash import http as trash_http
from limn.pins.trash.rules import NotInTrash
from limn.revisions import answer as revision_answer
from limn.revisions.core import DocumentBusy
from limn.runtime.documents import DocNotFound
from limn.viewer.assemble import ServedViewer
from limn.viewer.mark import ICON_ROUTES
from limn.web import answers
from limn.web.app import RouteRegistry, WebApplication
from limn.web.errors import HTTPError, InputRejected, error_page_html, page_lang, ui_text
from limn.web.reply import Reply
from limn.web.routes import RouteBundle

from helpers import ApplicationFixture, Base, ps, run_config
from helpers_access import AccessBase, member_add, talk_to

SRC = Path(__file__).resolve().parents[4] / "src"
HANDLER_SOURCE = (SRC / "limn" / "web" / "handler.py").read_text(encoding="utf-8")
BUILD_ROUTES_SOURCE = (SRC / "limn" / "builds" / "routes.py").read_text(encoding="utf-8")
REVISION_ROUTES_SOURCE = (SRC / "limn" / "revisions" / "routes.py").read_text(encoding="utf-8")
DOCUMENT_ROUTES_SOURCE = (SRC / "limn" / "documents" / "routes.py").read_text(encoding="utf-8")
COLLABORATION_ROUTES_SOURCE = (SRC / "limn" / "collaboration" / "routes.py").read_text(encoding="utf-8")
LISTING_ROUTES_SOURCE = (SRC / "limn" / "pins" / "listing" / "routes.py").read_text(encoding="utf-8")
LOCATION_ROUTES_SOURCE = (SRC / "limn" / "pins" / "location" / "routes.py").read_text(encoding="utf-8")
EDITING_ROUTES_SOURCE = (SRC / "limn" / "pins" / "editing" / "routes.py").read_text(encoding="utf-8")
VIEWER_SHELL_ROUTES_SOURCE = (SRC / "limn" / "viewer" / "routes.py").read_text(encoding="utf-8")
GET_ROUTE_SOURCES = (
    HANDLER_SOURCE,
    VIEWER_SHELL_ROUTES_SOURCE,
    BUILD_ROUTES_SOURCE,
    REVISION_ROUTES_SOURCE,
    DOCUMENT_ROUTES_SOURCE,
    COLLABORATION_ROUTES_SOURCE,
    LISTING_ROUTES_SOURCE,
    LOCATION_ROUTES_SOURCE,
)


def app_members() -> list:
    """Include fields, read-only collaborators and operations required by the handler."""
    methods = [
        n for n, v in vars(WebApplication).items() if (callable(v) or isinstance(v, property)) and not n.startswith("_")
    ]
    return sorted(set(WebApplication.__annotations__) | set(methods))


def show(record):
    """A stand-in for server.py's public(): the record as a plain dict, so a body shows what was passed through."""
    return dict(record)


class Binding(Base):
    """server.Handler is limn.web.handler.Handler bound to its server copy's explicit application."""

    def test_server_module_provides_every_app_member(self):
        """A service the handler calls through App but server.py no longer defines would fail only when a request
        reaches it; this catches a rename or a move (for example into store.py) at once."""
        missing = [n for n in app_members() if not hasattr(ps.Handler.app, n)]
        self.assertEqual(missing, [])
        not_callable = [
            n
            for n, v in vars(WebApplication).items()
            if callable(v) and not n.startswith("_") and not callable(getattr(ps.Handler.app, n))
        ]
        self.assertEqual(not_callable, [])

    def test_handler_has_no_capability_service_locator(self):
        """The HTTP application exposes only its concrete request-boundary collaborators."""
        self.assertEqual(
            set(app_members()), {"settings", "guards", "selector", "routes", "recorder", "messages", "header_text"}
        )
        self.assertFalse(hasattr(ps.Handler.app, "build_requests"))
        rebound = ps.new_runtime(ServedViewer("<p>rebound</p>", "", {}))
        with mock.patch.object(ps.APP, "RT", rebound):
            response = self.talk(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            self.assertEqual(response.split(b"\r\n\r\n", 1)[1], b"<p>rebound</p>")

    def test_handler_subclasses_can_use_distinct_app_collaborators(self):
        """Two listeners can replace route tables without mutating each other's assembly."""
        original = ps.Handler.app
        pages = []
        for label in ("First", "Second"):
            routes = RouteBundle(get=(lambda request, page=label: Reply(200, f"<p>{page}</p>".encode(), "text/html"),))
            app = dataclasses.replace(original, routes=RouteRegistry(routes))
            handler = type(f"{label}Handler", (ps.Handler,), {"app": app})
            pages.append(talk_to(types.SimpleNamespace(Handler=handler), b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"))
        self.assertEqual([reply.split(b"\r\n\r\n", 1)[1] for reply in pages], [b"<p>First</p>", b"<p>Second</p>"])
        self.assertIs(ps.Handler.app, original)

    def test_an_unknown_name_is_an_attribute_error(self):
        """The view answers like a module: a missing global is AttributeError, not KeyError."""
        with self.assertRaises(AttributeError):
            ps.Handler.app.no_such_service  # noqa: B018 - the lookup is the behaviour under test

    def test_server_reexports_the_error_type_it_raises(self):
        """server.py's services still raise the HTTP layer's own HTTPError, so the handler's except sees it. A refused
        request field is the parsers' (limn.web.parse): server.py neither makes nor imports InputRejected."""
        self.assertIs(ps.HTTPError, HTTPError)
        self.assertFalse(hasattr(ps, "InputRejected"))

    def test_file_loaded_server_copies_keep_their_own_run(self):
        """Two path-loaded server copies isolate settings, documents and a handler app replacement."""

        def load_copy(name):
            """Load server.py as instances and test tools do, without registering it in sys.modules."""
            spec = importlib.util.spec_from_file_location(name, SRC / "limn" / "server.py")
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        # Running server.py by path prepends src/ to sys.path; restore the test process's import path afterward.
        with mock.patch.object(sys, "path", sys.path.copy()):
            first, second = load_copy("limn_server_first"), load_copy("limn_server_second")
        for mod, label in ((first, "First"), (second, "Second")):
            config = run_config(self.src, self.main, self.src.parent / label, label=label)
            mod.APP = ApplicationFixture(config, mod.new_runtime(ServedViewer(f"<p>{label}</p>", "", {})), mod)
            mod.Handler.app = mod.APP.web
            mod.APP.set_docs([mod.Doc(label.lower(), label, legacy=True, paths=config.paths)])

        def get(mod, path):
            """One successful GET body from this copy's actual HTTP handler."""
            request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:18999\r\n\r\n".encode()
            response = talk_to(mod, request)
            self.assertTrue(response.startswith(b"HTTP/1.1 200"), response[:200])
            return response.split(b"\r\n\r\n", 1)[1]

        def docs(mod):
            """The document key and name exposed by this copy's GET /api/docs."""
            response = json.loads(get(mod, "/api/docs"))
            return response["default"], response["docs"][0]["name"]

        self.assertEqual(get(first, "/"), b"<p>First</p>")
        self.assertEqual(get(second, "/"), b"<p>Second</p>")
        self.assertEqual(docs(first), ("first", "First"))
        self.assertEqual(docs(second), ("second", "Second"))
        self.assertEqual(first.Handler.app.settings().label, "First")
        self.assertEqual(second.Handler.app.settings().label, "Second")
        self.assertIs(first.Handler.app.selector.select(None, None), first.APP.docs[0])
        self.assertIs(second.Handler.app.selector.select(None, None), second.APP.docs[0])
        self.assertIsNot(first.APP.docs, second.APP.docs)
        self.assertIsNot(first.APP.RT.pin_lock, second.APP.RT.pin_lock)

        config = run_config(self.src, self.main, self.src.parent / "Restarted", label="Restarted")
        first.APP = ApplicationFixture(config, first.new_runtime(ServedViewer("<p>Restarted</p>", "", {})), first)
        first.Handler.app = first.APP.web
        first.APP.set_docs([first.Doc("restarted", "Restarted", legacy=True, paths=config.paths)])
        self.assertEqual(get(first, "/"), b"<p>Restarted</p>")
        self.assertEqual(get(second, "/"), b"<p>Second</p>")
        self.assertEqual(docs(first), ("restarted", "Restarted"))
        self.assertEqual(docs(second), ("second", "Second"))
        self.assertEqual(second.Handler.app.settings().label, "Second")
        self.assertIs(second.Handler.app.selector.select(None, None), second.APP.docs[0])

        replacement = dataclasses.replace(
            first.Handler.app,
            routes=RouteRegistry(RouteBundle(get=(lambda request: Reply(200, b"<p>Replacement</p>", "text/html"),))),
        )
        with mock.patch.object(first.Handler, "app", replacement):
            self.assertEqual(get(first, "/"), b"<p>Replacement</p>")
            self.assertEqual(get(second, "/"), b"<p>Second</p>")
        self.assertEqual(get(first, "/"), b"<p>Restarted</p>")


class ImportDirection(unittest.TestCase):
    """limn.web depends on the pin domain and never on server.py (docs/handbook/architecture.md §의존 방향)."""

    def test_web_package_loads_without_server(self):
        """Importing the handler must not import server.py: the composition root binds it, not the other way round."""
        code = (
            "import sys, limn.web.handler, limn.web.answers, limn.web.app, limn.web.errors; "
            "print(sorted(m for m in sys.modules if m.startswith('limn') and 'server' in m))"
        )
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False, cwd=str(SRC)
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_server_still_runs_as_a_file(self):
        """Instances start python .../limn/server.py, which puts limn/ first on sys.path; a package named like a
        standard module (limn/http) would shadow it there and the server would not start."""
        r = subprocess.run(
            [sys.executable, str(SRC / "limn" / "server.py"), "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("limn "), r.stdout)


class HandlerStructure(unittest.TestCase):
    """What the handler's source may and may not do, checked on its syntax tree (a violation added later fails here)."""

    def test_routes_read_no_body_field_or_query_parameter_themselves(self):
        """The routes pass the body (d) and the query (q) whole to limn.web.parse (or to a member that supplies a
        parser's facts); none reads a field with .get() or [...] - so every value a route uses was parsed at the
        boundary."""
        raw = [
            "%d: %s" % (n.lineno, ast.unparse(n))
            for source in GET_ROUTE_SOURCES
            for n in ast.walk(ast.parse(source))
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in ("d", "q", "body")
            )
            or (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in ("d", "q", "body"))
        ]
        self.assertEqual(raw, [])

    def test_the_handler_raises_only_its_own_refusals(self):
        """Every other refusal is an answer's (limn.web.answers) or an access check's: the handler raises HTTPError
        only while reading the body, checking Host/Origin, and for a path no route serves (not_found)."""
        own = {"_read_raw", "_check_singleton_headers", "_check_origin", "_body"}
        raised = [
            (fn.name, ast.unparse(n.exc))
            for fn in ast.walk(ast.parse(HANDLER_SOURCE))
            if isinstance(fn, ast.FunctionDef) and fn.name not in own
            for n in ast.walk(fn)
            if isinstance(n, ast.Raise) and n.exc is not None
        ]
        self.assertTrue(raised)
        for name, exc in raised:
            with self.subTest(route=name):
                self.assertIn("reason='not_found'", exc)


# One request per route of the handler and registered feature routes (a /pages/, a /vendor/pdfjs/ and a /vendor/pretendard/
# name stand for their prefixes, pin 1 for an id). GuardOrder checks these lists against the route sources.
PIN_ACTIONS = ("close", "reopen", "drop", "restore", "purge", "edit", "claim", "unclaim", "reply", "confirm")
GET_ROUTES = (
    "/",
    "/api/people",
    "/favicon.ico",
    "/favicon-16.png",
    "/favicon-32.png",
    "/apple-touch-icon.png",
    "/api/version",
    "/api/meta",
    "/sw.js",
    "/api/revisions",
    "/api/revision-diff",
    "/api/revision-build",
    "/api/revision-pdf",
    "/api/outline-labels",
    "/api/build",
    "/pins.md",
    "/api/pins",
    "/api/docs",
    "/api/pins/dropped",
    "/api/pins/1",
    "/api/snippet",
    "/api/overlaps",
    "/pages/page-1.png",
    "/vendor/pdfjs/pdf.min.mjs",
    "/vendor/pretendard/pretendard.css",
    "/pdf",
    "/no-such-path",
)
POST_ROUTES = (
    "/api/pick",
    "/api/pin",
    "/api/rebuild",
    "/api/revision-build",
    "/api/clear",
    *("/api/pins/1/" + act for act in PIN_ACTIONS),
    "/api/no-such-path",
)


class Recorder:
    """The App a recorded handler calls: every member it reads is logged by name, in order, then read from the real
    one (server.py's live globals)."""

    def __init__(self, inner, log):
        """Wrap inner (server.Handler.app) and append to log."""
        self._inner, self._log = inner, log

    def __getattr__(self, name):
        """Log the member's name, then give the real member."""
        if name == "guards":
            return Recorder(self._inner.guards, self._log)
        self._log.append(name)
        return getattr(self._inner, name)


class GuardOrder(AccessBase):
    """Every route passes the same checks in the same order before it touches anything: the body is read (size and
    framing) before the handler reads any App member, then Host/Origin, identify, admit and - for a POST -
    check_role, and no other member is read before them (docs/handbook/architecture.md, the access boundary)."""

    def send(self, method, path, headers=None, body=b"", peer="127.0.0.1"):
        """One request through server.Handler with its App recorded -> (status, the members it read)."""
        log = []
        handler = type("RecordedHandler", (ps.Handler,), {"app": Recorder(ps.Handler.app, log)})
        h = {"Host": "127.0.0.1:18999", **(headers or {})}
        if body:
            h.setdefault("Content-Length", str(len(body)))
            h.setdefault("Content-Type", "application/json")
        head = "%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n"
        out = talk_to(types.SimpleNamespace(Handler=handler), head.encode() + body, peer)
        return int(out.split(b" ", 2)[1]), log

    def routes(self):
        """(method, path) of every route."""
        return [("GET", p) for p in GET_ROUTES] + [("POST", p) for p in POST_ROUTES]

    def test_the_route_lists_cover_the_handler(self):
        """Every path the handler or registered feature route matches, and every pin action, is in the lists."""
        literals = set()
        for source in GET_ROUTE_SOURCES:
            literals |= set(re.findall(r'path == "([^"]+)"', source))
            literals |= set(re.findall(r'path\.startswith\("([^"]+)"\)', source))
            for group in re.findall(r"path in \(([^)]*)\)", source):
                literals |= set(re.findall(r'"([^"]+)"', group))
        literals |= set(ICON_ROUTES)  # viewer_shell answers the icon table's paths (limn.viewer.mark.ICON_ROUTES)
        self.assertGreater(len(literals), 20)
        routes = GET_ROUTES + POST_ROUTES
        for literal in sorted(literals):
            with self.subTest(literal=literal):
                self.assertTrue(any(r == literal or (literal.endswith("/") and r.startswith(literal)) for r in routes))
        post_paths = set()
        for source in (BUILD_ROUTES_SOURCE, REVISION_ROUTES_SOURCE, LOCATION_ROUTES_SOURCE, EDITING_ROUTES_SOURCE):
            post_paths |= set(re.findall(r'^POST_PATH = "([^"]+)"', source, re.M))
        self.assertEqual(post_paths, {"/api/rebuild", "/api/revision-build", "/api/pick", "/api/pin"})
        self.assertTrue(post_paths <= set(POST_ROUTES))
        self.assertEqual(sorted(ps.APP.pin_actions), sorted(PIN_ACTIONS))
        self.assertEqual(set(ps.APP.other_posts), {"/api/clear"})

    def test_every_route_checks_host_identity_admission_and_role_first(self):
        """An admitted request reads C (origin check on), host_ok, [origin_ok], identify, admit and, for a POST,
        check_role - before any other member."""
        for origin in (None, "http://127.0.0.1:18999"):
            for method, path in self.routes():
                with self.subTest(method=method, path=path, origin=origin):
                    headers = {"Origin": origin} if origin else {}
                    _, log = self.send(method, path, headers, b"{}" if method == "POST" else b"")
                    first = ["settings", "host_ok"] + (["origin_ok"] if origin else []) + ["identify", "admit"]
                    first += ["check_role"] if method == "POST" else []
                    self.assertEqual(log[: len(first)], first)

    def test_a_refused_request_reaches_no_route(self):
        """Each refusal on each route stops where it is raised: an oversized body before any member is read, a
        foreign Host after host_ok, an unidentified tailnet peer at identify, a viewer's change at check_role."""
        member_add(ps.APP.C.state, "carol@example.com", "viewer")
        carol = {"Tailscale-User-Login": "carol@example.com", "Tailscale-User-Name": "Carol Lee"}
        for method, path in self.routes():
            with self.subTest(method=method, path=path):
                self.assertEqual(self.send(method, path, {"Content-Length": str((1 << 20) + 1)}), (413, []))
                self.assertEqual(
                    self.send(method, path, {"Host": "evil.example"}), (403, ["settings", "host_ok", "header_text"])
                )
                self.assertEqual(self.send(method, path, peer="100.64.0.9"), (401, ["settings", "host_ok", "identify"]))
                if method == "POST" and path not in ("/api/pick", "/api/revision-build"):
                    self.assertEqual(
                        self.send(method, path, carol, b"{}"),
                        (403, ["settings", "host_ok", "identify", "admit", "check_role"]),
                    )


class Answers(unittest.TestCase):
    """Each outcome becomes one body or one HTTPError with the contract's status and message."""

    def assert_refused(self, call, code, body):
        """call() raises HTTPError with exactly this status and JSON body (error, reason, then the extra fields)."""
        with self.assertRaises(HTTPError) as e:
            call()
        self.assertEqual((e.exception.code, e.exception.body), (code, body))

    def test_a_document_lookup_is_the_document_or_404_unknown_doc(self):
        """found_doc passes a document through and answers DocNotFound with the key (through text, 40 characters)
        and every key served."""
        self.assertEqual(answers.found_doc("doc", str.upper), "doc")
        self.assert_refused(
            lambda: answers.found_doc(DocNotFound("z" * 50, ("ms", "rv")), str.upper),
            404,
            {"error": "없는 문서입니다: " + "Z" * 40, "reason": "unknown_doc", "docs": ["ms", "rv"]},
        )

    def test_one_pin_drop_purge_and_clear(self):
        """GET /api/pins/{id}, drop, purge and clear: their bodies, and the 404s of an unknown pin or Trash entry."""
        self.assertEqual(listing_http.pin_answer({"id": 4}), {"pin": {"id": 4}})
        self.assert_refused(
            lambda: listing_http.pin_answer(PinNotFound(4)),
            404,
            {"error": "핀 #4 이 없습니다.", "reason": "pin_not_found"},
        )
        trashed = TrashedPin.from_record({"id": 4})
        self.assertEqual(trash_http.drop_answer(trashed), {"ok": True})
        self.assertEqual(trash_http.drop_answer(PinNotFound(4)), {"ok": False})
        self.assertEqual(trash_http.purge_answer(trashed, 4), {"ok": True, "purged": 4})
        self.assert_refused(
            lambda: trash_http.purge_answer(NotInTrash(4), 4),
            404,
            {"error": "휴지통에 핀 #4 이 없습니다.", "reason": "not_in_trash"},
        )
        self.assertEqual(trash_http.clear_answer({"cleared": 2}), {"cleared": 2, "ok": True})

    def test_a_build_pdf_that_cannot_be_served(self):
        """A named build is pdf_build_gone, no name is pdf_missing; the body names the build on screen."""
        self.assert_refused(
            lambda: builds_http.pdf_gone("pages-1", "pages-2", str),
            404,
            {
                "error": "그 빌드의 PDF 가 없습니다: pages-1",
                "reason": "pdf_build_gone",
                "pdf_build_gone": True,
                "pages_build": "pages-2",
            },
        )
        self.assert_refused(
            lambda: builds_http.pdf_gone("", "pages-2", str),
            404,
            {
                "error": "그 빌드의 PDF 가 없습니다: ",
                "reason": "pdf_missing",
                "pdf_build_gone": False,
                "pages_build": "pages-2",
            },
        )

    def test_a_revision_build_is_202_while_running(self):
        """POST /api/revision-build: 202 for running, 200 for any other state, a refusal through its table."""
        self.assertEqual(revision_answer.revision_start_answer({"state": "running"}), ({"state": "running"}, 202))
        self.assertEqual(revision_answer.revision_start_answer({"state": "ready"}), ({"state": "ready"}, 200))
        self.assert_refused(
            lambda: revision_answer.revision_start_answer(DocumentBusy()),
            409,
            {"error": "이 문서의 비교 PDF를 만드는 중입니다.", "reason": "busy"},
        )

    def test_confirm_answers_every_outcome(self):
        """done (also when already done) -> ok; unknown id -> ok:false; an agent -> 403; an open pin -> 409 open."""
        done = {"id": 3, "done": True}
        self.assertEqual(
            lifecycle_http.confirm_answer(DonePin.from_record(done), show), {"ok": True, "pin": done, "state": "done"}
        )
        self.assertEqual(lifecycle_http.confirm_answer(PinNotFound(3), show), {"ok": False, "pin": None, "state": None})
        self.assert_refused(
            lambda: lifecycle_http.confirm_answer(AgentCannotConfirm(), show),
            403,
            {"error": answers.CONFIRM_BY_HUMAN, "reason": "confirm_by_human"},
        )
        self.assert_refused(
            lambda: lifecycle_http.confirm_answer(PinStillOpen(OpenPin.from_record({"id": 3})), show),
            409,
            {"error": "open", "reason": "open", "pin": {"id": 3}, "detail": lifecycle_http.CONFIRM_OPEN_DETAIL},
        )

    def test_claim_reports_the_applied_eta_only_when_sent(self):
        """The applied (clamped) eta is added only for a claim that sent one; a held claim is 409 claimed."""
        pin = OpenPin.from_record({"id": 5})
        self.assertEqual(
            claims_http.claim_answer(pin, 30, None, show), {"ok": True, "pin": {"id": 5}, "ttl_min_applied": 30}
        )
        self.assertEqual(claims_http.claim_answer(pin, 30, 240, show)["eta_min_applied"], 240)
        self.assert_refused(
            lambda: claims_http.claim_answer(ClaimedByOther("bob", 1.0, None), 30, None, show),
            409,
            {"error": "claimed", "reason": "claimed", "claimed_by": "bob", "claim_until": 1.0, "eta_ts": None},
        )

    def test_reply_says_whether_it_reopened_and_refuses_a_full_thread(self):
        """reopened follows the new thread entry's ev; a full thread is 409 full with the limit in the detail."""
        record = {"id": 2, "thread": [{"text": "again", "ev": "reopen"}]}
        body = lifecycle_http.reply_answer(OpenPin.from_record(record), show, lambda r: "open")
        self.assertEqual((body["msg"], body["state"], body["reopened"]), (record["thread"][-1], "open", True))
        self.assert_refused(
            lambda: lifecycle_http.reply_answer(ThreadFull(200), show, lambda r: "open"),
            409,
            {"error": "full", "reason": "full", "detail": "스레드가 가득 찼습니다(답글 200건). 새 핀으로 이어 가세요."},
        )

    def test_pick_answers_every_refusal_with_its_200_body(self):
        """Each PickRefusal has one row in location_http.PICK_REFUSALS and answers the contract's 200 {"error", "reason"} body, the
        message filled with the refusal's detail."""
        self.assertEqual(set(location_http.PICK_REFUSALS), set(typing.get_args(pick_resolve.PickRefusal)))
        self.assertEqual(
            [
                location_http.pick_answer(r)
                for r in (
                    pick_resolve.GeneratedFile(".bbl"),
                    pick_resolve.SynctexOutside(Path("/elsewhere/x.tex")),
                    pick_resolve.SourceUnreadable(Path("/ms/bin.tex")),
                    pick_resolve.NoSourceHere(),
                )
            ],
            [
                {
                    "error": "여기는 생성 파일(.bbl)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다.",
                    "reason": "generated_file",
                },
                {
                    "error": "SyncTeX 가 원고 밖 파일을 가리킵니다(/elsewhere/x.tex). PDF 재빌드 뒤 다시 골라 보세요.",
                    "reason": "synctex_outside",
                },
                {"error": "원문 파일을 읽지 못했습니다: /ms/bin.tex", "reason": "source_unreadable"},
                {
                    "error": "그 자리에서 원문을 되짚지 못했습니다. 글자가 있는 쪽으로 조금 넓게 잡아 보세요.",
                    "reason": "no_source_here",
                },
            ],
        )

    def test_pick_warning_joins_its_sentences_in_order(self):
        """stale first, then weak (or else split), then building, one space apart; a region: blank, then redrawing."""
        traced = mapping.Traced("synctex", 8, 8, 0.23, 8, 9, "paragraph", [], "para", True, None)
        picked = pick_resolve.Picked(Path("/ms/main.tex"), 1, traced, 20, "", None, "", [], "pages", True, True)
        w = location_http.PICK_WARNINGS
        self.assertEqual(location_http.pick_warning(picked), " ".join([w["stale"], w["weak"] % 23.0, w["building"]]))
        split = dataclasses.replace(traced, weak=False, split=(8, 4))
        self.assertEqual(
            location_http.pick_warning(dataclasses.replace(picked, traced=split, stale=False, building=False)),
            "두 경로가 다른 곳을 가리킵니다(L8 / L4). 확인이 필요합니다.",
        )
        body = location_http.pick_answer(dataclasses.replace(picked, stale=False, building=False))
        self.assertEqual(
            list(body)[:11], ["file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score", "warn"]
        )
        self.assertEqual(
            (body["score"], body["warn"]), (0.23, "이 영역은 원문 대조가 약합니다(23%). 줄 범위를 눈으로 확인하세요.")
        )
        region = pick_resolve.PickedRegion(
            "rv", 1, [0.1, 0.1, 0.2, 0.2], "review.pdf", "review.pdf", "", 0, True, True, "p"
        )
        self.assertEqual(location_http.pick_answer(region)["warn"], w["blank"] + " " + w["redrawing"])

    def test_add_and_edit_answer_a_rejected_field_with_its_message(self):
        """A parser's InputRejected is a 400 whose error is the message, word for word, next to its reason code; a stale
        edit is 409 conflict."""
        self.assertEqual(editing_http.add_answer(OpenPin.from_record({"id": 9})), {"id": 9})
        self.assertEqual(answers.accepted(9), 9)
        self.assert_refused(
            lambda: answers.accepted(InputRejected("lo 는 정수여야 합니다.", "not_integer")),
            400,
            {"error": "lo 는 정수여야 합니다.", "reason": "not_integer"},
        )
        self.assert_refused(
            lambda: editing_http.edit_answer(PinNotFound(4), show),
            404,
            {"error": "핀 #4 이 없습니다.", "reason": "pin_not_found"},
        )
        self.assert_refused(
            lambda: editing_http.edit_answer(
                StaleEdit(ReviewPin.from_record({"id": 4, "done": True, "review": True})), show
            ),
            409,
            {"error": "conflict", "reason": "conflict", "pin": {"id": 4, "done": True, "review": True}},
        )


class ErrorPages(unittest.TestCase):
    """The page a browser gets when GET / is refused: the viewer's language rule and message table."""

    def headers(self, accept_language):
        """Request headers with one Accept-Language value."""
        h = Message()
        h["Accept-Language"] = accept_language
        return h

    def test_language_follows_the_query_then_accept_language(self):
        """?lang= wins; otherwise, with no instance default, a first ko* tag gives ko and anything else en."""
        self.assertEqual(page_lang(self.headers("en-US"), {"lang": ["ko"]}, None), "ko")
        self.assertEqual(page_lang(self.headers("ko-KR,en;q=0.8"), {}, None), "ko")
        self.assertEqual(page_lang(self.headers("en-US,ko;q=0.8"), {}, None), "en")

    def test_the_instance_default_comes_between_the_query_and_accept_language(self):
        """The viewer's order (docs/handbook/viewer.md §역할에 따른 화면): ?lang= > the instance's --ui-lang > Accept-Language.
        A ?lang= other than ko or en is no choice."""
        self.assertEqual(page_lang(self.headers("en-US"), {}, "ko"), "ko")
        self.assertEqual(page_lang(self.headers("ko-KR"), {}, "en"), "en")
        self.assertEqual(page_lang(self.headers("ko-KR"), {"lang": ["en"]}, "ko"), "en")
        self.assertEqual(page_lang(self.headers("ko-KR"), {"lang": ["fr"]}, "en"), "en")

    def test_the_page_reopens_in_a_saved_language_once(self):
        """The server cannot see this device's saved choice (localStorage limnLang), so the page carries one fixed line of
        script: without ?lang=, a saved ko or en other than the page's language reopens /?lang=<it> - which has ?lang=,
        so it stops there. The script carries no user data."""
        page = error_page_html(HTTPError(403, "x", reason="not_member", page=("not-member", {"login": "e"})), "ko", {})
        script = page[page.index("<script>") : page.index("</script>")]
        self.assertIn("localStorage.getItem('limnLang')", script)
        self.assertIn("location.search", script)
        self.assertIn("'/?lang='", script)
        self.assertIn("!=='ko'", script)
        self.assertNotIn("e</", script)

    def test_ui_text_uses_the_table_in_english_and_the_key_in_korean(self):
        """In en the table's entry (its "other" plural form) with placeholders filled; in ko the Korean key itself."""
        table = {"안녕 {name}": "Hello {name}", "핀 {n}개": {"one": "{n} pin", "other": "{n} pins"}}
        self.assertEqual(ui_text("안녕 {name}", "en", table, name="Alice"), "Hello Alice")
        self.assertEqual(ui_text("안녕 {name}", "ko", table, name="Alice"), "안녕 Alice")
        self.assertEqual(ui_text("핀 {n}개", "en", table, n=3), "3 pins")
        self.assertEqual(ui_text("없는 문장", "en", table), "없는 문장")

    def test_page_escapes_the_login_and_links_the_other_language(self):
        """A named page kind fills its heading with the escaped login and links to /?lang=<other>."""
        page = error_page_html(
            HTTPError(403, "x", reason="not_member", page=("not-member", {"login": "<b>eve</b>"})), "ko", {}
        )
        self.assertIn("이 뷰어의 멤버가 아닙니다: &lt;b&gt;eve&lt;/b&gt;", page)
        self.assertIn('<a href="/?lang=en">English</a>', page)
        self.assertNotIn("<b>eve</b>", page)


if __name__ == "__main__":
    unittest.main()
