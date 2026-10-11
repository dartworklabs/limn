"""A completed named build pairs real Poppler pages, its PDF and the captured source fingerprint.

The source may advance before page counting, between pages or after rendering. A process barrier makes
each replacement deterministic without replacing the renderer, files or stdlib globals with mocks.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from limn.builds import artifacts as build, engine
from limn.builds.artifacts import PagesNotRendered
from limn.runtime.documents import Doc, RunPaths

from helpers import Base, needs_tex, ps, req, set_config, split_resp

CHILD = Path(__file__).with_name("render_snapshot_child.py")
IMMUTABLE = "private, max-age=31536000, immutable"


def coloured_pdf(pages: int, colour: bytes) -> bytes:
    """Create a font-free real PDF whose pages all carry one distinguishable solid colour."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    for _ in range(pages):
        kids.append(len(objects) + 1)
        stream = colour + b" rg 0 0 50 40 re f"
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 50 40] /Contents %d 0 R >>" % (len(objects) + 2))
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), pages)
    output = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(output)


def replace_pdf(source: Path, raw: bytes) -> None:
    """Atomically replace the source, retaining its mtime to exercise the inode component of its signature."""
    before = source.stat()
    replacement = source.with_suffix(".next")
    replacement.write_bytes(raw)
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(source)


class BrokenNotes(dict):
    """An owned note supplier whose failure must leave no partial publication."""

    def items(self):
        """Raise an unexpected supplier defect after the renderer has drawn the pages."""
        raise RuntimeError("note supplier failed")


class RenderSnapshot(Base):
    """Observe tracked disk history and named HTTP URLs around actual source replacements and recovery."""

    def setUp(self):
        """Serve one synthetic watched PDF; each child receives its own process environment."""
        super().setUp()
        set_config(dpi=72)
        self.root = Path(self.tmp.name)
        self.source = self.src / "review.pdf"
        self.source.write_bytes(coloured_pdf(1, b"1 0 0"))
        self.doc = Doc(
            "rv", "Review", "pdf", self.src, self.source, paths=RunPaths(self.src, self.main, self.root / "state")
        )
        ps.APP.set_docs([self.doc])
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])

    def child(self, env=None):
        """Start one isolated tracked render and own its process group until normal completion or cleanup."""
        process = subprocess.Popen(
            [sys.executable, str(CHILD), str(self.source), str(self.root / "state")],
            env=self.env if env is None else env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.addCleanup(self.stop_child, process)
        return process

    def stop_child(self, process):
        """Retire the fixture process group on an assertion failure and reap the owned parent."""
        if process.poll() is None:
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)

    def finish(self, process):
        """Require a clean child exit and return the observable tracked result, with stderr on failure."""
        output, error = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, error)
        return json.loads(output)

    def published(self, result):
        """Require a successful result and read its exact named PDF and page bytes from disk."""
        self.assertEqual(result["type"], "BuildOk", result)
        name = result["result"]["build"]
        folder = self.doc.dir / name
        images = {path.name: path.read_bytes() for path in folder.glob("page-*.png")}
        return name, (folder / self.doc.pdf_name).read_bytes(), images

    def get(self, path):
        """Drive the existing handler and return status, cache headers and body for a named publication."""
        return split_resp(self.talk(req("GET", path)))

    def assert_named_pair(self, name, raw, images):
        """Both immutable HTTP routes serve exactly this build's coherent PDF and pages."""
        code, headers, body = self.get("/pdf?doc=rv&build=" + name)
        self.assertEqual((code, headers["cache-control"], body), (200, IMMUTABLE, raw))
        for page, expected in images.items():
            code, headers, body = self.get("/pages/%s/%s?doc=rv" % (name, page))
            self.assertEqual((code, headers["cache-control"], body), (200, IMMUTABLE, expected))

    def reference(self, raw):
        """Obtain independent expected page bytes by rendering an unchanged real file at the same resolution."""
        path = self.root / "reference.pdf"
        path.write_bytes(raw)
        folder = self.root / ("reference-%d" % len(list(self.root.glob("reference-*"))))
        folder.mkdir()
        self.assertIsNone(engine.draw_pages(path, folder, 72, 1))
        return {page.name: page.read_bytes() for page in folder.glob("page-*.png")}

    def raced(self, mode, raw_b):
        """Pause the genuine renderer, replace the input and release the exact owned process stage."""
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        for tool in ("pdfinfo", "pdftoppm"):
            wrapper = bin_dir / tool
            wrapper.write_text("#!%s\n" % sys.executable + CHILD.read_text(encoding="utf-8"), encoding="utf-8")
            wrapper.chmod(0o755)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)
            env = dict(
                self.env,
                PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                LIMN_SNAPSHOT_PORT=str(listener.getsockname()[1]),
                LIMN_SNAPSHOT_MODE=mode,
                LIMN_SNAPSHOT_RELEASE=str(self.root / "release"),
                LIMN_SNAPSHOT_REAL_PDFINFO=shutil.which("pdfinfo"),
                LIMN_SNAPSHOT_REAL_PDFTOPPM=shutil.which("pdftoppm"),
            )
            process = self.child(env)
            with listener.accept()[0] as gate:
                gate.settimeout(10)
                self.assertEqual(gate.recv(32), b"ready\n")
                self.assertIsNone(process.poll())
                replace_pdf(self.source, raw_b)
                (self.root / "release").touch()
                gate.sendall(b"release\n")
            return self.finish(process)

    def race_contract(self, mode, pages):
        """A captured A publication stays coherent and identifiable while the next watch tick publishes B."""
        raw_a, raw_b = coloured_pdf(pages, b"1 0 0"), coloured_pdf(pages, b"0 0 1")
        self.source.write_bytes(raw_a)
        expected_a, expected_b = self.reference(raw_a), self.reference(raw_b)
        self.assertNotEqual(expected_a, expected_b)
        captured_stat = self.source.stat()
        captured_signature = "%d:%d:%d" % (captured_stat.st_mtime_ns, captured_stat.st_size, captured_stat.st_ino)
        captured_hash = hashlib.sha256(raw_a).hexdigest()[:32]
        result = self.raced(mode, raw_b)
        name, copied, images = self.published(result)
        print(
            json.dumps(
                {
                    "snapshot_case": mode,
                    "pdf_a_sha256": hashlib.sha256(raw_a).hexdigest(),
                    "pdf_b_sha256": hashlib.sha256(raw_b).hexdigest(),
                    "published_pdf_sha256": hashlib.sha256(copied).hexdigest(),
                    "published_pages_sha256": {page: hashlib.sha256(raw).hexdigest() for page, raw in images.items()},
                    "reference_a_pages_sha256": {
                        page: hashlib.sha256(raw).hexdigest() for page, raw in expected_a.items()
                    },
                    "reference_b_pages_sha256": {
                        page: hashlib.sha256(raw).hexdigest() for page, raw in expected_b.items()
                    },
                    "result_src_hash": result["result"]["src_hash"],
                },
                sort_keys=True,
            )
        )
        self.assertEqual((copied, images), (raw_a, expected_a), "published PDF and pages must use captured A")
        self.assertEqual(result["result"]["src_hash"], captured_hash)
        self.assertEqual(build.load_builds(self.doc)["by"][name]["src_hash"], captured_hash)
        self.assertEqual((self.doc.dir / "pdf_sig.txt").read_text(), captured_signature)
        self.assertTrue(engine.pdf_changed(self.doc))
        self.assert_named_pair(name, raw_a, expected_a)
        self.assertTrue(ps.APP.build_requests.refresh_watched_now(self.doc, 15))
        current = build.cur_pages(self.doc)
        self.assertNotEqual(current.name, name)
        self.assertEqual((current / self.doc.pdf_name).read_bytes(), raw_b)
        self.assertEqual({path.name: path.read_bytes() for path in current.glob("page-*.png")}, expected_b)
        self.assertEqual(
            build.load_builds(self.doc)["by"][current.name]["src_hash"], hashlib.sha256(raw_b).hexdigest()[:32]
        )
        self.assertEqual((self.doc.dir / "pdf_sig.txt").read_text(), engine.pdf_signature(self.doc))
        self.assertFalse(engine.pdf_changed(self.doc))
        self.assert_named_pair(name, raw_a, expected_a)
        self.assertFalse(list(self.doc.dir.glob(".pages-*.part")))

    @needs_tex("pdfinfo", "pdftoppm")
    def test_named_pair_keeps_captured_version_after_page_render(self):
        """Replacing A after real Poppler renders it cannot attach B to A's immutable page URL."""
        self.race_contract("after-page", 1)

    @needs_tex("pdfinfo", "pdftoppm")
    def test_page_count_fingerprint_and_signature_share_captured_version(self):
        """Replacing A before pdfinfo cannot make B's pages carry A's source fingerprint or signature."""
        self.race_contract("before-info", 1)

    @needs_tex("pdfinfo", "pdftoppm")
    def test_every_page_uses_captured_version_when_source_changes_between_pages(self):
        """A source replacement between genuine page renders cannot mix versions in a multi-page build."""
        self.race_contract("during-pages", 2)

    @needs_tex("pdfinfo", "pdftoppm")
    def test_failed_render_retains_previous_publication_and_settles_until_source_changes(self):
        """A malformed new PDF leaves old page/PDF URLs unchanged, removes staging and can later recover."""
        previous = self.finish(self.child())
        name, raw, images = self.published(previous)
        replace_pdf(self.source, b"not a PDF")
        failed = self.finish(self.child())
        self.assertEqual(failed["type"], "BuildFailed")
        self.assertEqual(failed["result"]["kind"], "render")
        self.assertEqual(build.cur_pages(self.doc).name, name)
        self.assert_named_pair(name, raw, images)
        self.assertFalse(list(self.doc.dir.glob(".pages-*.part")))
        self.assertFalse(engine.pdf_changed(self.doc))
        replace_pdf(self.source, coloured_pdf(1, b"0 0 1"))
        self.assertTrue(ps.APP.build_requests.refresh_watched_now(self.doc, 15))
        self.assertFalse(engine.pdf_changed(self.doc))

    @needs_tex("pdfinfo", "pdftoppm")
    def test_companion_copy_failure_retains_previous_publication_and_cleans_staging(self):
        """An unreadable companion cannot publish a new named folder or replace the existing pointer."""
        name, raw, images = self.published(self.finish(self.child()))
        result = engine.render_pages(self.doc, self.source, [self.root / "missing.aux"], 72)
        self.assertIsInstance(result, PagesNotRendered)
        self.assertEqual(result.kind, "pdf_copy")
        self.assertEqual(build.cur_pages(self.doc).name, name)
        self.assert_named_pair(name, raw, images)
        self.assertFalse(list(self.doc.dir.glob(".pages-*.part")))

    @needs_tex("pdfinfo", "pdftoppm")
    def test_pdf_copy_failure_retains_previous_publication_and_cleans_staging(self):
        """A source that disappears before capture fails as a copy error without exposing a partial build."""
        name, raw, images = self.published(self.finish(self.child()))
        self.source.unlink()
        result = engine.render_pages(self.doc, self.source, [], 72)
        self.assertIsInstance(result, PagesNotRendered)
        self.assertEqual(result.kind, "pdf_copy")
        self.assertEqual(build.cur_pages(self.doc).name, name)
        self.assert_named_pair(name, raw, images)
        self.assertFalse(list(self.doc.dir.glob(".pages-*.part")))

    @needs_tex("pdfinfo", "pdftoppm")
    def test_unexpected_note_failure_cleans_staging_and_preserves_named_publication(self):
        """Even an unexpected supplier exception removes the partial folder and leaves old URLs intact."""
        name, raw, images = self.published(self.finish(self.child()))
        with self.assertRaisesRegex(RuntimeError, "note supplier failed"):
            engine.render_pages(self.doc, self.source, [], 72, notes=BrokenNotes({"recipe.json": "unused"}))
        self.assertEqual(build.cur_pages(self.doc).name, name)
        self.assert_named_pair(name, raw, images)
        self.assertFalse(list(self.doc.dir.glob(".pages-*.part")))
