"""API error bodies: every refusal carries a stable `reason` code next to the Korean `error` text.

The Korean `error` text is part of the agent contract and must not change by a byte; `reason` is additive
(docs/handbook/api.md §오류 응답). The viewer shows English in en mode by looking the reason up in its message
table (`reason:<code>` in src/limn/ui_en.json) and falls back to the server text (docs/handbook/viewer.md).

Run: uv run pytest -q tests/test_errors.py
"""
import ast
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from limn.web.errors import SCOPE_REJECTIONS, InputRejected
from test_access import BOB, AccessBase
from test_server import extract_js_fn, ps, run_node

# The modules that build error bodies: server.py and the HTTP layer moved out of it (limn/web: the handler, the
# answers to pin outcomes, SCOPE_REJECTIONS). Every static guard below reads all of them, keyed by file name.
SOURCES = {p.name if p.parent.name != "web" else "web/" + p.name: p.read_text(encoding="utf-8")
           for p in [Path(ps.__file__)] + sorted((Path(ps.__file__).parent / "web").glob("*.py"))}


def parsed():
    """(file name, module tree) for server.py and every limn/web module."""
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
    InputRejected reasons, the SCOPE_REJECTIONS table and error dict literals."""
    codes = {reason for _, _, reason in SCOPE_REJECTIONS.values()}
    for _, tree in parsed():
        codes |= {c for _, r in http_error_calls(tree) + input_rejections(tree) for c in _codes(r)}
        for d in error_dicts(tree):
            code = _const(_dict_get(d, "reason") or ast.Constant(None))
            if code:
                codes.add(code)
    return codes


class EveryErrorHasAReason(unittest.TestCase):
    """Static guard over server.py and limn/web: no refusal can be written without a stable reason code."""

    def test_every_http_error_names_a_reason_code(self):
        """Each HTTPError(...) passes reason=, a snake_case literal (or a conditional of two) - except where it passes
        on a reason carried by a value: scope_http_error (SCOPE_REJECTIONS) and the answers to an InputRejected."""
        missing = []
        for name, tree in parsed():
            for line, reason in http_error_calls(tree):
                if (isinstance(reason, ast.Name) and reason.id == "reason") or (
                        isinstance(reason, ast.Attribute) and reason.attr == "reason"):
                    continue                            # carried: SCOPE_REJECTIONS or InputRejected.reason
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
        lines = ["%s:%d" % (name, d.lineno) for name, tree in parsed() for d in error_dicts(tree)
                 if _dict_get(d, "reason") is None]
        self.assertEqual(lines, [])

    def test_the_scope_table_names_a_reason_for_every_refusal(self):
        """SCOPE_REJECTIONS maps each refusal to (status, Korean text, reason); the reason is never empty."""
        for name, (status, msg, reason) in SCOPE_REJECTIONS.items():
            with self.subTest(name=name):
                self.assertTrue(CODE.fullmatch(reason or ""), reason)
                e = ps.scope_http_error(ps.ScopeRejected(name))
                self.assertEqual((e.code, e.body), (status, {"error": msg, "reason": reason}))

    def test_http_error_requires_a_reason(self):
        """A refusal cannot be constructed without a reason (keyword-only, no default)."""
        with self.assertRaises(TypeError):
            ps.HTTPError(400, "x")          # noqa - the missing reason is the point
        self.assertEqual(ps.HTTPError(400, "x", reason="bad").body, {"error": "x", "reason": "bad"})


class EnglishTable(unittest.TestCase):
    """The viewer's English table has one message per reason code the server emits, and nothing stale."""

    def test_every_emitted_reason_has_an_english_message(self):
        """reason:<code> is in ui_en.json with a non-empty English value for every code the server can emit."""
        codes = emitted_reasons()
        self.assertGreater(len(codes), 60)
        missing = sorted(c for c in codes if not isinstance(ps.UI_EN.get("reason:" + c), str))
        self.assertEqual(missing, [])
        for c in codes:
            self.assertFalse(HANGUL.search(ps.UI_EN["reason:" + c]), c)

    def test_no_english_message_for_a_reason_the_server_never_emits(self):
        """A reason:<code> key the server no longer emits is stale."""
        keys = {k[len("reason:"):] for k in ps.UI_EN if k.startswith("reason:")}
        self.assertEqual(sorted(keys - emitted_reasons()), [])


class RefusalBodies(AccessBase):
    """The common refusals keep their exact Korean text and status, and add the reason (agent contract, additive)."""

    def test_viewer_role_refusal(self):
        """403 for a view-only person: same text as 0.3.2, reason viewer_only."""
        pid = self.add()
        self.set_people([{"login": "bob@example.com", "name": "Bob", "role": "viewer"}])
        code, d = self.call("POST", "/api/pins/%d/close" % pid, {}, BOB)
        self.assertEqual((code, d), (403, {"error": "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.",
                                           "reason": "viewer_only"}))

    def test_base_rev_conflict(self):
        """409 when base_rev is stale: error stays the code "conflict", the current pin comes along, reason repeats the code."""
        pid = self.add()
        self.call("POST", "/api/pins/%d/edit" % pid, {"note": "first", "base_rev": 0})
        code, d = self.call("POST", "/api/pins/%d/edit" % pid, {"note": "second", "base_rev": 0})
        self.assertEqual((code, d["error"], d["reason"], d["pin"]["note"]), (409, "conflict", "conflict", "first"))

    def test_validation_refusal(self):
        """400 for an over-long note: same text, reason note_too_long."""
        code, d = self.call("POST", "/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1,
                                                 "note": "x" * (ps.NOTE_MAX + 1)})
        self.assertEqual((code, d), (400, {"error": "메모가 너무 깁니다(%d자 이하)." % ps.NOTE_MAX, "reason": "note_too_long"}))

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
        self.assertEqual((code, d), (401, {"error": ps.UNAUTHENTICATED, "reason": "unauthenticated"}))
        ps.C.agent_loopback = False                         # 0.3.3 (ADR-0007): the local refusal names the token file
        code, d = self.call("GET", "/api/pins")
        self.assertEqual((code, d["reason"]), (401, "loopback_agent_off"))
        self.assertTrue(d["error"].startswith(ps.UNAUTHENTICATED))

    def test_pdf_without_a_build_is_missing_not_gone(self):
        """GET /pdf names what happened: an unknown or deleted ?build= is pdf_build_gone, no build at all is pdf_missing
        (its body already says pdf_build_gone: false)."""
        code, d = self.call("GET", "/pdf?build=pages-19990101000000")
        self.assertEqual((code, d["reason"], d["pdf_build_gone"]), (404, "pdf_build_gone", True))
        code, d = self.call("GET", "/pdf")
        self.assertEqual((code, d["reason"], d["pdf_build_gone"]), (404, "pdf_missing", False))
        self.assertTrue(d["error"].startswith("그 빌드의 PDF 가 없습니다"))

    def test_internal_error(self):
        """An unexpected exception is a 500 with the same text and reason internal."""
        with mock.patch.object(ps, "overlaps_api", side_effect=RuntimeError("boom")), \
                mock.patch.object(ps.traceback, "print_exc"):
            code, d = self.call("GET", "/api/overlaps?file=%s&lo=1&hi=2" % self.main)
        self.assertEqual((code, d), (500, {"error": "서버 내부 오류: boom", "reason": "internal"}))


class ErrText(unittest.TestCase):
    """errText(): the viewer's one way to show an API error body (node runs the real function from the viewer script)."""

    def run_js(self, lang, body):
        """Run the viewer's real tr/tl/trMsg/errText under node in lang and return the JSON of body."""
        js = "\n".join(["var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(ps.UI_EN, ensure_ascii=False)),
                        extract_js_fn("tr"), extract_js_fn("tl"), extract_js_fn("trMsg"), extract_js_fn("errText"),
                        "console.log(JSON.stringify(%s));" % body])
        out = run_node(js)
        if out is None:
            self.skipTest("node not available")
        return json.loads(out)

    def test_english_uses_the_reason_and_falls_back_to_the_server_text(self):
        """en: the reason's English message; an unknown reason falls back to the server text through the table."""
        out = self.run_js("en", "[errText({error:'핀 #9 이 없습니다.',reason:'pin_not_found'}),"
                                "errText({error:'변경사항을 읽지 못했습니다.',reason:'no_such_code'}),"
                                "errText({error:'서버 문구'}),errText(null),errText({reason:'conflict',error:'conflict'})]")
        self.assertEqual(out, [ps.UI_EN["reason:pin_not_found"], ps.UI_EN["변경사항을 읽지 못했습니다."], "서버 문구", "",
                               ps.UI_EN["reason:conflict"]])

    def test_korean_shows_the_server_text_unchanged(self):
        """ko: exactly the server's error text, whatever the reason."""
        out = self.run_js("ko", "[errText({error:'핀 #9 이 없습니다.',reason:'pin_not_found'}),errText({error:'conflict',reason:'conflict'})]")
        self.assertEqual(out, ["핀 #9 이 없습니다.", "conflict"])


if __name__ == "__main__":
    unittest.main()
