"""Every declared read must preserve persistent trees, even when old GET upkeep would have work to do."""

import ast
import dataclasses
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from unittest import mock

from limn.builds import artifacts
from limn.pins.maintenance import PinMaintenance
from limn.platform import files, git as gitrun
from limn.platform.diagnostics import BoundedDiagnostics
from limn.platform.effects import reading
from limn.security import access
from limn.security.access import READ_PATHS
from limn.web.app import RouteRegistry
from limn.web.routes import RouteBundle

from helpers import Base, add_pin, blank_png, minimal_pdf, ps, req, set_config, split_resp
from helpers_access import A_LOGIN, ALICE, B_LOGIN, BOB, C_LOGIN, CAROL, ScopedRepo, configure, member_add, token_create

FAMILIES = {
    "/api/pins/1",
    "/pages/page-1.png",
    "/vendor/pdfjs/pdf.min.mjs",
    "/vendor/markdown-it/markdown-it.esm.min.mjs",
    "/vendor/pretendard/pretendard.css",
}


def tree(root: Path):
    """Snapshot bytes, inode and nanosecond mtime of every file and directory, without following links."""
    return {
        str(p.relative_to(root)): (
            p.lstat().st_ino,
            p.lstat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).digest() if p.is_file() else None,
        )
        for p in [root, *sorted(root.rglob("*"))]
        if not p.is_symlink()
    }


class TestReadContract(Base):
    """Exercise real route dispatch with conditionally dirty state, never a mocked store."""

    def response(self, method, path, body=None, headers=None):
        """Send a real handler request and retain binary replies as bytes."""
        headers = dict(headers or {})
        raw = b"" if body is None else json.dumps(body).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        return split_resp(self.talk(req(method, path, raw, headers)))

    @property
    def state(self):
        """Use the state directory of this isolated application fixture."""
        return ps.APP.C.state

    def dirty(self):
        """Seed stale/moved/legacy anchors, damaged JSONL, expired Trash and a live shadow."""
        pin = add_pin(
            {"file": str(self.src / "main.tex"), "lo": 4, "hi": 4, "note": "note"}, {"login": A_LOGIN, "name": "Reader"}
        )
        row = pin.record
        legacy = dict(row, id=2)
        legacy.pop("anchor", None)
        legacy.pop("synced_at", None)
        (self.state / "pins.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(legacy) + "\ninvalid\n")
        (self.state / "pins.dropped.jsonl").write_text(
            json.dumps(dict(row, dropped_at="2000-01-01T00:00:00+00:00"))
            + "\n"
            + json.dumps(dict(row, id=99, dropped_at="2000-01-01T00:00:00+00:00"))
            + "\n"
        )
        main = self.src / "main.tex"
        main.write_text("% moved\n" + main.read_text())
        os.utime(main, (2000000000, 2000000000))

    def test_all_registered_reads_preserve_trees(self):
        """GET/HEAD × identity × metadata × routes preserve bytes/inodes/mtimes and schedule no work."""
        self.dirty()
        member_add(self.state, A_LOGIN, "owner")
        member_add(self.state, B_LOGIN, "viewer")
        member_add(self.state, C_LOGIN, "editor")
        _, token = token_create(self.state, "reader")
        identities = (
            ALICE,
            BOB,
            CAROL,
            {"Authorization": "Bearer " + token},
            {"Tailscale-User-Login": "refused@example.com"},
        )
        set_config(ps, allow=frozenset({A_LOGIN, B_LOGIN, C_LOGIN}))
        paths = sorted(READ_PATHS | FAMILIES) + [
            "/api/pins/999",
            "/api/meta?light=1",
            "/api/meta?after=bad",
            "/api/pins/" + "9" * 5000,
        ]
        pages = artifacts.cur_pages(ps.APP.docs[0])
        pages.mkdir(parents=True, exist_ok=True)
        (pages / ps.APP.docs[0].pdf_name).write_bytes(minimal_pdf())
        (pages / "page-1.png").write_bytes(blank_png(10, 10))
        from limn.administration import serve_documents

        (self.src / "notes.md").write_text("# Notes\n\nA paragraph.\n")
        notes = serve_documents.make_docs(["notes=Notes:notes.md"], self.src, ps.APP.C)
        ps.APP.set_docs([ps.APP.docs[0], *notes])
        paths += [
            "/pdf",
            "/pages/page-1.png",
            "/api/source?doc=notes",
            "/api/snippet?file=" + str(self.main) + "&lo=4&hi=5",
            "/api/overlaps?file=" + str(self.main) + "&lo=4&hi=5",
        ]
        before = tree(self.state), tree(self.src)
        with (
            mock.patch.object(type(ps.APP.RT), "start_thread", side_effect=AssertionError("GET scheduled work")),
            mock.patch.object(
                type(ps.APP.assembly.builds.commands), "build_async", side_effect=AssertionError("GET build")
            ),
        ):
            for root_exists in (False, True):
                if root_exists:
                    (self.state / "revisions").mkdir()
                    before = tree(self.state), tree(self.src)
                for identity in identities:
                    for site in (None, "cross-site", "same-site", "same-origin", "none"):
                        headers = dict(identity, **({"Sec-Fetch-Site": site} if site else {}))
                        for method in ("GET", "HEAD"):
                            for path in paths:
                                with self.subTest(method=method, path=path[:80], identity=identity is ALICE, site=site):
                                    status, _, _ = self.response(
                                        method, path, headers={**headers, "If-None-Match": "*"}
                                    )
                                    self.assertNotEqual(status, 500)
                                    if method == "GET" and path in (
                                        "/",
                                        "/api/meta",
                                        "/api/pins",
                                        "/pins.md",
                                        "/api/people",
                                    ):
                                        self.assertEqual(status, 403 if identity is identities[-1] else 200)
                                    if (
                                        method == "GET"
                                        and path in ("/pdf", "/pages/page-1.png")
                                        and identity is not identities[-1]
                                    ):
                                        self.assertEqual(status, 304)
                                    if (
                                        method == "GET"
                                        and path.startswith(
                                            ("/api/source?doc=notes", "/api/snippet?", "/api/overlaps?")
                                        )
                                        and identity is not identities[-1]
                                    ):
                                        self.assertEqual(status, 200)
                                    self.assertEqual((tree(self.state), tree(self.src)), before)

    def test_registered_route_errors_preserve_trees_and_deduplicate_tracebacks(self):
        """Every route's 500 path is read-only too, and repeated identical failures print one traceback."""
        self.dirty()
        member_add(self.state, B_LOGIN, "viewer")
        _, token = token_create(self.state, "reader")
        set_config(ps, allow=frozenset({A_LOGIN, B_LOGIN}))
        original = ps.Handler.app

        def broken(request):
            """Inject an infrastructure failure before the feature reply."""
            raise RuntimeError("repeatable failure")

        ps.Handler.app = dataclasses.replace(original, routes=RouteRegistry(RouteBundle(get=(broken,))))
        self.addCleanup(setattr, ps.Handler, "app", original)
        before = tree(self.state), tree(self.src)
        import io
        from contextlib import redirect_stderr

        stderr = io.StringIO()
        with mock.patch("limn.web.handler.diagnostics", BoundedDiagnostics()), redirect_stderr(stderr):
            for headers in (
                ALICE,
                BOB,
                {"Authorization": "Bearer " + token},
                {"Tailscale-User-Login": "refused@example.com"},
            ):
                for path in sorted(READ_PATHS | FAMILIES):
                    self.assertEqual(
                        self.response("GET", path, headers=headers)[0],
                        403 if headers.get("Tailscale-User-Login") == "refused@example.com" else 500,
                    )
                    self.assertEqual((tree(self.state), tree(self.src)), before)
        self.assertEqual(stderr.getvalue().count("Traceback"), 1)

    def test_read_cannot_obtain_writer_or_schedule(self):
        """Even a regressed GET collaborator cannot obtain the writer, atomic writer or worker scheduler."""
        with reading():
            self.assertFalse(hasattr(ps.APP.assembly.pins.commands.pin_reader(), "transact"))
            for action in (
                ps.APP.pin_store,
                lambda: files.atomic_write(self.state / "forbidden", "bad"),
                lambda: ps.APP.RT.start_thread(lambda: None),
                lambda: ps.APP.assembly.builds.commands.build_async(ps.APP.docs[0]),
            ):
                with self.assertRaises(PermissionError):
                    action()

    def test_http_boundary_denies_writers_captured_by_get_routes(self):
        """A future GET accidentally capturing a factory or an old writer fails before archive/file changes."""
        self.dirty()
        original = ps.Handler.app
        writer = ps.APP.pin_store()
        before = tree(self.state), tree(self.src)
        try:
            for action in (ps.APP.pin_store, writer.clear):

                def regressed(request, action=action):
                    """Try a forbidden effect through the real HTTP boundary, ignoring any query flag."""
                    self.assertFalse(hasattr(request, "record_person"))
                    action()
                    raise AssertionError("GET obtained writer")

                ps.Handler.app = dataclasses.replace(original, routes=RouteRegistry(RouteBundle(get=(regressed,))))
                self.assertEqual(self.response("GET", "/api/pins?read_only=0", headers=ALICE)[0], 500)
                self.assertEqual((tree(self.state), tree(self.src)), before)
        finally:
            ps.Handler.app = original

    def test_person_only_after_real_post(self):
        """Opening and refused/missing actions do not register a reader; a saved pin does."""
        for path in ("/", "/api/meta"):
            self.assertEqual(self.response("GET", path, headers=ALICE)[0], 200)
        self.assertFalse((self.state / "people.json").exists())
        self.response("POST", "/api/pins/999/drop", {}, headers=ALICE)
        self.response("POST", "/api/pin", {"note": "bad", "lo": -1}, headers=ALICE)
        self.assertFalse((self.state / "people.json").exists())
        status, _, _ = self.response(
            "POST", "/api/pin", {"file": str(self.src / "main.tex"), "lo": 4, "hi": 4, "note": "saved"}, headers=ALICE
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads((self.state / "people.json").read_text())["people"][0]["login"], A_LOGIN)

    def test_synchronous_rebuild_records_the_person_after_publication(self):
        """A synchronous rebuild POST that publishes new state registers its human just like a saved pin."""
        from limn.builds.service import BuildRequests
        from limn.builds.values import BuildOk

        def publish(doc, *args, **kwargs):
            """Stand in for the compiler at its owned adapter, publishing a real file to this temporary state."""
            files.atomic_write(self.state / "published-test.txt", "published")
            return BuildOk("", 0.0, None, None, None, "head", "pages", 1)

        with mock.patch.object(BuildRequests, "tracked", side_effect=publish):
            status, _, _ = self.response("POST", "/api/rebuild", {}, headers=ALICE)
        self.assertEqual(status, 200)
        self.assertTrue((self.state / "people.json").exists())
        self.assertEqual(json.loads((self.state / "people.json").read_text())["people"][0]["login"], A_LOGIN)

    def test_maintenance_converges_and_leaves_unchanged_files(self):
        """Independent upkeep saves positions/Markdown, prunes Trash, then leaves identical inodes and mtimes."""
        self.dirty()
        path = self.state / "pins.jsonl"
        path.write_text(path.read_text().replace("invalid\n", ""))
        upkeep = PinMaintenance(ps.APP.pin_store, 30)
        upkeep.run()
        self.assertEqual((self.state / "pins.dropped.jsonl").read_text(), "")
        self.assertEqual(json.loads(path.read_text().splitlines()[0])["lo"], 5)
        before = tree(self.state)
        from datetime import datetime, timedelta

        later = datetime.now().astimezone() + timedelta(minutes=5)
        with mock.patch("limn.pins.listing.markdown.datetime") as clock:
            clock.now.return_value = later
            upkeep.run()
        self.assertEqual(tree(self.state), before)

    def test_maintenance_preserves_originals_on_failure(self):
        """A staging error or later replacement error retains all original bytes and inodes."""
        self.dirty()
        before = tree(self.state)
        with mock.patch("limn.pins.store.replace_files", side_effect=OSError("unavailable")):
            PinMaintenance(ps.APP.pin_store, 30).run()
        self.assertEqual(tree(self.state), before)
        a, b = self.state / "a", self.state / "b"
        a.write_text("old a")
        b.write_text("old b")
        originals = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (a, b)}
        replace = os.replace

        def fail_second(src, dst):
            """Fail only the second publication, allowing restoration of the first original inode."""
            if dst == b:
                raise OSError("replace failed")
            return replace(src, dst)

        with mock.patch("limn.platform.files.os.replace", side_effect=fail_second), self.assertRaises(OSError):
            files.replace_files({a: "new a", b: "new b"})
        self.assertEqual({p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (a, b)}, originals)

    def test_unreadable_manuscript_preserves_legacy_pins_until_retry(self):
        """A failed source read cannot poison a legacy anchor through upkeep, GET, or a POST transaction."""
        if os.geteuid() == 0:
            self.skipTest("root can read chmod 000 manuscripts")
        self.dirty()
        path = self.state / "pins.jsonl"
        # Preserve a valid legacy row and another file's dirty pin to catch partial-batch publication.
        legacy = json.loads(path.read_text().splitlines()[1])
        other = self.src / "other.tex"
        other.write_text(self.main.read_text())
        healthy = dict(legacy, id=3, file=str(other), file_rel="other.tex")
        path.write_text(json.dumps(healthy) + "\n" + json.dumps(legacy) + "\n")
        upkeep = PinMaintenance(ps.APP.pin_store, 30)
        mode = self.main.stat().st_mode
        self.main.chmod(0)
        try:
            before = tree(self.state)
            import io
            from contextlib import redirect_stderr

            stderr = io.StringIO()
            with mock.patch("limn.pins.maintenance.diagnostics", BoundedDiagnostics()), redirect_stderr(stderr):
                upkeep.run()
                upkeep.run()
            self.assertEqual(tree(self.state), before)
            self.assertEqual(stderr.getvalue().count("pin maintenance failed"), 1)
            records = [pin.record for pin in ps.APP.snapshot_pins()]
            self.assertTrue(all("anchor" not in row and "synced_at" not in row for row in records))
            status, _, body = self.response("GET", "/api/pins", headers=ALICE)
            self.assertEqual(status, 200)
            self.assertTrue(all(row.get("anchor") is None and row.get("synced_at") is None for row in json.loads(body)))
            self.assertEqual(tree(self.state), before)
            # Even a later writer cannot save a fabricated empty anchor from a failed resync.
            status, _, post_body = self.response(
                "POST", "/api/pins/2/edit", {"note": "changed", "base_rev": legacy["rev"]}, headers=ALICE
            )
            self.assertEqual(status, 500, post_body)
            self.assertEqual(tree(self.state), before)
        finally:
            self.main.chmod(mode)
        upkeep.run()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertTrue(all(row["anchor"] and row["synced_at"] > 0 for row in rows))

    def test_maintenance_never_overlaps(self):
        """A concurrent pass is skipped, and shutdown wakes a sleeping watcher without a new pass."""
        upkeep = PinMaintenance(ps.APP.pin_store, 30)
        entered, release = threading.Event(), threading.Event()
        from limn.pins.store import PinStore

        maintain = PinStore.maintain

        def held(store, days, now):
            """Hold a real pass at its entry so a simultaneous call must skip it."""
            entered.set()
            assert release.wait(5)
            maintain(store, days, now)

        with mock.patch.object(PinStore, "maintain", autospec=True, side_effect=held) as passes:
            worker = threading.Thread(target=upkeep.run)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                upkeep.run()
                self.assertEqual(passes.call_count, 1)
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
        stop = threading.Event()
        stop.set()
        with mock.patch.object(upkeep, "run") as run:
            upkeep.watch(stop, 0.001)
            run.assert_not_called()
        with (
            mock.patch.object(stop, "wait", side_effect=[False, True]) as wait,
            mock.patch.object(upkeep, "run") as run,
        ):
            upkeep.watch(stop)
            self.assertEqual(wait.call_args_list, [mock.call(60.0), mock.call(60.0)])
            run.assert_called_once_with()

    def test_long_id_and_repeated_error_logs_are_bounded(self):
        """Long ids refuse before int(); identical 500s and damaged-file warnings have bounded output."""
        self.assertEqual(self.response("GET", "/api/pins/" + "9" * 5000, headers=ALICE)[0], 414)
        for length in (21, 1000):
            self.assertEqual(self.response("GET", "/api/pins/" + "9" * length, headers=ALICE)[0], 404)
        self.dirty()
        import io
        from contextlib import redirect_stderr

        stderr_text = io.StringIO()
        with mock.patch("limn.pins.store.diagnostics", BoundedDiagnostics()), redirect_stderr(stderr_text):
            for _ in range(20):
                self.assertEqual(self.response("GET", "/api/pins", headers=ALICE)[0], 200)
        self.assertEqual(stderr_text.getvalue().count("warning: failed to read"), 1)
        sink = BoundedDiagnostics()
        with mock.patch("sys.stderr") as stderr:
            for i in range(1000):
                sink.emit("same", lambda: "failure")
                sink.emit(str(i), lambda: "x" * 20000)
            self.assertLessEqual(sum(len(c.args[0].encode()) for c in stderr.write.call_args_list), 64 * 8193)


class TestComparisonReads(ScopedRepo):
    """Reach comparison cache lookup with a real authorized commit, rather than an invalid-query shortcut."""

    def test_partial_clone_reads_never_fetch_or_refresh_index(self):
        """Missing historic blobs produce existing refusals, never lazy-fetch packs or index refreshes."""
        self.git("config", "uploadpack.allowFilter", "true")
        # A fresh clone per route proves each request preserves a genuinely incomplete object store.
        routes = (
            ("/api/revisions", 200, None),
            ("/api/revision-diff?commit=" + self.fix, 404, "diff_unreadable"),
            ("/api/revision-build?commit=" + self.fix, 200, "idle"),
            ("/api/revision-pdf?commit=" + self.fix, 404, "revision_not_ready"),
            ("/api/meta", 200, None),
            ("/api/docs", 200, None),
        )
        state = ps.APP.C.state
        for i, (route, expected, reason) in enumerate(routes):
            with self.subTest(route=route):
                clone = self.repo / ("partial-%d" % i)
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--quiet",
                        "--no-local",
                        "--no-checkout",
                        "--filter=blob:none",
                        self.repo.as_uri(),
                        str(clone),
                    ],
                    check=True,
                    capture_output=True,
                )
                shutil.copytree(self.src, clone / "ms")
                # Create a real index without checking out/fetching any missing blobs.
                subprocess.run(["git", "reset", "--quiet", "HEAD"], cwd=clone, check=True, capture_output=True)
                missing = subprocess.run(
                    ["git", "rev-list", "--objects", "--all", "--missing=print"],
                    cwd=clone,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                self.assertIn("?", missing)
                configure(ps, clone / "ms", clone / "ms/main.tex", state)
                # Repository configuration cannot reopen a transport for a GET.
                subprocess.run(
                    ["git", "config", "protocol.file.allow", "always"], cwd=clone, check=True, capture_output=True
                )
                before = tree(clone / ".git")
                code, data = self.call("GET", route, headers=ALICE)
                self.assertEqual(tree(clone / ".git"), before)
                self.assertEqual(code, expected, data)
                if reason is not None:
                    self.assertEqual(data["state" if reason == "idle" else "reason"], reason)
                # Also exercise optional index refresh and blob readers through every process adapter.
                with reading():
                    self.assertEqual(gitrun.run_git(["status", "--porcelain"], clone, 10).returncode, 0)
                    self.assertNotEqual(gitrun.git(["cat-file", "-p", self.fix + ":ms/main.tex"], clone)[0], 0)
                    with gitrun.open_git(["blame", self.fix, "--", "ms/main.tex"], clone) as proc:
                        proc.communicate(timeout=10)
                        self.assertNotEqual(proc.returncode, 0)
                    from limn.revisions.core import git_exec

                    self.assertNotEqual(git_exec(["show", self.fix + ":ms/main.tex"], clone, 10, 4096)[0], 0)
                self.assertEqual(tree(clone / ".git"), before)
                if route == "/api/revisions":
                    self.assertIn(self.fix, [row["id"] for row in data["revisions"]])

    def test_absent_and_existing_root_are_read_only(self):
        """Status is idle without mkdir; PDF retains not-ready, including an existing empty root."""
        root = ps.APP.docs[0].dir / "revisions"
        for phase in ("missing", "empty", "ready"):
            if phase == "empty":
                root.mkdir()
            if phase == "ready":
                from helpers import revision_spec

                key = revision_spec(self.fix).key
                job = root / key
                job.mkdir()
                (job / "status.json").write_text(json.dumps({"state": "ready"}))
                (job / "revision.pdf").write_bytes(minimal_pdf())
            before = tree(ps.APP.C.state), tree(self.src)
            with mock.patch("limn.revisions.jobs._start_job", side_effect=AssertionError("GET scheduled build")):
                code, status = self.call("GET", "/api/revision-build?commit=" + self.fix, headers=ALICE)
                self.assertEqual((code, status["state"]), (200, "ready" if phase == "ready" else "idle"))
                raw = self.talk(req("GET", "/api/revision-pdf?commit=" + self.fix, headers=ALICE))
                code, _, body = split_resp(raw)
                self.assertEqual(code, 200 if phase == "ready" else 404)
                if phase != "ready":
                    self.assertEqual(json.loads(body)["reason"], "revision_not_ready")
            self.assertEqual((tree(ps.APP.C.state), tree(self.src)), before)


def test_read_route_family_inventory():
    """An added allowed resource family requires a test representative; exact paths come directly from READ_PATHS."""
    source = ast.parse(inspect.getsource(access.check_read))
    prefixes = {
        arg.value
        for node in ast.walk(source)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith"
        for seq in node.args
        if isinstance(seq, ast.Tuple)
        for arg in seq.elts
        if isinstance(arg, ast.Constant)
    }
    assert prefixes == {"/pages/", "/vendor/pdfjs/", "/vendor/markdown-it/", "/vendor/pretendard/"}
    assert all(any(path.startswith(prefix) for path in FAMILIES) for prefix in prefixes)


def test_nested_read_scope_property():
    """Generated nested read scopes can never obtain effects, and always restore the outer scope."""
    from contextlib import ExitStack

    from hypothesis import given, strategies as st

    from limn.platform.effects import require_writer

    @given(st.integers(min_value=1, max_value=40))
    def check(depth):
        """Any depth denies writers while entered and restores the thread's previous scope on exit."""
        with ExitStack() as stack:
            for _ in range(depth):
                stack.enter_context(reading())
                try:
                    require_writer()
                except PermissionError:
                    pass
                else:
                    raise AssertionError("nested read obtained writer")
        require_writer()

    check()
