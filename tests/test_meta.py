"""limn.meta and the document lookups of limn.documents, called directly - no server, no run arguments.

GET /api/meta, /api/docs and /api/outline-labels are pinned end to end through the server in test_server.py
(MultiDoc) and, for the light polling and the instance label, at the end of this file through server.py (LightMeta,
InstanceMeta); their bodies were compared byte for byte with the code they came from when they moved. Above them each
read is called
with the document, the document list and the settings as arguments: the modules must not read the server's globals
or import it, and each rule holds on its own - which .aux the outline reads, what the light meta body carries, how
open pins are counted per document, which document a request or a pin belongs to.

Run: uv run pytest -q tests/test_meta.py
"""
import ast
import json
import os
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

from limn import documents, meta
from limn import build as limn_build
from limn import meta as limn_meta
from limn.access import LOCAL_ACTOR
from limn.documents import Doc, DocNotFound
from limn.meta import MetaSettings

from helpers import Base, ps, req

PKG = Path(meta.__file__).parent
SERVER_GLOBALS = {"C", "cur_doc", "using_doc", "DOCS", "LEGACY_DOC", "BUILD_STATE", "BUILD_LOCK"}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (300).to_bytes(4, "big") + (150).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
AUX = "\\@writefile{toc}{\\contentsline {section}{\\numberline {1}Intro}{1}{section.1}}\n"
# The light /api/meta body's keys, in order: the agent contract (docs/handbook/api.md).
LIGHT_KEYS = ["pages", "built_at", "head", "main", "pins_md", "state_dir", "me", "label", "accent", "repo", "building",
              "sync", "doc", "doc_name", "kind", "view_only", "multi", "stale_build", "src_age_s", "src_mtime",
              "build_src_mtime", "pages_build", "pins_rev", "build_seq", "last_build", "build"]


@dataclass
class Paths:
    """The run paths a Doc reads (documents.RunPaths), fixed for one test."""
    src: Path
    main: Path
    state: Path
    build: Path


class Fixture(unittest.TestCase):
    """A manuscript tree with a body (main.tex), a second LaTeX document (rr/rr.tex) and a view-only PDF."""

    def setUp(self):
        """Temp manuscript and state folders; three documents under --doc and the single legacy document."""
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "ms"
        (self.src / "rr").mkdir(parents=True)
        (self.src / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.src / "rr" / "rr.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
        (self.src / "review.pdf").write_bytes(b"%PDF-1.4\n")
        self.state = root / "state"
        self.state.mkdir()
        self.paths = Paths(self.src, self.src / "main.tex", self.state, self.state / "build")
        self.legacy = Doc("main", "본문", legacy=True, paths=self.paths)
        self.ms = Doc("ms", "본문", "tex", self.src, self.src / "main.tex", paths=self.paths)
        self.rr = Doc("rr", "답변서", "tex", self.src / "rr", self.src / "rr" / "rr.tex", paths=self.paths)
        self.rv = Doc("rv", "리뷰", "pdf", self.src, self.src / "review.pdf", paths=self.paths)
        self.settings = MetaSettings(state=self.state, pins_md=self.state / "pins.md", pins_jsonl=self.state / "pins.jsonl",
                                     label="원고", accent="#1d4ed8", repo=None, dpi=150)

    def tearDown(self):
        """Remove the temp folders."""
        self.tmp.cleanup()

    def pages(self, D: Doc, name: str = "pages-20260101000000", aux: str | None = None) -> Path:
        """Put page directory `name` on screen for D with one 300x150 page and, if given, the .aux it published."""
        d = D.dir / name
        d.mkdir(parents=True)
        (d / "page-1.png").write_bytes(PNG)
        if aux is not None:
            (d / (D.main.stem + ".aux")).write_text(aux, encoding="utf-8")
        (D.dir / "pages.cur").write_text(name, encoding="utf-8")
        return d


class NoServerState(unittest.TestCase):
    """The moved reads must not reach the server's run arguments or its document list (R5)."""

    def test_reads_no_server_global_and_never_imports_the_server(self):
        """No name the server keeps as hidden state appears, no `C.` is read, and nothing imports server.py."""
        for name in ("meta.py", "documents.py", "outline.py"):
            with self.subTest(module=name):
                source = (PKG / name).read_text(encoding="utf-8")
                tree = ast.parse(source)
                names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                self.assertEqual(names & SERVER_GLOBALS, set())
                self.assertNotRegex(source, r"(?<![\w.])C\.[a-z_]")
                modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                modules |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
                self.assertFalse({m for m in modules if "server" in m or m.startswith("limn.web")})


class OutlineLabels(Fixture):
    """outline_labels reads only the .aux the build on screen published."""

    def test_reads_the_aux_of_the_build_on_screen(self):
        """The labels come from the page directory named by pages.cur, never the mutable build copy."""
        d = self.pages(self.ms, aux=AUX)
        self.ms.build.mkdir(parents=True)
        (self.ms.build / "main.aux").write_text(AUX.replace("Intro", "Stale"), encoding="utf-8")
        self.assertEqual(meta.outline_labels(self.ms), {"build": d.name, "labels": [
            {"number": "1", "title": "Intro", "page": "1", "level": "section", "anchor": "section.1"}]})

    def test_no_labels_without_an_aux_or_before_any_build(self):
        """A build without .aux, and a document never built (the legacy pages folder), give no labels."""
        self.assertEqual(meta.outline_labels(self.ms), {"build": "pages", "labels": []})
        d = self.pages(self.ms)
        self.assertEqual(meta.outline_labels(self.ms), {"build": d.name, "labels": []})

    def test_no_labels_for_a_view_only_document(self):
        """A PDF has no .aux; even a file of that name is not read."""
        d = self.pages(self.rv, aux=AUX)
        self.assertEqual(meta.outline_labels(self.rv), {"build": d.name, "labels": []})

    def test_symlinked_or_oversized_aux_is_not_read(self):
        """A symlink could point anywhere; a file over AUX_MAX_BYTES is not worth parsing on a poll."""
        d = self.pages(self.ms)
        target = Path(self.tmp.name) / "elsewhere.aux"
        target.write_text(AUX, encoding="utf-8")
        (d / "main.aux").symlink_to(target)
        self.assertEqual(meta.outline_labels(self.ms)["labels"], [])
        (d / "main.aux").unlink()
        with open(d / "main.aux", "w", encoding="utf-8") as fh:
            fh.write(AUX)
            fh.truncate(meta.AUX_MAX_BYTES + 1)
        self.assertEqual(meta.outline_labels(self.ms)["labels"], [])


class Meta(Fixture):
    """meta() is the light /api/meta body; the pin counts are added by the caller from pin_counts()."""

    def test_single_document_body_keys_and_values(self):
        """The contract's keys in order; pages sized at the settings' dpi; age measured against the given clock."""
        self.pages(self.legacy)
        (self.state / "head.txt").write_text("abc1234\n", encoding="utf-8")
        mtime = os.stat(self.src / "main.tex").st_mtime
        out = meta.meta(self.legacy, {"login": "local"}, self.settings, [self.legacy], {"state": "disabled"}, mtime + 10)
        self.assertEqual(list(out), LIGHT_KEYS)
        self.assertEqual(out["pages"], [{"name": "page-1.png", "pt_w": 144.0, "pt_h": 72.0}])
        self.assertEqual((out["head"], out["built_at"]), ("abc1234", "?"))
        self.assertEqual((out["pins_md"], out["state_dir"]), (str(self.state / "pins.md"), str(self.state)))
        self.assertEqual((out["src_age_s"], out["multi"], out["sync"]), (10.0, False, {"state": "disabled"}))
        self.assertEqual(out["pins_rev"], "0")

    def test_several_documents_add_their_briefs_and_signature(self):
        """With more than one document, docs lists each one's brief and src_sig their manuscript mtimes."""
        self.pages(self.rr)
        docs = [self.ms, self.rr, self.rv]
        out = meta.meta(self.rr, {}, self.settings, docs, {}, 0.0)
        self.assertEqual(list(out), LIGHT_KEYS + ["docs", "src_sig"])
        self.assertEqual([d["key"] for d in out["docs"]], ["ms", "rr", "rv"])
        self.assertEqual(out["docs"][1]["n_pages"], 1)
        self.assertEqual(out["src_sig"], ",".join("%s=%.3f" % (d["key"], d["src_mtime"]) for d in out["docs"]))
        self.assertTrue(out["docs"][2]["view_only"])

    def test_pin_counts_in_order(self):
        """open, done (review excluded) and review, each counted once."""
        self.assertEqual(list(meta.pin_counts(["open", "review", "done", "open"]).items()),
                         [("n_open", 2), ("n_done", 1), ("n_review", 1)])

    def test_pins_rev_follows_the_pins_file(self):
        """"0" with no file; mtime_ns:size once written, changing when the file is replaced."""
        f = self.settings.pins_jsonl
        self.assertEqual(meta.pins_rev(f), "0")
        f.write_text("{}\n", encoding="utf-8")
        first = meta.pins_rev(f)
        self.assertEqual(first, "%d:%d" % (f.stat().st_mtime_ns, 3))
        self.assertEqual(meta.pins_rev(f), first)
        f.write_text("{}\n{}\n", encoding="utf-8")
        self.assertNotEqual(meta.pins_rev(f), first)


class DocsPayload(Fixture):
    """docs_payload counts open pins per document from the records it is given."""

    def test_counts_open_pins_per_document_and_orphans(self):
        """Done pins are not counted; a key no document serves goes to other_open; the first document is default."""
        rows = [{"doc": "rr"}, {"doc": "rr"}, {"doc": "rr", "done": True}, {}, {"doc": "gone"}]
        docs = [self.ms, self.rr, self.rv]
        out = meta.docs_payload(docs, rows, lambda r: documents.pin_doc_key(r, docs), self.state)
        self.assertEqual([(d["key"], d["n_open"]) for d in out["docs"]], [("ms", 1), ("rr", 2), ("rv", 0)])
        self.assertEqual((out["default"], out["multi"], out["other_open"]), ("ms", True, 1))
        self.assertEqual(out["docs"][1]["path"], "rr/rr.tex")


class Lookups(Fixture):
    """Which document a key, a file or a pin record names, over the list given."""

    def test_request_doc_by_key_or_unknown(self):
        """A served key is its document; an unknown key is DocNotFound listing the served keys in order."""
        docs = [self.ms, self.rr, self.rv]
        self.assertIs(documents.request_doc(docs, self.src, "rr"), self.rr)
        self.assertEqual(documents.request_doc(docs, self.src, "nope"), DocNotFound("nope", ("ms", "rr", "rv")))

    def test_request_doc_without_key_follows_the_file_only_with_several_documents(self):
        """No key: the document holding the file when several are served, else the first."""
        docs = [self.ms, self.rr, self.rv]
        self.assertIs(documents.request_doc(docs, self.src, None, "rr/rr.tex"), self.rr)
        self.assertIs(documents.request_doc(docs, self.src, "", str(self.src / "rr" / "rr.tex")), self.rr)
        self.assertIs(documents.request_doc(docs, self.src, None), self.ms)
        self.assertIs(documents.request_doc([self.ms], self.src, None, "rr/rr.tex"), self.ms)

    def test_doc_for_file_takes_the_deepest_latex_root(self):
        """The deepest build root containing the file wins; view-only documents never match; else the first."""
        docs = [self.rv, self.ms, self.rr]
        self.assertIs(documents.doc_for_file(docs, self.src, "rr/rr.tex"), self.rr)
        self.assertIs(documents.doc_for_file(docs, self.src, "main.tex"), self.ms)
        self.assertIs(documents.doc_for_file(docs, self.src, "/elsewhere/x.tex"), self.rv)
        self.assertIs(documents.doc_for_file(docs, self.src, "bad\x00name"), self.rv)

    def test_pin_doc_key_reads_legacy_records_as_the_first_document(self):
        """A record without a usable doc field belongs to the first document; no field is written."""
        docs = [self.ms, self.rr]
        for rec, want in (({"doc": "rr"}, "rr"), ({}, "ms"), ({"doc": ""}, "ms"), ({"doc": 3}, "ms")):
            with self.subTest(rec=rec):
                self.assertEqual(documents.pin_doc_key(rec, docs), want)
        self.assertEqual(documents.doc_by_key(docs, "rr"), self.rr)
        self.assertIsNone(documents.doc_by_key(docs, "rv"))


class DocumentFactsReads(Fixture):
    """DocumentFacts reads a document's lines and pages at call time."""

    def test_pages_of_the_build_on_screen_or_a_named_one(self):
        """page_count and pick_pages use the named build, the one on screen for None, and refuse a vanished name."""
        old = self.pages(self.ms, "pages-20260101000000")
        new = self.pages(self.ms, "pages-20260102000000")
        (new / "page-2.png").write_bytes(PNG)
        facts = documents.DocumentFacts(self.ms, self.src, 150)
        self.assertEqual((facts.current_build(), facts.page_count(None), facts.page_count(old.name)), (new.name, 2, 1))
        self.assertEqual(facts.pick_pages(None), (new, [(144.0, 72.0), (144.0, 72.0)]))
        self.assertIsNone(facts.pick_pages("pages-20250101000000"))
        self.assertEqual(facts.lines(self.src / "main.tex"), ["\\documentclass{article}"])
        self.assertEqual(facts.lines(self.src / "missing.tex"), [])
        self.assertEqual((facts.key, facts.is_pdf, facts.root, facts.pdf), ("ms", False, self.src, self.src / "main.tex"))


class ToSource(Fixture):
    """to_source maps a SyncTeX path in the build copy back to the manuscript."""

    def test_build_copy_path_maps_to_the_manuscript(self):
        """A path under the build copy becomes the same relative path under the build root."""
        self.assertEqual(documents.to_source(self.rr, str(self.rr.build / "sec" / "a.tex")), self.src / "rr" / "sec" / "a.tex")

    def test_moved_state_folder_falls_back_to_the_longest_existing_tail(self):
        """An old absolute build path whose tail is a real manuscript file maps to it; otherwise the path is unchanged."""
        self.assertEqual(documents.to_source(self.ms, "/old/state/build/rr/rr.tex"), self.src / "rr" / "rr.tex")
        self.assertEqual(documents.to_source(self.ms, "/old/state/build/none.tex"), Path("/old/state/build/none.tex"))


# ---------------------------------------------------------------- through server.py's wiring
#
# GET /api/meta's light polling and the instance label, accent and repo. These classes load server.py (helpers.ps) and
# drive the module through its bindings; the tests above call the module on its own.

# ---------------------------------------------------------------- light meta polling (docs/handbook/build-sync.md §자동 동기화 (가벼운 meta 폴링))

class LightMeta(Base):
    def test_light_meta_has_no_write_side_effect(self):
        self.add()
        before = ps.C.pins_jsonl.stat().st_mtime_ns
        for _ in range(5):
            d = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        after = ps.C.pins_jsonl.stat().st_mtime_ns
        self.assertEqual(before, after)
        self.assertNotIn("n_open", d)
        for k in ("src_mtime", "build_src_mtime", "pins_rev", "build", "pages_build"):
            self.assertIn(k, d)

    def test_pins_rev_changes_only_when_file_changes(self):
        rev0 = limn_meta.pins_rev(ps.C.pins_jsonl)
        self.add()
        rev1 = limn_meta.pins_rev(ps.C.pins_jsonl)
        self.assertNotEqual(rev0, rev1)
        rev2 = limn_meta.pins_rev(ps.C.pins_jsonl)
        self.assertEqual(rev1, rev2)      # unchanged if nothing changed

    def test_src_mtime_ignores_main_pdf_and_build_dir(self):
        m0 = limn_build.src_mtime(ps.DOCS[0], ps.C.state)
        (ps.C.src / "main.pdf").write_bytes(b"%PDF-fake")
        (ps.C.src / "build").mkdir()
        (ps.C.src / "build" / "leftover.tex").write_text("x", encoding="utf-8")
        self.assertEqual(limn_build.src_mtime(ps.DOCS[0], ps.C.state), m0)          # must not change even outside the cache window (even after 2s)
        ps._SRC_MTIME_CACHE[2] = 0.0                  # force-expire the cache to check recomputation
        self.assertEqual(limn_build.src_mtime(ps.DOCS[0], ps.C.state), m0)

    def test_src_mtime_ignores_diff_dir(self):
        # bug (should): the build rsync excludes diff/ (latexdiff output, exclude "diff/") but
        # src_mtime didn't — so running latexdiff even once flipped the "manuscript modified" badge on,
        # and after the next rebuild every pin was falsely marked "estimated" even though the layout was
        # unchanged.
        m0 = limn_build.src_mtime(ps.DOCS[0], ps.C.state)
        (ps.C.src / "diff").mkdir()
        (ps.C.src / "diff" / "latexdiff-out.tex").write_text("x", encoding="utf-8")
        self.assertEqual(limn_build.src_mtime(ps.DOCS[0], ps.C.state), m0)
        ps._SRC_MTIME_CACHE[2] = 0.0                  # force-expire the cache to check recomputation
        self.assertEqual(limn_build.src_mtime(ps.DOCS[0], ps.C.state), m0)

    def test_src_mtime_reacts_to_tex_change(self):
        ps._SRC_MTIME_CACHE[2] = 0.0
        m0 = limn_build.src_mtime(ps.DOCS[0], ps.C.state)
        time.sleep(0.05)
        os.utime(self.main, (time.time() + 10, time.time() + 10))
        ps._SRC_MTIME_CACHE[2] = 0.0
        self.assertGreater(limn_build.src_mtime(ps.DOCS[0], ps.C.state), m0)

    def test_built_src_mtime_file_missing_is_fine(self):
        self.assertIsNone(limn_build.read_built_src_mtime(ps.DOCS[0]))
        d = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertIsNone(d["build_src_mtime"])

    def test_src_mtime_force_bypasses_cache(self):
        # bug: write_built_src_mtime() used to just take the 2-second-cached value — editing the
        # manuscript and rebuilding right away, within 2 seconds of the cache filling, wrongly recorded
        # the "pre-edit" mtime as the build-start time.
        m0 = limn_build.src_mtime(ps.DOCS[0], ps.C.state, force=True)      # fill the cache
        time.sleep(0.05)
        os.utime(self.main, (time.time() + 10, time.time() + 10))
        cached = limn_build.src_mtime(ps.DOCS[0], ps.C.state)            # inside the cache window (within 2s) — the stale value
        self.assertEqual(cached, m0)
        forced = limn_build.src_mtime(ps.DOCS[0], ps.C.state, force=True)  # bypass the cache and measure for real — a fresh value
        self.assertGreater(forced, m0)

    def test_write_built_src_mtime_uses_fresh_value(self):
        os.utime(self.main, (time.time() + 20, time.time() + 20))
        limn_build.write_built_src_mtime(ps.DOCS[0], ps.C.state)
        self.assertAlmostEqual(limn_build.read_built_src_mtime(ps.DOCS[0]), limn_build.src_mtime(ps.DOCS[0], ps.C.state, force=True), delta=1.0)

    def test_light_query_param_via_handler(self):
        out = self.talk(req("GET", "/api/meta?light=1"))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("n_open", data)
        self.assertIn("pins_rev", data)


class InstanceMeta(Base):
    def test_meta_exposes_label_accent_repo(self):
        ps.C.label, ps.C.accent, ps.C.repo = "A-DEMO", "#1d4ed8", "git@example.com:org/a-demo.git"
        d = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR))
        self.assertEqual(d["label"], "A-DEMO")
        self.assertEqual(d["accent"], "#1d4ed8")
        self.assertEqual(d["repo"], "git@example.com:org/a-demo.git")

    def test_meta_repo_is_none_without_remote(self):
        ps.C.repo = None
        d = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertIsNone(d["repo"])

    def test_meta_endpoint_serves_new_fields(self):
        ps.C.label, ps.C.accent = "A-DEMO", "#1d4ed8"
        out = self.talk(req("GET", "/api/meta"))
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(data["label"], "A-DEMO")
        self.assertEqual(data["accent"], "#1d4ed8")
        self.assertIn("repo", data)



if __name__ == "__main__":
    unittest.main()
