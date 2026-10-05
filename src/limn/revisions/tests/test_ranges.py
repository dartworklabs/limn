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

from helpers import ps
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

    def call(self, method, path, body=None, headers=None, peer="127.0.0.1", token=None):
        """AccessBase.call, keeping a PDF answer's text in self.last_body_text."""
        code, out = super().call(method, path, body, headers, peer, token)
        self.last_body_text = out if isinstance(out, str) else None
        return code, out

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
        history's rows keep their id, date and subject (as a set). LIMN_RECORD_SNAPSHOT=1 re-records - from the code
        before `base` (03c5b0e), so the file stays the old answers."""
        seen = []

        def step(method: str, path: str, body: object | None = None) -> None:
            """Send one request and record its status and masked body under its masked request line."""
            code, out = self.call(method, path, body)
            seen.append({"step": "%s %s" % (method, self.masked(path)), "status": code, "body": self.masked(out)})

        code, history = self.call("GET", "/api/revisions")
        # The unpaged list keeps its rows (id, date, subject) but is in ancestry order since 0.4.18 (api.md §두 커밋
        # 사이): compared as a set here; RangeHistory and OneWindow pin its order.
        rows = sorted(
            ({k: r[k] for k in ("id", "date", "subject")} for r in history["revisions"]), key=lambda r: r["id"]
        )
        seen.append({"step": "GET /api/revisions", "status": code, "body": self.masked(dict(history, revisions=rows))})
        ids = [self.sha[n] for n in ("after", "merge", "gamma", "beta", "rename", "alpha", "root")]
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
        more: false. Pages list by ancestry: the merged branch's commit (beta) right below its merge, before trunk's
        gamma, and the unpaged list is the same order (one window, OneWindow)."""
        code, first = self.call("GET", "/api/revisions?limit=3")
        self.assertEqual(code, 200)
        ids = [r["id"] for r in first["revisions"]]
        self.assertEqual(ids, [self.sha["after"], self.sha["merge"], self.sha["beta"]])
        self.assertTrue(first["more"])
        code, second = self.call("GET", "/api/revisions?before=%s&limit=3" % ids[-1])
        self.assertEqual([r["id"] for r in second["revisions"]], [self.sha[n] for n in ("gamma", "rename", "alpha")])
        unpaged = [r["id"] for r in self.call("GET", "/api/revisions")[1]["revisions"]]
        self.assertEqual(unpaged[:3], [self.sha["after"], self.sha["merge"], self.sha["beta"]])
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
        self.assertEqual((body["diff"], body["commits"], body["commit_ids"], body["files"]), ("", 0, [], []))

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


class RangePdf(RangeRepo):
    """The comparison PDF of a range: POST/GET /api/revision-build and GET /api/revision-pdf with base."""

    def range_query(self, base: str, commit: str) -> str:
        """commit=<commit>&base=<base> for two named commits."""
        return "commit=%s&base=%s" % (self.sha[commit], self.sha[base])

    def build(self, base: str, commit: str) -> tuple[int, dict]:
        """POST /api/revision-build for the range base..commit with the fake build -> (status, body) of the POST."""
        return self.call("POST", "/api/revision-build", {"commit": self.sha[commit], "base": self.sha[base]})

    def cache_dir(self, body: dict) -> Path:
        """The cache folder of a status answer's job."""
        return ps.APP.C.state / "revisions" / body["job_id"]

    def test_a_range_build_compares_its_two_ends(self):
        """base=alpha, commit=after: the job's sides are alpha and after, its status says so, the PDF is served for
        the same query, and the cache folder is marked ranged."""
        with mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile):
            code, started = self.build("alpha", "after")
            self.assertEqual(code, 202, started)
            self.assertEqual((started["base"], started["head"]), (self.sha["alpha"], self.sha["after"]))
            status = self.wait_build(self.range_query("alpha", "after"))
        self.assertEqual(status["state"], "ready", status)
        self.assertNotIn("merge_base", status)
        code, _ = self.call("GET", "/api/revision-pdf?" + self.range_query("alpha", "after"))
        self.assertEqual(code, 200)
        self.assertEqual(self.last_body_text, "%PDF-1.4\n" + self.sha["alpha"] + ".." + self.sha["after"])
        self.assertTrue((self.cache_dir(status) / revisions.RANGED_MARK).is_file())

    def test_a_side_branch_range_builds_from_the_merge_base(self):
        """base=beta (on the branch), commit=gamma: the comparison starts at their merge base, named in base and in
        merge_base; merge_base is a field of the request, never stored in the shared status."""
        with mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile):
            code, started = self.build("beta", "gamma")
            self.assertEqual(code, 202, started)
            status = self.wait_build(self.range_query("beta", "gamma"))
        self.assertEqual((status["base"], status["merge_base"]), (self.sha["rename"], self.sha["rename"]))
        stored = json.loads((self.cache_dir(status) / "status.json").read_text(encoding="utf-8"))
        self.assertNotIn("merge_base", stored)

    def test_a_first_parent_base_shares_the_single_commit_comparison(self):
        """A range whose old side is the commit's first parent is the single commit's comparison: same key, found in
        the cache the single-commit request filled, not marked ranged."""
        with mock.patch.object(revision_execution, "revision_compile", side_effect=fake_compile):
            self.call("POST", "/api/revision-build", {"commit": self.sha["after"]})
            single = self.wait_build("commit=" + self.sha["after"])
        code, ranged = self.call("GET", "/api/revision-build?" + self.range_query("merge", "after"))
        self.assertEqual((code, ranged["state"], ranged["job_id"]), (200, "ready", single["job_id"]))
        self.assertFalse((self.cache_dir(single) / revisions.RANGED_MARK).exists())

    def test_the_range_refusals_of_the_build_routes(self):
        """base == commit is 422 empty_range (no comparison to build), base after commit 422 base_after_head, a base
        outside the history 404 commit_not_recent - on POST, the status and the PDF alike."""
        cases = [
            (self.range_query("gamma", "gamma"), 422, "empty_range"),
            (self.range_query("after", "alpha"), 422, "base_after_head"),
            ("commit=%s&base=%s" % (self.sha["after"], "0" * 40), 404, "commit_not_recent"),
        ]
        for query, status, reason in cases:
            commit, base = (part.split("=")[1] for part in query.split("&"))
            code, body = self.call("POST", "/api/revision-build", {"commit": commit, "base": base})
            self.assertEqual((code, body["reason"]), (status, reason), query)
            for path in ("/api/revision-build?", "/api/revision-pdf?"):
                code, body = self.call("GET", path + query)
                self.assertEqual((code, body["reason"]), (status, reason), path + query)

    def test_unrelated_histories_have_no_merge_base(self):
        """A commit from a history merged in with --allow-unrelated-histories shares no ancestor with a trunk commit
        from before that merge: 422 no_merge_base for the source diff and the comparison PDF."""
        self.git("checkout", "--quiet", "--orphan", "loose")
        self.git("rm", "-r", "--quiet", "--cached", ".")
        (self.src / "extra.tex").write_text("Loose text.\n", encoding="utf-8")
        self.commit("loose", "loose history", "Alice Kim", paths=("ms/extra.tex",))
        self.git("clean", "-fdq", "ms/sec")
        self.git("checkout", "--quiet", "-f", "main")
        self.tick()
        self.git("merge", "--quiet", "--allow-unrelated-histories", "-m", "join loose", "loose")
        query = self.range_query("loose", "after")
        code, body = self.call("GET", "/api/revision-diff?" + query)
        self.assertEqual((code, body.get("reason")), (422, "no_merge_base"), body)
        code, body = self.call("GET", "/api/revision-build?" + query)
        self.assertEqual((code, body.get("reason")), (422, "no_merge_base"), body)

    def test_ranged_comparisons_are_counted_apart_and_kept_at_most_four(self):
        """Ranged cache entries have their own limit (REVISION_RANGED_KEEP, 4): many ranges never push out
        single-commit or pin-scoped comparisons, and the oldest ranges go first."""
        from limn.revisions import jobs as revision_jobs

        root = revision_jobs.revision_cache_root(ps.APP.docs[0])
        whole = [root / ("%064x" % i) for i in range(3)]
        scoped = [root / ("%064x" % (50 + i)) for i in range(2)]
        ranged = [root / ("%064x" % (100 + i)) for i in range(revisions.REVISION_RANGED_KEEP + 3)]
        for i, d in enumerate(whole + scoped + ranged):
            d.mkdir()
            if d in scoped:
                (d / revisions.SCOPED_MARK).write_text("")
            if d in ranged:
                (d / revisions.RANGED_MARK).write_text("")
            t = time.time() - 1000 + (500 + i if d in ranged else i)  # every ranged entry is newer
            os.utime(d, (t, t))
        revision_jobs.revision_prune(root, "f" * 64, ps.APP.RT.revision_jobs.active)
        self.assertTrue(all(d.exists() for d in whole + scoped))
        self.assertEqual([d.exists() for d in ranged], [False] * 3 + [True] * revisions.REVISION_RANGED_KEEP)
        self.assertEqual(revisions.REVISION_RANGED_KEEP, 4)


class OneWindow(AccessBase):
    """One order and one set for every path that names commits (review of #188): the unpaged list, the paged list (the
    viewer's), the commits a pin's close_ref is resolved among, and the commits a request may name. The repository has
    a merged side line with dates older than everything on trunk, so date order and ancestry order disagree."""

    def setUp(self):
        """root; side line S1..S3 (dated in January) off root; trunk B1..B10 (September); the --no-ff merge of the
        side line; B11 and B12. A pin on the line S2 changes, closed with S2's hash and that line."""
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not available")
        self.repo = self.src.parent
        self.sha: dict[str, str] = {}
        self.git("2026-09-01T08:00:00+09:00", "init", "--quiet", "--initial-branch=main")
        self.main.write_text("".join("Line %d.\n" % n for n in range(1, 41)), encoding="utf-8")
        self.commit("root", "2026-09-01T08:00:00+09:00")
        self.git("2026-09-01T08:00:00+09:00", "checkout", "--quiet", "-b", "side")
        for n in (1, 2, 3):
            self.edit(30 + n, "Side %d." % n)
            self.commit("S%d" % n, "2026-01-0%dT08:00:00+09:00" % n)
        self.git("2026-09-01T08:00:00+09:00", "checkout", "--quiet", "main")
        for n in range(1, 11):
            self.edit(n, "Trunk %d." % n)
            self.commit("B%d" % n, "2026-09-%02dT08:00:00+09:00" % (n + 1))
        self.git("2026-09-20T08:00:00+09:00", "merge", "--quiet", "--no-ff", "-m", "merge side", "side")
        self.sha["M"] = self.git("2026-09-20T08:00:00+09:00", "rev-parse", "HEAD").strip()
        for n in (11, 12):
            self.edit(n, "Trunk %d." % n)
            self.commit("B%d" % n, "2026-09-%02dT08:00:00+09:00" % (n + 10))
        self.pin = self.add(lo=32, hi=32, note="side two")
        self.call(
            "POST",
            "/api/pins/%d/close" % self.pin,
            {"ref": self.sha["S2"][:8], "changes": [{"file": "main.tex", "lo": 32, "hi": 32}]},
        )

    def git(self, when: str, *args: str) -> str:
        """Run git at the fixed time when (author and committer); its stdout."""
        env = dict(
            os.environ,
            GIT_AUTHOR_DATE=when,
            GIT_COMMITTER_DATE=when,
            GIT_AUTHOR_NAME="Alice Kim",
            GIT_COMMITTER_NAME="Alice Kim",
            GIT_AUTHOR_EMAIL="a@example.com",
            GIT_COMMITTER_EMAIL="a@example.com",
        )
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, text=True, env=env).stdout

    def edit(self, line: int, text: str) -> None:
        """Replace line `line` of main.tex with text."""
        lines = self.main.read_text(encoding="utf-8").splitlines(keepends=True)
        lines[line - 1] = text + "\n"
        self.main.write_text("".join(lines), encoding="utf-8")

    def commit(self, name: str, when: str) -> None:
        """Commit ms/ at when and record the SHA under name."""
        self.git(when, "add", "ms")
        self.git(when, "commit", "--quiet", "-m", name)
        self.sha[name] = self.git(when, "rev-parse", "HEAD").strip()

    def names(self, ids) -> list[str]:
        """The fixture names of ids, in order."""
        back = {v: k for k, v in self.sha.items()}
        return [back.get(i, i[:8]) for i in ids]

    def test_the_lists_share_one_ancestry_order(self):
        """The unpaged answer is the first 12 rows of the paged one, in the same (ancestry) order: the merged line sits
        under its merge although its dates are older than all of trunk."""
        _, unpaged = self.call("GET", "/api/revisions")
        _, paged = self.call("GET", "/api/revisions?limit=50")
        ids = [r["id"] for r in paged["revisions"]]
        self.assertEqual([r["id"] for r in unpaged["revisions"]], ids[:12])
        self.assertEqual(self.names(ids[:6]), ["B12", "B11", "M", "S3", "S2", "S1"])

    def test_a_close_ref_on_the_side_line_is_resolved_among_the_listed_commits(self):
        """S2 is among the first 12 listed commits, so the pin's ref resolves to it and its recorded line is used."""
        code, body = self.call("GET", "/api/revision-diff?commit=%s&pin=%d" % (self.sha["S2"], self.pin))
        self.assertEqual(code, 200, body)
        self.assertEqual(body["scope"]["source"], "changes", body["scope"])

    def test_every_listed_commit_may_be_named(self):
        """With a window of 10, every commit the pages list is accepted and nothing else: the validation window and the
        list are one set."""
        with mock.patch.object(revisions, "REVISION_HISTORY_MAX", 10):
            listed, before = [], ""
            while True:
                _, page = self.call("GET", "/api/revisions?limit=4" + before)
                listed += [r["id"] for r in page["revisions"]]
                if not page["more"]:
                    break
                before = "&before=" + listed[-1]
            self.assertEqual(len(listed), 10)
            for commit in listed:
                code, body = self.call("GET", "/api/revision-diff?commit=" + commit)
                self.assertEqual(code, 200, (self.names([commit]), body))
            unlisted = [c for c in self.sha.values() if c not in listed]
            code, body = self.call("GET", "/api/revision-diff?commit=" + unlisted[0])
            self.assertEqual((code, body["reason"]), (404, "commit_not_recent"))

    def test_the_window_is_read_once_per_head(self):
        """Repeated requests at the same HEAD (a comparison's status poll) read the history once; a new commit reads it
        again."""
        calls = []
        real = revisions._log_rows

        def counted(*args, **kwargs):
            """_log_rows, recording each call."""
            calls.append(args)
            return real(*args, **kwargs)

        with mock.patch.object(revisions, "_log_rows", side_effect=counted):
            for _ in range(3):
                self.assertEqual(self.call("GET", "/api/revision-diff?commit=" + self.sha["B12"])[0], 200)
            self.assertEqual(len(calls), 1)
            self.edit(40, "Last.")
            self.commit("B13", "2026-09-30T08:00:00+09:00")
            self.assertEqual(self.call("GET", "/api/revision-diff?commit=" + self.sha["B13"])[0], 200)
            self.assertEqual(len(calls), 2)


class RangeBodyBase(RangeRepo):
    """POST /api/revision-build's body base is a full SHA-1 string when present (review of #188, api.md)."""

    def test_a_null_or_empty_body_base_is_refused(self):
        """A body base of null or "" is 400 bad_commit - not read as absent - so a body that names base always means
        a range; only the query's empty base= is absent, like pin=."""
        for base in (None, "", 5):
            code, body = self.call("POST", "/api/revision-build", {"commit": self.sha["after"], "base": base})
            self.assertEqual((code, body["reason"]), (400, "bad_commit"), base)


class RangeCommitIds(RangeRepo):
    """A range answer names the document's commits it covers, so the viewer paints what is compared (review of #188)."""

    def test_commit_ids_are_the_ranges_commits_in_ancestry_order(self):
        """commit_ids is `git rev-list --topo-order <old>..<commit>` over the manuscript - for a side-line base, from
        the merge base - and commits is its length; an empty range names none."""
        for base, commit in (("alpha", "after"), ("beta", "gamma"), ("notes", "rename"), ("gamma", "gamma")):
            code, body = self.call("GET", "/api/revision-diff?commit=%s&base=%s" % (self.sha[commit], self.sha[base]))
            self.assertEqual(code, 200, body)
            want = self.git("rev-list", "--topo-order", "%s..%s" % (body["base"], self.sha[commit]), "--", "ms").split()
            self.assertEqual(body["commit_ids"], want, (base, commit))
            self.assertEqual(body["commits"], len(want))
