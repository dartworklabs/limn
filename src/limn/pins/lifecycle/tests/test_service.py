"""Lifecycle service and HTTP behavior over real pin storage and explicit collaborators."""

import json
from unittest import mock

from limn.pins import runtime as pin_runtime
from limn.pins.claims.rules import ClaimClosedPin
from limn.pins.lifecycle import input as lifecycle_input
from limn.pins.lifecycle.rules import AlreadyClosed, AlreadyDone, CloseRequest, ShownCloseChanged, ThreadFull
from limn.pins.lifecycle.service import PinLifecycle
from limn.pins.listing.projection import pin_state
from limn.pins.model import DonePin, OpenPin, PinNotFound, ReviewPin
from limn.pins.store import PinFiles, PinStore
from limn.security.access import LOCAL_ACTOR
from limn.web.errors import HTTPError, InputRejected

from helpers import (
    Base,
    fits,
    ps,
    record_of,
    req,
    split_resp,
)
from helpers_access import ALICE_ACTOR, BOB, BOB_ACTOR, AccessBase
from helpers_authority import post_authority
from helpers_pin_service import AGENT, ServiceBase, parse_rec, parse_trash


class Transitions(ServiceBase):
    """reply_pin, close_pin, reopen_pin and confirm_pin around the lifecycle feature rules."""

    def test_agent_close_awaits_review_and_tells_the_author(self):
        """An agent's close is a ReviewPin with a review_requested notice to the author; a second close is
        AlreadyClosed and leaves the file as it was."""
        pid = self.add()
        out = PinLifecycle(lambda: self.ctx).close_pin(
            pid,
            post_authority(PinLifecycle(lambda: self.ctx).context().store, AGENT, "close", pid),
            CloseRequest(reply="fixed"),
        )
        self.assertIsInstance(out, ReviewPin)
        self.assertEqual(self.rec.emitted[-1], [{"type": "review_requested", "pin": pid, "to": ["alice@example.com"]}])
        before = self.pins_bytes()
        self.assertIsInstance(
            PinLifecycle(lambda: self.ctx).close_pin(
                pid,
                post_authority(PinLifecycle(lambda: self.ctx).context().store, BOB_ACTOR, "close", pid),
                CloseRequest(),
            ),
            AlreadyClosed,
        )
        self.assertEqual(self.pins_bytes(), before)

    def test_a_person_reply_on_a_closed_pin_reopens_it(self):
        """A person's untagged reply on a done pin is a reopen: the pin is open again and the author hears reopened."""
        pid = self.add()
        PinLifecycle(lambda: self.ctx).close_pin(
            pid,
            post_authority(PinLifecycle(lambda: self.ctx).context().store, ALICE_ACTOR, "close", pid),
            CloseRequest(),
        )
        out = PinLifecycle(lambda: self.ctx).reply_pin(
            pid, "redo please", post_authority(PinLifecycle(lambda: self.ctx).context().store, BOB_ACTOR, "reply", pid)
        )
        self.assertIsInstance(out, OpenPin)
        self.assertEqual(self.pin(pid)["thread"][-1]["ev"], "reopen")
        self.assertIn({"type": "reopened", "pin": pid, "to": ["alice@example.com"]}, self.rec.emitted[-1])

    def test_a_full_thread_refuses_the_reply_without_writing(self):
        """With thread_max replies already there the next is ThreadFull and pins.jsonl is unchanged."""
        pid = self.add()
        self.ctx = self.context(thread_max=1)
        self.assertIsInstance(
            PinLifecycle(lambda: self.ctx).reply_pin(
                pid, "one", post_authority(PinLifecycle(lambda: self.ctx).context().store, BOB_ACTOR, "reply", pid)
            ),
            OpenPin,
        )
        before = self.pins_bytes()
        self.assertIsInstance(
            PinLifecycle(lambda: self.ctx).reply_pin(
                pid, "two", post_authority(PinLifecycle(lambda: self.ctx).context().store, BOB_ACTOR, "reply", pid)
            ),
            ThreadFull,
        )
        self.assertEqual(self.pins_bytes(), before)

    def test_close_or_reopen_of_a_missing_pin_is_a_named_miss(self):
        """close_pin and reopen_pin on no pin are PinNotFound, and nothing is written."""
        pid = self.add()
        before = self.pins_bytes()
        self.assertEqual(
            PinLifecycle(lambda: self.ctx).close_pin(
                pid + 6,
                post_authority(PinLifecycle(lambda: self.ctx).context().store, ALICE_ACTOR, "close", pid + 6),
                CloseRequest(reply="x"),
            ),
            PinNotFound(pid + 6),
        )
        self.assertEqual(
            PinLifecycle(lambda: self.ctx).reopen_pin(
                pid + 6,
                post_authority(PinLifecycle(lambda: self.ctx).context().store, ALICE_ACTOR, "reopen", pid + 6),
                "why",
                None,
            ),
            PinNotFound(pid + 6),
        )
        self.assertEqual(self.pins_bytes(), before)

    def test_an_agent_confirm_never_loads_the_store(self):
        """An agent cannot acquire confirm authority; issuance refuses before reading or writing the store."""

        def boom(pins):
            """A re-sync that must not run."""
            raise AssertionError("store touched")

        ctx = self.context(
            store=PinStore(PinFiles(self.state), self.lock, parse_rec, parse_trash, boom, lambda pins: "")
        )
        before = self.pins_bytes()
        with self.assertRaises(HTTPError) as refused:
            post_authority(ctx.store, AGENT, "confirm", 1)
        self.assertEqual((refused.exception.code, refused.exception.body["reason"]), (403, "confirm_by_human"))
        self.assertEqual(self.pins_bytes(), before)

    def test_a_person_confirms_a_pin_awaiting_review(self):
        """Review -> done by a person; confirming again is refused and writes nothing."""
        pid = self.add()
        PinLifecycle(lambda: self.ctx).close_pin(
            pid, post_authority(PinLifecycle(lambda: self.ctx).context().store, AGENT, "close", pid), CloseRequest()
        )
        self.assertIsInstance(
            PinLifecycle(lambda: self.ctx).confirm_pin(
                pid, post_authority(PinLifecycle(lambda: self.ctx).context().store, ALICE_ACTOR, "confirm", pid)
            ),
            DonePin,
        )
        before = self.pins_bytes()
        self.assertNotIsInstance(
            PinLifecycle(lambda: self.ctx).confirm_pin(
                pid, post_authority(PinLifecycle(lambda: self.ctx).context().store, ALICE_ACTOR, "confirm", pid)
            ),
            DonePin,
        )
        self.assertEqual(self.pins_bytes(), before)


class CloseReplyRef(Base):
    """§C: /close accepts optional {"reply","ref"} and stores them as close_reply/close_ref."""

    def test_close_with_reply_and_ref_is_stored(self):
        """Parsed close text and reference survive persistence alongside the completed flag."""
        pid = self.add()
        p = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                lifecycle_input.parse_close({"reply": "제목을 고침", "ref": "PR #227"}, ps.APP.C.src, ps.APP.C.state),
            )
        )
        self.assertEqual(p["close_reply"], "제목을 고침")
        self.assertEqual(p["close_ref"], "PR #227")
        self.assertTrue(p["done"])

    def test_close_without_body_behaves_as_before(self):
        """Legacy bodyless close requests do not introduce optional reply or reference fields."""
        pid = self.add()
        p = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                CloseRequest(),
            )
        )
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
        first = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, {"login": "alice", "name": "Wendy"}, "close", pid),
                CloseRequest(),
            )
        )
        self.assertEqual(first["rev"], 1)
        second = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, {"login": "bob", "name": "Bob"}, "close", pid),
                CloseRequest(),
            )
        )
        self.assertEqual(second["closed_by"]["login"], "alice")
        self.assertEqual(second["rev"], first["rev"])
        self.assertEqual(second["done_at"], first["done_at"])

    def test_second_close_with_reply_does_not_apply(self):
        """A reply on a repeated close cannot replace the first close reply."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            lifecycle_input.parse_close({"reply": "first"}, ps.APP.C.src, ps.APP.C.state),
        )
        again = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                lifecycle_input.parse_close({"reply": "second"}, ps.APP.C.src, ps.APP.C.state),
            )
        )
        self.assertEqual(again["close_reply"], "first")

    def test_reopen_then_close_allows_new_reply(self):
        """Reopening clears the prior close details so a later close records its own reply."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            lifecycle_input.parse_close({"reply": "first", "ref": "PR #1"}, ps.APP.C.src, ps.APP.C.state),
        )
        ps.APP.pin_lifecycle.reopen_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "reopen", pid)
        )
        reopened = self.pin(pid)
        self.assertNotIn("close_reply", reopened)
        self.assertNotIn("close_ref", reopened)
        closed_again = record_of(
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                lifecycle_input.parse_close({"reply": "second"}, ps.APP.C.src, ps.APP.C.state),
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
        """Review pins disappear from the legacy open list, refuse claims, and retain their separate metadata count."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        _, _, raw = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(json.loads(raw), [])  # not in the open-pin list (legacy contract)
        self.assertIsInstance(
            ps.APP.pin_claims.claim_pin(
                pid, post_authority(ps.APP.pin_claims.context().store, dict(LOCAL_ACTOR), "claim", pid), 30
            ),
            ClaimClosedPin,
        )  # 409 "done"
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR))
        self.assertEqual((m["n_open"], m["n_review"], m["n_done"]), (0, 1, 0))

    def test_reopen_after_confirm_drops_confirmation(self):
        """Reopening a confirmed pin returns it to open and removes obsolete confirmation attribution."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )
        ps.APP.pin_lifecycle.confirm_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "confirm", pid)
        )
        ps.APP.pin_lifecycle.reopen_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reopen", pid), reason="다시"
        )
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
        """A full message thread refuses another reply but still records a closing state transition."""
        pid = self.add()
        with mock.patch.object(pin_runtime, "THREAD_MAX", 2):
            ps.APP.pin_lifecycle.reply_pin(
                pid, "1", post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reply", pid)
            )
            ps.APP.pin_lifecycle.reply_pin(
                pid, "2", post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reply", pid)
            )
            self.assertEqual(
                ps.APP.pin_lifecycle.reply_pin(
                    pid, "3", post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reply", pid)
                ),
                ThreadFull(2),
            )  # answered 409 "full" over HTTP
            # a status-transition record is exempt from the cap
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", pid),
                CloseRequest(reply="닫음"),
            )
        self.assertEqual([m.get("ev") for m in self.pin(pid)["thread"]], [None, None, "close"])

    def test_close_reply_is_appended_to_thread_once(self):
        """Repeated close requests append one transition only and preserve the legacy close_reply projection."""
        pid = self.add()
        ps.APP.pin_lifecycle.reply_pin(
            pid, "질문이 있어요", post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "reply", pid)
        )
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", pid),
            CloseRequest(reply="제목을 고침", ref="PR #227"),
        )
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", pid),
            CloseRequest(reply="두 번째 닫기"),
        )  # already closed — nothing gets appended
        th = self.pin(pid)["thread"]
        self.assertEqual(
            [(m["id"], m.get("ev"), m["text"], m.get("ref")) for m in th],
            [(1, None, "질문이 있어요", None), (2, "close", "제목을 고침", "PR #227")],
        )
        # the old field is left in place too (compat with old viewers/agents)
        self.assertEqual(self.pin(pid)["close_reply"], "제목을 고침")


class ConfirmShownClose(ServiceBase):
    """confirm_pin with the done_at of the close the person saw, over real pin storage and an injected clock."""

    def setUp(self):
        """A clock this test moves, so a reopen and a second close happen at a later second than the first close."""
        super().setUp()
        self.clock = ["2026-10-03 09:00:00"]
        self.ctx = self.context(now=lambda: self.clock[0])
        self.life = PinLifecycle(lambda: self.ctx)

    def act(self, actor, operation, pid):
        """Authority for actor to run operation on pid, issued over this test's store."""
        return post_authority(self.ctx.store, actor, operation, pid)

    def closed_by_the_agent(self):
        """A pin the agent closed into review at the clock's first second -> (id, the done_at a person sees)."""
        pid = self.add()
        self.life.close_pin(pid, self.act(AGENT, "close", pid), CloseRequest())
        return pid, self.pin(pid)["done_at"]

    def test_a_close_redone_after_the_person_looked_is_not_confirmed(self):
        """The agent reopens and closes again; confirming the close the person saw changes nothing on disk."""
        pid, seen = self.closed_by_the_agent()
        self.clock[0] = "2026-10-03 09:05:00"
        self.life.reopen_pin(pid, self.act(AGENT, "reopen", pid))
        self.life.close_pin(pid, self.act(AGENT, "close", pid), CloseRequest())
        before = self.pins_bytes()
        result = self.life.confirm_pin(pid, self.act(ALICE_ACTOR, "confirm", pid), seen)
        self.assertIsInstance(result, ShownCloseChanged)
        self.assertEqual(self.pins_bytes(), before)
        self.assertTrue(self.pin(pid)["review"])

    def test_the_close_the_person_saw_is_confirmed_once(self):
        """The same done_at confirms the pin; a second confirm of that close is AlreadyDone and writes nothing."""
        pid, seen = self.closed_by_the_agent()
        self.assertIsInstance(self.life.confirm_pin(pid, self.act(ALICE_ACTOR, "confirm", pid), seen), DonePin)
        before = self.pins_bytes()
        self.assertIsInstance(self.life.confirm_pin(pid, self.act(ALICE_ACTOR, "confirm", pid), seen), AlreadyDone)
        self.assertEqual(self.pins_bytes(), before)


class ConfirmInput(Base):
    """The confirm body's optional done_at: absent is None, a timestamp string passes, anything else is bad_done_at."""

    def test_absent_or_null_done_at_is_none(self):
        """No body field, or null, confirms whatever close the pin holds, as before the field existed."""
        self.assertIsNone(lifecycle_input.parse_confirm({}))
        self.assertIsNone(lifecycle_input.parse_confirm({"done_at": None}))

    def test_a_done_at_string_is_kept(self):
        """The close's done_at comes back as sent."""
        self.assertEqual(lifecycle_input.parse_confirm({"done_at": "2026-10-03 09:00:00"}), "2026-10-03 09:00:00")

    def test_other_values_are_refused(self):
        """A number, a list, a blank string or one longer than a timestamp is refused before the pin is read."""
        for value in (5, ["x"], "", "   ", "x" * 65):
            with self.subTest(value=value):
                refused = lifecycle_input.parse_confirm({"done_at": value})
                self.assertIsInstance(refused, InputRejected)
                self.assertEqual(refused.reason, "bad_done_at")


class ConfirmShownCloseHttp(AccessBase):
    """POST /api/pins/{id}/confirm with done_at through the real handler (docs/handbook/api.md §검토 대기)."""

    def review_pin(self):
        """A pin the loopback agent closed into review -> (id, its done_at as GET /api/pins/{id} shows it)."""
        pid = self.add()
        self.assertEqual(self.call("POST", "/api/pins/%d/close" % pid)[1]["state"], "review")
        return pid, self.call("GET", "/api/pins/%d" % pid)[1]["pin"]["done_at"]

    def test_another_close_is_a_conflict_with_the_pin(self):
        """A done_at that is not the pin's close answers 409 conflict with the current pin and writes nothing."""
        pid, _ = self.review_pin()
        before = ps.APP.C.pins_jsonl.read_bytes()
        code, d = self.call("POST", "/api/pins/%d/confirm" % pid, {"done_at": "1999-01-01 00:00:00"}, BOB)
        self.assertEqual((code, d["error"], d["reason"], d["pin"]["id"]), (409, "conflict", "conflict", pid))
        self.assertEqual(ps.APP.C.pins_jsonl.read_bytes(), before)

    def test_the_shown_close_is_confirmed(self):
        """The pin's own done_at confirms it, and sending it again is the idempotent ok."""
        pid, seen = self.review_pin()
        code, d = self.call("POST", "/api/pins/%d/confirm" % pid, {"done_at": seen}, BOB)
        self.assertEqual((code, d["ok"], d["state"]), (200, True, "done"))
        code, d = self.call("POST", "/api/pins/%d/confirm" % pid, {"done_at": seen}, BOB)
        self.assertEqual((code, d["ok"], d["state"]), (200, True, "done"))

    def test_a_malformed_done_at_is_bad_done_at(self):
        """A done_at that is not a string is a 400 bad_done_at and the pin stays awaiting review."""
        pid, _ = self.review_pin()
        code, d = self.call("POST", "/api/pins/%d/confirm" % pid, {"done_at": 1}, BOB)
        self.assertEqual((code, d["reason"]), (400, "bad_done_at"))
        self.assertEqual(self.call("GET", "/api/pins/%d" % pid)[1]["pin"]["state"], "review")


class FilesBeforeClose(ServiceBase):
    """close_pin brings a watched document's files up to date (the context's refresh_files) before the close is written
    and before its notice is emitted, so the person who gets the notice already sees the edited figure; no other close
    calls it (docs/handbook/api.md §닫을 때 사유 남기기)."""

    def setUp(self):
        """An open pin and an empty log of the refresh and emit calls in the order they happen."""
        super().setUp()
        self.pid = self.add()
        self.log = []

    def close(self, actor, request, watched=True, pid=None):
        """Close pin pid (default the open pin) as actor with request, over a context whose document is watched (or
        not) and whose refresh_files and emit_events log what they see: whether the pin is already closed on disk
        when the files are refreshed, and the notices emitted."""

        def refresh(record):
            """Log the refresh with the pin's stored state at that moment."""
            self.log.append(("refresh", record["id"], bool(self.pin(record["id"]).get("done"))))

        def emit(evs):
            """Log the notices, then record them as the recorder does."""
            self.log.append(("emit", [e["type"] for e in evs if e]))
            self.rec.emit(evs)

        ctx = self.context(watches_files=lambda r: watched, refresh_files=refresh, emit_events=emit)
        pid = self.pid if pid is None else pid
        return PinLifecycle(lambda: ctx).close_pin(pid, post_authority(ctx.store, actor, "close", pid), request)

    def test_an_agents_close_with_a_reference_refreshes_before_it_is_written_and_announced(self):
        """The refresh sees the pin still open on disk, and the review_requested notice comes after it."""
        out = self.close(AGENT, CloseRequest(reply="fixed", ref="PR #3 (abc1234)"))
        self.assertIsInstance(out, ReviewPin)
        self.assertEqual(self.log, [("refresh", self.pid, False), ("emit", ["review_requested"])])

    def test_other_closes_close_at_once(self):
        """A person's close, a close without a reference and a close on a document whose files are not watched never
        refresh; neither does a second close of a closed pin, nor a close of a pin that does not exist."""
        for name, actor, request, watched in (
            ("a person's close", ALICE_ACTOR, CloseRequest(ref="abc1234"), True),
            ("no reference", AGENT, CloseRequest(reply="fixed"), True),
            ("not watched", AGENT, CloseRequest(ref="abc1234"), False),
        ):
            with self.subTest(name):
                self.pid, self.log = self.add(), []
                self.assertIsInstance(self.close(actor, request, watched), ReviewPin | DonePin)
                self.assertNotIn("refresh", [entry[0] for entry in self.log])
        self.log = []
        self.assertIsInstance(self.close(AGENT, CloseRequest(ref="abc1234")), AlreadyClosed)
        self.assertIsInstance(self.close(AGENT, CloseRequest(ref="abc1234"), pid=999), PinNotFound)
        self.assertEqual([entry for entry in self.log if entry[0] == "refresh"], [])
