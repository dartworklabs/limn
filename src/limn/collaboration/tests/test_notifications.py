"""Notices through the server: who gets a `mention`, `replied`, `reopened`, `review_requested` or `assigned` event in
a pin's life, and how a person's poll collects them (GET /api/meta?light=1&ev=<seq>).

The rules are pure and tested on their own in test_mentions.py (whom a text tags, the note cooldown) and
test_events.py (building and picking events). Here they run through server.py's pin operations and the handler:

- MentionRules (the v0.2.1 QA, finding A): every explicit @-tag in a reply, reopen reason or note edit notifies that
  person, whatever was tagged before, never the author; nobody gets both `mention` and `replied`.
- NoteMentionCooldown (v0.3.1, issue #10 L3): toggling a tag through note edits notifies once per ten minutes per
  editor, person and pin; replies and reopen reasons still notify every time.
- MentionEvents: the events of a pin's life over HTTP. EventCursor: the poll's cursor.

Run: uv run pytest -q src/limn/collaboration/tests/test_notifications.py
"""

import json
import time
from unittest import mock

from limn.collaboration.events import NOTIFY_TYPES
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.mentions import NOTE_MENTION_COOLDOWN_S
from limn.security.access import LOCAL_ACTOR

from helpers import Base, add_pin, edit_pin, find_record, ps, req, split_resp
from helpers_access import A_LOGIN, ALICE, B_LOGIN, BOB, C_LOGIN, CAROL, DAVE, actor
from helpers_authority import post_authority


class MentionRules(Base):
    """Every explicit @mention in a new reply, reopen reason or note edit is a `mention` event for that person (never
    the author themself), whatever was mentioned before; everyone else involved gets `replied`; nobody gets both."""

    def setUp(self):
        super().setUp()
        for h in (ALICE, BOB, CAROL, DAVE):
            ps.APP.people_directory.record(actor(h))
        self.A, self.B, self.C, self.D = (actor(h) for h in (ALICE, BOB, CAROL, DAVE))

    def events_after(self, n):
        return [(e["type"], sorted(e["to"])) for e in ps.APP.notices.read()[0][n:]]

    def n(self):
        return len(ps.APP.notices.read()[0])

    def test_first_mention_in_a_reply(self):
        """A first explicit reply mention emits one notification to the tagged person."""
        pid = self.add(actor=self.A)
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Bob Park 봐 주세요", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])

    def test_re_mention_in_a_second_reply_notifies_again(self):
        """Repeated explicit tags notify again; subsequent untagged replies notify the existing participant as replied."""
        pid = self.add(actor=self.A)
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Bob Park 봐 주세요", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Bob Park 다시 부름", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid, "태그 없는 답글", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )  # no tag: Bob (mentioned before) gets replied
        self.assertEqual(self.events_after(n), [("replied", ["bob@example.com"])])

    def test_note_mention_then_reply_mention(self):
        """Retagging a note recipient emits a mention while the untagged pin author receives a reply notice."""
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단"}, self.A).record["id"]
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid,
            "@Bob Park 이것도 봐 주세요",
            post_authority(ps.APP.pin_lifecycle.context().store, self.C, "reply", pid),
        )
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"]), ("replied", ["alice@example.com"])])

    def test_self_mention_never_notifies_the_author(self):
        """A self-tag never notifies its author, but other existing participants still receive reply notices."""
        pid = self.add(actor=self.A)
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Bob Park 확인", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid,
            "@Bob Park 제가 스스로 부름",
            post_authority(ps.APP.pin_lifecycle.context().store, self.B, "reply", pid),
        )  # Bob tags himself: nothing for Bob
        self.assertEqual(self.events_after(n), [("replied", ["alice@example.com"])])
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Alice Kim 나", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )  # the pin author tags herself
        self.assertEqual(self.events_after(n), [("replied", ["bob@example.com"])])

    def test_mention_plus_other_participants_nobody_gets_both(self):
        """Explicitly tagged participants receive mention notices without duplicate replied delivery."""
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Carol Lee 참고"}, self.A).record["id"]
        ps.APP.pin_lifecycle.reply_pin(
            pid, "@Bob Park 의견?", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
        )
        n = self.n()
        ps.APP.pin_lifecycle.reply_pin(
            pid,
            "@Bob Park @Carol Lee 둘 다 봐 주세요",
            post_authority(ps.APP.pin_lifecycle.context().store, self.D, "reply", pid),
        )
        evs = ps.APP.notices.read()[0][n:]
        self.assertEqual(
            [(e["type"], sorted(e["to"])) for e in evs],
            [("mention", ["bob@example.com", "carol@example.com"]), ("replied", ["alice@example.com"])],
        )
        to = [lg for e in evs for lg in e["to"]]
        self.assertEqual(len(to), len(set(to)))  # one event per person per reply

    def test_reopen_reason_re_mention_notifies(self):
        """Reopening mentions notify tagged people and suppress duplicate reopened delivery to a tagged author."""
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 부탁"}, self.A).record["id"]
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )
        n = self.n()
        ps.APP.pin_lifecycle.reopen_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, self.C, "reopen", pid),
            reason="@Bob Park 다시 봐 주세요",
        )
        self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"]), ("reopened", ["alice@example.com"])])
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )
        n = self.n()
        # the author tagged: mention only, not also reopened
        ps.APP.pin_lifecycle.reopen_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, self.C, "reopen", pid),
            reason="@Alice Kim 확인 부탁",
        )
        self.assertEqual(self.events_after(n), [("mention", ["alice@example.com"])])

    def test_note_edit_that_tags_again_notifies_but_a_typo_fix_does_not(self):
        """A note edit notifies whoever it tags one more time; a typo fix next to an existing tag notifies nobody.

        v0.3.1 (issue #10 L3): tagging the same person again from the same pin's note by the same editor notifies at most
        once per NOTE_MENTION_COOLDOWN_S, so the re-tag below is made after the window (fake clock)."""
        from unittest import mock

        t0 = float(int(time.time()))  # whole seconds: ts is stored rounded to ms
        with mock.patch.object(ps.time, "time", return_value=t0):
            pid = add_pin(
                {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단 줄여 주세요"}, self.A
            ).record["id"]
            n = self.n()
            edit_pin(pid, {"note": "@Bob Park 이 문단을 줄여 주세요", "base_rev": 0}, self.A)  # typo fix only
            self.assertEqual(self.events_after(n), [])
        with mock.patch.object(ps.time, "time", return_value=t0 + NOTE_MENTION_COOLDOWN_S):
            edit_pin(pid, {"note_append": "@Bob Park 급합니다"}, self.A)  # tags Bob again
            self.assertEqual(self.events_after(n), [("mention", ["bob@example.com"])])
            n = self.n()
            edit_pin(
                pid, {"note": find_record(ps.APP.snapshot_pins(), pid)["note"] + " @Carol Lee", "base_rev": 2}, self.A
            )
            self.assertEqual(self.events_after(n), [("mention", ["carol@example.com"])])


class NoteMentionCooldown(Base):
    """Toggling @Bob through note edits notifies Bob once per ten minutes per editor and pin; replies are unchanged."""

    def setUp(self):
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.APP.people_directory.record(actor(h))
        self.A, self.B, self.C = (actor(h) for h in (ALICE, BOB, CAROL))
        self.t0 = float(int(time.time()))  # whole seconds: events.jsonl rounds ts to milliseconds

    def mentions_to_bob(self):
        return [e for e in ps.APP.notices.read()[0] if e["type"] == "mention" and B_LOGIN in e["to"]]

    def edit_note(self, pid, note, who):
        return edit_pin(pid, {"note": note, "base_rev": find_record(ps.APP.snapshot_pins(), pid)["rev"]}, who)

    def toggle(self, pid, who, times=3):
        for _ in range(times):
            self.edit_note(pid, "이 문단 줄여 주세요", who)
            self.edit_note(pid, "@Bob Park 이 문단 줄여 주세요", who)

    def test_toggling_a_tag_three_times_within_ten_minutes_sends_one_mention(self):
        """Issue #10 L3: pin with @Bob, then remove and re-add the tag three times - Bob hears of it once, not four times."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin(
                {"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 이 문단 줄여 주세요"}, self.A
            ).record["id"]
            self.toggle(pid, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        self.assertEqual(find_record(ps.APP.snapshot_pins(), pid)["mentions"], [B_LOGIN])  # the note still tags him

    def test_the_tag_notifies_again_after_the_window(self):
        """Ten minutes after the last sent note mention, re-adding the tag is a new mention (fake clock)."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = self.add(actor=self.A)
            self.edit_note(pid, "@Bob Park 봐 주세요", self.A)
            self.toggle(pid, self.A, times=2)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S - 1):
            self.toggle(pid, self.A, times=1)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S):
            self.toggle(pid, self.A, times=2)
        self.assertEqual(len(self.mentions_to_bob()), 2)  # one more, then quiet again

    def test_note_append_with_the_tag_is_under_the_same_cooldown(self):
        """note_append that writes @Bob again counts as a note edit: suppressed inside the window, sent after it."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 부탁"}, self.A).record["id"]
            edit_pin(pid, {"note_append": "@Bob Park 급합니다"}, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 1)
        with mock.patch.object(ps.time, "time", return_value=self.t0 + NOTE_MENTION_COOLDOWN_S + 5):
            edit_pin(pid, {"note_append": "@Bob Park 아직입니다"}, self.A)
        self.assertEqual(len(self.mentions_to_bob()), 2)

    def test_another_editor_or_pin_has_its_own_cooldown(self):
        """Carol tagging Bob on the same pin, or Alice tagging him on another pin, still notifies Bob."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            p1 = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 하나"}, self.A).record["id"]
            self.edit_note(p1, "없음", self.C)
            self.edit_note(p1, "@Bob Park 둘", self.C)
            p2 = self.add(lo=8, hi=9, actor=self.A)
            self.edit_note(p2, "@Bob Park 셋", self.A)
        by = [(e["by"]["login"], e["pin"]) for e in self.mentions_to_bob()]
        self.assertEqual(by, [(A_LOGIN, p1), (C_LOGIN, p1), (A_LOGIN, p2)])

    def test_replies_and_reopen_reasons_still_notify_every_time(self):
        """Explicit messages are not rate-limited: every reply or reopen reason that tags Bob is a mention."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 메모"}, self.A).record["id"]
            ps.APP.pin_lifecycle.reply_pin(
                pid, "@Bob Park 하나", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
            )
            ps.APP.pin_lifecycle.reply_pin(
                pid, "@Bob Park 둘", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
            )
            ps.APP.pin_lifecycle.close_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
                CloseRequest(),
            )
            ps.APP.pin_lifecycle.reopen_pin(
                pid,
                post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reopen", pid),
                reason="@Bob Park 다시",
            )
        self.assertEqual(len(self.mentions_to_bob()), 4)

    def test_a_reply_mention_does_not_silence_a_following_note_tag(self):
        """The cooldown counts note mentions only: a reply that tagged Bob does not stop the next note tag."""
        with mock.patch.object(ps.time, "time", return_value=self.t0):
            pid = self.add(actor=self.A)
            ps.APP.pin_lifecycle.reply_pin(
                pid, "@Bob Park 답글", post_authority(ps.APP.pin_lifecycle.context().store, self.A, "reply", pid)
            )
            self.edit_note(pid, "@Bob Park 메모에서도", self.A)
        self.assertEqual(len(self.mentions_to_bob()), 2)


class MentionEvents(Base):
    """The notices of a pin's life over HTTP: mention, replied, review_requested, reopened and assigned, each to the
    right people, never to the actor, with seq counting up."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}

    HW = {"Tailscale-User-Login": "wendy@example.com", "Tailscale-User-Name": "Wendy Kim"}

    def setUp(self):
        super().setUp()

    def events(self):
        return ps.APP.notices.read()[0]

    def post(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        code, _, raw = split_resp(
            self.talk(req("POST", path, json.dumps(body).encode() if body is not None else b"", h))
        )
        return code, json.loads(raw)

    def test_mentions_stored_on_pin_and_message_with_events(self):
        ps.APP.people_directory.record(dict(self.W))
        code, d = self.post(
            "/api/pin",
            {
                "file": str(self.main),
                "lo": 4,
                "hi": 5,
                "page": 1,
                "kind_req": "question",
                "note": "@Wendy Kim 구간의 정의는?",
            },
            self.HS,
        )
        pid = d["id"]
        p = self.pin(pid)
        self.assertEqual(p["mentions"], [self.W["login"]])
        self.assertEqual(p["note"], "@Wendy Kim 구간의 정의는?")  # the text is unchanged
        ev = self.events()
        self.assertEqual(
            [(e["type"], e["pin"], e["to"], e["by"]["login"]) for e in ev],
            [("mention", pid, [self.W["login"]], self.S["login"])],
        )
        self.assertEqual(ev[0]["kind_req"], "question")
        self.assertEqual(ev[0]["seq"], 1)
        self.assertIn("구간의 정의는?", ev[0]["excerpt"])
        # agent reply -> replied goes to the author and the mentioned person
        self.post("/api/pins/%d/reply" % pid, {"text": "구간은 95% 신뢰구간입니다"})
        e = self.events()[-1]
        self.assertEqual(
            (e["type"], sorted(e["to"]), e["msg"]), ("replied", sorted([self.S["login"], self.W["login"]]), 1)
        )
        # when the mentioned person replies, they're excluded from the recipients themselves
        self.post("/api/pins/%d/reply" % pid, {"text": "@Bob Park 맞아요"}, self.HW)
        types = [(x["type"], x["to"]) for x in self.events()[2:]]
        # the author, mentioned by this message, gets only one mention (doesn't overlap with replied)
        self.assertEqual(types, [("mention", [self.S["login"]])])
        self.assertEqual(self.pin(pid)["thread"][-1]["mentions"], [self.S["login"]])
        # when an agent closes it, review_requested goes to the author; when the author reopens with a reason, reopened is skipped since it's themself
        self.post("/api/pins/%d/close" % pid, {"reply": "답함"})
        self.assertEqual(self.events()[-1]["type"], "review_requested")
        self.assertEqual(self.events()[-1]["to"], [self.S["login"]])
        n = len(self.events())
        self.post("/api/pins/%d/reopen" % pid, {"reason": "@Wendy Kim 한 번 더 봐 주세요"}, self.HS)
        tail = self.events()[n:]
        # v0.2.1: every @-tag in a reopen reason notifies, even someone tagged before; the author reopened it themself
        self.assertEqual([(x["type"], x["to"]) for x in tail], [("mention", [self.W["login"]])])
        self.post("/api/pins/%d/close" % pid, {"reply": "다시 답함"})
        self.post("/api/pins/%d/reopen" % pid, {"reason": "아직"}, self.HW)
        self.assertEqual((self.events()[-1]["type"], self.events()[-1]["to"]), ("reopened", [self.S["login"]]))
        seqs = [x["seq"] for x in self.events()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_assignee_validation_and_events(self):
        ps.APP.people_directory.record(dict(self.W))
        ps.APP.people_directory.record(dict(self.S))
        base = {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "@Bob Park 봐 주세요"}
        for bad in ("nobody@example.com", "local", 3, ""):
            code, d = self.post("/api/pin", dict(base, assignee=bad), self.HW)
            self.assertEqual(code, 400, bad)
            self.assertTrue("assignee" in d["error"] or "담당" in d["error"], d)
        code, d = self.post("/api/pin", dict(base, assignee=self.S["login"]), self.HW)
        self.assertEqual(code, 200)
        pid = d["id"]
        self.assertEqual(self.pin(pid)["assignee"], self.S["login"])
        self.assertEqual(
            sorted((e["type"], tuple(e["to"])) for e in self.events()),
            [("assigned", (self.S["login"],)), ("mention", (self.S["login"],))],
        )  # the mentioned person also gets a notification
        self.assertNotIn("thread", self.pin(pid))  # the assignee set at creation isn't a thread record
        # switching the assignee to an agent leaves an ev=assign entry with no event. Switching back to a person emits assigned.
        n = len(self.events())
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": "agent", "base_rev": 0}, self.HW)
        self.assertEqual(code, 200)
        p = self.pin(pid)
        self.assertEqual(
            (p["assignee"], p["thread"][-1]["ev"], p["thread"][-1]["text"]), ("agent", "assign", "담당: 에이전트")
        )
        self.assertEqual(self.events()[n:], [])
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": self.S["login"], "base_rev": 1}, self.HW)
        self.assertEqual(self.pin(pid)["thread"][-1]["text"], "담당: @Bob Park")
        self.assertEqual([(e["type"], e["to"]) for e in self.events()[n:]], [("assigned", [self.S["login"]])])
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": "ghost", "base_rev": 2}, self.HW)
        self.assertEqual(code, 400)
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("담당 바꿈(Wendy Kim): 담당: @Bob Park", md)
        self.assertIn("assigned", NOTIFY_TYPES)


class EventCursor(Base):
    """GET /api/meta?light=1&ev=<seq> hands a person the notices after the cursor that are theirs (not their own acts, none
    for the agent), and the poll writes nothing."""

    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}

    HW = {"Tailscale-User-Login": "wendy@example.com", "Tailscale-User-Name": "Wendy Kim"}

    def setUp(self):
        super().setUp()

    def get(self, path, headers=None):
        code, h, raw = split_resp(self.talk(req("GET", path, headers=headers)))
        return code, h, raw

    def test_event_cursor_in_light_meta(self):
        ps.APP.notices.emit_events(
            [
                {
                    "type": "mention",
                    "pin": 1,
                    "doc": "main",
                    "to": ["wendy@example.com"],
                    "by": {"login": "bob@example.com"},
                },
                {"type": "replied", "pin": 1, "doc": "main", "to": ["bob@example.com"], "by": {"login": "local"}},
                {
                    "type": "mention",
                    "pin": 2,
                    "doc": "main",
                    "to": ["wendy@example.com"],
                    "by": {"login": "wendy@example.com"},
                },
            ]
        )
        _, _, raw = self.get("/api/meta?light=1", self.HW)
        d = json.loads(raw)
        self.assertEqual(d["ev_seq"], 3)
        self.assertNotIn("events", d)  # not included without a cursor
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual(
            [(e["seq"], e["type"], e["doc_name"]) for e in json.loads(raw)["events"]], [(1, "mention", "본문")]
        )
        _, _, raw = self.get("/api/meta?light=1&ev=1", self.HW)
        self.assertEqual(json.loads(raw)["events"], [])  # something you did yourself (seq 3) doesn't come back
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HS)
        self.assertEqual([e["seq"] for e in json.loads(raw)["events"]], [2])
        _, _, raw = self.get("/api/meta?light=1&ev=0")
        self.assertEqual(json.loads(raw)["events"], [])  # not included for local/agent
        code, _, _ = self.get("/api/meta?light=1&ev=x", self.HW)
        self.assertEqual(code, 400)
        before = sorted(p.name for p in ps.APP.C.state.iterdir())
        self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual(sorted(p.name for p in ps.APP.C.state.iterdir()), before)  # polling doesn't count
