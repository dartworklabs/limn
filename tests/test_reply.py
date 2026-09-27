"""POST /api/pins/{id}/reply - one [Reply] whose outcome the server's reply rule decides (v0.2.2, issue #8).

The rule (docs/handbook/domain.md §전이와 할 수 있는 쪽, api.md §스레드 (답글)):

| pin state            | who    | reply tags a person? | result                                   |
| review / done        | human  | no                   | reopens; the reply is the reason (ev:reopen) |
| review / done        | human  | yes                  | state unchanged; that person is notified |
| open                 | anyone | -                    | state unchanged                          |
| question pin         | anyone | -                    | recorded as an answer, state unchanged   |

An optional "reopen": true/false on the request overrides the rule ([Keep state] sends false). Every row of the table
is test_pins_lifecycle.ReplyRule (the server's rule) and test_viewer.FrontendReplyRule (the viewer's preview); here
the route applies it and answers `reopened` and `state` (ReplyApi), and an agent that sends as a person is a person
to the rule (AgentAsPerson). The route's plain thread behaviour is test_server.KindAndThread.

Run: uv run pytest -q tests/test_reply.py
"""

from limn.access import LOCAL_ACTOR
from limn.pins import render as md_render
from limn.pins.lifecycle import CloseRequest
from limn.pins.model import OpenPin, ReviewPin
from limn.pins.view import pin_state
from limn.store import find_pin

from helpers import ROOT, add_pin, ps, records, write_records
from helpers_access import ALICE, BOB, CAROL, AccessBase, actor, token_create

A, B = actor(ALICE), actor(BOB)


class ReplyApi(AccessBase):
    """POST /api/pins/{id}/reply applies the rule on the server; the response adds `reopened` and `state`."""

    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))

    def review_pin(self, kind="fix", author=A):
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기", "kind_req": kind}, author
        ).record["id"]
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="줄였습니다", ref="PR #9"))
        self.assertEqual(pin_state(self.pin(pid)), "review")
        return pid

    def done_pin(self):
        pid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "오타"}, A).record["id"]
        ps.close_pin(pid, A, CloseRequest(reply="고침"))
        self.assertEqual(pin_state(self.pin(pid)), "done")
        return pid

    def reply(self, pid, body, headers=None, token=None):
        return self.call("POST", "/api/pins/%d/reply" % pid, body, headers, token=token)

    def events(self):
        return [(e["type"], sorted(e["to"])) for e in ps._read_events()[0]]

    def test_human_reply_on_review_pin_reopens_with_the_reply_as_reason(self):
        pid = self.review_pin()
        n = len(self.events())
        code, d = self.reply(pid, {"text": "식 번호가 아직 틀립니다"}, BOB)
        self.assertEqual(code, 200, d)
        self.assertEqual((d["ok"], d["reopened"], d["state"]), (True, True, "open"))
        p = self.pin(pid)
        self.assertFalse(p["done"])
        for k in ("review", "close_reply", "close_ref", "confirmed_by"):
            self.assertNotIn(k, p)
        self.assertEqual(p["reopened_by"], {"login": "bob@example.com", "name": "Bob Park"})
        self.assertEqual((p["thread"][-1]["ev"], p["thread"][-1]["text"]), ("reopen", "식 번호가 아직 틀립니다"))
        self.assertEqual(d["msg"]["ev"], "reopen")
        self.assertEqual(self.events()[n:], [("reopened", ["alice@example.com"])])

    def test_human_reply_on_done_pin_reopens(self):
        pid = self.done_pin()
        code, d = self.reply(pid, {"text": "다시 보니 문장이 어색합니다"}, CAROL)
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))
        self.assertEqual(self.pin(pid)["thread"][-1]["ev"], "reopen")

    def test_reply_that_tags_a_person_keeps_state_and_notifies_them(self):
        pid = self.review_pin()
        n = len(self.events())
        code, d = self.reply(pid, {"text": "@Carol Lee 이 수정 괜찮은지 봐 주세요"}, BOB)
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        last = self.pin(pid)["thread"][-1]
        self.assertNotIn("ev", last)
        self.assertEqual(last["mentions"], ["carol@example.com"])
        self.assertEqual(self.events()[n:], [("mention", ["carol@example.com"]), ("replied", ["alice@example.com"])])

    def test_reopening_reply_still_tells_everyone_involved(self):
        # A reply on a closed pin used to reach everyone tagged on the pin (replied); reopening must not silence them.
        pid = add_pin(
            {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "@Carol Lee 참고로 봐 주세요"}, A
        ).record["id"]
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))
        n = len(self.events())
        code, d = self.reply(pid, {"text": "아직 틀립니다"}, BOB)
        self.assertEqual(d["reopened"], True)
        self.assertEqual(self.events()[n:], [("reopened", ["alice@example.com"]), ("replied", ["carol@example.com"])])
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="다시 고침"))
        n = len(self.events())
        self.reply(pid, {"text": "제가 다시 엽니다"}, ALICE)  # the author: only Carol hears of it
        self.assertEqual(self.events()[n:], [("replied", ["carol@example.com"])])

    def test_tagging_only_yourself_is_not_tagging_a_person(self):
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "@Bob Park 메모: 다시 봐야 함"}, BOB)
        self.assertEqual((d["reopened"], d["state"]), (True, "open"))

    def test_reply_on_open_pin_never_changes_state(self):
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n"}, A).record["id"]
        for body in ({"text": "이유 없이"}, {"text": "강제로", "reopen": True}):
            code, d = self.reply(pid, body, BOB)
            self.assertEqual((code, d["reopened"], d["state"]), (200, False, "open"))
        self.assertTrue(all("ev" not in m for m in self.pin(pid)["thread"]))

    def test_agent_reply_never_reopens_by_rule(self):
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "추가 설명: 식 (3) 도 같이 고쳤습니다"})  # headerless loopback agent
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        _, tok = token_create(ps.C.state, "bot")
        code, d = self.reply(pid, {"text": "토큰으로 단 답글"}, token=tok)
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))

    def test_person_with_agent_role_is_an_agent_for_the_rule(self):
        self.set_people([{"login": "carol@example.com", "name": "Carol Lee", "role": "agent"}])
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "에이전트 역할의 답글"}, CAROL)
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))

    def test_question_pin_reply_is_an_answer(self):
        pid = self.review_pin(kind="question")
        code, d = self.reply(pid, {"text": "95% 신뢰구간입니다"}, BOB)
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        code, d = self.reply(pid, {"text": "그래도 다시 봐 주세요", "reopen": True}, BOB)
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))

    def test_keep_state_override(self):
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "확인은 내일 할게요", "reopen": False}, BOB)
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        self.assertNotIn("ev", self.pin(pid)["thread"][-1])

    def test_explicit_reopen_by_an_agent(self):
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "제가 놓친 부분이 있어 다시 엽니다", "reopen": True})
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))

    def test_tagging_an_agent_role_person_is_not_tagging_a_person(self):
        self.set_people([{"login": "carol@example.com", "name": "Carol Lee", "role": "agent"}])
        pid = self.review_pin()
        code, d = self.reply(pid, {"text": "@Carol Lee 이 부분 다시 고쳐 주세요"}, BOB)
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))

    def test_reopen_field_must_be_a_boolean(self):
        pid = self.review_pin()
        before = self.pin(pid)
        for bad in ("yes", 1, [], {}):
            code, d = self.reply(pid, {"text": "x", "reopen": bad}, BOB)
            self.assertEqual(code, 400, bad)
        self.assertEqual(self.pin(pid), before)

    def test_viewer_role_cannot_reply(self):
        self.set_people([{"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"}])
        pid = self.review_pin()
        code, _ = self.reply(pid, {"text": "x"}, CAROL)
        self.assertEqual(code, 403)
        self.assertEqual(pin_state(self.pin(pid)), "review")

    def test_unknown_pin(self):
        code, d = self.reply(999, {"text": "x"}, BOB)
        self.assertEqual((code, d["ok"]), (200, False))

    def test_reopened_pin_shows_in_open_table_with_reply_as_reason(self):
        pid = self.review_pin()
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertNotRegex(md, r"\n\| %d · " % pid)  # awaiting review: not in the open table
        self.reply(pid, {"text": "식 번호가 아직 틀립니다"}, BOB)
        md = ps.pins_md_text(ps.snapshot_pins())
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d · " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀립니다", row)
        self.assertNotIn("## 검토 대기", md)

    def test_full_thread_still_reopens(self):
        pid = self.review_pin()
        rows = records(ps.read_pins()[0])
        r = find_pin(rows, pid)
        r["thread"] = r["thread"] + [
            {"id": 100 + i, "by": A, "at": "2026-09-25 10:00:00", "text": "x"} for i in range(ps.THREAD_MAX)
        ]
        write_records(rows)
        code, d = self.reply(pid, {"text": "다시"}, BOB)
        self.assertEqual((code, d["reopened"]), (200, True))
        code, d = self.reply(pid, {"text": "이제는 가득"}, BOB)
        self.assertEqual((code, d["error"]), (409, "full"))

    def test_reopen_endpoint_is_kept_for_compatibility(self):
        pid = self.review_pin()
        code, d = self.call("POST", "/api/pins/%d/reopen" % pid, {"reason": "옛 경로"}, BOB)
        self.assertEqual((code, d["state"]), (200, "open"))

    def test_python_api_returns_the_pin_with_its_new_entry_last(self):
        """reply_pin() returns the pin as it now stands (its state type); the reply's entry is the thread's last."""
        pid = self.review_pin()
        pin = ps.reply_pin(pid, "사람 답글", B)
        self.assertIsInstance(pin, OpenPin)  # a person's reply reopened it
        self.assertEqual(pin.record["thread"][-1]["ev"], "reopen")
        pid = self.review_pin()
        pin = ps.reply_pin(pid, "에이전트 답글", dict(LOCAL_ACTOR))
        self.assertIsInstance(pin, ReviewPin)  # an agent's reply leaves it for review
        self.assertNotIn("ev", pin.record["thread"][-1])


class AgentAsPerson(AccessBase):
    """An agent without a token that sends as a person (--auth local headerless curl, or a person-logged-in machine
    through the tailnet address) is a person to the rule - its reply reopens a review pin unless it sends reopen:false."""

    def setUp(self):
        super().setUp()
        ps.C.auth = "local"
        ps.C.agent_loopback = False
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n"}, A).record["id"]
        ps.close_pin(pid, dict(LOCAL_ACTOR), CloseRequest(reply="고침"))
        self.pid = pid

    def test_headerless_local_curl_reopens_unless_it_says_reopen_false(self):
        code, d = self.call("POST", "/api/pins/%d/reply" % self.pid, {"text": "설명 덧붙임", "reopen": False})
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        code, d = self.call("POST", "/api/pins/%d/reply" % self.pid, {"text": "설명 덧붙임"})
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))

    def test_the_instruction_is_in_pins_md_skill_and_api(self):
        md = ps.pins_md_text(ps.snapshot_pins()).splitlines()
        i = md.index(md_render.TOKEN_GUIDANCE)
        self.assertEqual(md[i + 1], md_render.REPLY_GUIDANCE)  # additive line after the token line
        self.assertIn('`"reopen":false`', md_render.REPLY_GUIDANCE)
        self.assertIn("토큰 없이", md_render.REPLY_GUIDANCE)
        for f, needle in (
            (ROOT / "skill" / "SKILL.md", '"reopen": false'),
            (ROOT / "skill" / "SKILL.ko.md", '"reopen": false'),
            (ROOT / "docs" / "handbook" / "api.md", '"reopen": false'),
        ):
            text = f.read_text(encoding="utf-8")
            self.assertIn(needle, text, f.name)
            j = text.index(needle)
            self.assertIn('"review": true', text[max(0, j - 800) : j + 800], f.name)  # next to the review:true note
