"""limn.revisions.answer.revision_refused - the HTTP answer to every refusal of the revision routes, as one table.

GET /api/revision-diff|-build|-pdf and POST /api/revision-build answer each refusal value of limn.revisions.core (and the
pin-scoping refusals of limn.pins.changes) with a fixed status, the Korean `error` text agents read and a stable `reason`
(docs/handbook/api.md §변경 보기와 비교 PDF, §오류 응답). Most of these refusals need a git failure, a symlinked cache, a
held lock or a vanished file to reach through a route, so the table builds each value directly and checks the whole
answer: status, reason, text and a body with nothing else in it. One route test shows a table row is what the handler
really sends.

Run: uv run pytest -q src/limn/web/tests/test_web_answers.py
"""

import json
import typing
import unittest

from limn.pins.changes import PinNotInDoc, ScopeMismatch, ScopeRefusal, ScopeUnreadable, ScopeUnwritable, UnsafePath
from limn.revisions import answer as revision_answer, core as revisions
from limn.revisions.core import (
    AllSlotsBusy,
    CommitNotRecent,
    DiffFailed,
    DiffUnavailable,
    DocumentBusy,
    NoHistory,
    NoParent,
    NotInRepo,
    RevisionNotReady,
    RevisionPdfMissing,
    UnsafeCache,
)
from limn.web.errors import HTTPError

from helpers import Base, req, split_resp

# Every refusal type of the revision routes -> (status, error text, reason): the agent contract, byte for byte.
REFUSALS = {
    NoHistory: (404, "이 문서는 원고 변경사항을 볼 수 없습니다.", "no_history"),
    CommitNotRecent: (404, "현재 문서의 최근 커밋이 아닙니다.", "commit_not_recent"),
    DiffFailed: (404, "변경사항을 읽지 못했습니다.", "diff_unreadable"),
    DiffUnavailable: (503, "변경사항을 읽지 못했습니다.", "diff_unreadable"),
    NotInRepo: (400, "Git 저장소 안의 문서 빌드 루트가 필요합니다.", "not_in_repo"),
    NoParent: (422, "첫 커밋은 이전 원고가 없어 비교 PDF를 만들 수 없습니다.", "no_parent"),
    AllSlotsBusy: (409, "다른 비교 PDF를 만드는 중입니다. 잠시 뒤 다시 시도하세요.", "busy"),
    DocumentBusy: (409, "이 문서의 비교 PDF를 만드는 중입니다.", "busy"),
    UnsafeCache: (503, "비교 캐시 경로가 올바르지 않습니다.", "unsafe_cache"),
    RevisionNotReady: (404, "해당 비교 PDF가 아직 없거나 만료됐습니다.", "revision_not_ready"),
    RevisionPdfMissing: (404, "해당 비교 PDF가 없습니다.", "revision_pdf_missing"),
    PinNotInDoc: (404, "이 문서의 핀이 아닙니다.", "pin_not_in_doc"),
    ScopeUnreadable: (422, "이 핀의 변경만 골라 적용하지 못했습니다.", "scope_failed"),
    ScopeMismatch: (422, "이 핀의 변경을 커밋에서 다시 찾지 못했습니다.", "scope_failed"),
    UnsafePath: (422, "사본에 허용되지 않는 경로가 있습니다.", "unsafe_snapshot"),
    ScopeUnwritable: (422, "이 핀의 변경만 넣은 사본을 쓰지 못했습니다.", "scope_failed"),
}


def refusal_types() -> set[type]:
    """Every member of limn.revisions.core.RevisionRefusal, its nested unions flattened."""
    seen: set[type] = set()
    todo = list(typing.get_args(revisions.RevisionRefusal))
    while todo:
        t = todo.pop()
        args = typing.get_args(t)
        if args:
            todo.extend(args)
        else:
            seen.add(t)
    return seen


def answer_of(refusal) -> HTTPError:
    """The HTTPError revision_refused raises for refusal (it never returns)."""
    try:
        revision_answer.revision_refused(refusal)
    except HTTPError as e:
        return e
    raise AssertionError("revision_refused returned for %r" % (refusal,))


class RevisionRefusalTable(unittest.TestCase):
    """Each refusal value is answered with its own status, reason and text, in a body of exactly error and reason."""

    def test_the_table_names_every_refusal_of_the_revision_routes(self):
        """A refusal type added to RevisionRefusal (or to the scoping refusals revision_refused also answers) without
        a row here would go unpinned: the sets must agree."""
        self.assertEqual(refusal_types() | set(typing.get_args(ScopeRefusal)), set(REFUSALS))
        self.assertEqual(len([t for t in REFUSALS if t.__module__ == "limn.revisions.core"]), 11)

    def test_each_refusal_gets_its_status_reason_and_text(self):
        """revision_refused raises HTTPError(status, text, reason) and nothing more: no extra body field, no page."""
        for kind, (status, text, reason) in REFUSALS.items():
            with self.subTest(refusal=kind.__name__):
                e = answer_of(kind())
                self.assertEqual((e.code, e.body, e.page), (status, {"error": text, "reason": reason}, None))

    def test_both_route_answers_refuse_through_the_same_table(self):
        """revision_answer (JSON routes) and revision_pdf_answer (the PDF route) pass a result through and answer a
        refusal exactly as revision_refused does."""
        self.assertEqual(revision_answer.revision_answer({"state": "ready"}), {"state": "ready"})
        self.assertEqual(revision_answer.revision_pdf_answer(b"%PDF-1.4"), b"%PDF-1.4")
        for route in (revision_answer.revision_answer, revision_answer.revision_pdf_answer):
            for kind, (status, text, reason) in REFUSALS.items():
                with self.subTest(route=route.__name__, refusal=kind.__name__), self.assertRaises(HTTPError) as cm:
                    route(kind())
                self.assertEqual((cm.exception.code, cm.exception.body), (status, {"error": text, "reason": reason}))


class RevisionRefusalOverHttp(Base):
    """A table row is what the handler sends: the fixture manuscript lies outside any git repository."""

    def test_a_manuscript_without_history_is_answered_no_history(self):
        """GET /api/revision-diff on a folder outside git -> 404 with the NoHistory row's body, as JSON."""
        code, hdrs, body = split_resp(self.talk(req("GET", "/api/revision-diff?commit=" + "a" * 40)))
        status, text, reason = REFUSALS[NoHistory]
        self.assertEqual((code, json.loads(body)), (status, {"error": text, "reason": reason}))
        self.assertTrue(hdrs["content-type"].startswith("application/json"), hdrs)


if __name__ == "__main__":
    unittest.main()
