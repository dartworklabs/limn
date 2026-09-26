"""limn.pull - the pure rules of --git-pull and the remote-main watch, driven with plain values.

The pull against real repositories is tests/test_gitsync.py, and so is the server wiring (GET /api/meta's sync, a
build's pull) at its end. This file pins each rule, the outcome records of the agent contract, and the import boundary.

Run: uv run pytest -q tests/test_pull.py
"""
import ast
import typing
import unittest
from pathlib import Path

from limn import pull
from limn.pull import (
    Building, Built, Pulled, PullFailed, PullSkipped, UpToDate, after_pull, behind, deferred, fetch_failure, head_of,
    is_dirty, merged, needs_rebuild, pull_record, repo_top, settled, sync_state, tracks_main, unexpected,
)

A, B = "a" * 40, "b" * 40


class ModuleBoundary(unittest.TestCase):
    """limn.pull decides; it runs nothing."""

    def test_imports_nothing_effectful(self):
        """Only typing, dataclasses and collections.abc: no subprocess, file, clock, thread or HTTP import, no limn."""
        tree = ast.parse(Path(pull.__file__).read_text(encoding="utf-8"))
        modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertLessEqual(modules, {"__future__", "collections.abc", "dataclasses", "typing"})

    def test_refusal_set_names_the_two_refusals(self):
        """PullRefusal is the skipped and the failed pull; PullOutcome adds the two successes."""
        self.assertEqual(set(typing.get_args(pull.PullRefusal)), {PullSkipped, PullFailed})
        self.assertEqual(set(typing.get_args(pull.PullOutcome)), {Pulled, UpToDate, PullSkipped, PullFailed})


class Records(unittest.TestCase):
    """pull_record(): the {"state", "reason", "head_before", "head_after"} object of the agent contract."""

    def test_each_outcome_writes_its_state_reason_and_heads_in_contract_order(self):
        """ok/up_to_date carry no reason; a refusal keeps HEAD on both sides; keys in the old order."""
        cases = [
            (Pulled(A, B), {"state": "ok", "reason": None, "head_before": A, "head_after": B}),
            (Pulled(None, B), {"state": "ok", "reason": None, "head_before": None, "head_after": B}),
            (UpToDate(A), {"state": "up_to_date", "reason": None, "head_before": A, "head_after": A}),
            (PullSkipped("not_git", None), {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None}),
            (PullSkipped("dirty", A), {"state": "skipped", "reason": "dirty", "head_before": A, "head_after": A}),
            (PullFailed("fetch_timeout", A), {"state": "error", "reason": "fetch_timeout", "head_before": A, "head_after": A}),
        ]
        for outcome, record in cases:
            with self.subTest(outcome=outcome):
                got = pull_record(outcome)
                self.assertEqual(got, record)
                self.assertEqual(list(got), ["state", "reason", "head_before", "head_after"])


class ReadingGit(unittest.TestCase):
    """What each git answer means for the pull."""

    def test_repo_top_needs_success_and_a_path(self):
        """The stripped root on success; None when git refused, could not run, or printed nothing."""
        self.assertEqual(repo_top(0, "/r/repo\n"), "/r/repo")
        self.assertIsNone(repo_top(128, "fatal"))
        self.assertIsNone(repo_top(None, ""))
        self.assertIsNone(repo_top(0, "  \n"))

    def test_head_of_is_none_unless_git_succeeded(self):
        """rev-parse HEAD on an empty repository (or a git that could not run) gives no head."""
        self.assertEqual(head_of(0, A + "\n"), A)
        self.assertIsNone(head_of(128, ""))
        self.assertIsNone(head_of(None, ""))

    def test_fetch_failure_tells_timeout_from_error(self):
        """rc None (timeout or no git) is fetch_timeout, any other failure fetch_failed; success is no failure."""
        self.assertIsNone(fetch_failure(0, A))
        self.assertEqual(fetch_failure(None, A), PullFailed("fetch_timeout", A))
        self.assertEqual(fetch_failure(1, None), PullFailed("fetch_failed", None))

    def test_tracks_main_needs_branch_main_and_a_main_upstream(self):
        """Only branch main tracking some remote's main passes; a detached HEAD (rc 1) or another branch does not."""
        self.assertTrue(tracks_main(0, "main\n", "origin/main\n"))
        self.assertTrue(tracks_main(0, "main", "upstream/main"))
        self.assertFalse(tracks_main(0, "feature", "origin/feature"))
        self.assertFalse(tracks_main(0, "main", "origin/develop"))
        self.assertFalse(tracks_main(1, "", "origin/main"))

    def test_dirty_means_a_listed_change(self):
        """Any porcelain line is dirty; blank output is clean."""
        self.assertTrue(is_dirty(" M f.txt\n"))
        self.assertFalse(is_dirty("\n"))

    def test_merged_compares_head_before_and_after(self):
        """A moved HEAD is Pulled; the same HEAD, or one that cannot be read after the merge, is UpToDate."""
        self.assertEqual(merged(A, 0, B + "\n"), Pulled(A, B))
        self.assertEqual(merged(A, 0, A), UpToDate(A))
        self.assertEqual(merged(A, 128, ""), UpToDate(A))
        self.assertEqual(merged(None, 128, ""), UpToDate(None))
        self.assertEqual(merged(None, 0, B), Pulled(None, B))


class Watch(unittest.TestCase):
    """The remote-main watch's status and what a round does next."""

    def test_sync_state_per_outcome(self):
        """updated, current, blocked, error - one per outcome type."""
        self.assertEqual([sync_state(o) for o in (Pulled(A, B), UpToDate(A), PullSkipped("diverged", A),
                                                  PullFailed("status_failed", A))],
                         ["updated", "current", "blocked", "error"])

    def test_after_pull_is_the_record_with_watch_state_and_time(self):
        """The pull's record, its state replaced by the watch's, checked_at last."""
        got = after_pull(PullSkipped("not_main", A), "2026-09-26T10:00:00+09:00")
        self.assertEqual(got, {"state": "blocked", "reason": "not_main", "head_before": A, "head_after": A,
                               "checked_at": "2026-09-26T10:00:00+09:00"})
        self.assertEqual(list(got), ["state", "reason", "head_before", "head_after", "checked_at"])

    def test_deferred_and_unexpected_are_merged_fields(self):
        """Both set state, reason and checked_at only, so the previous heads stay when merged."""
        self.assertEqual(deferred("t"), {"state": "deferred", "reason": "building", "checked_at": "t"})
        self.assertEqual(unexpected("t"), {"state": "error", "reason": "unexpected", "checked_at": "t"})

    def test_behind_reads_short_ids_and_missing_builds(self):
        """No head.txt, a build outside git ("-") or another commit is behind; a prefix of head is not."""
        self.assertTrue(behind(B, ""))
        self.assertTrue(behind(B, "-"))
        self.assertTrue(behind(B, "aaaaaaa"))
        self.assertFalse(behind(B, "bbbbbbb"))

    def test_needs_rebuild_after_a_fast_forward_or_when_behind(self):
        """Pulled rebuilds everything; UpToDate only what is behind; a refusal nothing."""
        self.assertTrue(needs_rebuild(Pulled(A, B), B, "bbbbbbb"))
        self.assertTrue(needs_rebuild(UpToDate(B), B, "aaaaaaa"))
        self.assertFalse(needs_rebuild(UpToDate(B), B, "bbbbbbb"))
        self.assertFalse(needs_rebuild(PullSkipped("dirty", A), A, ""))
        self.assertFalse(needs_rebuild(PullFailed("fetch_failed", A), A, ""))

    def test_settled_waits_for_every_document(self):
        """A running build or a document behind without a failure keeps "updating" (None)."""
        self.assertIsNone(settled(B, [Building()]))
        self.assertIsNone(settled(B, [Built("bbbbbbb", False), Built("aaaaaaa", False)]))

    def test_settled_current_when_all_built_from_head(self):
        """Every document built from the commit settles "current", even one whose older build failed."""
        self.assertEqual(settled(B, [Built("bbbbbbb", True)]), {"state": "current", "reason": None})
        self.assertEqual(settled(B, []), {"state": "current", "reason": None})

    def test_settled_error_when_a_document_behind_failed(self):
        """A document still behind with a failed build settles error/build_failed, even beside a running one."""
        self.assertEqual(settled(B, [Building(), Built("aaaaaaa", True)]), {"state": "error", "reason": "build_failed"})


if __name__ == "__main__":
    unittest.main()
