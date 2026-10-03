"""API error bodies: every refusal carries a stable `reason` code next to the Korean `error` text.

The Korean `error` text is part of the agent contract and must not change by a byte; `reason` is additive
(docs/handbook/api.md §오류 응답). The one role-dependent text is the 500 of an unexpected exception: a viewer, and a
request that fails before it is admitted, get the fixed sentence without the exception text (issue #140). The viewer shows English in en mode by looking the reason up in its message
table (`reason:<code>` in src/limn/viewer/ui_en.json) and falls back to the server text (docs/handbook/viewer.md). A
person who is not a member gets a readable HTML page instead of JSON (ErrorPage, v0.2.1 QA).

Run: uv run pytest -q src/limn/web/tests/test_errors.py
"""

import ast
import contextlib
import io
import json
import re
import typing
import unittest
from pathlib import Path
from unittest import mock

from limn.builds import artifacts as build
from limn.builds.answer import BUILD_FAILURES
from limn.pins.editing.values import NOTE_MAX
from limn.pins.location import resolve as pick_resolve
from limn.pins.location.http import PICK_REFUSALS
from limn.pins.location.service import PinLocationService
from limn.revisions import core as revisions
from limn.revisions.answer import REVISION_FAILURES, SCOPE_REJECTIONS, scope_http_error
from limn.security.access import Principal
from limn.security.application import SecurityApplication
from limn.security.guidance import UNAUTHENTICATED
from limn.web import handler as web_handler
from limn.web.errors import HTTPError, InputRejected

from helpers import UI_EN, extract_js_fn, ps, req, run_node, set_config, split_resp
from helpers_access import A_LOGIN, ALICE, B_LOGIN, BOB, CAROL, AccessBase, talk_to, token_create

# The modules that build error bodies or statuses: server.py, the services moved out of it (limn/revisions/core.py: the
# comparison worker's own "build_failed" status; limn/revisions/scope.py, limn/runtime/documents.py: the refusal values), the access boundary (limn/security/access.py: identify,
# admit, check_role and bearer_of raise their refusals) and the HTTP layer (limn/web: the handler, the parsers, the
# answers, the refusal tables), plus feature-owned production modules, excluding colocated tests.
# Every static guard below reads all of them;
# the two tables
# (SCOPE_REJECTIONS, REVISION_FAILURES) are read as data.
PKG = Path(ps.__file__).parent
SOURCES = {
    p.relative_to(PKG).as_posix(): p.read_text(encoding="utf-8")
    for p in [
        Path(ps.__file__),
        PKG / "revisions/core.py",
        PKG / "revisions/execution.py",
        PKG / "revisions/jobs.py",
        PKG / "revisions/scope.py",
        PKG / "runtime/documents.py",
        PKG / "pins/location/lookup.py",
        PKG / "security/access.py",
    ]
    + sorted((PKG / "web").glob("*.py"))
    + sorted((PKG).rglob("*.py"))
    if not p.match("test_*.py")
}


def parsed():
    """(file name, module tree) for every module in SOURCES."""
    return [(name, ast.parse(text)) for name, text in SOURCES.items()]


HANGUL = re.compile(r"[가-힣]")
CODE = re.compile(r"[a-z][a-z0-9_]*")


def _const(node):
    """The value of a string constant node, else None."""
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _codes(node) -> list:
    """The reason codes a reason= expression can take: a string constant, or both branches of a conditional
    expression of string constants ("a" if x else "b"); [] for anything else."""
    if isinstance(node, ast.IfExp):
        codes = [_const(node.body), _const(node.orelse)]
        return codes if all(codes) else []
    code = _const(node)
    return [code] if code else []


def _dict_get(node: ast.Dict, key: str):
    """The value node stored under a constant key in a dict literal, else None."""
    for k, v in zip(node.keys, node.values, strict=True):
        if k is not None and _const(k) == key:
            return v
    return None


def http_error_calls(tree):
    """(line, reason node or None) for every HTTPError(...) construction in one module."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "HTTPError":
            kw = {k.arg: k.value for k in n.keywords}
            out.append((n.lineno, kw.get("reason")))
    return out


def error_dicts(tree):
    """Dict literals that are error bodies or error statuses: an "error" key whose value is not None. A dict used
    as a lookup table ({...}.get(state), the sync-state names) is not a body."""
    tables = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Dict)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict) and id(n) not in tables:
            v = _dict_get(n, "error")
            if v is not None and not (isinstance(v, ast.Constant) and v.value is None):
                yield n


def input_rejections(tree):
    """(line, reason node or None) for every InputRejected(message, reason) construction: the parse_* refusals (R3
    values) whose reason the HTTP answer passes on with the message."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "InputRejected":
            reason = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "reason"), None)
            out.append((n.lineno, reason))
    return out


def emitted_reasons():
    """Every reason code the server can put in an error body or error status: HTTPError reason= literals, the
    InputRejected reasons, the SCOPE_REJECTIONS, REVISION_FAILURES and PICK_REFUSALS tables and error dict literals."""
    codes = (
        {reason for _, _, reason in SCOPE_REJECTIONS.values()}
        | {reason for _, reason in REVISION_FAILURES.values()}
        | {reason for _, reason in PICK_REFUSALS.values()}
    )
    for _, tree in parsed():
        codes |= {c for _, r in http_error_calls(tree) + input_rejections(tree) for c in _codes(r)}
        for d in error_dicts(tree):
            code = _const(_dict_get(d, "reason") or ast.Constant(None))
            if code:
                codes.add(code)
    return codes


class EveryErrorHasAReason(unittest.TestCase):
    """Static guard over server, shared HTTP, and feature routes: every refusal has a stable reason code."""

    def test_every_http_error_names_a_reason_code(self):
        """Each HTTPError(...) passes reason=, a snake_case literal (or a conditional of two) - except where it passes
        on a reason carried by a value: scope_http_error (SCOPE_REJECTIONS) and the answers to an InputRejected."""
        missing = []
        for name, tree in parsed():
            for line, reason in http_error_calls(tree):
                if (isinstance(reason, ast.Name) and reason.id == "reason") or (
                    isinstance(reason, ast.Attribute) and reason.attr == "reason"
                ):
                    continue  # carried: SCOPE_REJECTIONS or InputRejected.reason
                codes = _codes(reason)
                if not codes or not all(CODE.fullmatch(c) for c in codes):
                    missing.append("%s:%d" % (name, line))
        self.assertEqual(missing, [], "HTTPError without a literal reason code at these lines")

    def test_every_input_rejection_names_a_reason_code(self):
        """Each InputRejected(message, reason) - the parse_* refusals - names a snake_case literal, or passes one on."""
        missing = []
        for name, tree in parsed():
            for line, reason in input_rejections(tree):
                if isinstance(reason, ast.Attribute) and reason.attr == "reason":
                    continue
                if not _codes(reason) or not all(CODE.fullmatch(c) for c in _codes(reason)):
                    missing.append("%s:%d" % (name, line))
        self.assertEqual(missing, [])
        self.assertIn("reason", InputRejected._fields)

    def test_every_error_dict_names_a_reason_code(self):
        """Error bodies built as dicts (the pick refusals, the 500, the comparison worker's status) carry a reason."""
        lines = [
            "%s:%d" % (name, d.lineno)
            for name, tree in parsed()
            for d in error_dicts(tree)
            if _dict_get(d, "reason") is None
        ]
        self.assertEqual(lines, [])

    def test_the_scope_table_names_a_reason_for_every_refusal(self):
        """SCOPE_REJECTIONS maps each refusal type to (status, Korean text, reason); the reason is never empty."""
        for kind, (status, msg, reason) in SCOPE_REJECTIONS.items():
            with self.subTest(kind=kind.__name__):
                self.assertTrue(CODE.fullmatch(reason or ""), reason)
                e = scope_http_error(kind())
                self.assertEqual((e.code, e.body), (status, {"error": msg, "reason": reason}))

    def test_the_build_failure_table_names_a_reason_for_every_kind(self):
        """REVISION_FAILURES gives every kind of a failed comparison step (limn.revisions.core.FailureKind) its Korean text
        and a snake_case reason."""
        self.assertEqual(set(REVISION_FAILURES), set(typing.get_args(revisions.FailureKind)))
        for kind, (msg, reason) in REVISION_FAILURES.items():
            with self.subTest(kind=kind):
                self.assertTrue(HANGUL.search(msg))
                self.assertTrue(CODE.fullmatch(reason), reason)

    def test_the_pick_table_names_a_reason_for_every_refusal(self):
        """PICK_REFUSALS gives every way a selection is not traced (limn.pick_resolve.PickRefusal) its Korean text and a
        snake_case reason; the texts take exactly the refusal's own fields as their placeholders."""
        self.assertEqual(set(PICK_REFUSALS), set(typing.get_args(pick_resolve.PickRefusal)))
        for kind, (msg, reason) in PICK_REFUSALS.items():
            with self.subTest(kind=kind.__name__):
                self.assertTrue(HANGUL.search(msg))
                self.assertTrue(CODE.fullmatch(reason), reason)
                self.assertEqual(msg.count("%s"), len(kind.__dataclass_fields__))

    def test_the_document_build_failure_table_has_a_text_for_every_kind(self):
        """BUILD_FAILURES gives every kind of a failed document build (limn.builds.artifacts.BuildFailureKind) its Korean text, and
        the kinds each failure type may carry are exactly those kinds (with "copy", CopyFailed's own)."""
        kinds = set(typing.get_args(build.BuildFailureKind))
        self.assertEqual(set(BUILD_FAILURES), kinds)
        carried = {"copy"} | set(typing.get_args(build.OutputFailureKind)) | set(typing.get_args(build.AbortKind))
        self.assertEqual(carried, kinds)
        self.assertLessEqual(
            set(typing.get_args(build.RenderFailureKind)), set(typing.get_args(build.OutputFailureKind))
        )
        for kind, text in BUILD_FAILURES.items():
            with self.subTest(kind=kind):
                self.assertTrue(HANGUL.search(text))

    def test_http_error_requires_a_reason(self):
        """A refusal cannot be constructed without a reason (keyword-only, no default)."""
        with self.assertRaises(TypeError):
            HTTPError(400, "x")  # noqa - the missing reason is the point
        self.assertEqual(HTTPError(400, "x", reason="bad").body, {"error": "x", "reason": "bad"})


class EnglishTable(unittest.TestCase):
    """The viewer's English table has one message per reason code the server emits, and nothing stale."""

    def test_every_emitted_reason_has_an_english_message(self):
        """reason:<code> is in ui_en.json with a non-empty English value for every code the server can emit."""
        codes = emitted_reasons()
        self.assertGreater(len(codes), 60)
        missing = sorted(c for c in codes if not isinstance(UI_EN.get("reason:" + c), str))
        self.assertEqual(missing, [])
        for c in codes:
            self.assertFalse(HANGUL.search(UI_EN["reason:" + c]), c)

    def test_no_english_message_for_a_reason_the_server_never_emits(self):
        """A reason:<code> key the server no longer emits is stale."""
        keys = {k[len("reason:") :] for k in UI_EN if k.startswith("reason:")}
        self.assertEqual(sorted(keys - emitted_reasons()), [])


class RefusalBodies(AccessBase):
    """The common refusals keep their exact Korean text and status, and add the reason (agent contract, additive)."""

    def test_viewer_role_refusal(self):
        """403 for a view-only person: same text as 0.3.2, reason viewer_only."""
        pid = self.add()
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "viewer"}])
        code, d = self.call("POST", "/api/pins/%d/close" % pid, {}, BOB)
        self.assertEqual(
            (code, d),
            (
                403,
                {
                    "error": "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.",
                    "reason": "viewer_only",
                },
            ),
        )

    def test_base_rev_conflict(self):
        """409 when base_rev is stale: error stays the code "conflict", the current pin comes along, reason repeats the code."""
        pid = self.add()
        self.call("POST", "/api/pins/%d/edit" % pid, {"note": "first", "base_rev": 0})
        code, d = self.call("POST", "/api/pins/%d/edit" % pid, {"note": "second", "base_rev": 0})
        self.assertEqual((code, d["error"], d["reason"], d["pin"]["note"]), (409, "conflict", "conflict", "first"))

    def test_validation_refusal(self):
        """400 for an over-long note: same text, reason note_too_long."""
        code, d = self.call(
            "POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "x" * (NOTE_MAX + 1)}
        )
        self.assertEqual(
            (code, d), (400, {"error": "메모가 너무 깁니다(%d자 이하)." % NOTE_MAX, "reason": "note_too_long"})
        )

    def test_missing_pin_refusal(self):
        """404 for an unknown pin: same text, reason pin_not_found."""
        code, d = self.call("POST", "/api/pins/999/edit", {"note": "x", "base_rev": 0})
        self.assertEqual((code, d), (404, {"error": "핀 #999 이 없습니다.", "reason": "pin_not_found"}))

    def test_unknown_path_and_unauthenticated_requests(self):
        """404 for an unknown path and 401 without an identity keep their text and add not_found / unauthenticated
        (loopback_agent_off for a header-less local request when the loopback agent is off)."""
        code, d = self.call("GET", "/api/nope")
        self.assertEqual((code, d), (404, {"error": "없는 경로입니다: /api/nope", "reason": "not_found"}))
        code, d = self.call("GET", "/api/pins", peer="10.0.0.5")
        self.assertEqual((code, d), (401, {"error": UNAUTHENTICATED, "reason": "unauthenticated"}))
        set_config(agent_loopback=False)  # 0.3.3 (ADR-0007): the local refusal names the token file
        code, d = self.call("GET", "/api/pins")
        self.assertEqual((code, d["reason"]), (401, "loopback_agent_off"))
        self.assertTrue(d["error"].startswith(UNAUTHENTICATED))

    def test_pdf_without_a_build_is_missing_not_gone(self):
        """GET /pdf names what happened: an unknown or deleted ?build= is pdf_build_gone, no build at all is pdf_missing
        (its body already says pdf_build_gone: false)."""
        code, d = self.call("GET", "/pdf?build=pages-19990101000000")
        self.assertEqual((code, d["reason"], d["pdf_build_gone"]), (404, "pdf_build_gone", True))
        code, d = self.call("GET", "/pdf")
        self.assertEqual((code, d["reason"], d["pdf_build_gone"]), (404, "pdf_missing", False))
        self.assertTrue(d["error"].startswith("그 빌드의 PDF 가 없습니다"))

    def overlaps_raising(self, text, headers=None, token=None):
        """GET /api/overlaps as the given identity while the overlap lookup raises RuntimeError(text) ->
        (status, body, what the server wrote to stderr)."""
        err = io.StringIO()
        with (
            mock.patch.object(PinLocationService, "overlaps", side_effect=RuntimeError(text)),
            contextlib.redirect_stderr(err),
        ):
            code, d = self.call("GET", "/api/overlaps?file=%s&lo=1&hi=2" % self.main, headers=headers, token=token)
        return code, d, err.getvalue()

    def role_of(self, headers=None, token=None):
        """The role GET /api/meta reports for the given identity (its `me`), so a case knows whom it exercises."""
        code, d = self.call("GET", "/api/meta", headers=headers, token=token)
        self.assertEqual(code, 200, d)
        return d["me"]["role"]

    def test_internal_error(self):
        """An unexpected exception is a 500 with the same text and reason internal for every role that may read the
        exception: the owner, an editor and an agent (the loopback agent and a token) all get `서버 내부 오류: boom`."""
        self.set_people(
            [
                {"login": A_LOGIN, "name": "Alice", "role": "owner"},
                {"login": B_LOGIN, "name": "Bob", "role": "editor"},
            ]
        )
        _, tok = token_create(ps.APP.C.state, "ci")
        for role, headers, token in (
            ("owner", ALICE, None),
            ("editor", BOB, None),
            ("agent", None, None),
            ("agent", None, tok),
        ):
            with self.subTest(role=role, token=token is not None):
                self.assertEqual(self.role_of(headers, token), role)
                code, d, _ = self.overlaps_raising("boom", headers, token)
                self.assertEqual((code, d), (500, {"error": "서버 내부 오류: boom", "reason": "internal"}))

    def test_a_viewer_gets_the_fixed_internal_error_without_the_exception_text(self):
        """Issue #140: a view-only principal - the viewer role, an unknown role value (closed to viewer) and anyone a
        header admits while people.json cannot be read - gets the fixed `서버 내부 오류`; the exception text, which can
        name a state path, reaches only stderr with its traceback."""
        cases = {
            "viewer role": '{"version": 1, "people": [{"login": "bob@example.com", "name": "Bob", "role": "viewer"}]}',
            "unknown role": '{"version": 1, "people": [{"login": "bob@example.com", "name": "Bob", "role": "admin"}]}',
            "unreadable people.json": '{"version": 1, "people": [',
        }
        for case, people in cases.items():
            with self.subTest(case):
                ps.APP.C.people_file.write_text(people, encoding="utf-8")
                self.assertEqual(self.role_of(BOB), "viewer")
                code, d, err = self.overlaps_raising("cannot read /state/pins.jsonl", BOB)
                self.assertEqual((code, d), (500, {"error": "서버 내부 오류", "reason": "internal"}))
                self.assertIn("Traceback", err)
                self.assertIn("RuntimeError: cannot read /state/pins.jsonl", err)

    def test_a_failure_before_the_role_is_known_gets_the_fixed_internal_error(self):
        """An exception while the request's identity is still being resolved (here: reading people.json's roles) is
        the closed default: the fixed `서버 내부 오류`, never the exception text; stderr still has the traceback."""
        err = io.StringIO()
        with (
            mock.patch.object(
                SecurityApplication, "people_roles", side_effect=RuntimeError("cannot read /state/people.json")
            ),
            contextlib.redirect_stderr(err),
        ):
            code, d = self.call("GET", "/api/pins", headers=BOB)
        self.assertEqual((code, d), (500, {"error": "서버 내부 오류", "reason": "internal"}))
        self.assertIn("RuntimeError: cannot read /state/people.json", err.getvalue())

    def test_a_reused_connection_does_not_lend_the_previous_requests_role_to_a_failure(self):
        """Keep-alive: after an agent's request succeeds on a connection, the next request on it that fails before its
        own role is known still gets the fixed sentence - the earlier request's role does not carry over."""
        first = req("GET", "/api/version")
        second = req("GET", "/api/pins", b"", BOB)
        with (
            mock.patch.object(
                SecurityApplication, "people_roles", side_effect=RuntimeError("cannot read /state/people.json")
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            out = talk_to(ps, first + second)
        self.assertEqual(split_resp(out)[0], 200)
        code, _, body = split_resp(out[out.rindex(b"HTTP/1.1 ") :])
        self.assertEqual((code, json.loads(body)), (500, {"error": "서버 내부 오류", "reason": "internal"}))


class InternalErrorBody(unittest.TestCase):
    """internal_error_body(): the pure choice of the 500 sentence from the admitted principal (issue #140)."""

    def test_the_sentence_follows_the_admitted_principals_role(self):
        """owner, editor and agent read the exception text; viewer and a request not yet admitted (None) get the
        fixed sentence; the reason is internal for all."""
        actor = {"login": "alice@example.com", "name": "Alice"}
        error = RuntimeError("cannot read /state/pins.jsonl")
        detail = {"error": "서버 내부 오류: cannot read /state/pins.jsonl", "reason": "internal"}
        fixed = {"error": "서버 내부 오류", "reason": "internal"}
        cases = [
            (Principal(actor, "owner", "header"), detail),
            (Principal(actor, "editor", "header"), detail),
            (Principal(actor, "agent", "token"), detail),
            (Principal(actor, "viewer", "header"), fixed),
            (None, fixed),
        ]
        for principal, want in cases:
            with self.subTest(role=None if principal is None else principal.role):
                self.assertEqual(web_handler.internal_error_body(principal, error), want)


class ErrText(unittest.TestCase):
    """errText(): the viewer's one way to show an API error body (node runs the real function from the viewer script)."""

    def run_js(self, lang, body):
        """Run the viewer's real tr/tl/trMsg/errText under node in lang and return the JSON of body."""
        js = "\n".join(
            [
                "var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(UI_EN, ensure_ascii=False)),
                extract_js_fn("tr"),
                extract_js_fn("tl"),
                extract_js_fn("trMsg"),
                extract_js_fn("errText"),
                "console.log(JSON.stringify(%s));" % body,
            ]
        )
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        return json.loads(out)

    def test_english_uses_the_reason_and_falls_back_to_the_server_text(self):
        """en: the reason's English message; an unknown reason falls back to the server text through the table."""
        out = self.run_js(
            "en",
            "[errText({error:'핀 #9 이 없습니다.',reason:'pin_not_found'}),"
            "errText({error:'변경사항을 읽지 못했습니다.',reason:'no_such_code'}),"
            "errText({error:'서버 문구'}),errText(null),errText({reason:'conflict',error:'conflict'})]",
        )
        self.assertEqual(
            out,
            [
                UI_EN["reason:pin_not_found"],
                UI_EN["변경사항을 읽지 못했습니다."],
                "서버 문구",
                "",
                UI_EN["reason:conflict"],
            ],
        )

    def test_korean_shows_the_server_text_unchanged(self):
        """ko: exactly the server's error text, whatever the reason."""
        out = self.run_js(
            "ko",
            "[errText({error:'핀 #9 이 없습니다.',reason:'pin_not_found'}),errText({error:'conflict',reason:'conflict'})]",
        )
        self.assertEqual(out, ["핀 #9 이 없습니다.", "conflict"])


# ---------------------------------------------------------------- a readable 403 page for a person who is not a member (v0.2.1 QA)


class ErrorPage(AccessBase):
    """Access refusal pages remain readable and escape untrusted identity text."""

    def test_members_only_refusal_is_a_readable_page(self):
        set_config(members_only=True)
        for lang, want in (
            ("ko-KR,ko;q=0.9", "이 뷰어의 멤버가 아닙니다"),
            ("en-US,en;q=0.9", "not a member of this viewer"),
        ):
            code, hdrs, body = split_resp(
                talk_to(ps, req("GET", "/", b"", dict(CAROL, **{"Accept": "text/html", "Accept-Language": lang})))
            )
            self.assertEqual(code, 403)
            self.assertTrue(hdrs["content-type"].startswith("text/html"), hdrs)
            text = body.decode("utf-8")
            self.assertIn("<html", text)
            self.assertIn(want, text)
            self.assertIn("carol@example.com", text)
            self.assertNotIn('{"error"', text)
        code, hdrs, _ = split_resp(talk_to(ps, req("GET", "/api/pins", b"", CAROL)))
        self.assertEqual((code, hdrs["content-type"].split(";")[0]), (403, "application/json"))  # the API stays JSON

    def test_the_instance_default_language_beats_the_browser_language(self):
        """--ui-lang ko: an English browser refused at GET / reads the Korean page (the viewer's own order)."""
        set_config(members_only=True, ui_lang="ko")
        _, _, body = split_resp(
            talk_to(ps, req("GET", "/", b"", dict(CAROL, **{"Accept": "text/html", "Accept-Language": "en-US"})))
        )
        self.assertIn("이 뷰어의 멤버가 아닙니다", body.decode("utf-8"))

    def test_page_escapes_the_login(self):
        set_config(members_only=True)
        h = {"Tailscale-User-Login": "<b>x</b>@example.com", "Tailscale-User-Name": "X", "Accept": "text/html"}
        _, _, body = split_resp(talk_to(ps, req("GET", "/", b"", h)))
        self.assertNotIn("<b>x</b>", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
