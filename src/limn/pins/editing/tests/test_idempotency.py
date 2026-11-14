"""POST /api/pin's idempotency key `idem` (docs/handbook/api.md §핀 만들기와 상태 바꾸기, limn.pins.idem).

A viewer that queued a pin with no network sends it with a key; a send whose answer was lost is sent again with the
same key and is answered with the pin the first send made, writing nothing. These tests drive the real handler over
a socket pair, as the viewer does, and read the state files byte for byte.
"""

import json
import os
import threading
import time
import unittest
from unittest import mock

from limn.pins import idem as pin_idem
from limn.pins.editing import service as editing_service
from limn.pins.editing.fields import parse_idem
from limn.pins.model import parse_pin
from limn.pins.store import dump_jsonl
from limn.platform.files import atomic_write
from limn.runtime.documents import Doc
from limn.web.errors import InputRejected

from helpers import fits, ps, req, split_resp, trash_records
from helpers_access import ALICE, BOB, CAROL, TS_HOST, AccessBase, actor, talk_to

KEY = "q-7f3a9c2e1b4d5a6c"  # 18 characters of the allowed alphabet
OTHER = "q-0000000000000000"
# The contract's harsh samples (docs/superpowers/plans/2026-11-14-offline-pin-completion.md §계약 1): each is 400 bad_idem.
BAD_KEYS = ["", "a" * 15, "a" * 65, "한글키-0123456789abcd", 12345678901234567]
NOTE = "이 문단 톤을 낮춰줘"


class ParseIdem(unittest.TestCase):
    """The key's shape: 16-64 characters of [A-Za-z0-9_-], absent or null being no key."""

    def test_the_harsh_samples_are_refused_as_bad_idem(self):
        """Empty, 15 and 65 characters, Hangul, a number - and other shapes a body could carry."""
        for value in [*BAD_KEYS, "a" * 16 + "\n", "a" * 16 + " ", "a" * 15 + ".", True, [KEY], {"k": KEY}, 1.5]:
            with self.subTest(value=value):
                got = parse_idem(value)
                self.assertIsInstance(got, InputRejected)
                assert isinstance(got, InputRejected)
                self.assertEqual(got.reason, "bad_idem")

    def test_absent_or_null_is_no_key_and_the_bounds_are_inclusive(self):
        """None is no key; exactly 16 and exactly 64 characters, with every allowed character class, are keys."""
        self.assertIsNone(parse_idem(None))
        for value in ["a" * 16, "Z" * 64, "AZaz09_-" * 2, "-" * 16, "_" * 64]:
            with self.subTest(value=value):
                self.assertEqual(parse_idem(value), value)

    def test_a_stored_value_that_is_no_key_answers_for_nothing(self):
        """idem_of reads only a well-formed stored key; a hand edit's number or short string is no key."""
        self.assertEqual(pin_idem.idem_of({"idem": KEY}), KEY)
        for stored in (12345678901234567, "short", None, ["x" * 16]):
            with self.subTest(stored=stored):
                self.assertIsNone(pin_idem.idem_of({"idem": stored}))
        self.assertIsNone(pin_idem.idem_of({}))


class IdemBase(AccessBase):
    """The handler over a socket pair, with helpers that read every state file a pin write touches."""

    def body(self, **extra):
        """A line pin on main.tex lines 4-5 as the viewer sends it."""
        return {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": NOTE, **extra}

    def post_raw(self, body, headers=None):
        """POST /api/pin as headers (default the loopback agent): (status, raw response body)."""
        h = {"Content-Type": "application/json", **(headers or {})}
        code, _, out = split_resp(talk_to(ps, req("POST", "/api/pin", json.dumps(body).encode(), h), "127.0.0.1"))
        return code, out

    def post(self, body, headers=None):
        """POST /api/pin: (status, parsed answer)."""
        code, out = self.post_raw(body, headers)
        return code, json.loads(out)

    def files(self):
        """The bytes of every state file a pin write can touch (None for one that does not exist), and pins_rev."""
        C = ps.APP.C
        out = {}
        for name, path in (
            ("pins.jsonl", C.pins_jsonl),
            ("pins.md", C.pins_md),
            ("pins.seq", C.seq),
            ("pins.dropped.jsonl", C.dropped),
            ("events.jsonl", C.events_file),
        ):
            out[name] = path.read_bytes() if path.exists() else None
        out["pins_rev"] = self.call("GET", "/api/meta?light=1")[1]["pins_rev"]
        return out

    def stored(self):
        """The live records as stored, in file order."""
        return [json.loads(t) for t in ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines() if t.strip()]


class Replay(IdemBase):
    """A key already held answers with its pin and writes nothing."""

    def test_the_first_send_stores_the_key_last_and_answers_as_before(self):
        """A keyed request makes its pin as always; the record ends with idem and the answer is just {id}."""
        code, d = self.post(self.body(idem=KEY))
        self.assertEqual((code, d), (200, {"id": 1}))
        rec = self.stored()[0]
        self.assertEqual(list(rec)[-1], "idem")
        self.assertEqual(rec["idem"], KEY)

    def test_a_replay_answers_the_first_pin_and_writes_nothing(self):
        """The same key again: 200 {id, replay:true} with the first id; pins.jsonl, pins.md, pins.seq, the Trash, the
        events file and pins_rev are all byte-identical before and after."""
        ps.APP.people_directory.record(actor(ALICE))  # a known assignee, so the first send leaves a notice
        sent = self.body(idem=KEY, assignee="alice@example.com")
        code, first = self.post(sent, BOB)
        self.assertEqual(code, 200, first)
        before = self.files()
        self.assertIn(b'"assigned"', before["events.jsonl"])
        for _ in range(3):
            code, raw = self.post_raw(sent, BOB)
            self.assertEqual(code, 200, raw)
            self.assertEqual(json.loads(raw), {"id": first["id"], "replay": True})
            self.assertEqual(list(json.loads(raw)), ["id", "replay"])
        self.assertEqual(self.files(), before)

    def test_a_replay_writes_nothing_even_when_the_manuscript_moved(self):
        """Lines inserted above the pin make its stored range stale, so any pin transaction would write a re-sync. A
        replay is not one: it answers from the stored pins and leaves every file and pins_rev as they were. The next
        write that is not a replay re-syncs as always."""
        pid = self.post(self.body(idem=KEY))[1]["id"]
        text = self.main.read_text(encoding="utf-8")
        self.main.write_text("% one\n% two\n" + text, encoding="utf-8")
        later = time.time() + 5
        os.utime(self.main, (later, later))
        before = self.files()
        self.assertEqual(self.post(self.body(idem=KEY))[1], {"id": pid, "replay": True})
        self.assertEqual(self.files(), before)
        self.assertEqual(self.post(self.body(idem=OTHER))[1], {"id": pid + 1})
        self.assertEqual((self.stored()[0]["lo"], self.stored()[0]["hi"]), (6, 7))  # the re-sync, written now

    def test_a_replay_whose_body_differs_still_answers_the_first_pin(self):
        """The first send wins: another note, other lines, a suggestion that would be refused, a verdict an agent may
        not make, a question - each is answered with the first pin, which keeps its first note and lines."""
        code, first = self.post(self.body(idem=KEY))
        self.assertEqual(code, 200, first)
        before = self.files()
        for other in (
            {"note": "다른 메모"},
            {"lo": 2, "hi": 3},
            {"suggest": {"base": "x", "text": "x"}},  # suggest_noop on a fresh request
            {"verdict": "accept"},  # verdict_human for the loopback agent on a fresh request
            {"kind_req": "question", "note": "?"},
        ):
            with self.subTest(other=other):
                code, d = self.post({**self.body(idem=KEY), **other})
                self.assertEqual((code, d), (200, {"id": first["id"], "replay": True}))
        self.assertEqual(self.files(), before)
        rec = self.stored()[0]
        self.assertEqual((rec["note"], rec["lo"], rec["hi"]), (NOTE, 4, 5))

    def test_another_key_and_no_key_each_make_a_new_pin(self):
        """Keys tell pins apart, not their content: the same body under another key, or with no key, is a new pin."""
        self.assertEqual(self.post(self.body(idem=KEY))[1], {"id": 1})
        self.assertEqual(self.post(self.body(idem=OTHER))[1], {"id": 2})
        self.assertEqual(self.post(self.body())[1], {"id": 3})
        self.assertEqual(self.post(self.body())[1], {"id": 4})
        self.assertEqual([r.get("idem") for r in self.stored()], [KEY, OTHER, None, None])

    def test_a_key_on_a_closed_or_edited_pin_still_answers(self):
        """Closing (to review, by the agent; then done, by a person), editing and replying keep idem on the record,
        so every later send of the key is still a replay."""
        pid = self.post(self.body(idem=KEY))[1]["id"]
        rev = self.call("GET", "/api/pins/%d" % pid)[1]["pin"]["rev"]
        self.assertEqual(self.call("POST", "/api/pins/%d/edit" % pid, {"note": "고친 메모", "base_rev": rev})[0], 200)
        self.assertEqual(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "봤어요"}, ALICE)[0], 200)
        code, closed = self.call("POST", "/api/pins/%d/close" % pid)
        self.assertEqual((code, closed["state"]), (200, "review"))
        self.assertEqual(self.post(self.body(idem=KEY))[1], {"id": pid, "replay": True})
        self.assertEqual(self.call("POST", "/api/pins/%d/confirm" % pid, {}, ALICE)[0], 200)
        self.assertEqual(self.stored()[0]["idem"], KEY)
        self.assertEqual(self.post(self.body(idem=KEY))[1], {"id": pid, "replay": True})
        self.assertEqual(len(self.stored()), 1)


class Refusals(IdemBase):
    """A malformed key is 400 bad_idem and writes nothing; null or no key is a request without one."""

    def test_the_harsh_samples_are_400_bad_idem_over_http(self):
        """Each sample is refused before anything is written, with the contract's error shape."""
        for value in BAD_KEYS:
            with self.subTest(value=value):
                before = self.files()
                code, d = self.post(self.body(idem=value))
                self.assertEqual((code, d["reason"]), (400, "bad_idem"))
                self.assertIsInstance(d["error"], str)
                self.assertEqual(self.files(), before)

    def test_a_bad_key_is_refused_before_the_rest_of_the_body(self):
        """A malformed key is the first refusal: before a file outside the manuscript, a note of the wrong type."""
        code, d = self.post({"file": "/nowhere/x.tex", "lo": 1, "hi": 1, "note": 7, "idem": ""})
        self.assertEqual((code, d["reason"]), (400, "bad_idem"))

    def test_null_is_a_request_without_a_key(self):
        """idem: null makes a new pin each time and stores no idem field."""
        self.assertEqual(self.post(self.body(idem=None))[1], {"id": 1})
        self.assertEqual(self.post(self.body(idem=None))[1], {"id": 2})
        self.assertEqual([("idem" in r) for r in self.stored()], [False, False])


class WithoutAKey(IdemBase):
    """A request without idem behaves exactly as before keys existed."""

    def test_record_and_answer_match_the_keyed_path_byte_for_byte_apart_from_the_key(self):
        """The same body sent without a key and with one, at the same clock: the answers are the same bytes but for
        the id, and the stored lines are the same bytes but for the id and the trailing idem - so the key adds one
        field and changes nothing else. Without a key the answer has no replay and the record no idem."""
        commands = ps.APP.assembly.pins.commands
        with mock.patch.object(commands, "now_str", lambda: "2026-11-14 10:00:00"):
            code_a, raw_a = self.post_raw(self.body())
            code_b, raw_b = self.post_raw(self.body(idem=KEY))
        self.assertEqual((code_a, code_b), (200, 200))
        self.assertEqual(raw_a.replace(b"1", b"N"), raw_b.replace(b"2", b"N"))
        self.assertNotIn(b"replay", raw_a)
        line_a, line_b = ps.APP.C.pins_jsonl.read_text(encoding="utf-8").splitlines()
        a, b = json.loads(line_a), json.loads(line_b)
        self.assertNotIn("idem", a)
        self.assertEqual(b.pop("idem"), KEY)
        a.pop("id"), b.pop("id")
        a.pop("synced_at"), b.pop("synced_at")  # the file's mtime as read before the lock, the same file
        self.assertEqual(json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False))
        self.assertEqual(list(json.loads(line_b))[:-1], list(json.loads(line_a)))

    def test_the_stored_line_is_the_one_the_writer_always_wrote(self):
        """A pin made without a key round-trips through the store's parse to the same bytes, with no idem."""
        self.post(self.body())
        line = ps.APP.C.pins_jsonl.read_text(encoding="utf-8")
        rec = json.loads(line)
        self.assertNotIn("idem", rec)
        self.assertEqual(dump_jsonl([parse_pin(rec).record]), line)


class Hidden(IdemBase):
    """idem is stored, never shown: not in pins.md, GET /api/pins rows, a pin's GET, the Trash list or a change
    response's pin."""

    def assert_hidden(self, value):
        """The key appears nowhere in value as JSON text."""
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        self.assertNotIn(KEY, text)
        self.assertNotIn('"idem"', text)

    def test_no_read_shows_the_key(self):
        """Every read of a keyed pin, open, closed and in the Trash, and the disk and HTTP pins.md."""
        pid = self.post(self.body(idem=KEY))[1]["id"]
        self.assertIn(KEY, ps.APP.C.pins_jsonl.read_text(encoding="utf-8"))
        self.assert_hidden(self.call("GET", "/api/pins")[1])
        self.assert_hidden(self.call("GET", "/api/pins?all=1")[1])
        self.assert_hidden(self.call("GET", "/api/pins/%d" % pid)[1])
        self.assert_hidden(self.call("GET", "/pins.md")[1])
        self.assert_hidden(ps.APP.C.pins_md.read_text(encoding="utf-8"))
        rev = self.call("GET", "/api/pins/%d" % pid)[1]["pin"]["rev"]
        self.assert_hidden(self.call("POST", "/api/pins/%d/edit" % pid, {"note": "x", "base_rev": rev})[1])
        self.assert_hidden(self.call("POST", "/api/pins/%d/reply" % pid, {"text": "y"}, ALICE)[1])
        self.assert_hidden(self.call("POST", "/api/pins/%d/close" % pid)[1])
        self.assert_hidden(self.call("GET", "/api/pins?all=1")[1])
        self.assert_hidden(self.call("POST", "/api/pins/%d/drop" % pid)[1])
        self.assert_hidden(self.call("GET", "/api/pins/dropped")[1])
        self.assert_hidden(self.call("POST", "/api/pins/%d/restore" % pid, None, ALICE)[1])
        self.assert_hidden(self.call("GET", "/api/meta")[1])


class Trash(IdemBase):
    """A pin in the Trash still holds its key; a purged or expired one does not."""

    def setUp(self):
        """Alice is the owner, who alone purges."""
        super().setUp()
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])

    def test_a_dropped_pin_still_answers_for_its_key_and_after_its_restore(self):
        """Dropped: a replay with its id, writing nothing (not even the Trash). Restored: still the same pin."""
        pid = self.post(self.body(idem=KEY), BOB)[1]["id"]
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)[1]["ok"], True)
        self.assertEqual(trash_records()[0]["idem"], KEY)
        before = self.files()
        self.assertEqual(self.post(self.body(idem=KEY), BOB)[1], {"id": pid, "replay": True})
        self.assertEqual(self.files(), before)
        self.assertEqual(self.call("POST", "/api/pins/%d/restore" % pid, None, BOB)[0], 200)
        self.assertEqual(self.post(self.body(idem=KEY), BOB)[1], {"id": pid, "replay": True})
        self.assertEqual([r["idem"] for r in self.stored()], [KEY])

    def test_a_purged_pins_key_makes_a_new_pin(self):
        """After the owner's permanent delete the key is free: the same key makes a new pin with a new id, holding it."""
        pid = self.post(self.body(idem=KEY), BOB)[1]["id"]
        self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)
        code, d = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual((code, d["purged"]), (200, pid))
        code, d = self.post(self.body(idem=KEY), BOB)
        self.assertEqual(code, 200)
        self.assertEqual(d, {"id": pid + 1})
        self.assertEqual([(r["id"], r["idem"]) for r in self.stored()], [(pid + 1, KEY)])
        self.assertEqual(self.post(self.body(idem=KEY), BOB)[1], {"id": pid + 1, "replay": True})

    def test_an_expired_trash_entry_holds_no_key(self):
        """An entry past its 30 days is as good as purged (restore answers 404 for it): the key makes a new pin."""
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 31 * 86400))
        rec = {"id": 40, "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "old", "author": actor(BOB)}
        rec.update(dropped_at=old, dropped_by=actor(BOB), idem=KEY)
        atomic_write(ps.APP.C.dropped, dump_jsonl([rec]))
        ps.APP.C.seq.write_text("40")
        self.assertEqual(self.post(self.body(idem=KEY), BOB)[1], {"id": 41})


class AcrossDocuments(IdemBase):
    """A key belongs to the instance, not to one document."""

    def setUp(self):
        """Two documents: the LaTeX manuscript ms and a Markdown document nt (notes/plan.md)."""
        super().setUp()
        (self.src / "notes").mkdir()
        self.md = self.src / "notes" / "plan.md"
        self.md.write_text("# Plan\n\nFirst line.\nSecond line.\n", encoding="utf-8")
        ms = Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        nt = Doc("nt", "계획", "markdown", self.src / "notes", self.md, paths=ps.APP.C.paths)
        ps.APP.set_docs([ms, nt])
        self.addCleanup(ps.APP.set_docs, None)

    def test_a_key_held_in_one_document_answers_a_send_to_another(self):
        """The key of a pin in ms, sent with a body for nt, is answered with the ms pin; nt gets no pin."""
        code, d = self.post(self.body(doc="ms", idem=KEY))
        self.assertEqual((code, d), (200, {"id": 1}))
        nt = {"doc": "nt", "file": str(self.md), "lo": 3, "hi": 4, "note": "n", "idem": KEY}
        self.assertEqual(self.post(nt)[1], {"id": 1, "replay": True})
        self.assertEqual([r["doc"] for r in self.stored()], ["ms"])
        self.assertEqual(self.post({**nt, "idem": OTHER})[1], {"id": 2})


class Concurrency(IdemBase):
    """Two sends of one key at the same moment make one pin: the lookup and the write share one transaction."""

    def test_concurrent_sends_of_one_key_make_exactly_one_pin(self):
        """Eight threads post the same key through the handler at once, each over its own connection. The lookup is
        slowed down inside the transaction to widen any window between looking and writing. Exactly one pin is
        stored and pins.seq advanced once; every answer is a 200 with that pin's id, exactly one of them not a
        replay."""
        n = 8
        real = editing_service.keyed_pin

        def slow(*args, **kwargs):
            """The real lookup after a pause, so a lookup outside the transaction would race."""
            time.sleep(0.05)
            return real(*args, **kwargs)

        barrier = threading.Barrier(n)
        answers: list[tuple[int, dict]] = []
        lock = threading.Lock()

        def send(i):
            """One send of the key, with a body that differs per thread."""
            barrier.wait()
            got = self.post(self.body(idem=KEY, note="thread %d" % i))
            with lock:
                answers.append(got)

        with mock.patch.object(editing_service, "keyed_pin", slow):
            threads = [threading.Thread(target=send, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(len(answers), n)
        self.assertEqual({code for code, _ in answers}, {200})
        ids = {d["id"] for _, d in answers}
        self.assertEqual(len(ids), 1)
        self.assertEqual(sum(1 for _, d in answers if "replay" not in d), 1)
        self.assertEqual(sum(1 for _, d in answers if d.get("replay") is True), n - 1)
        stored = self.stored()
        self.assertEqual([(r["id"], r["idem"]) for r in stored], [(ids.pop(), KEY)])
        self.assertEqual(ps.APP.C.seq.read_text().strip(), "1")


class ReplayOnly(IdemBase):
    """POST /api/pin {idem, replay_only: true}: only whether the key is held. A viewer asks it for a queued pin whose
    earlier send may have landed, before it looks for that pin's place again - which may be gone by then."""

    def test_a_held_key_answers_its_pin_and_writes_nothing(self):
        code, first = self.post(self.body(idem=KEY))
        self.assertEqual(code, 200, first)
        before = self.files()
        code, raw = self.post_raw({"idem": KEY, "replay_only": True})
        self.assertEqual(code, 200, raw)
        self.assertEqual(json.loads(raw), {"id": first["id"], "replay": True})
        self.assertEqual(self.files(), before)

    def test_an_unknown_key_is_409_and_makes_no_pin(self):
        """Nothing is created: the body has no place, and even one that had a whole pin in it must not make it."""
        before = self.files()
        for body in ({"idem": KEY, "replay_only": True}, self.body(idem=KEY, replay_only=True)):
            with self.subTest(body=sorted(body)):
                code, d = self.post(body)
                self.assertEqual(code, 409, d)
                self.assertEqual(d["reason"], "idem_unknown")
        self.assertEqual(self.files(), before)
        self.assertIsNone(before["pins.jsonl"], "no pin file was ever written")

    def test_the_rest_of_the_body_is_not_read(self):
        """The question is asked for a pin whose place could not be found again: fields that would refuse a new pin
        (a file outside the tree, a range past the file, a malformed note) do not refuse the question."""
        code, first = self.post(self.body(idem=KEY))
        self.assertEqual(code, 200, first)
        code, d = self.post({"idem": KEY, "replay_only": True, "file": "/etc/passwd", "lo": 99999, "hi": 1, "note": 7})
        self.assertEqual((code, d), (200, {"id": first["id"], "replay": True}))

    def test_a_question_needs_a_well_formed_key(self):
        """Without a key, or with a malformed one, it is 400 bad_idem - and null is not a key here either."""
        for value in [*BAD_KEYS, None]:
            with self.subTest(value=value):
                body = {"replay_only": True} if value is None else {"idem": value, "replay_only": True}
                code, d = self.post(body)
                self.assertEqual(code, 400, d)
                self.assertEqual(d["reason"], "bad_idem")
        code, d = self.post({"idem": None, "replay_only": True})
        self.assertEqual((code, d["reason"]), (400, "bad_idem"))

    def test_only_the_literal_true_asks_the_question(self):
        """Any other value is ignored, as the query switches are: the request is a pin to create."""
        for value in (False, 1, "true", "1", None):
            with self.subTest(value=value):
                code, d = self.post(self.body(note="n%r" % (value,), replay_only=value))
                self.assertEqual(code, 200, d)
                self.assertNotIn("replay", d)

    def test_a_key_in_the_trash_answers_and_a_purged_one_does_not(self):
        self.set_people([{"login": "alice@example.com", "name": "Alice Kim", "role": "owner"}])
        pid = self.post(self.body(idem=KEY), BOB)[1]["id"]
        self.assertEqual(self.call("POST", "/api/pins/%d/drop" % pid, None, BOB)[1]["ok"], True)
        self.assertEqual(self.post({"idem": KEY, "replay_only": True}, BOB), (200, {"id": pid, "replay": True}))
        code, d = self.call("POST", "/api/pins/%d/purge" % pid, None, ALICE)
        self.assertEqual((code, d["purged"]), (200, pid))
        code, d = self.post({"idem": KEY, "replay_only": True}, BOB)
        self.assertEqual((code, d["reason"]), (409, "idem_unknown"))

    def test_a_viewer_may_not_ask(self):
        """The question needs the authority a new pin needs: it is asked on the way to writing one."""
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice", "role": "owner"},
                {"login": "carol@example.com", "name": "Carol", "role": "viewer"},
            ]
        )
        code, first = self.post(self.body(idem=KEY), ALICE)
        self.assertEqual(code, 200, first)
        code, d = self.post({"idem": KEY, "replay_only": True}, dict(CAROL, Host=TS_HOST))
        self.assertEqual((code, d.get("reason")), (403, "viewer_only"), d)


class Capability(IdemBase):
    """GET /api/meta, light and full, says the server takes the key."""

    def test_both_meta_forms_carry_pin_idem(self):
        """pin_idem is true in the full body and in the light poll's."""
        for path in ("/api/meta", "/api/meta?light=1"):
            with self.subTest(path=path):
                code, d = self.call("GET", path)
                self.assertEqual(code, 200)
                self.assertIs(d["pin_idem"], True)


class StoredField(unittest.TestCase):
    """idem on a stored record: the store trusts the line and writes it back unchanged, whatever its value."""

    def test_a_record_with_idem_parses_and_round_trips_byte_for_byte(self):
        """With a key, a number or a short string, the line is not broken and is written back as it was read."""
        base = {"id": 3, "file": "/m/main.tex", "lo": 1, "hi": 2, "note": "n", "rev": 0}
        for value in (KEY, 12345678901234567, "short"):
            with self.subTest(value=value):
                rec = {**base, "idem": value, "later": {"x": 1}}
                self.assertTrue(fits(rec))
                line = dump_jsonl([rec])
                self.assertEqual(dump_jsonl([parse_pin(json.loads(line)).record]), line)
