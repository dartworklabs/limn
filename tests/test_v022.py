"""v0.2.2 (issue #8): one [Reply] whose outcome a server rule decides, Trash instead of the dropped section, and
collapsible list sections that share one header component.

Reply rule (docs/handbook/domain.md §전이와 할 수 있는 쪽, api.md §스레드 (답글)):

| pin state            | who    | reply tags a person? | result                                   |
| review / done        | human  | no                   | reopens; the reply is the reason (ev:reopen) |
| review / done        | human  | yes                  | state unchanged; that person is notified |
| open                 | anyone | -                    | state unchanged                          |
| question pin         | anyone | -                    | recorded as an answer, state unchanged   |

An optional "reopen": true/false on the request overrides the rule ([Keep state] sends false).

Run: uv run pytest -q tests/test_v022.py
"""
import json
import re
import time
import unittest
from pathlib import Path

from limn import access
from limn.pins.model import OpenPin, ReviewPin
from limn import store as limn_store
from limn.store import dump_jsonl
from test_access import ALICE, BOB, CAROL, AccessBase, token_create
from test_qa_021 import BrowserBase, actor
from test_server import add_pin, Base, extract_js_fn, js_i18n, js_icons, ps, run_node

ROOT = Path(__file__).resolve().parent.parent
HANGUL = re.compile(r"[가-힣]")
A, B, C = actor(ALICE), actor(BOB), actor(CAROL)

# (state, kind_req, human, mentioned, override) -> reopens?
RULE_CASES = []
for _st in ("open", "review", "done"):
    for _kind in ("fix", "question"):
        for _human in (True, False):
            for _ment in ([], ["bob@example.com"]):
                for _ov in (None, True, False):
                    if _st == "open":
                        _want = False
                    elif _ov is not None:
                        _want = _ov
                    else:
                        _want = _kind == "fix" and _human and not _ment
                    RULE_CASES.append((_st, _kind, _human, _ment, _ov, _want))


def rec_for(state, kind):
    r = {"id": 1, "file": "/m.tex", "lo": 1, "hi": 2, "kind_req": kind}
    if state != "open":
        r["done"] = True
    if state == "review":
        r["review"] = True
    return r


# ---------------------------------------------------------------- 1. the reply rule

class ReplyRule(unittest.TestCase):
    def test_every_row_of_the_rule_table(self):
        for st, kind, human, ment, ov, want in RULE_CASES:
            with self.subTest(state=st, kind=kind, human=human, mentioned=ment, override=ov):
                self.assertIs(ps.reply_reopens(rec_for(st, kind), human, ment, ov), want)

    def test_viewer_mirrors_the_server_rule(self):
        # The one-line preview under the reply box must predict exactly what the server will do.
        js = "\n".join([extract_js_fn("pinState"), extract_js_fn("replyReopens"),
                        "const cases=%s;" % json.dumps([[rec_for(st, k), h, m, ov] for st, k, h, m, ov, _ in RULE_CASES]),
                        "console.log(JSON.stringify(cases.map(c=>replyReopens(c[0],c[1],c[2],c[3]===null?undefined:c[3]))));"])
        self.assertEqual(json.loads(run_node(js)), [w for *_, w in RULE_CASES])


class ReplyApi(AccessBase):
    """POST /api/pins/{id}/reply applies the rule on the server; the response adds `reopened` and `state`."""

    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))

    def review_pin(self, kind="fix", author=A):
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기", "kind_req": kind}, author).record["id"]
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="줄였습니다", ref="PR #9")
        self.assertEqual(ps.pin_state(self.pin(pid)), "review")
        return pid

    def done_pin(self):
        pid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "오타"}, A).record["id"]
        ps.set_done(pid, True, A, reply="고침")
        self.assertEqual(ps.pin_state(self.pin(pid)), "done")
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
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "@Carol Lee 참고로 봐 주세요"}, A).record["id"]
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="고침")
        n = len(self.events())
        code, d = self.reply(pid, {"text": "아직 틀립니다"}, BOB)
        self.assertEqual(d["reopened"], True)
        self.assertEqual(self.events()[n:], [("reopened", ["alice@example.com"]), ("replied", ["carol@example.com"])])
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="다시 고침")
        n = len(self.events())
        self.reply(pid, {"text": "제가 다시 엽니다"}, ALICE)                 # the author: only Carol hears of it
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
        code, d = self.reply(pid, {"text": "추가 설명: 식 (3) 도 같이 고쳤습니다"})            # headerless loopback agent
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
        self.assertEqual(ps.pin_state(self.pin(pid)), "review")

    def test_unknown_pin(self):
        code, d = self.reply(999, {"text": "x"}, BOB)
        self.assertEqual((code, d["ok"]), (200, False))

    def test_reopened_pin_shows_in_open_table_with_reply_as_reason(self):
        pid = self.review_pin()
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertNotRegex(md, r"\n\| %d · " % pid)                          # awaiting review: not in the open table
        self.reply(pid, {"text": "식 번호가 아직 틀립니다"}, BOB)
        md = ps.pins_md_text(ps.snapshot_pins())
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d · " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀립니다", row)
        self.assertNotIn("## 검토 대기", md)

    def test_full_thread_still_reopens(self):
        pid = self.review_pin()
        rows = ps.read_pins()[0]
        r = ps.find_pin(rows, pid)
        r["thread"] = r["thread"] + [{"id": 100 + i, "by": A, "at": "2026-09-25 10:00:00", "text": "x"}
                                     for i in range(ps.THREAD_MAX)]
        ps.write_pins(rows)
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
        self.assertIsInstance(pin, OpenPin)                               # a person's reply reopened it
        self.assertEqual(pin.record["thread"][-1]["ev"], "reopen")
        pid = self.review_pin()
        pin = ps.reply_pin(pid, "에이전트 답글", dict(ps.LOCAL_ACTOR))
        self.assertIsInstance(pin, ReviewPin)                             # an agent's reply leaves it for review
        self.assertNotIn("ev", pin.record["thread"][-1])


# ---------------------------------------------------------------- 2. Trash

class Trash(AccessBase):
    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))

    def dropped_file(self):
        return ps.read_jsonl(ps.C.dropped)[0]

    def put_dropped(self, pid, days_ago, **extra):
        rec = {"id": pid, "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "old %d" % pid,
               "author": A, "dropped_by": B, **extra}
        if days_ago is not None:
            rec["dropped_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days_ago * 86400))
        ps.atomic_write(ps.C.dropped, dump_jsonl(self.dropped_file() + [rec]))

    def test_retention_is_thirty_days(self):
        self.assertEqual(ps.TRASH_DAYS, 30)

    def test_trash_listing_carries_the_purge_time(self):
        self.put_dropped(70, 10)
        rec = ps.dropped_payload()[0]
        self.assertAlmostEqual(rec["expires_ts"], ps._epoch(rec["dropped_at"]) + 30 * 86400, delta=1)
        self.assertNotIn("expires_ts", ps.read_jsonl(ps.C.dropped)[0][0])   # computed, never stored

    def test_iso_timestamps_with_an_offset_expire_too(self):
        self.put_dropped(71, None, dropped_at="2026-01-01T10:00:00+09:00")
        self.assertEqual(ps.purge_trash(), 1)

    def test_unreadable_trash_lines_are_kept_in_a_backup(self):
        ps.atomic_write(ps.C.dropped, "{not json\n")
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        baks = list(ps.C.state.glob("pins.dropped.jsonl.corrupt-*.bak"))
        self.assertEqual(len(baks), 1)
        self.assertIn("{not json", baks[0].read_text(encoding="utf-8"))

    def test_a_failing_purge_never_stops_the_server(self):
        from unittest import mock
        self.put_dropped(72, 40)
        with mock.patch.object(limn_store, "atomic_write", side_effect=OSError("read-only")):   # the Trash writer's
            self.assertEqual(ps.purge_trash(), 0)

    def test_someone_elses_delete_notifies_the_author(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        code, d = self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        self.assertEqual((code, d["ok"]), (200, True))
        evs = ps._read_events()[0][n:]
        self.assertEqual([(e["type"], e["to"], e["by"]["login"], e["pin"]) for e in evs],
                         [("dropped", ["alice@example.com"], "bob@example.com", pid)])
        self.assertIn("dropped", ps.NOTIFY_TYPES)
        m = self.call("GET", "/api/meta?light=1&ev=%d" % (evs[0]["seq"] - 1), headers=ALICE)[1]
        self.assertEqual([e["type"] for e in m["events"]], ["dropped"])

    def test_deleting_your_own_pin_notifies_nobody(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        self.assertEqual(ps._read_events()[0][n:], [])

    def test_agent_delete_notifies_the_author(self):
        pid = self.pin_id(ALICE)
        n = len(ps._read_events()[0])
        self.call("POST", "/api/pins/%d/drop" % pid)
        self.assertEqual([(e["type"], e["to"]) for e in ps._read_events()[0][n:]], [("dropped", ["alice@example.com"])])

    def test_expired_pins_are_hidden_then_purged(self):
        self.put_dropped(50, 31)
        self.put_dropped(51, 29)
        self.put_dropped(52, None)                            # no timestamp (hand-edited): kept, never guessed
        ids = sorted(r["id"] for r in ps.dropped_payload())
        self.assertEqual(ids, [51, 52])                       # a read never shows an expired pin...
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [50, 51, 52])   # ...and never writes
        self.assertEqual(ps.purge_trash(), 1)
        self.assertEqual(sorted(r["id"] for r in self.dropped_file()), [51, 52])
        self.assertEqual(ps.purge_trash(now=time.time() + 2 * 86400), 1)   # two days later #51 is 31 days old
        self.assertEqual([r["id"] for r in self.dropped_file()], [52])

    def test_a_drop_purges_expired_pins(self):
        self.put_dropped(60, 40)
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, ALICE)
        self.assertEqual([r["id"] for r in self.dropped_file()], [pid])

    def test_an_expired_pin_cannot_be_restored(self):
        self.put_dropped(61, 45)
        code, _ = self.call("POST", "/api/pins/61/restore", None, ALICE)
        self.assertEqual(code, 404)

    def test_owner_deletes_permanently(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        n = len(ps._read_events()[0])
        code, d = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual((code, d["ok"], d["purged"]), (200, True, pid))
        self.assertEqual(self.dropped_file(), [])
        self.assertEqual([(e["type"], e["to"], e["pin"]) for e in ps._read_events()[0][n:]], [("purged", [], pid)])
        code, _ = self.call("POST", "/api/pins/%d/restore" % pid, None, ALICE)
        self.assertEqual(code, 404)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        nid = self.pin_id(ALICE)
        self.assertGreater(nid, pid)                          # an id is never reused, even after a purge

    def test_only_the_owner_may_delete_permanently(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
                         {"login": "carol@example.com", "name": "Carol Lee", "role": "viewer"}])
        pid = self.pin_id(BOB)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        _, tok = token_create(ps.C.state, "bot")
        for who, kw in (("editor", {"headers": BOB}), ("viewer", {"headers": CAROL}), ("loopback agent", {}),
                        ("token", {"token": tok})):
            with self.subTest(who=who):
                code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, **kw)
                self.assertEqual(code, 403)
        self.assertEqual([r["id"] for r in self.dropped_file()], [pid])

    def test_purge_of_an_open_pin_is_refused(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.pin_id(ALICE)
        code, _ = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual(code, 404)
        self.assertIsNotNone(self.pin(pid))

    def test_pins_md_never_lists_trash(self):
        pid = self.pin_id(ALICE)
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotRegex(md, r"\n\| %d[ ·|]" % pid)


# ---------------------------------------------------------------- 3. viewer pure functions and markup

class ViewerMarkup(unittest.TestCase):
    def test_no_reopen_button_anywhere(self):
        self.assertNotIn('data-act="rv-reopen"', ps.HTML)
        self.assertNotIn("case 'rv-reopen'", ps.HTML)
        self.assertNotIn("openReply(id,'reopen')", ps.HTML)

    def test_dropped_section_left_the_list(self):
        lst = ps.HTML[ps.HTML.index('<div id="list">'):ps.HTML.index('<div id="c-actions">')]
        self.assertNotIn("sec-dropped", lst)
        self.assertIn('<dialog id="trash"', ps.HTML)
        more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index("</dialog>", ps.HTML.index('<dialog id="more"'))]
        self.assertIn('id="m-trash"', more)
        self.assertIn('data-act="trash-open"', more)

    def test_three_sections_share_one_header_component(self):
        for sec in ("open", "review", "done"):
            with self.subTest(section=sec):
                m = re.search(r'<button class="sec-tg" id="%s-toggle" data-act="sec-toggle" data-sec="%s" aria-expanded="(true|false)" '
                              r'aria-controls="[a-z-]+"' % (sec, sec), ps.HTML)
                self.assertIsNotNone(m, sec)

    def test_help_defines_pin_once(self):
        help_ = ps.HTML[ps.HTML.index('<dialog id="help"'):ps.HTML.index("</dialog>", ps.HTML.index('<dialog id="help"'))]
        self.assertIn("<tr><td>핀</td><td>출력물의 한 자리 + 요청이나 질문 + 그 대화", help_)
        self.assertEqual(help_.count("<tr><td>핀</td>"), 1)
        en = ps.UI_EN["출력물의 한 자리 + 요청이나 질문 + 그 대화. 번호(#N)는 다시 쓰이지 않습니다"]
        self.assertTrue(en.startswith("A place in the output + a request or question + its conversation"), en)

    def test_dropped_is_a_notification_type(self):
        self.assertIn("dropped:", re.search(r"const NOTIFY_RANK=\{[^}]*\}", ps.HTML).group(0))
        self.assertIn("dropped", ps.EVENT_TYPES)

    def test_system_notification_for_a_deleted_pin_offers_restore(self):
        # a hidden tab gets a system notification: [되살리기] is a notification action the service worker hands to the tab
        self.assertIn("actions:e.type==='dropped'&&!isViewer()?[{action:'restore',title:tr('되살리기')}]:[]", extract_js_fn("notifyShow"))
        self.assertIn("e.action==='restore'", ps.SW_JS)
        self.assertIn("d.type==='restore-pin'", ps.HTML)


class ViewerFunctions(unittest.TestCase):
    def setUp(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not available")

    def preview(self, lang, cases):
        js = "\n".join([js_i18n(lang), "const PEOPLE=[{login:'bob@example.com',name:'Bob Park'},{login:'carol@example.com',name:'Carol Lee'}];",
                        extract_js_fn("peopleName"), extract_js_fn("pinState"), extract_js_fn("replyReopens"),
                        extract_js_fn("replyPreview"), "const cases=%s;" % json.dumps(cases),
                        "console.log(JSON.stringify(cases.map(c=>replyPreview(c[0],c[1],c[2],c[3]))));"])
        return json.loads(run_node(js))

    def test_preview_line_for_each_outcome(self):
        rv, dn, op, q = rec_for("review", "fix"), rec_for("done", "fix"), rec_for("open", "fix"), rec_for("review", "question")
        cases = [[rv, True, [], False], [dn, True, [], False], [rv, True, ["bob@example.com"], False],
                 [rv, True, [], True], [q, True, [], False], [rv, False, [], False], [op, True, [], False]]
        ko = self.preview("ko", cases)
        self.assertEqual([(x or {}).get("text") for x in ko], [
            "보내면 이 핀이 다시 열려 에이전트에게 갑니다", "보내면 이 핀이 다시 열려 에이전트에게 갑니다",
            "보내면 Bob Park에게 알림이 가고 상태는 그대로입니다", "보내도 상태는 그대로입니다",
            "답으로 남고 상태는 그대로입니다", "이 화면은 에이전트로 보내므로 상태는 그대로입니다", None])
        # the one override toggle: [상태 유지] where the rule reopens, [다시 열기] where it keeps a closed pin as it is
        self.assertEqual([(x or {}).get("toggle") for x in ko], ["keep", "keep", "reopen", "keep", "reopen", "reopen", None])
        flipped = self.preview("ko", [[rv, True, ["bob@example.com"], True], [q, True, [], True], [rv, False, [], True]])
        self.assertEqual([x["text"] for x in flipped], ["보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다",
                                                        "보내면 이 핀이 다시 열려 에이전트에게 갑니다", "보내면 이 핀이 다시 열려 에이전트에게 갑니다"])
        en = self.preview("en", cases)
        self.assertEqual([(x or {}).get("text") for x in en], [
            "Sending will reopen this pin for the agent", "Sending will reopen this pin for the agent",
            "Sending notifies Bob Park; state stays", "Sending keeps the state as it is",
            "Recorded as an answer; state stays", "This screen posts as the agent; state stays", None])

    def test_section_state_defaults_and_new_count(self):
        js = "\n".join(["const SEC_DEFAULT={open:true,review:true,done:false};", extract_js_fn("secState"),
                        extract_js_fn("secNewCount"), r"""
            console.log(JSON.stringify([secState(undefined), secState({done:true}), secState({open:false,x:1,review:'no'}),
              secNewCount(new Set([1,2]),[1,2,3,4]), secNewCount(new Set([1,2]),[2]), secNewCount(null,[1])]));"""])
        self.assertEqual(json.loads(run_node(js)), [
            {"open": True, "review": True, "done": False}, {"open": True, "review": True, "done": True},
            {"open": False, "review": True, "done": False}, 2, 0, 0])

    def test_trash_days_left(self):
        js = "\n".join(["const TRASH_DAYS=30;", extract_js_fn("trashDaysLeft"), r"""
            const now=new Date(2026,8,25,12,0).getTime();
            console.log(JSON.stringify([trashDaysLeft('2026-09-25 11:00:00',now), trashDaysLeft('2026-08-27 12:00:00',now),
              trashDaysLeft('2026-08-20 12:00:00',now), trashDaysLeft('',now)]));"""])
        self.assertEqual(json.loads(run_node(js)), [30, 1, 0, None])     # Aug 27 -> Sep 25 is 29 days: 1 left

    def test_ref_to_a_deleted_pin_renders_as_deleted(self):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            let PEOPLE=[], META=null; const DROPPED=[{id:12}];
            function findAnyPin(id){return id===3?{id:3}:null;}
            """, extract_js_fn("mentionToks"), extract_js_fn("reEsc"), extract_js_fn("meLogin"), extract_js_fn("pinRefExists"),
            extract_js_fn("pinRefGone"), extract_js_fn("fmtText"),
            "console.log(JSON.stringify([fmtText('#3 와 #12 와 #99',[])]));"])
        out = json.loads(run_node(js))[0]
        self.assertIn('data-ref="3"', out)
        self.assertRegex(out, r'<span class="pin-ref gone"[^>]*data-ref="12"[^>]*>#12 <small>삭제된 핀</small></span>')
        self.assertIn("#99", out)
        self.assertNotIn('data-ref="99"', out)


# ---------------------------------------------------------------- 4. the real viewer in a browser

DEVICES = {
    "desktop": {"viewport": {"width": 1400, "height": 850}},
    "fold": {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True},
    "phone": {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True},
}
TXT = {
    "ko": {"reopen": "보내면 이 핀이 다시 열려 에이전트에게 갑니다", "keep": "보내도 상태는 그대로입니다", "undo": "되돌리기",
           "mention": "보내면 Bob Park에게 알림이 가고 상태는 그대로입니다", "trash": "휴지통 1", "restore": "되살리기",
           "purge": "영구 삭제", "new": "새 1", "gone": "삭제된 핀"},
    "en": {"reopen": "Sending will reopen this pin for the agent", "keep": "Sending keeps the state as it is", "undo": "Undo",
           "mention": "Sending notifies Bob Park; state stays", "trash": "Trash (1)", "restore": "Restore",
           "purge": "Delete forever", "new": "new 1", "gone": "deleted pin"},
}


class ViewerFlows(BrowserBase):
    WHO = ALICE

    def setUp(self):
        super().setUp()
        for h in (ALICE, BOB, CAROL):
            ps.record_person(actor(h))
        self.open_id = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "문단 줄이기"}, A).record["id"]
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식 번호 확인"}, A).record["id"]
        ps.set_done(self.rv, True, dict(ps.LOCAL_ACTOR), reply="식 번호를 고쳤습니다", ref="PR #9")
        self.dn = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 2, "note": "오타"}, A).record["id"]
        ps.set_done(self.dn, True, A, reply="고침")

    def state(self, pid):
        return ps.pin_state(ps.find_pin(ps.snapshot_pins(), pid))

    def pump(self):
        """Wait a little while letting Playwright run - the in-process server answers routed requests on this thread, so a
        plain time.sleep() would block the very request being waited for."""
        self._page.wait_for_timeout(100)

    def wait_state(self, pid, want, secs=8):
        end = time.time() + secs
        while time.time() < end:
            if self.state(pid) == want:
                return
            self.pump()
        self.assertEqual(self.state(pid), want)

    def page_for(self, device, lang, n_open=1):
        page = self._page = self.open(n_open, lang=lang, **DEVICES[device])
        page.evaluate("setSide(true); OPEN_CARDS.add(%d); OPEN_CARDS.add(%d); drawPins()" % (self.open_id, self.rv))
        page.wait_for_timeout(150)
        return page

    def toast(self, page, text):
        return page.locator("#toasts .toast").filter(has_text=text).first

    def english_only(self, page, sel):
        text = page.inner_text(sel)
        self.assertFalse(HANGUL.search(text), (sel, text))

    def run_matrix(self, fn):
        for device in DEVICES:
            for lang in ("ko", "en"):
                with self.subTest(device=device, lang=lang):
                    self.setUp_fresh()
                    fn(self.page_for(device, lang), device, lang)

    def setUp_fresh(self):
        self.tearDown()
        self.setUp()

    # -- 1. one Reply: the rule, the preview, keep state, undo

    def test_reply_reopens_with_preview_and_undo(self):
        def flow(page, device, lang):
            t = TXT[lang]
            card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
            acts = page.evaluate("[...document.querySelectorAll('%s .acts [data-act]')].map(e=>e.dataset.act)" % card.replace('"', '\\"'))
            self.assertNotIn("rv-reopen", acts)
            self.assertIn("reply-open", acts)
            self.assertIn("confirm", acts)
            page.click(card + " .acts [data-act=reply-open]")
            page.fill(card + " textarea.r-text", "식 번호가 아직 틀립니다")
            page.wait_for_selector(card + " .r-outcome:not([hidden])")
            self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), t["reopen"])
            keep = page.locator(card + " [data-act=reply-flip]")
            self.assertTrue(keep.is_visible())
            self.assertEqual(keep.get_attribute("aria-checked"), "false")
            if lang == "en":
                self.english_only(page, card + " .reply-box")
            page.click(card + " [data-act=reply-send]")
            tst = self.toast(page, t["undo"])
            tst.wait_for(state="visible")
            self.assertEqual(self.state(self.rv), "review")                     # nothing sent while undo is possible
            tst.get_by_role("button", name=t["undo"]).click()
            page.wait_for_selector(card + " textarea.r-text")
            self.assertEqual(page.input_value(card + " textarea.r-text"), "식 번호가 아직 틀립니다")
            page.wait_for_timeout(300)
            self.assertEqual(self.state(self.rv), "review")
            page.click(card + " [data-act=reply-send]")
            tst = self.toast(page, t["undo"])
            tst.wait_for(state="visible")
            tst.locator("button.btn-icon").click()                             # dismissing the toast sends at once
            self.wait_state(self.rv, "open")
            last = ps.find_pin(ps.snapshot_pins(), self.rv)["thread"][-1]
            self.assertEqual((last.get("ev"), last["text"]), ("reopen", "식 번호가 아직 틀립니다"))
            page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.rv, timeout=8000)
        self.run_matrix(flow)

    def test_keep_state_sends_a_comment(self):
        def flow(page, device, lang):
            t = TXT[lang]
            card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
            page.click(card + " .acts [data-act=reply-open]")
            page.fill(card + " textarea.r-text", "내일 다시 볼게요")
            page.click(card + " [data-act=reply-flip]")
            self.assertEqual(page.get_attribute(card + " [data-act=reply-flip]", "aria-checked"), "true")
            self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), t["keep"])
            page.click(card + " [data-act=reply-send]")
            self.toast(page, t["undo"]).locator("button.btn-icon").click()
            end = time.time() + 8
            while time.time() < end and "내일" not in ps.find_pin(ps.snapshot_pins(), self.rv)["thread"][-1]["text"]:
                self.pump()
            last = ps.find_pin(ps.snapshot_pins(), self.rv)["thread"][-1]
            self.assertEqual((last.get("ev"), last["text"], self.state(self.rv)), (None, "내일 다시 볼게요", "review"))
        self.run_matrix(flow)

    def test_mention_preview_keeps_state(self):
        page = self.page_for("desktop", "ko")
        card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.click(card + " textarea.r-text")
        page.keyboard.type("@Bob Park 이 수정 괜찮나요")
        page.wait_for_timeout(100)
        self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), TXT["ko"]["mention"])
        flip = page.locator(card + " [data-act=reply-flip]")                   # the rare override is [다시 열기] here
        self.assertEqual((flip.inner_text(), flip.get_attribute("aria-checked")), ("다시 열기", "false"))
        flip.click()
        self.assertEqual(page.inner_text(card + " .r-outcome .r-out-t"), "보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다")
        page.click(card + " [data-act=reply-send]")
        self.toast(page, "되돌리기").locator("button.btn-icon").click()
        self.wait_state(self.rv, "open")

    def test_done_row_offers_reply_not_reopen(self):
        def flow(page, device, lang):
            page.click("#done-toggle")
            row = "#done-list .arc-row[data-id=\"%d\"]" % self.dn
            page.wait_for_selector(row)
            acts = page.evaluate("[...document.querySelectorAll('#done-list [data-act]')].map(e=>e.dataset.act)")
            self.assertNotIn("rv-reopen", acts)
            self.assertIn("reply-open", acts)
            page.click(row + " [data-act=reply-open]")
            page.fill(row + " textarea.r-text", "다시 보니 문장이 어색합니다")
            self.assertEqual(page.inner_text(row + " .r-outcome .r-out-t"), TXT[lang]["reopen"])
            page.click(row + " [data-act=reply-send]")
            self.toast(page, TXT[lang]["undo"]).locator("button.btn-icon").click()
            self.wait_state(self.dn, "open")
        self.run_matrix(flow)

    def test_hidden_page_sends_at_once_and_drops_the_undo(self):
        page = self.page_for("desktop", "ko")
        card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "숨기기 전에 보냄")
        page.click(card + " [data-act=reply-send]")
        self.toast(page, "되돌리기").wait_for(state="visible")
        page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        self.wait_state(self.rv, "open")
        page.wait_for_timeout(200)
        self.assertEqual(self.toast(page, "되돌리기").count(), 0)             # an undo that could no longer work is gone

    def test_newer_toasts_pushing_it_out_send_it(self):
        page = self.page_for("desktop", "ko")
        card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
        page.click(card + " .acts [data-act=reply-open]")
        page.fill(card + " textarea.r-text", "밀려나면 보냄")
        page.click(card + " [data-act=reply-send]")
        page.evaluate("for(let i=0;i<6;i++)toast('다른 알림 '+i,'ok')")
        self.wait_state(self.rv, "open")

    def test_outcome_line_follows_a_state_change_while_typing(self):
        page = self.page_for("desktop", "ko")
        card = "#pins .pin[data-id=\"%d\"]" % self.open_id
        page.click(card + " .acts [data-act=reply-open]")
        page.fill("textarea.r-text", "이 문장도 봐 주세요")
        self.assertFalse(page.is_visible(".r-outcome"))                       # open pin: a reply never changes it
        ps.set_done(self.open_id, True, dict(ps.LOCAL_ACTOR), reply="줄였습니다")   # the agent closes it meanwhile
        page.evaluate("loadPins()")
        page.wait_for_selector("#review-pins .pin[data-id=\"%d\"] .r-outcome:not([hidden])" % self.open_id)
        self.assertEqual(page.inner_text(".r-outcome .r-out-t"), TXT["ko"]["reopen"])
        self.assertEqual(page.input_value("textarea.r-text"), "이 문장도 봐 주세요")

    def test_jumping_to_a_card_expands_its_collapsed_section(self):
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                page = self.page_for(device, "ko")
                page.click("#open-toggle")
                self.assertFalse(page.is_visible("#pins"))
                page.evaluate("revealCard(%d); jumpToCard(%d)" % (self.open_id, self.open_id))
                page.wait_for_selector("#pins .pin[data-id=\"%d\"]" % self.open_id, state="visible")
                self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "true")

    def test_delete_toast_undo_restores(self):
        page = self.page_for("desktop", "ko")
        page.click("#pins .pin[data-id=\"%d\"] [data-act=drop]" % self.open_id)
        self.toast(page, "되돌리기").get_by_role("button", name="되돌리기").click()
        page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.open_id, timeout=5000)
        self.assertIsNotNone(ps.find_pin(ps.snapshot_pins(), self.open_id))
        self.assertEqual(ps.read_jsonl(ps.C.dropped)[0], [])

    # -- 2. Trash

    def open_trash(self, page, device):
        if device == "desktop":
            page.click("#trash-link")
        else:
            page.click("#btn-more")
            page.click("#m-trash")
        page.wait_for_selector("#trash[open]")

    def test_delete_undo_and_trash_restore(self):
        def flow(page, device, lang):
            t = TXT[lang]
            page.click("#pins .pin[data-id=\"%d\"] [data-act=drop]" % self.open_id)
            page.wait_for_function("!document.querySelector('#pins .pin[data-id=\"%d\"]')" % self.open_id, timeout=3000)
            self.toast(page, t["undo"]).wait_for(state="visible")
            end = time.time() + 5
            while time.time() < end and ps.find_pin(ps.snapshot_pins(), self.open_id) is not None:
                self.pump()
            self.assertIsNone(ps.find_pin(ps.snapshot_pins(), self.open_id))
            page.wait_for_function("DROPPED.length===1", timeout=5000)
            self.assertFalse(page.locator("#sec-dropped").count())
            if device == "desktop":
                self.assertEqual(page.inner_text("#trash-link").strip(), t["trash"])
            self.open_trash(page, device)
            row = "#trash .arc-row[data-id=\"%d\"]" % self.open_id
            page.wait_for_selector(row)
            self.assertFalse(page.locator(row + " [data-act=purge]").count())   # not the owner
            if lang == "en":                                                     # the UI, not the Korean note a person wrote
                for sel in ("#trash-h", "#trash-note", row + " .arc-l1"):
                    self.english_only(page, sel)
            page.click(row + " [data-act=restore]")
            page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.open_id, timeout=5000)
            self.assertIsNotNone(ps.find_pin(ps.snapshot_pins(), self.open_id))
        self.run_matrix(flow)

    def test_owner_deletes_forever_with_undo(self):
        ps.C.people_file.write_text(json.dumps({"version": 1, "people": [
            {"login": "alice@example.com", "name": "Alice Kim", "role": "owner"},
            {"login": "bob@example.com", "name": "Bob Park"}]}), encoding="utf-8")
        ps.ROLES_CACHE = access.FileCache()
        ps.drop_pin(self.open_id, B)
        page = self.page_for("desktop", "ko", n_open=0)
        page.click("#trash-link")
        row = "#trash .arc-row[data-id=\"%d\"]" % self.open_id
        page.wait_for_selector(row + " [data-act=purge]")
        page.click(row + " [data-act=purge]")
        tst = self.toast(page, "되돌리기")
        tst.get_by_role("button", name="되돌리기").click()
        page.wait_for_timeout(300)
        self.assertEqual([r["id"] for r in ps.read_jsonl(ps.C.dropped)[0]], [self.open_id])
        page.click(row + " [data-act=purge]")
        self.toast(page, "되돌리기").locator("button.btn-icon").click()
        end = time.time() + 5
        while time.time() < end and ps.read_jsonl(ps.C.dropped)[0]:
            self.pump()
        self.assertEqual(ps.read_jsonl(ps.C.dropped)[0], [])

    def test_ref_to_deleted_pin_in_a_thread(self):
        ps.reply_pin(self.open_id, "#%d 와 같은 문제" % self.dn, B)
        ps.drop_pin(self.dn, A)
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                page = self.page_for("desktop", lang)
                ref = page.locator("#pins .pin[data-id=\"%d\"] .pin-ref.gone" % self.open_id)
                self.assertEqual(ref.inner_text().replace("\n", " "), "#%d %s" % (self.dn, TXT[lang]["gone"]))
                ref.click()
                page.wait_for_selector("#trash[open] .arc-row[data-id=\"%d\"]" % self.dn)

    # -- 3. Collapsible sections

    def test_sections_toggle_remember_and_count_new(self):
        def flow(page, device, lang):
            heads = page.evaluate("[...document.querySelectorAll('.sec-tg')].map(b=>[b.id,b.getAttribute('aria-expanded')])")
            self.assertEqual(heads, [["open-toggle", "true"], ["review-toggle", "true"], ["done-toggle", "false"]])
            self.assertFalse(page.is_visible("#done-list"))
            page.click("#open-toggle")
            self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "false")
            self.assertFalse(page.is_visible("#pins"))
            page.focus("#review-toggle")
            page.keyboard.press("Enter")
            self.assertEqual(page.get_attribute("#review-toggle", "aria-expanded"), "false")
            page.keyboard.press(" ")
            self.assertEqual(page.get_attribute("#review-toggle", "aria-expanded"), "true")
            add_pin({"file": str(self.main), "lo": 20, "hi": 21, "page": 2, "note": "새 핀"}, B).record["id"]
            page.evaluate("loadPins()")
            page.wait_for_selector("#open-toggle .sec-new:not([hidden])")
            self.assertEqual(page.inner_text("#open-toggle .sec-new"), TXT[lang]["new"])
            page.reload()
            page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=2&&META", timeout=20000)
            page.evaluate("setSide(true)")                                   # compact: the sheet starts collapsed after a reload
            self.assertEqual(page.get_attribute("#open-toggle", "aria-expanded"), "false")    # remembered
            page.click("#open-toggle")
            self.assertTrue(page.is_visible("#pins"))
            self.assertFalse(page.is_visible("#open-toggle .sec-new"))
            if lang == "en":
                for sel in ("#open-toggle", "#review-toggle", "#done-toggle"):
                    self.english_only(page, sel)
        self.run_matrix(flow)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- v0.2.2 follow-ups: cold deep links, lazy Trash expiry, styles

class LazyTrashExpiry(AccessBase):
    """A long-running server drops expired Trash entries during normal reads, at most once an hour, never on a light poll."""

    def setUp(self):
        super().setUp()
        ps._TRASH_CHECKED[0] = 0.0

    def put_dropped(self, pid, dropped_epoch):
        rec = {"id": pid, "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "old",
               "dropped_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(dropped_epoch))}
        ps.atomic_write(ps.C.dropped, dump_jsonl(ps.read_jsonl(ps.C.dropped)[0] + [rec]))

    def ids(self):
        return sorted(r["id"] for r in ps.read_jsonl(ps.C.dropped)[0])

    def test_hourly_purge_on_reads_with_a_fake_clock(self):
        from unittest import mock
        t0 = time.time()
        self.put_dropped(80, t0 - 31 * 86400)
        with mock.patch.object(ps.time, "time", return_value=t0):
            self.assertEqual(self.call("GET", "/api/meta?light=1")[0], 200)      # a light poll never writes
            self.assertEqual(self.ids(), [80])
            self.assertEqual(self.call("GET", "/api/pins")[0], 200)              # a normal read purges
            self.assertEqual(self.ids(), [])
            self.put_dropped(81, t0 - 31 * 86400)
            self.call("GET", "/api/pins?all=1")                                  # within the hour: no second check
            self.assertEqual(self.ids(), [81])
        with mock.patch.object(ps.time, "time", return_value=t0 + 3601):
            self.call("GET", "/pins.md")                                         # an hour later: checked again
            self.assertEqual(self.ids(), [])

    def test_an_entry_expiring_while_the_server_runs(self):
        from unittest import mock
        t0 = time.time()
        self.put_dropped(82, t0 - 29.99 * 86400)
        with mock.patch.object(ps.time, "time", return_value=t0):
            self.call("GET", "/api/pins")
            self.assertEqual(self.ids(), [82])                                   # not yet 30 days old
        with mock.patch.object(ps.time, "time", return_value=t0 + 2 * 3600):
            self.call("GET", "/api/pins")
            self.assertEqual(self.ids(), [])


class ButtonStyles(unittest.TestCase):
    def test_done_row_reply_and_trash_restore_are_filled_secondary(self):
        body = extract_js_fn("doneCard")
        self.assertIn('<button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open"', body)
        dc = extract_js_fn("droppedCard")
        self.assertIn('<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore"', dc)
        self.assertIn('<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge"', dc)


class ColdDeepLink(BrowserBase):
    """A notification click with no tab open loads /#doc=<key>&pin=<n> cold (the service worker's openWindow). On an
    instance with several documents the boot rewrote the hash to #doc=<key> before reading pin=, so the pin was lost."""

    WHO = ALICE

    def setUp(self):
        super().setUp()
        from test_i18n import _png
        src = ps.C.src
        (src / "hl.tex").write_text((src / "main.tex").read_text(encoding="utf-8"), encoding="utf-8")
        ps.set_docs(ps.make_docs(["ms=본문:main.tex", "hl=하이라이트:hl.tex"], src))
        for D in ps.DOCS:
            pages = D.dir / "pages-20260925100000"
            pages.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (pages / ("page-%d.png" % i)).write_bytes(_png(1275, 1650))
            (D.dir / "pages.cur").write_text(pages.name)
            (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
            (D.dir / "head.txt").write_text("abc1234")
        ms, hl = ps.DOCS
        for lo in range(4, 30, 2):
            add_pin({"file": str(src / "main.tex"), "lo": lo, "hi": lo + 1, "page": 1, "note": "본문 %d" % lo}, A).record["id"]
        for lo in range(4, 24, 2):
            add_pin({"file": str(src / "hl.tex"), "lo": lo, "hi": lo + 1, "page": 1, "note": "하이라이트 %d" % lo}, A, doc=hl).record["id"]
        self.target = add_pin({"file": str(src / "hl.tex"), "lo": 30, "hi": 31, "page": 2, "note": "여기로 와야 함"}, A, doc=hl).record["id"]
        self.gone = add_pin({"file": str(src / "hl.tex"), "lo": 32, "hi": 33, "page": 2, "note": "되살릴 핀"}, A, doc=hl).record["id"]
        ps.drop_pin(self.gone, B)
        self.addCleanup(ps.set_docs, None)

    def cold(self, hash_, device):
        context = self.browser.new_context(**DEVICES[device])
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko" + hash_)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=20&&META", timeout=20000)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def assert_card_shown(self, page, pid, device):
        page.wait_for_function("DOC==='hl'&&OPEN_CARDS.has(%d)&&!!document.querySelector('.pin[data-id=\"%d\"]')" % (pid, pid), timeout=8000)
        if device == "desktop":                                                  # the card is scrolled into the panel
            page.wait_for_function("""(()=>{const c=document.querySelector('.pin[data-id="%d"]').getBoundingClientRect(),
                l=document.getElementById('list').getBoundingClientRect(); return c.height>0&&c.top>=l.top-1&&c.bottom<=l.bottom+1;})()""" % pid,
                timeout=5000)

    def test_cold_link_opens_the_pin_in_another_document(self):
        for device in ("desktop", "phone"):
            with self.subTest(device=device):
                page = self.cold("#doc=hl&pin=%d" % self.target, device)
                self.assert_card_shown(page, self.target, device)
                self.assertEqual(page.evaluate("location.hash"), "#doc=hl")      # the one-shot pin= is consumed

    def test_cold_restore_link_restores_and_opens(self):
        page = self.cold("#doc=hl&pin=%d&act=restore" % self.gone, "desktop")
        page.wait_for_function("OPEN_ALL.some(p=>p.id===%d)" % self.gone, timeout=8000)
        self.assertIsNotNone(ps.find_pin(ps.snapshot_pins(), self.gone))
        self.assert_card_shown(page, self.gone, "desktop")
        self.assertEqual(page.evaluate("location.hash"), "#doc=hl")

    def test_service_worker_carries_the_restore_action_into_a_new_window(self):
        self.assertIn("e.action==='restore'?'&act=restore':''", ps.SW_JS)


# ---------------------------------------------------------------- review of PR #11: what the preview says is what happens

class AgentAsPerson(AccessBase):
    """An agent without a token that sends as a person (--auth local headerless curl, or a person-logged-in machine
    through the tailnet address) is a person to the rule - its reply reopens a review pin unless it sends reopen:false."""

    def setUp(self):
        super().setUp()
        ps.C.auth = "local"
        ps.C.agent_loopback = False
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n"}, A).record["id"]
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="고침")
        self.pid = pid

    def test_headerless_local_curl_reopens_unless_it_says_reopen_false(self):
        code, d = self.call("POST", "/api/pins/%d/reply" % self.pid, {"text": "설명 덧붙임", "reopen": False})
        self.assertEqual((code, d["reopened"], d["state"]), (200, False, "review"))
        code, d = self.call("POST", "/api/pins/%d/reply" % self.pid, {"text": "설명 덧붙임"})
        self.assertEqual((code, d["reopened"], d["state"]), (200, True, "open"))

    def test_the_instruction_is_in_pins_md_skill_and_api(self):
        md = ps.pins_md_text(ps.snapshot_pins()).splitlines()
        i = md.index(ps.TOKEN_GUIDANCE)
        self.assertEqual(md[i + 1], ps.REPLY_GUIDANCE)                          # additive line after the token line
        self.assertIn('`"reopen":false`', ps.REPLY_GUIDANCE)
        self.assertIn("토큰 없이", ps.REPLY_GUIDANCE)
        for f, needle in ((ROOT / "skill" / "SKILL.md", '"reopen": false'), (ROOT / "skill" / "SKILL.ko.md", '"reopen": false'),
                          (ROOT / "docs" / "handbook" / "api.md", '"reopen": false')):
            text = f.read_text(encoding="utf-8")
            self.assertIn(needle, text, f.name)
            j = text.index(needle)
            self.assertIn('"review": true', text[max(0, j - 800):j + 800], f.name)   # next to the review:true note


class TrashClockStart(Base):
    def test_startup_purge_starts_the_hourly_clock(self):
        ps._TRASH_CHECKED[0] = 0.0
        ps.purge_trash()
        self.assertGreater(ps._TRASH_CHECKED[0], time.time() - 5)


class ViewerFunctions2(unittest.TestCase):
    def setUp(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("node not available")

    def js(self, lang, script):
        return json.loads(run_node("\n".join([js_i18n(lang),
            "const PEOPLE=[{login:'bob@example.com',name:'Bob Park'},{login:'carol@example.com',name:'Carol Lee'}];",
            extract_js_fn("peopleName"), extract_js_fn("pinState"), extract_js_fn("replyReopens"), extract_js_fn("replyPreview"),
            extract_js_fn("replyPlaceholder"), extract_js_fn("replyServerNote"), script])))

    def test_override_on_still_names_who_is_notified(self):
        rv, q = rec_for("review", "fix"), rec_for("review", "question")
        out = self.js("ko", "console.log(JSON.stringify([replyPreview(%s,true,['bob@example.com'],true).text, replyPreview(%s,true,['carol@example.com'],true).text]));"
                      % (json.dumps(rv), json.dumps(q)))
        self.assertEqual(out, ["보내면 이 핀이 다시 열려 에이전트에게 가고, Bob Park에게 알림이 갑니다",
                               "보내면 이 핀이 다시 열려 에이전트에게 가고, Carol Lee에게 알림이 갑니다"])
        en = self.js("en", "console.log(JSON.stringify([replyPreview(%s,true,['bob@example.com'],true).text]));" % json.dumps(rv))
        self.assertEqual(en, ["Sending reopens this pin for the agent and notifies Bob Park"])

    def test_placeholder_follows_the_outcome(self):
        rv, q, op = rec_for("review", "fix"), rec_for("review", "question"), rec_for("open", "fix")
        out = self.js("ko", "console.log(JSON.stringify([replyPlaceholder(%s,true,false),replyPlaceholder(%s,true,true),"
                      "replyPlaceholder(%s,true,false),replyPlaceholder(%s,false,false),replyPlaceholder(%s,true,false)]));"
                      % tuple(json.dumps(x) for x in (rv, rv, q, rv, op)))
        reopen = "무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)"
        plain = "답글 (⌘/Ctrl+Enter 보내기)"
        self.assertEqual(out, [reopen, plain, plain, plain, plain])

    def test_post_send_note_says_what_the_server_did(self):
        out = self.js("ko", r"""console.log(JSON.stringify([
            replyServerNote(7,true,{ok:true,reopened:true,state:'open'}),
            replyServerNote(7,true,{ok:true,reopened:false,state:'open'}),
            replyServerNote(7,false,{ok:true,reopened:true,state:'open'}),
            replyServerNote(7,false,{ok:true,reopened:false,state:'done'})]));""")
        self.assertEqual(out, [None, "#7 은 그사이 이미 열려 있어 답글로만 남았습니다",
                               "#7 은 그사이 닫혀서 이 답글이 다시 열었습니다", None])

    def test_trash_row_shows_who_and_separates_the_times(self):
        """A Trash row shows who deleted it and separates the relative time from the days left."""
        js = "\n".join([js_i18n("ko"), js_icons(), r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={loc:'l',restore:'s',purge:'u'}; let SHOW_ALL=false,DOCS=[],DOC='main',DEFAULT_DOC='main',META=null; const ARC_OPEN=new Set();
            function docInfo(){return null;} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            function relSpan(s,cls,tip){return '<span class="rt '+cls+'">7시간 전</span>';} function fmtText(t){return esc(t);}
            const TRASH_DAYS=30;""", extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locCopy"), extract_js_fn("docChip"), extract_js_fn("arcLoc"), extract_js_fn("arcLine"),
            extract_js_fn("trashDaysLeft"), extract_js_fn("isOwner"), extract_js_fn("isViewer"), extract_js_fn("droppedCard"), r"""
            const h=droppedCard({id:4,file:'/m.tex',name:'m.tex',lo:2,hi:9,page:1,note:'메모',dropped_at:'2026-09-25 09:00:00',dropped_by:{name:'Bob Park'},expires_ts:Date.now()/1000+30*86400-60});
            console.log(JSON.stringify([h.replace(/<svg.*?<\/svg>/g,'').replace(/<[^>]+>/g,'|').replace(/\|+/g,'|')]));"""])
        text = json.loads(run_node(js))[0]
        self.assertIn("7시간 전|·|Bob Park 삭제|·|30일 뒤 지워짐", text)


class PreviewEqualsServer(BrowserBase):
    """The real input pipeline: text + autocomplete state -> the outcome line -> the request body -> the server decision."""
    WHO = ALICE
    LEE = {"login": "sl@example.com", "name": "Robin Lee"}
    PARK = {"login": "sp@example.com", "name": "Robin Park"}

    def setUp(self):
        super().setUp()
        for p in (A, self.LEE, self.PARK):
            ps.record_person(p)
        self.pins = []
        for i in range(5):
            pid = add_pin({"file": str(self.main), "lo": 4 + 2 * i, "hi": 5 + 2 * i, "page": 1, "note": "검토 %d" % i}, A).record["id"]
            ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), reply="고침 %d" % i)
            self.pins.append(pid)

    def run_case(self, page, pid, pick, text):
        card = "#review-pins .pin[data-id=\"%d\"]" % pid
        page.evaluate("OPEN_CARDS.add(%d); drawPins()" % pid)
        page.click(card + " .acts [data-act=reply-open]")
        ta = card + " textarea.r-text"
        if pick:
            page.click(ta)
            page.keyboard.type("@Rob")
            page.wait_for_selector("#mention-pop:not([hidden])")
            page.click("#mention-pop button:has-text('%s')" % pick)
        page.fill(ta, text)
        page.wait_for_timeout(100)
        preview = page.inner_text(card + " .r-outcome .r-out-t")
        page.click(card + " [data-act=reply-send]")
        page.locator("#toasts .toast").first.locator("button.btn-icon").click()
        end = time.time() + 8
        while time.time() < end and ps.find_pin(ps.snapshot_pins(), pid)["thread"][-1].get("text") != text:
            page.wait_for_timeout(100)
        r = ps.find_pin(ps.snapshot_pins(), pid)
        last = r["thread"][-1]
        return preview, not r.get("done"), [ps.known_people()[lg]["name"] for lg in last.get("mentions") or []]

    def test_preview_matches_the_server_for_ambiguous_partial_and_edited_names(self):
        page = self.open(0)
        cases = [("Robin Lee", "@Robin Lee 확인 부탁"),              # autocompleted, kept
                 ("Robin Lee", "@Robin 확인 부탁"),                  # autocompleted, then edited down to the ambiguous first word
                 (None, "@Robin Park 봐 주세요"),                      # typed in full, no autocomplete
                 ("Robin Park", "@Robin 이것도요"),                  # picked Park, edited to the first word
                 (None, "@Robin 누구든 봐 주세요")]                    # ambiguous, never picked
        for pid, (pick, text) in zip(self.pins, cases, strict=True):
            with self.subTest(pick=pick, text=text):
                preview, reopened, notified = self.run_case(page, pid, pick, text)
                said_reopen = preview.startswith("보내면 이 핀이 다시 열려")
                self.assertEqual(said_reopen, reopened, (preview, reopened, notified))
                for name in notified:
                    self.assertIn(name, preview)
                if not reopened:
                    self.assertTrue(notified, preview)


class ReplyKeyboardAndFailure(BrowserBase):
    WHO = ALICE

    def setUp(self):
        super().setUp()
        ps.record_person(A)
        self.rv = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "식"}, A).record["id"]
        ps.set_done(self.rv, True, dict(ps.LOCAL_ACTOR), reply="고침")

    def box(self, page):
        card = "#review-pins .pin[data-id=\"%d\"]" % self.rv
        page.evaluate("OPEN_CARDS.add(%d); drawPins()" % self.rv)
        page.click(card + " .acts [data-act=reply-open]")
        return card

    def test_ctrl_enter_moves_focus_to_undo(self):
        page = self.open(0)
        card = self.box(page)
        page.fill(card + " textarea.r-text", "키보드로 보냄")
        page.focus(card + " textarea.r-text")
        page.keyboard.press("Control+Enter")
        page.wait_for_function("document.activeElement&&document.activeElement.closest('.toast')&&document.activeElement.textContent==='되돌리기'")
        page.keyboard.press("Enter")
        page.wait_for_selector(card + " textarea.r-text")
        self.assertEqual(page.input_value(card + " textarea.r-text"), "키보드로 보냄")
        page.wait_for_timeout(300)
        self.assertEqual(ps.pin_state(ps.find_pin(ps.snapshot_pins(), self.rv)), "review")

    def test_offline_failure_reopens_the_box_with_the_draft_and_an_error(self):
        page = self.open(0)
        page.route("**/api/pins/*/reply", lambda r: r.abort())
        card = self.box(page)
        page.fill(card + " textarea.r-text", "오프라인에서 쓴 글")
        page.click(card + " [data-act=reply-send]")
        page.locator("#toasts .toast").first.locator("button.btn-icon").click()
        page.wait_for_selector(card + " .reply-box .r-err:not([hidden])", timeout=5000)
        self.assertEqual(page.input_value(card + " textarea.r-text"), "오프라인에서 쓴 글")
        self.assertEqual(ps.pin_state(ps.find_pin(ps.snapshot_pins(), self.rv)), "review")

    def test_override_is_a_switch(self):
        page = self.open(0)
        card = self.box(page)
        page.fill(card + " textarea.r-text", "x")
        sw = page.locator(card + " [data-act=reply-flip]")
        self.assertEqual((sw.get_attribute("role"), sw.get_attribute("aria-checked")), ("switch", "false"))
        self.assertIn("상태 유지", sw.inner_text())
        sw.click()
        self.assertEqual(sw.get_attribute("aria-checked"), "true")


class RestoreLinkRunsOnce(BrowserBase):
    WHO = ALICE

    def test_reload_does_not_restore_again(self):
        ps.record_person(A)
        pid = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "page": 1, "note": "지운 핀"}, A).record["id"]
        keep = add_pin({"file": str(self.main), "lo": 12, "hi": 13, "page": 1, "note": "남은 핀"}, A).record["id"]
        ps.drop_pin(pid, B)
        context = self.browser.new_context(viewport={"width": 1400, "height": 850})
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko#pin=%d&act=restore" % pid)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.some(p=>p.id===%d)" % pid, timeout=20000)
        self.assertNotIn("act=restore", page.evaluate("location.href"))
        ps.drop_pin(pid, A)                                                        # dropped again elsewhere
        page.reload()
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.some(p=>p.id===%d)&&META" % keep, timeout=20000)
        page.wait_for_timeout(800)
        self.assertIsNone(ps.find_pin(ps.snapshot_pins(), pid))


class TrashOfAnotherDocument(ColdDeepLink):
    def test_opening_the_trash_at_another_documents_pin_keeps_the_list_filter(self):
        page = self.cold("#doc=ms", "desktop")
        page.evaluate("openTrash(%d)" % self.gone)
        page.wait_for_selector("#trash .arc-row[data-id=\"%d\"]" % self.gone)
        self.assertFalse(page.evaluate("SHOW_ALL"))
        page.click("#trash [data-act=trash-close]")
        self.assertFalse(page.evaluate("SHOW_ALL"))

    # the parent's tests run in ColdDeepLink already
    test_cold_link_opens_the_pin_in_another_document = None
    test_cold_restore_link_restores_and_opens = None
    test_service_worker_carries_the_restore_action_into_a_new_window = None
