"""limn.mentions - the pure @-tag rules, driven directly with no server, no file and no clock.

The HTTP flows that use them (notices on add/edit/reply/reopen) are covered in test_server.py, test_v022.py,
test_qa_021.py and test_v031.py; this file pins the rules themselves and the module's import boundary.

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
        """Its imports are typing/collections helpers and limn.pins.edit (for ASSIGNEE_AGENT) - nothing effectful."""
        tree = ast.parse(MENTIONS_PY.read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(modules, {"__future__", "collections", "collections.abc", "typing", "limn.pins.edit"})

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
    """addressed_to()/fyi_mentions_to()/pin_mentions_all() over a pin record and its thread rounds."""

    def test_a_question_pin_addresses_its_round_and_a_fix_pin_only_informs(self):
        """A question's tags are asked; a fix pin's tags are FYI."""
        q = {"kind_req": "question", "mentions": [B]}
        self.assertEqual((addressed_to(q), fyi_mentions_to(q)), ([B], []))
        f = {"kind_req": "fix", "mentions": [B]}
        self.assertEqual((addressed_to(f), fyi_mentions_to(f)), ([], [B]))

    def test_an_assignee_is_addressed_and_the_other_tags_are_fyi(self):
        """A person assignee is asked, every other tag informed; the agent assignee asks nobody."""
        r = {"assignee": B, "mentions": [B, BL]}
        self.assertEqual((addressed_to(r), fyi_mentions_to(r)), ([B], [BL]))
        self.assertEqual(addressed_to({"assignee": "agent", "mentions": [B]}), [])

    def test_the_old_round_does_not_count_after_a_reopen(self):
        """A reply during review (before the reopen) is not part of the new round."""
        r = {"kind_req": "question", "mentions": [], "thread": [
            {"ev": "close"}, {"text": "during review", "mentions": [BL]}, {"ev": "reopen", "mentions": [B]}]}
        self.assertEqual(thread_round(r), [{"ev": "reopen", "mentions": [B]}])
        self.assertEqual(addressed_to(r), [B])
        self.assertEqual(pin_mentions_all(r), [BL, B])

    def test_under_review_the_round_is_everything_after_the_close(self):
        """Closed and not reopened: the posts after the last close; never closed: the whole thread."""
        th = [{"text": "a"}, {"ev": "close"}, {"text": "b"}]
        self.assertEqual(thread_round({"thread": th}), [{"text": "b"}])
        self.assertEqual(thread_round({"thread": [{"text": "a"}, "junk"]}), [{"text": "a"}])
        self.assertEqual(thread_round({"thread": "junk"}), [])


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
        self.assertEqual(note_mention_targets([B], [dict(recent[0], msg=1)], A, 3, 101.0), [B])   # a reply's mention
        self.assertEqual(note_mention_targets([B], [dict(recent[0], ts=True)], A, 3, 101.0), [B])  # not a number


if __name__ == "__main__":
    unittest.main()
