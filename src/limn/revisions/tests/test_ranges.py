"""Comparing two commits (issue #188, docs/adr/0014-two-commit-comparison.md): the optional `base` of the revision
routes, the paged history and its window, and the answers that must not move when `base` is absent.

One deterministic repository (fixed authors and dates, so every SHA is the same on every machine) holds a root commit,
an edit, a commit outside the manuscript, a rename, a side branch merged back with --no-ff and a commit after the
merge. RangeSnapshot drives every request the viewer made before 0.4.18 - each commit's source diff, a pin's scoped
diff, the comparison build's status, POST and PDF, and the refusals - and compares the answers with
tests/data/revision_snapshot.json, recorded from the code before `base` existed: without `base` the bytes stay. A
deliberate change re-records it: LIMN_RECORD_SNAPSHOT=1 uv run pytest -q src/limn/revisions/tests/test_ranges.py.

Run: uv run pytest -q src/limn/revisions/tests/test_ranges.py
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest import mock

from limn.revisions import core as revisions, execution as revision_execution

from helpers_access import REPO_OLD, AccessBase

SNAPSHOT = Path(__file__).resolve().parents[4] / "tests" / "data" / "revision_snapshot.json"
SIDE = "ms/sec/method.tex"


class RangeRepo(AccessBase):
    """The fixed repository of this module and a server pointed at its manuscript folder ms/."""

    def setUp(self):
        """Commit, in order: root (main.tex + sec/method.tex), alpha (two places, a pin on one of them closed with
        the commit), notes (outside the manuscript), rename (sec/method.tex -> sec/methods.tex with one line
        changed), then a branch `feature` with beta, trunk's gamma, the --no-ff merge of feature, and after (filler
        line). self.sha names each commit."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.clock = 0
        self.sha: dict[str, str] = {}
        self.git("init", "--quiet", "--initial-branch=main")
        self.main.write_text(REPO_OLD, encoding="utf-8")
        (self.src / "sec").mkdir()
        (self.repo / SIDE).write_text("Method one.\nMethod two.\nMethod three.\n", encoding="utf-8")
        self.commit("root", "draft", "Alice Kim")
        self.pin_alpha = self.add(lo=4, hi=4, note="alpha")
        self.edit("Alpha paragraph talks about apples.", "Alpha paragraph talks about apricots.")
        self.edit("Filler one.", "Filler one, longer.")
        self.commit("alpha", "alpha and filler", "Bob Park")
        self.call(
            "POST",
            "/api/pins/%d/close" % self.pin_alpha,
            {"ref": self.sha["alpha"][:8], "changes": [{"file": "main.tex", "lo": 4, "hi": 4}]},
        )
        (self.repo / "other").mkdir()
        (self.repo / "other" / "notes.txt").write_text("notes\n", encoding="utf-8")
        self.commit("notes", "notes outside the manuscript", "Alice Kim", paths=("other",))
        self.git("mv", SIDE, "ms/sec/methods.tex")
        (self.repo / "ms/sec/methods.tex").write_text("Method one.\nMethod 2.\nMethod three.\n", encoding="utf-8")
        self.commit("rename", "rename method to methods", "Alice Kim")
        self.git("checkout", "--quiet", "-b", "feature")
        self.edit("Beta paragraph talks about bananas.", "Beta paragraph talks about blueberries.")
        self.commit("beta", "beta on the branch", "Bob Park")
        self.git("checkout", "--quiet", "main")
        self.edit("Gamma paragraph talks about cherries.", "Gamma paragraph talks about cranberries.")
        self.commit("gamma", "gamma on trunk", "Alice Kim")
        self.tick()
        self.git("merge", "--quiet", "--no-ff", "-m", "merge feature", "feature")
        self.sha["merge"] = self.head()
        self.edit("Filler eight.", "Filler eight, reworded.")
        self.commit("after", "after the merge", "Bob Park")

    def env(self, who: str = "Alice Kim") -> dict[str, str]:
        """git's environment with this author and committer and the current fixed clock (2026-09-21 + ticks hours)."""
        when = "2026-09-21T%02d:00:00+09:00" % (8 + self.clock)
        email = who.split()[0].lower() + "@example.com"
        return dict(
            os.environ,
            GIT_AUTHOR_NAME=who,
            GIT_AUTHOR_EMAIL=email,
            GIT_COMMITTER_NAME=who,
            GIT_COMMITTER_EMAIL=email,
            GIT_AUTHOR_DATE=when,
            GIT_COMMITTER_DATE=when,
        )

    def git(self, *args: str, who: str = "Alice Kim") -> str:
        """Run git in the repository at the fixed clock; returns its stdout (a failure raises)."""
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True, env=self.env(who)
        ).stdout

    def tick(self) -> None:
        """Move the fixed clock one hour on, so commits are ordered by time as written."""
        self.clock += 1

    def head(self) -> str:
        """The full SHA-1 of HEAD."""
        return self.git("rev-parse", "HEAD").strip()

    def edit(self, old: str, new: str) -> None:
        """Replace old by new in main.tex, with an mtime ahead so the server sees the file as changed."""
        self.main.write_text(self.main.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        t = time.time() + 5
        os.utime(self.main, (t, t))

    def commit(self, name: str, msg: str, who: str, paths: tuple[str, ...] = ("ms",)) -> str:
        """Commit paths as who at the next tick; records and returns the SHA under name."""
        self.tick()
        self.git("add", *paths, who=who)
        self.git("commit", "--quiet", "-m", msg, who=who)
        self.sha[name] = self.head()
        return self.sha[name]

    def masked(self, data: object) -> object:
        """data as JSON with every known SHA written as <name> (short forms too) and job_id as <KEY>, so a snapshot
        reads as the fixture and does not depend on the temporary folder."""
        if isinstance(data, dict) and "job_id" in data:
            data = dict(data, job_id="<KEY>")
        text = json.dumps(data, ensure_ascii=False)
        for name, sha in self.sha.items():
            text = text.replace(sha, "<%s>" % name).replace(sha[:8], "<%s:8>" % name)
        return json.loads(text)

    def wait_build(self, query: str) -> dict:
        """GET /api/revision-build?<query> until the job is no longer running (5 s at most)."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            code, body = self.call("GET", "/api/revision-build?" + query)
            if code != 200 or body.get("state") != "running":
                return body
            time.sleep(0.01)
        self.fail("revision worker did not finish")


def fake_compile(spec, jobdir, timeout):
    """A comparison build that writes a PDF naming its two sides, instead of latexdiff and latexmk."""
    (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4\n" + spec.base.encode() + b".." + spec.head.encode())
    return revisions.ComparisonBuilt(["fake build"])


class RangeSnapshot(RangeRepo):
    """Every answer without `base` is the one recorded before `base` existed."""

    def test_answers_without_base_are_the_recorded_ones(self):
        """The source diff of every listed commit, the pin's scoped diff, the build status, POST and PDF of every
        commit with a parent, and the refusals - status and body - equal tests/data/revision_snapshot.json; the
        history's rows keep their id, date and subject. LIMN_RECORD_SNAPSHOT=1 re-records."""
        seen = []

        def step(method: str, path: str, body: object | None = None) -> None:
            """Send one request and record its status and masked body under its masked request line."""
            code, out = self.call(method, path, body)
            seen.append({"step": "%s %s" % (method, self.masked(path)), "status": code, "body": self.masked(out)})

        code, history = self.call("GET", "/api/revisions")
        rows = [{k: r[k] for k in ("id", "date", "subject")} for r in history["revisions"]]
        seen.append({"step": "GET /api/revisions", "status": code, "body": self.masked(dict(history, revisions=rows))})
        ids = [r["id"] for r in history["revisions"]]
        for commit in ids:
            step("GET", "/api/revision-diff?commit=" + commit)
        step("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.sha["alpha"], self.pin_alpha))
        step("GET", "/api/revision-diff?commit=" + self.sha["notes"])
        step("GET", "/api/revision-diff?commit=HEAD")
        step("POST", "/api/revision-build", {"commit": self.sha["root"]})
        with mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile):
            for commit in ids[:-1]:
                step("GET", "/api/revision-build?commit=" + commit)
                step("GET", "/api/revision-pdf?commit=" + commit)
                code, out = self.call("POST", "/api/revision-build", {"commit": commit})
                seen.append(
                    {
                        "step": self.masked("POST build " + commit),
                        "status": code,
                        "body": self.masked({"base": out["base"]}),
                    }
                )
                seen.append(
                    {"step": self.masked("status " + commit), "body": self.masked(self.wait_build("commit=" + commit))}
                )
                code, _ = self.call("GET", "/api/revision-pdf?commit=" + commit)
                seen.append(
                    {"step": self.masked("pdf " + commit), "status": code, "body": self.masked(self.last_body_text)}
                )
            pin_query = "commit=%s&pin=%d" % (self.sha["alpha"], self.pin_alpha)
            code, out = self.call("POST", "/api/revision-build", {"commit": self.sha["alpha"], "pin": self.pin_alpha})
            kept = {k: out[k] for k in ("base", "head", "scope", "pin", "source", "hunks", "other")}
            seen.append({"step": "POST build <alpha> pin", "status": code, "body": self.masked(kept)})
            seen.append({"step": "status <alpha> pin", "body": self.masked(self.wait_build(pin_query))})
            step("GET", "/api/revision-pdf?" + pin_query)
        if os.environ.get("LIMN_RECORD_SNAPSHOT") == "1":
            SNAPSHOT.write_text(json.dumps(seen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual([s["step"] for s in seen], [s["step"] for s in recorded])
        for got, want in zip(seen, recorded, strict=True):
            self.assertEqual(got, want, got["step"])

    def call(self, method, path, body=None, headers=None, peer="127.0.0.1", token=None):
        """AccessBase.call, keeping a PDF answer's text in self.last_body_text."""
        code, out = super().call(method, path, body, headers, peer, token)
        self.last_body_text = out if isinstance(out, str) else None
        return code, out


class RangeHistory(RangeRepo):
    """GET /api/revisions: rows with author, time and parents, and paging over the document's history window."""

    def test_rows_carry_author_commit_time_and_parents(self):
        """Every row adds author, time (the commit time in ISO 8601) and parents (full SHA-1s, first parent first) to
        id, date and subject; a merge lists both parents, the root none."""
        code, body = self.call("GET", "/api/revisions")
        self.assertEqual(code, 200)
        rows = {r["id"]: r for r in body["revisions"]}
        after, merge, root = rows[self.sha["after"]], rows[self.sha["merge"]], rows[self.sha["root"]]
        self.assertEqual(list(after)[:3], ["id", "date", "subject"])
        self.assertEqual((after["author"], after["time"]), ("Bob Park", "2026-09-21T16:00:00+09:00"))
        self.assertEqual(after["parents"], [self.sha["merge"]])
        self.assertEqual(merge["parents"], [self.sha["gamma"], self.sha["beta"]])
        self.assertEqual(root["parents"], [])
        self.assertEqual(
            rows[self.sha["rename"]]["parents"], [self.sha["notes"]]
        )  # the true parent, not the listed one

    def test_without_paging_the_answer_keeps_its_two_keys_and_twelve_rows(self):
        """No before or limit: {available, revisions} with the 12 most recent rows, as before paging existed."""
        for n in range(8):
            self.edit("\\end{document}", "%% more %d\n\\end{document}" % n)
            self.commit("more%d" % n, "more %d" % n, "Alice Kim")
        code, body = self.call("GET", "/api/revisions")
        self.assertEqual((code, sorted(body)), (200, ["available", "revisions"]))
        self.assertEqual(len(body["revisions"]), 12)

    def test_pages_follow_before_and_limit_and_say_whether_more_remain(self):
        """limit=n gives the n newest rows and more; before=<id> continues after that row; the last page has
        more: false."""
        code, first = self.call("GET", "/api/revisions?limit=3")
        self.assertEqual(code, 200)
        ids = [r["id"] for r in first["revisions"]]
        self.assertEqual(ids, [self.sha["after"], self.sha["merge"], self.sha["gamma"]])
        self.assertTrue(first["more"])
        code, second = self.call("GET", "/api/revisions?before=%s&limit=3" % ids[-1])
        self.assertEqual([r["id"] for r in second["revisions"]], [self.sha[n] for n in ("beta", "rename", "alpha")])
        self.assertTrue(second["more"])
        code, last = self.call("GET", "/api/revisions?before=%s&limit=3" % self.sha["alpha"])
        self.assertEqual(([r["id"] for r in last["revisions"]], last["more"]), ([self.sha["root"]], False))

    def test_paging_refusals(self):
        """A limit outside 1..50 or not a number is 400 bad_limit; a malformed before is 400 bad_commit; a before
        outside the document's history is 404 commit_not_recent."""
        for bad in ("0", "51", "x", "-1"):
            code, body = self.call("GET", "/api/revisions?limit=" + bad)
            self.assertEqual((code, body["reason"]), (400, "bad_limit"), bad)
        code, body = self.call("GET", "/api/revisions?before=HEAD")
        self.assertEqual((code, body["reason"]), (400, "bad_commit"))
        code, body = self.call("GET", "/api/revisions?before=" + self.sha["notes"])
        self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_the_window_reaches_past_the_twelve_newest(self):
        """A commit older than the 12 newest is still listed on a later page and can be diffed (the window is
        REVISION_HISTORY_MAX commits)."""
        for n in range(12):
            self.edit("\\end{document}", "%% more %d\n\\end{document}" % n)
            self.commit("more%d" % n, "more %d" % n, "Alice Kim")
        code, body = self.call("GET", "/api/revisions?before=%s&limit=50" % self.sha["more0"])
        self.assertIn(self.sha["alpha"], [r["id"] for r in body["revisions"]])
        code, body = self.call("GET", "/api/revision-diff?commit=" + self.sha["alpha"])
        self.assertEqual(code, 200, body)
        self.assertIn("+Alpha paragraph talks about apricots.", body["diff"])


class RangeSourceDiff(RangeRepo):
    """GET /api/revision-diff with base: the cumulative diff between two commits of the document's history."""

    def diff(self, base: str, commit: str):
        """GET /api/revision-diff?commit=<commit>&base=<base> -> (status, body)."""
        return self.call("GET", "/api/revision-diff?commit=%s&base=%s" % (self.sha[commit], self.sha[base]))

    def test_a_range_is_the_cumulative_diff_with_renames_paired(self):
        """base=alpha, commit=after: git diff -M alpha after over the manuscript, the rename as one file with its
        changed line, the count of manuscript commits in between and the changed files with their line counts."""
        code, body = self.diff("alpha", "after")
        self.assertEqual(code, 200, body)
        want = self.git("diff", "-M", "--unified=3", self.sha["alpha"], self.sha["after"], "--", "ms")
        self.assertEqual(body["diff"], want)
        self.assertIn("rename from ms/sec/method.tex", body["diff"])
        self.assertEqual((body["id"], body["base"], body["truncated"]), (self.sha["after"], self.sha["alpha"], False))
        self.assertNotIn("merge_base", body)
        self.assertEqual(body["commits"], 5)  # rename, beta, gamma, merge, after
        self.assertEqual(
            body["files"],
            [
                {"path": "ms/main.tex", "add": 3, "del": 3},
                {"path": "ms/sec/methods.tex", "old_path": "ms/sec/method.tex", "add": 1, "del": 1},
            ],
        )

    def test_base_may_be_the_first_parent_of_a_listed_commit(self):
        """'From this commit' sends the commit's first parent as base, even when that parent is not itself in the
        manuscript history (notes only touched other/): the range then includes the commit."""
        code, body = self.diff("notes", "rename")
        self.assertEqual(code, 200, body)
        self.assertEqual((body["base"], body["commits"]), (self.sha["notes"], 1))
        self.assertIn("rename to ms/sec/methods.tex", body["diff"])

    def test_a_base_after_the_head_is_refused(self):
        """base newer than commit (a descendant of it) is 422 base_after_head: the server never swaps the ends."""
        code, body = self.diff("after", "alpha")
        self.assertEqual((code, body["reason"]), (422, "base_after_head"))
        self.assertIn("error", body)

    def test_a_side_branch_base_is_compared_from_the_merge_base(self):
        """beta (on the branch) is not an ancestor of gamma (on trunk): the old side is their merge base, and the
        answer names it in base and merge_base."""
        code, body = self.diff("beta", "gamma")
        self.assertEqual(code, 200, body)
        self.assertEqual((body["base"], body["merge_base"]), (self.sha["rename"], self.sha["rename"]))
        self.assertEqual(body["diff"], self.git("diff", "-M", self.sha["rename"], self.sha["gamma"], "--", "ms"))
        self.assertEqual(body["commits"], 1)

    def test_base_equal_to_commit_is_an_empty_range(self):
        """base == commit answers an empty diff with commits 0 and no files."""
        code, body = self.diff("gamma", "gamma")
        self.assertEqual(code, 200, body)
        self.assertEqual((body["diff"], body["commits"], body["files"]), ("", 0, []))

    def test_a_base_outside_the_history_is_not_read(self):
        """A commit neither in the document's history nor a first parent of one is 404 commit_not_recent - however
        valid a Git object it is."""
        self.git("checkout", "--quiet", "-b", "elsewhere", self.sha["notes"])
        (self.repo / "other" / "notes.txt").write_text("elsewhere\n", encoding="utf-8")
        self.commit("elsewhere", "elsewhere", "Alice Kim", paths=("other",))
        self.git("checkout", "--quiet", "main")
        code, body = self.diff("elsewhere", "after")
        self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_malformed_base_and_base_with_pin_are_400(self):
        """A base that is not a full SHA-1 is 400 bad_commit; base and pin together are 400 pin_with_base on every
        revision route (phase 1 does not scope a range to a pin)."""
        code, body = self.call("GET", "/api/revision-diff?commit=%s&base=HEAD" % self.sha["after"])
        self.assertEqual((code, body["reason"]), (400, "bad_commit"))
        both = "commit=%s&base=%s&pin=%d" % (self.sha["after"], self.sha["alpha"], self.pin_alpha)
        for path in ("/api/revision-diff?", "/api/revision-build?", "/api/revision-pdf?"):
            code, body = self.call("GET", path + both)
            self.assertEqual((code, body["reason"]), (400, "pin_with_base"), path)
        code, body = self.call(
            "POST",
            "/api/revision-build",
            {"commit": self.sha["after"], "base": self.sha["alpha"], "pin": self.pin_alpha},
        )
        self.assertEqual((code, body["reason"]), (400, "pin_with_base"))

    def test_an_empty_base_is_the_single_commit_answer(self):
        """base= (empty) is absent: the single-commit answer, byte for byte."""
        plain = self.call("GET", "/api/revision-diff?commit=" + self.sha["after"])
        empty = self.call("GET", "/api/revision-diff?commit=%s&base=" % self.sha["after"])
        self.assertEqual(plain, empty)
