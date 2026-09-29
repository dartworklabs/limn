"""Lifecycle service and HTTP behavior over real pin storage and explicit collaborators."""

import json
from unittest import mock

from limn.access import LOCAL_ACTOR
from limn.features.pins.claims.rules import ClaimClosedPin
from limn.features.pins.lifecycle import input as lifecycle_input
from limn.features.pins.lifecycle.rules import AgentCannotConfirm, AlreadyClosed, CloseRequest, ThreadFull
from limn.features.pins.lifecycle.service import PinLifecycle
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin
from limn.pins.view import pin_state
from limn.store import PinFiles, PinStore
from limn.web.errors import InputRejected

from helpers import (
    Base,
    fits,
    ps,
    record_of,
    req,
    split_resp,
)
from helpers_access import ALICE_ACTOR, BOB_ACTOR, AccessBase
from helpers_pin_service import AGENT, ServiceBase, parse_rec, parse_trash


class Transitions(ServiceBase):
    """reply_pin, close_pin, reopen_pin and confirm_pin around the lifecycle feature rules."""

    def test_agent_close_awaits_review_and_tells_the_author(self):
        """An agent's close is a ReviewPin with a review_requested notice to the author; a second close is
        AlreadyClosed and leaves the file as it was."""
        pid = self.add()
        out = PinLifecycle(lambda: self.ctx).close_pin(pid, AGENT, CloseRequest(reply="fixed"))
        self.assertIsInstance(out, ReviewPin)
        self.assertEqual(self.rec.emitted[-1], [{"type": "review_requested", "pin": pid, "to": ["alice@example.com"]}])
        before = self.pins_bytes()
        self.assertIsInstance(PinLifecycle(lambda: self.ctx).close_pin(pid, BOB_ACTOR, CloseRequest()), AlreadyClosed)
        self.assertEqual(self.pins_bytes(), before)

    def test_a_person_reply_on_a_closed_pin_reopens_it(self):
        """A person's untagged reply on a done pin is a reopen: the pin is open again and the author hears reopened."""
        pid = self.add()
        PinLifecycle(lambda: self.ctx).close_pin(pid, ALICE_ACTOR, CloseRequest())
        out = PinLifecycle(lambda: self.ctx).reply_pin(pid, "redo please", BOB_ACTOR)
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(self.pin(pid)["thread"][-1]["ev"], "reopen")
        self.assertIn({"type": "reopened", "pin": pid, "to": ["alice@example.com"]}, self.rec.emitted[-1])

    def test_a_full_thread_refuses_the_reply_without_writing(self):
        """With thread_max replies already there the next is ThreadFull and pins.jsonl is unchanged."""
        pid = self.add()
        self.ctx = self.context(thread_max=1)
        self.assertIsInstance(PinLifecycle(lambda: self.ctx).reply_pin(pid, "one", BOB_ACTOR), OpenPin)
        before = self.pins_bytes()
        self.assertIsInstance(PinLifecycle(lambda: self.ctx).reply_pin(pid, "two", BOB_ACTOR), ThreadFull)
        self.assertEqual(self.pins_bytes(), before)

    def test_close_or_reopen_of_a_missing_pin_is_a_named_miss(self):
        """close_pin and reopen_pin on no pin are PinNotFound, and nothing is written."""
        pid = self.add()
        before = self.pins_bytes()
        self.assertEqual(
            PinLifecycle(lambda: self.ctx).close_pin(pid + 6, ALICE_ACTOR, CloseRequest(reply="x")),
            PinNotFound(pid + 6),
        )
        self.assertEqual(
            PinLifecycle(lambda: self.ctx).reopen_pin(pid + 6, ALICE_ACTOR, "why", None), PinNotFound(pid + 6)
        )
        self.assertEqual(self.pins_bytes(), before)

    def test_an_agent_confirm_never_loads_the_store(self):
        """AgentCannotConfirm comes back before the store is read: a store whose re-sync would fail is never asked."""

        def boom(pins):
            """A re-sync that must not run."""
            raise AssertionError("store touched")

        ctx = self.context(
            store=PinStore(PinFiles(self.state), self.lock, parse_rec, parse_trash, boom, lambda pins: "")
        )
        self.assertEqual(PinLifecycle(lambda: ctx).confirm_pin(1, AGENT), AgentCannotConfirm())

    def test_a_person_confirms_a_pin_awaiting_review(self):
        """Review -> done by a person; confirming again is refused and writes nothing."""
        pid = self.add()
        PinLifecycle(lambda: self.ctx).close_pin(pid, AGENT, CloseRequest())
        self.assertIsInstance(PinLifecycle(lambda: self.ctx).confirm_pin(pid, ALICE_ACTOR), DonePin)
        before = self.pins_bytes()
        self.assertNotIsInstance(PinLifecycle(lambda: self.ctx).confirm_pin(pid, ALICE_ACTOR), DonePin)
        self.assertEqual(self.pins_bytes(), before)


class CloseReplyRef(Base):
    """§C: /close accepts optional {"reply","ref"} and stores them as close_reply/close_ref."""

    def test_close_with_reply_and_ref_is_stored(self):
        pid = self.add()
        p = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                dict(LOCAL_ACTOR),
                lifecycle_input.parse_close({"reply": "제목을 고침", "ref": "PR #227"}, ps.APP.C.src, ps.APP.C.state),
            )
        )
        self.assertEqual(p["close_reply"], "제목을 고침")
        self.assertEqual(p["close_ref"], "PR #227")
        self.assertTrue(p["done"])

    def test_close_without_body_behaves_as_before(self):
        pid = self.add()
        p = record_of(ps.APP.pin_lifecycle.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest()))
        self.assertNotIn("close_reply", p)
        self.assertNotIn("close_ref", p)

    def test_clean_close_body_empty_or_whitespace_is_none(self):
        self.assertEqual(lifecycle_input.parse_close_body({}), (None, None))
        self.assertEqual(lifecycle_input.parse_close_body({"reply": "", "ref": "  "}), (None, None))
        self.assertEqual(lifecycle_input.parse_close_body({"reply": None, "ref": None}), (None, None))

    def test_clean_close_body_rejects_wrong_type(self):
        self.assertIsInstance(lifecycle_input.parse_close_body({"reply": 123}), InputRejected)
        self.assertIsInstance(lifecycle_input.parse_close_body({"ref": ["PR #227"]}), InputRejected)

    def test_clean_close_body_enforces_length_caps(self):
        self.assertIsInstance(
            lifecycle_input.parse_close_body({"reply": "x" * (lifecycle_input.CLOSE_REPLY_MAX + 1)}), InputRejected
        )
        self.assertIsInstance(
            lifecycle_input.parse_close_body({"ref": "x" * (lifecycle_input.CLOSE_REF_MAX + 1)}), InputRejected
        )
        # the cap itself is allowed through.
        reply, ref = lifecycle_input.parse_close_body(
            {"reply": "x" * lifecycle_input.CLOSE_REPLY_MAX, "ref": "x" * lifecycle_input.CLOSE_REF_MAX}
        )
        self.assertEqual(len(reply), lifecycle_input.CLOSE_REPLY_MAX)
        self.assertEqual(len(ref), lifecycle_input.CLOSE_REF_MAX)

    def test_close_endpoint_http_stores_reply_and_escapes_in_card(self):
        pid = self.add()
        body = json.dumps({"reply": "제목을 <b>고침</b>", "ref": "PR #227"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        p = self.pin(pid)
        self.assertEqual(p["close_reply"], "제목을 <b>고침</b>")
        self.assertEqual(p["close_ref"], "PR #227")

    def test_close_endpoint_http_rejects_oversized_reply(self):
        pid = self.add()
        body = json.dumps({"reply": "x" * (lifecycle_input.CLOSE_REPLY_MAX + 1)}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)
        self.assertFalse(self.pin(pid).get("done"))


class CloseIdempotent(Base):
    """§D: re-closing an already-closed pin changes nothing (rev stays the same too)."""

    def test_second_close_does_not_overwrite_closed_by_or_rev(self):
        """A repeated close preserves the first actor, timestamp, and revision."""
        pid = self.add()
        first = record_of(ps.APP.pin_lifecycle.close_pin(pid, {"login": "alice", "name": "Wendy"}, CloseRequest()))
        self.assertEqual(first["rev"], 1)
        second = record_of(ps.APP.pin_lifecycle.close_pin(pid, {"login": "bob", "name": "Bob"}, CloseRequest()))
        self.assertEqual(second["closed_by"]["login"], "alice")
        self.assertEqual(second["rev"], first["rev"])
        self.assertEqual(second["done_at"], first["done_at"])

    def test_second_close_with_reply_does_not_apply(self):
        """A reply on a repeated close cannot replace the first close reply."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid, dict(LOCAL_ACTOR), lifecycle_input.parse_close({"reply": "first"}, ps.APP.C.src, ps.APP.C.state)
        )
        again = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid, dict(LOCAL_ACTOR), lifecycle_input.parse_close({"reply": "second"}, ps.APP.C.src, ps.APP.C.state)
            )
        )
        self.assertEqual(again["close_reply"], "first")

    def test_reopen_then_close_allows_new_reply(self):
        """Reopening clears the prior close details so a later close records its own reply."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            dict(LOCAL_ACTOR),
            lifecycle_input.parse_close({"reply": "first", "ref": "PR #1"}, ps.APP.C.src, ps.APP.C.state),
        )
        ps.APP.pin_lifecycle.reopen_pin(pid, dict(LOCAL_ACTOR))
        reopened = self.pin(pid)
        self.assertNotIn("close_reply", reopened)
        self.assertNotIn("close_ref", reopened)
        closed_again = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid, dict(LOCAL_ACTOR), lifecycle_input.parse_close({"reply": "second"}, ps.APP.C.src, ps.APP.C.state)
            )
        )
        self.assertEqual(closed_again["close_reply"], "second")
        self.assertNotIn("close_ref", closed_again)

    def test_close_http_endpoint_second_call_returns_ok_unchanged(self):
        pid = self.add()
        out1 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out1)
        rev_after_first = self.pin(pid)["rev"]
        out2 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out2)
        self.assertTrue(json.loads(out2.split(b"\r\n\r\n", 1)[1])["ok"])
        self.assertEqual(self.pin(pid)["rev"], rev_after_first)


class ReviewTransitions(Base):
    """A pin awaiting review is not open work for agents (not listed, not claimable, counted apart), and reopening a
    confirmed pin drops the confirmation."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_review_pins_are_not_open_for_agents(self):
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))
        _, _, raw = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(json.loads(raw), [])  # not in the open-pin list (legacy contract)
        self.assertIsInstance(ps.APP.pin_claims.claim_pin(pid, dict(LOCAL_ACTOR), 30), ClaimClosedPin)  # 409 "done"
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR))
        self.assertEqual((m["n_open"], m["n_review"], m["n_done"]), (0, 1, 0))

    def test_reopen_after_confirm_drops_confirmation(self):
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest())
        ps.APP.pin_lifecycle.confirm_pin(pid, dict(self.S))
        ps.APP.pin_lifecycle.reopen_pin(pid, dict(self.S), reason="다시")
        p = self.pin(pid)
        self.assertNotIn("confirmed_by", p)
        self.assertEqual(pin_state(p), "open")


class CloseChanges(AccessBase):
    """The optional `changes` on POST /api/pins/{id}/close: validation, storage, reopen, pins.md."""

    def setUp(self):
        super().setUp()
        (self.src / "sec").mkdir()
        (self.src / "sec" / "a.tex").write_text("x\n" * 30)
        self.pid = self.add()

    def close(self, body):
        return self.call("POST", "/api/pins/%d/close" % self.pid, body)

    def test_valid_changes_are_stored_as_absolute_paths_and_exposed(self):
        """A valid changes list is stored resolved and absolute on the first close and appears in the pins API."""
        code, d = self.close(
            {
                "reply": "fixed",
                "ref": "abc1234",
                "changes": [
                    {"file": "main.tex", "lo": 4, "hi": 5},
                    {"file": str(self.src / "sec" / "a.tex"), "lo": 7, "hi": 7},
                ],
            }
        )
        self.assertEqual(code, 200, d)
        want = [
            {"file": str(self.main.resolve()), "lo": 4, "hi": 5},
            {"file": str((self.src / "sec" / "a.tex").resolve()), "lo": 7, "hi": 7},
        ]
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins/%d" % self.pid)
        self.assertEqual(d["pin"]["changes"], want)
        code, d = self.call("GET", "/api/pins?all=1")
        self.assertEqual([p.get("changes") for p in d if p["id"] == self.pid], [want])
        self.assertTrue(fits(self.pin(self.pid)))

    def test_invalid_changes_are_rejected_with_400_and_change_nothing(self):
        """Each malformed changes item or list is a 400 and leaves the pin open (boundary validation)."""
        bad = [
            {"file": "main.tex", "lo": 5, "hi": 4},
            {"file": "main.tex", "lo": 0, "hi": 1},
            {"file": "main.tex", "lo": 1.5, "hi": 2},
            {"file": "main.tex", "lo": True, "hi": 2},
            {"file": "main.tex", "lo": "1", "hi": 2},
            {"file": "main.tex", "lo": 1},
            {"file": "", "lo": 1, "hi": 1},
            {"file": 3, "lo": 1, "hi": 1},
            {"file": "../outside.tex", "lo": 1, "hi": 1},
            {"file": "/etc/passwd", "lo": 1, "hi": 1},
            {"file": "main.tex", "lo": 1, "hi": 1, "extra": 1},
            {"file": "main.tex", "lo": 1, "hi": 10**7},
            {"file": "a\x00b", "lo": 1, "hi": 1},
            "main.tex:1-2",
        ]
        for item in bad:
            with self.subTest(item=item):
                code, d = self.close({"changes": [item]})
                self.assertEqual(code, 400, d)
                self.assertFalse(self.pin(self.pid).get("done"))
        for whole in (
            {"file": "main.tex", "lo": 1, "hi": 1},
            "x",
            [{"file": "main.tex", "lo": 1, "hi": 1}] * (lifecycle_input.CLOSE_CHANGES_MAX + 1),
        ):
            with self.subTest(whole=str(whole)[:40]):
                code, d = self.close({"changes": whole})
                self.assertEqual(code, 400, d)
        self.assertFalse(self.pin(self.pid).get("done"))

    def test_absent_or_empty_changes_close_like_0_2_2(self):
        """Old agents: a close without changes (or with []) stores nothing new."""
        code, d = self.close({"changes": []})
        self.assertEqual(code, 200)
        self.assertNotIn("changes", d["pin"])
        other = self.add(lo=8, hi=9)
        code, d = self.call("POST", "/api/pins/%d/close" % other)
        self.assertEqual((code, "changes" in d["pin"]), (200, False))

    def test_reclose_keeps_and_reopen_clears_changes(self):
        """Changes follow close_reply/close_ref: the first close wins, a reopen clears them."""
        self.close({"changes": [{"file": "main.tex", "lo": 4, "hi": 5}]})
        self.close({"changes": [{"file": "main.tex", "lo": 9, "hi": 9}]})
        self.assertEqual(self.pin(self.pid)["changes"][0]["lo"], 4)
        self.call("POST", "/api/pins/%d/reopen" % self.pid, {})
        self.assertNotIn("changes", self.pin(self.pid))

    def test_a_malformed_stored_changes_field_marks_the_line_broken(self):
        """The record parse (parse_record) refuses a record whose stored changes have the wrong shape."""
        r = dict(self.pin(self.pid), changes=[{"file": 3, "lo": 1, "hi": 2}])
        self.assertFalse(fits(r))
        self.assertTrue(fits(dict(r, changes=[{"file": "/a.tex", "lo": 1, "hi": 2}])))

    def test_pins_md_close_instruction_line_asks_for_changes_and_the_merged_commit(self):
        """Owner decision (review of #13): the close line asks for changes and ref = PR #N (hash); the rest of the line is 0.2.2's."""
        # decided after review (ADR-0005, accepted): paper repos squash-merge and agents close after the merge, so the
        # line asks for `changes` in the numbering of the commit `ref` names, and ref = "PR #N (<hash>)"; per-pin commits
        # help but are optional
        text = ps.APP.pin_markdown.pins_md_text(ps.APP.snapshot_pins())
        line = next(ln for ln in text.splitlines() if ln.startswith("처리한 핀은 닫는다"))
        self.assertTrue(
            line.startswith(
                "처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: `curl"
            ),
            line,
        )
        self.assertIn(
            '"ref":"PR #12 (커밋 해시)","changes":[{"file":"main.tex","lo":12,"hi":14}]}'
            + "' http://127.0.0.1:18999/api/pins/N/close`",
            line,
        )
        self.assertIn(
            "(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. 핀마다 커밋을 나누면 더 좋지만 필수는 아니다)"
            + " · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · '질문' 핀은 원고를 고치지 말고",
            line,
        )
        self.assertNotIn("스쿼시하지", line)
        self.assertTrue(
            line.endswith(
                "에이전트는 확인(confirm)하지 않는다 — `/api/pins/N/confirm` 은 사람 신원(테일넷 헤더)이 없으면 403"
            )
        )


class PinKindAndThread(Base):
    """Reply limits exempt state transitions, and closing appends its reply exactly once."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def test_thread_is_capped(self):
        pid = self.add()
        with mock.patch.object(ps, "THREAD_MAX", 2):
            ps.APP.pin_lifecycle.reply_pin(pid, "1", dict(self.S))
            ps.APP.pin_lifecycle.reply_pin(pid, "2", dict(self.S))
            self.assertEqual(
                ps.APP.pin_lifecycle.reply_pin(pid, "3", dict(self.S)), ThreadFull(2)
            )  # answered 409 "full" over HTTP
            # a status-transition record is exempt from the cap
            ps.APP.pin_lifecycle.close_pin(pid, dict(self.S), CloseRequest(reply="닫음"))
        self.assertEqual([m.get("ev") for m in self.pin(pid)["thread"]], [None, None, "close"])

    def test_close_reply_is_appended_to_thread_once(self):
        pid = self.add()
        ps.APP.pin_lifecycle.reply_pin(pid, "질문이 있어요", dict(self.S))
        ps.APP.pin_lifecycle.close_pin(pid, dict(self.S), CloseRequest(reply="제목을 고침", ref="PR #227"))
        ps.APP.pin_lifecycle.close_pin(
            pid, dict(self.S), CloseRequest(reply="두 번째 닫기")
        )  # already closed — nothing gets appended
        th = self.pin(pid)["thread"]
        self.assertEqual(
            [(m["id"], m.get("ev"), m["text"], m.get("ref")) for m in th],
            [(1, None, "질문이 있어요", None), (2, "close", "제목을 고침", "PR #227")],
        )
        # the old field is left in place too (compat with old viewers/agents)
        self.assertEqual(self.pin(pid)["close_reply"], "제목을 고침")
