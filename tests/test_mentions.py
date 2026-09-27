"""limn.mentions - the pure @-tag rules, driven directly with no server, no file and no clock.

The flows that use them (notices on add/edit/reply/reopen) run through the server in test_notifications.py,
test_reply.py and test_service.py; this file pins the rules themselves - including the note-mention cooldown of
v0.3.1 (issue #10 L3) - and the module's import boundary.

Run: uv run pytest -q tests/test_mentions.py
"""

import ast
import unittest
from pathlib import Path

from limn import mentions
from limn.mentions import (
    NOTE_MENTION_COOLDOWN_S,
    NoteTags,
    addressed_to,
    fyi_mentions_to,
    mention_hits,
    mention_tokens,
    note_mention_targets,
    pin_mentions_all,
    resolve_mentions,
    tag_note,
    thread_round,
)
from limn.pins.model import ThreadEntry, parse_pin

MENTIONS_PY = Path(mentions.__file__)
PEOPLE = {
    "alice@example.com": {"login": "alice@example.com", "name": "Alice Kim"},
    "bob@example.com": {"login": "bob@example.com", "name": "Bob Park"},
    "bob.lee@example.com": {"login": "bob.lee@example.com", "name": "Bob Lee"},
    "seojun@example.com": {"login": "seojun@example.com", "name": "김서준"},
}
A, B, BL, S = "alice@example.com", "bob@example.com", "bob.lee@example.com", "seojun@example.com"


class ModuleBoundary(unittest.TestCase):
    """mentions.py is pure: it reaches no file, clock, process, network or server."""

    def test_imports_only_pure_modules(self):
        """Its imports are typing/collections helpers, limn.pins.edit (ASSIGNEE_AGENT), limn.pins.lifecycle (the round
        scan), limn.pins.model (the pin and thread entry types it reads) and limn.pins.shapes (is_num) - nothing
        effectful."""
        tree = ast.parse(MENTIONS_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(
            modules,
            {
                "__future__",
                "collections",
                "collections.abc",
                "typing",
                "limn.pins.edit",
                "limn.pins.lifecycle",
                "limn.pins.model",
                "limn.pins.shapes",
            },
        )

    def test_reads_no_server_global(self):
        """No run-argument object, current document or server helper is named in the module."""
        tree = ast.parse(MENTIONS_PY.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"C", "cur_doc", "DOCS", "PIN_LOCK", "read_pins", "time", "is_agent"})


class Resolve(unittest.TestCase):
    """resolve_mentions()/mention_hits(): '@name' to logins, and the text that must not resolve."""

    def test_full_name_login_and_login_part_resolve(self):
        """A full name, a login and the part of a login before @ all name the same person."""
        self.assertEqual(resolve_mentions("@Bob Park @bob@example.com @alice", PEOPLE), [B, A])

    def test_a_shared_first_name_needs_a_hint(self):
        """'@Bob' matches two people: nobody without a hint, only the hinted one with it."""
        self.assertEqual(resolve_mentions("@Bob hi", PEOPLE), [])
        self.assertEqual(resolve_mentions("@Bob hi", PEOPLE, hints=[BL]), [BL])

    def test_email_like_and_glued_text_do_not_resolve(self):
        """'x@alice' (an address), '@Alicex' (a longer ASCII word) and '_@alice' are not tags."""
        self.assertEqual(resolve_mentions("mail x@alice and @Alicex and _@alice", PEOPLE), [])

    def test_a_korean_particle_after_the_name_is_fine(self):
        """'@김서준님' tags 김서준: the ASCII-word rule does not apply after a Korean name."""
        self.assertEqual(resolve_mentions("@김서준님 봐 주세요", PEOPLE), [S])

    def test_the_excluded_login_is_dropped(self):
        """A self-tag never resolves to the author (exclude)."""
        self.assertEqual(resolve_mentions("@Alice Kim @Bob Park", PEOPLE, exclude=A), [B])

    def test_hits_keep_repeats_and_resolve_deduplicates(self):
        """mention_hits counts every occurrence; resolve_mentions keeps first-seen order without repeats."""
        self.assertEqual(mention_hits("@Bob Park @Alice Kim @Bob Park", PEOPLE), [B, A, B])
        self.assertEqual(resolve_mentions("@Bob Park @Alice Kim @Bob Park", PEOPLE), [B, A])

    def test_no_people_or_no_at_sign_resolves_nothing(self):
        """Without candidates or without '@' there is nothing to resolve."""
        self.assertEqual(mention_hits("@Bob Park", {}), [])
        self.assertEqual(mention_hits("Bob Park", PEOPLE), [])

    def test_tokens_are_longest_first(self):
        """'bob park' is tried before 'bob', so the full name wins over the shared first word."""
        toks = [t for t, _ in mention_tokens(PEOPLE)]
        self.assertLess(toks.index("bob park"), toks.index("bob"))
        self.assertEqual(dict(mention_tokens(PEOPLE))["bob"], {B, BL})


class Addressed(unittest.TestCase):
    """addressed_to()/fyi_mentions_to()/pin_mentions_all() over a pin and its thread rounds."""

    def test_a_question_pin_addresses_its_round_and_a_fix_pin_only_informs(self):
        """A question's tags are asked; a fix pin's tags are FYI."""
        q = parse_pin({"kind_req": "question", "mentions": [B]})
        self.assertEqual((addressed_to(q), fyi_mentions_to(q)), ([B], []))
        f = parse_pin({"kind_req": "fix", "mentions": [B]})
        self.assertEqual((addressed_to(f), fyi_mentions_to(f)), ([], [B]))

    def test_an_assignee_is_addressed_and_the_other_tags_are_fyi(self):
        """A person assignee is asked, every other tag informed; the agent assignee asks nobody."""
        r = parse_pin({"assignee": B, "mentions": [B, BL]})
        self.assertEqual((addressed_to(r), fyi_mentions_to(r)), ([B], [BL]))
        agent = parse_pin({"assignee": "agent", "mentions": [B]})
        self.assertEqual((addressed_to(agent), fyi_mentions_to(agent)), ([], [B]))

    def test_legacy_duplicate_note_tags_keep_order_while_thread_tags_append_once(self):
        """A stored duplicate in the note remains visible; repeated thread tags do not add more recipients."""
        pin = parse_pin(
            {
                "kind_req": "question",
                "mentions": [B, B],
                "thread": [
                    {"mentions": [B, BL, BL]},
                    {"mentions": [BL, A]},
                ],
            }
        )
        self.assertEqual(pin_mentions_all(pin), [B, B, BL, A])
        self.assertEqual(addressed_to(pin), [B, B, BL, A])

    def test_the_old_round_does_not_count_after_a_reopen(self):
        """A reply during review (before the reopen) is not part of the new round."""
        r = parse_pin(
            {
                "kind_req": "question",
                "mentions": [],
                "thread": [
                    {"ev": "close"},
                    {"text": "during review", "mentions": [BL]},
                    {"ev": "reopen", "mentions": [B]},
                ],
            }
        )
        self.assertEqual([e.record for e in thread_round(r.core.thread)], [{"ev": "reopen", "mentions": [B]}])
        self.assertEqual(addressed_to(r), [B])
        self.assertEqual(pin_mentions_all(r), [BL, B])

    def test_under_review_the_round_is_everything_after_the_close(self):
        """Closed and not reopened: the posts after the last close; never closed: the whole thread."""
        th = [ThreadEntry.from_record(e) for e in ({"text": "a"}, {"ev": "close"}, {"text": "b"})]
        self.assertEqual(thread_round(th), [th[2]])
        self.assertEqual(thread_round(th[:1]), th[:1])
        self.assertEqual(thread_round(None), [])


class NoteTagging(unittest.TestCase):
    """tag_note(): the note's tags and who this save newly tags (before the cooldown)."""

    def test_a_new_pin_tags_everyone_in_its_note(self):
        """Against an empty old note, every resolved tag is new, in first-seen order."""
        self.assertEqual(tag_note("@Bob Park @Alice Kim", "", PEOPLE, None, None), NoteTags((B, A), [B, A]))

    def test_a_typo_fix_tags_nobody_new_and_a_second_tag_does(self):
        """Only a person whose '@name' now occurs more often than before is newly tagged."""
        self.assertEqual(tag_note("@Bob Park fix this!", "@Bob Park fix this", PEOPLE, None, None), NoteTags((B,), []))
        self.assertEqual(tag_note("@Bob Park again @Bob Park", "@Bob Park", PEOPLE, None, None), NoteTags((B,), [B]))

    def test_the_editor_is_never_tagged(self):
        """me is left out of both the mentions and the newly tagged."""
        self.assertEqual(tag_note("@Alice Kim @Bob Park", "", PEOPLE, None, A), NoteTags((B,), [B]))

    def test_the_cooldown_leaves_out_a_person_notified_moments_ago(self):
        """note_mention_targets drops a target the same editor's note notified about the same pin within the window."""
        recent = [{"type": "mention", "pin": 3, "to": [B], "by": {"login": A}, "ts": 100.0}]
        self.assertEqual(note_mention_targets([B, BL], recent, A, 3, 100.0 + NOTE_MENTION_COOLDOWN_S - 1), [BL])
        self.assertEqual(note_mention_targets([B], recent, A, 3, 100.0 + NOTE_MENTION_COOLDOWN_S), [B])
        self.assertEqual(note_mention_targets([B], recent, "someone-else", 3, 101.0), [B])
        self.assertEqual(note_mention_targets([B], [dict(recent[0], msg=1)], A, 3, 101.0), [B])  # a reply's mention
        self.assertEqual(note_mention_targets([B], [dict(recent[0], ts=True)], A, 3, 101.0), [B])  # not a number


class MentionsOnPins(unittest.TestCase):
    """resolve_mentions() on people records, and who a pin addresses (the current round only, question pins only)."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def people(self, extra=()):
        d = {p["login"]: dict(p) for p in (self.S, self.W) + tuple(extra)}
        return d

    def test_resolve_mentions_rules(self):
        ppl = self.people(
            ({"login": "wlee@example.com", "name": "Wendy Lee"}, {"login": "sy@example.com", "name": "박서준"})
        )
        R = mentions.resolve_mentions
        self.assertEqual(R("@Bob Park 확인 부탁", ppl), [self.S["login"]])
        self.assertEqual(R("@bob park님 이거요", ppl), [self.S["login"]])  # case-insensitive, Korean particle attached
        self.assertEqual(R("@Bob 봐 주세요", ppl), [self.S["login"]])  # first word of the name (only one match)
        self.assertEqual(R("@Wendy 어때요", ppl), [])  # two candidates share the first word — ambiguous, don't resolve
        # resolved via the viewer's chosen hint
        self.assertEqual(R("@Wendy 어때요", ppl, [self.W["login"]]), [self.W["login"]])
        self.assertEqual(R("메일 bob@example.com 로", ppl), [])  # an email address is not a mention
        self.assertEqual(R("@Bobx", ppl), [])  # letters right after an English name = a different word
        self.assertEqual(R("@박서준님 @Wendy Kim @박서준", ppl), ["sy@example.com", self.W["login"]])
        self.assertEqual(R("@nobody", ppl), [])

    def test_addressed_counts_current_round_only_and_needs_question_kind(self):
        r = {
            "kind_req": "question",
            "mentions": [],
            "thread": [
                {"id": 1, "mentions": ["a"], "text": "", "at": "", "by": {}},
                {"id": 2, "ev": "close", "text": "", "at": "", "by": {}},
                {"id": 3, "ev": "reopen", "mentions": ["b"], "text": "", "at": "", "by": {}},
            ],
        }
        fix = parse_pin(dict(r, kind_req="fix"))
        r = parse_pin(r)
        self.assertEqual(mentions.addressed_to(r), ["b"])
        self.assertEqual(mentions.pin_mentions_all(r), ["a", "b"])
        self.assertEqual(mentions.fyi_mentions_to(r), [])  # a question pin isn't fyi — it's captured only as addressed
        self.assertEqual(mentions.addressed_to(fix), [])  # a fix-request pin isn't skipped even with an @-mention
        self.assertEqual(mentions.fyi_mentions_to(fix), ["b"])  # it's captured only as fyi instead


# ---------------------------------------------------------------- note-mention cooldown (v0.3.1, issue #10 L3): the decision


# The logins of the test identities (helpers_access.ALICE, BOB, CAROL).
A_LOGIN, B_LOGIN, C_LOGIN = "alice@example.com", "bob@example.com", "carol@example.com"


def note_ev(by, to, pin, ts, **extra):
    """An events.jsonl mention record as a note save writes it (no `msg`: it did not come from a thread post)."""
    return dict(
        {
            "type": "mention",
            "pin": pin,
            "doc": "main",
            "to": list(to),
            "by": {"login": by, "name": by},
            "seq": 1,
            "at": "2026-09-26 10:00:00",
            "ts": ts,
        },
        **extra,
    )


class NoteMentionCooldownRule(unittest.TestCase):
    """note_mention_targets() decides which newly tagged people a note save notifies, from the recent events and a clock
    reading passed in - no file, no clock of its own."""

    def targets(self, recent, now, added=(B_LOGIN,), by=A_LOGIN, pin=7):
        return note_mention_targets(list(added), recent, by, pin, now)

    def test_everyone_added_is_notified_when_there_is_no_recent_note_mention(self):
        """With an empty log every newly tagged person gets a mention, in the order given."""
        self.assertEqual(self.targets([], 1000.0, added=(B_LOGIN, C_LOGIN)), [B_LOGIN, C_LOGIN])

    def test_same_actor_target_and_pin_is_suppressed_within_the_window(self):
        """A note mention from the same actor to the same person about the same pin inside ten minutes suppresses the next."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1000.0 + 1), [])
        self.assertEqual(self.targets(recent, 1000.0 + NOTE_MENTION_COOLDOWN_S - 0.001), [])

    def test_a_mention_is_sent_again_once_the_window_has_passed(self):
        """Exactly NOTE_MENTION_COOLDOWN_S (ten minutes) after the last sent note mention, the tag notifies again."""
        self.assertEqual(NOTE_MENTION_COOLDOWN_S, 600)
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1000.0 + NOTE_MENTION_COOLDOWN_S), [B_LOGIN])

    def test_each_key_part_keeps_its_own_cooldown(self):
        """The key is (actor login, target login, pin id): changing any one of them is not suppressed."""
        recent = [note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0)]
        self.assertEqual(self.targets(recent, 1001.0, by=C_LOGIN), [B_LOGIN])  # another actor
        self.assertEqual(self.targets(recent, 1001.0, pin=8), [B_LOGIN])  # another pin
        self.assertEqual(self.targets(recent, 1001.0, added=(B_LOGIN, C_LOGIN)), [C_LOGIN])  # another target

    def test_reply_and_reopen_mentions_never_start_a_note_cooldown(self):
        """Mentions from thread posts (they carry `msg`) and other event types do not count - replies notify every time."""
        recent = [
            note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0, msg=3),
            dict(note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0), type="assigned"),
            dict(note_ev(A_LOGIN, [B_LOGIN], 7, ts=1000.0), type="replied"),
        ]
        self.assertEqual(self.targets(recent, 1001.0), [B_LOGIN])

    def test_records_without_a_usable_time_or_far_from_now_are_ignored(self):
        """A record the rule cannot place in time (missing, non-numeric, boolean) or more than the window away from now on
        either side (the clock stepped back) suppresses nothing."""
        recent = [
            note_ev(A_LOGIN, [B_LOGIN], 7, ts=None),
            note_ev(A_LOGIN, [B_LOGIN], 7, ts="1000"),
            note_ev(A_LOGIN, [B_LOGIN], 7, ts=True),
            note_ev(A_LOGIN, [B_LOGIN], 7, ts=5000.0),
        ]
        self.assertEqual(self.targets(recent, 1001.0), [B_LOGIN])

    def test_a_record_rounded_just_past_now_still_counts(self):
        """events.jsonl stores ts rounded to milliseconds, so the previous mention may read as slightly after `now`."""
        self.assertEqual(self.targets([note_ev(A_LOGIN, [B_LOGIN], 7, ts=1001.0005)], 1001.0), [])


if __name__ == "__main__":
    unittest.main()
