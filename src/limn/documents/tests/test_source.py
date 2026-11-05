"""GET /api/source: the source of a document the browser draws, as the server numbers its lines (ADR-0025 D7,
docs/handbook/api.md §화면·PDF·정적 파일).

SourceLinesRule holds source_lines to the text-mode read every other line consumer makes (tex_lines), over generated
text and bytes and over a file holding every line end str.splitlines() knows. SourceStamp holds read_source's stamp to
the descriptor its bytes came from, across an atomic save that lands while it reads. SourceRoute drives the route through the
handler on a Markdown document made directly (no --doc suffix chooses the kind yet): its answer, the 1 MiB limit, the
path checks every file route makes, who may read it, that an edit reaches the viewer's light poll, and that no request
writes the manuscript.

Run: uv run pytest -q src/limn/documents/tests/test_source.py
"""

import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from hypothesis import given, strategies as st

from limn.builds import artifacts as limn_build
from limn.documents.source import SOURCE_MAX_BYTES, SourceLines, other_line_ends, read_source, source_lines
from limn.platform import files
from limn.platform.files import ManuscriptFile, file_in_tree, tex_lines
from limn.runtime.documents import Doc, RunPaths

from helpers import ps, set_config
from helpers_access import ALICE, BOB, CAROL, TS_HOST, AccessBase, token_create

# Every line end str.splitlines() knows, a byte-order mark at the start, a blank line and no line end at the very end.
EVERY_LINE_END = (
    "﻿# Title\r\ncrlf\rlone cr\nlf\x0bvtab\x0cform feed\x1cfs\x1dgs\x1ers\x85nel line sep para sep\n\nlast, 한글"
)
EVERY_LINE_END_LINES = [
    "﻿# Title",
    "crlf",
    "lone cr",
    "lf",
    "vtab",
    "form feed",
    "fs",
    "gs",
    "rs",
    "nel",
    "line sep",
    "para sep",
    "",
    "last, 한글",
]
LINE_ENDS = "\r\n\x0b\x0c\x1c\x1d\x1e\x85  "


def text_mode_lines(data: bytes) -> list[str] | None:
    """What tex_lines would answer for a file holding data: the text-mode UTF-8 read its descriptor makes (universal
    newlines), split with str.splitlines(); None where that read raises (the bytes are not UTF-8)."""
    try:
        return io.TextIOWrapper(io.BytesIO(data), encoding="utf-8").read().splitlines()
    except UnicodeDecodeError:
        return None


class SourceLinesRule(unittest.TestCase):
    """source_lines numbers lines exactly as the server's other line consumers do."""

    @given(st.text(alphabet=st.sampled_from(list(LINE_ENDS + "ab é한﻿")), max_size=60))
    def test_text_is_split_as_a_text_mode_read_splits_it(self, text):
        """For any text over every line end, letters and a byte-order mark, the lines equal the text-mode read's."""
        self.assertEqual(source_lines(text.encode("utf-8")), text_mode_lines(text.encode("utf-8")))

    @given(st.binary(max_size=40))
    def test_any_bytes_are_lines_or_not_utf8_as_a_text_mode_read_has_them(self, data):
        """Any bytes give the text-mode read's lines, or None exactly where that read refuses them as not UTF-8."""
        self.assertEqual(source_lines(data), text_mode_lines(data))

    @given(st.text(alphabet=st.sampled_from(list(LINE_ENDS + "ab é한")), max_size=60))
    def test_the_other_line_ends_are_the_split_ends_that_are_not_lf_or_crlf(self, text):
        """other_line_ends counts, by code point name and in the order they first appear, each line end that
        splitlines(keepends=True) leaves on a line and that is not LF or CRLF - a lone CR among them."""
        want: dict[str, int] = {}
        for piece in text.splitlines(keepends=True):
            end = piece[len((piece.splitlines() or [""])[0]) :]
            if end and end not in ("\n", "\r\n"):
                want["U+%04X" % ord(end)] = want.get("U+%04X" % ord(end), 0) + 1
        self.assertEqual(list(other_line_ends(text)), list(want.items()))

    def test_a_file_with_every_line_end_is_numbered_as_tex_lines_numbers_it(self):
        """A real file holding every line end: its lines are the fourteen written out above, and tex_lines reads the same."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        path = root / "every.md"
        path.write_bytes(EVERY_LINE_END.encode("utf-8"))
        checked = file_in_tree(str(path), root, root / "state")
        assert isinstance(checked, ManuscriptFile)
        self.assertEqual(source_lines(path.read_bytes()), EVERY_LINE_END_LINES)
        self.assertEqual(tex_lines(checked), EVERY_LINE_END_LINES)


class SourceStamp(unittest.TestCase):
    """read_source's src_mtime is the stamp of the very file version whose lines it returns."""

    def test_an_atomic_save_while_reading_never_pairs_new_lines_with_the_old_stamp(self):
        """plan.md holds "old" stamped 1700000000 s. The first time a descriptor on it is closed during read_source, an
        editor saves "new" stamped 1700000001 s by atomic replacement (write a temporary file, rename it over plan.md),
        as editors do. Whatever read_source answers is one version whole - the old lines with the old stamp or the new
        lines with the new stamp - never the new lines with the replaced file's stamp; the next read has the new pair."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        path = root / "plan.md"
        path.write_bytes(b"old\n")
        os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)
        checked = file_in_tree(str(path), root, root / "state")
        assert isinstance(checked, ManuscriptFile)
        old = (("old",), os.stat(path).st_mtime)
        original_open, original_close = files.os.open, files.os.close
        leaves: set[int] = set()
        saved: list[tuple[tuple[str, ...], float]] = []

        def open_noting_leaves(name, flags, *args, **kwargs):
            """Open as the OS does and remember each descriptor on plan.md itself."""
            descriptor = original_open(name, flags, *args, **kwargs)
            if name == "plan.md":
                leaves.add(descriptor)
            return descriptor

        def close_then_save(descriptor):
            """Close as the OS does; after the first close of a plan.md descriptor, save "new" atomically."""
            original_close(descriptor)
            if descriptor in leaves and not saved:
                part = root / "plan.md.part"
                part.write_bytes(b"new\n")
                os.utime(part, ns=(1_700_000_001_000_000_000,) * 2)
                os.replace(part, path)
                saved.append((("new",), os.stat(path).st_mtime))

        with (
            mock.patch.object(files.os, "open", open_noting_leaves),
            mock.patch.object(files.os, "close", close_then_save),
        ):
            got = read_source(checked)
        self.assertEqual(len(saved), 1, "the save never landed inside the read")
        assert isinstance(got, SourceLines)
        self.assertIn((got.lines, got.src_mtime), (old, saved[0]))
        after = read_source(checked)
        assert isinstance(after, SourceLines)
        self.assertEqual((after.lines, after.src_mtime), saved[0])


class SourceRoute(AccessBase):
    """The route on a LaTeX document ms (main.tex) and a Markdown document nt (notes/plan.md) inside its tree."""

    def setUp(self):
        """Serve ms and nt, with nt's source holding every line end; owner Alice, editor Bob and viewer Carol in
        people.json and an API token for the agent role."""
        super().setUp()
        (self.src / "notes").mkdir()
        self.md = self.src / "notes" / "plan.md"
        self.md.write_bytes(EVERY_LINE_END.encode("utf-8"))
        self.serve(self.md, ps.APP.C.paths)
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice", "role": "owner"},
                {"login": "bob@example.com", "name": "Bob", "role": "editor"},
                {"login": "carol@example.com", "name": "Carol", "role": "viewer"},
            ]
        )
        _, self.token = token_create(ps.APP.C.state, "ci")

    def serve(self, md: Path, paths: RunPaths) -> None:
        """Serve ms over the manuscript and nt (Markdown, made directly) at md, both with run paths `paths`."""
        self.nt = Doc("nt", "계획", "markdown", md.parent, md, paths=paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=paths), self.nt])
        self.addCleanup(ps.APP.set_docs, None)

    def source(self, **kw):
        """GET /api/source?doc=nt as the loopback agent unless call keywords say otherwise: (status, body)."""
        return self.call("GET", "/api/source?doc=nt", **kw)

    def test_it_answers_the_lines_as_the_server_numbers_them(self):
        """200 with the document, the source's path as a pin stores it, the stamp of its st_mtime and its lines -
        tex_lines' lines of the same file, every line end included - and each line end that is not LF or CRLF, counted
        by name (CRLF is not one of them)."""
        code, body = self.source()
        self.assertEqual(code, 200, body)
        checked = file_in_tree(str(self.md), self.src, ps.APP.C.state)
        assert isinstance(checked, ManuscriptFile)
        want = {
            "doc": "nt",
            "file": str(self.md),
            "src_mtime": os.stat(self.md).st_mtime,
            "lines": EVERY_LINE_END_LINES,
            "line_ends": {
                "U+000D": 1,
                "U+000B": 1,
                "U+000C": 1,
                "U+001C": 1,
                "U+001D": 1,
                "U+001E": 1,
                "U+0085": 1,
                "U+2028": 1,
                "U+2029": 1,
            },
        }
        self.assertEqual(body, want)
        self.assertEqual(body["lines"], tex_lines(checked))

    def test_a_1_mib_source_is_served_and_one_byte_more_is_413_without_lines(self):
        """Exactly SOURCE_MAX_BYTES (1 MiB) of source: 200 with all its lines. One byte more: 413 source_too_large with
        the size and the limit, and no lines."""
        self.assertEqual(SOURCE_MAX_BYTES, 1_048_576)
        self.md.write_bytes(b"a\n" * (SOURCE_MAX_BYTES // 2))
        code, body = self.source()
        self.assertEqual((code, len(body["lines"])), (200, SOURCE_MAX_BYTES // 2))
        with open(self.md, "ab") as fh:
            fh.write(b"b")
        code, body = self.source()
        self.assertEqual(code, 413, body)
        self.assertEqual(
            body,
            {
                "error": "원문이 너무 커서 보내지 않습니다(1048577바이트, 한도 1048576바이트).",
                "reason": "source_too_large",
                "bytes": SOURCE_MAX_BYTES + 1,
                "limit": SOURCE_MAX_BYTES,
            },
        )

    def test_a_document_shown_as_pages_has_no_source_route(self):
        """The LaTeX document, named or the default: 400 not_rendered_in_browser, pointing at /api/snippet."""
        for path in ("/api/source?doc=ms", "/api/source"):
            with self.subTest(path=path):
                code, body = self.call("GET", path)
                self.assertEqual((code, body["reason"]), (400, "not_rendered_in_browser"), body)
                self.assertIn("/api/snippet", body["error"])

    def test_a_source_outside_the_tree_is_refused_as_every_file_route_refuses_it(self):
        """A Markdown document whose file lies outside --manuscript, under a dot-named folder, behind a link that leads
        out, in a state folder inside the manuscript, or is not there gets the answer /api/snippet gives for the same
        path - file_outside_manuscript or file_not_found - and no lines."""
        outside = self.src.parent / "outside.md"
        outside.write_text("# Secret\n", encoding="utf-8")
        hidden = self.src / ".notes" / "plan.md"
        hidden.parent.mkdir()
        hidden.write_text("# Hidden\n", encoding="utf-8")
        link = self.src / "notes" / "link.md"
        link.symlink_to(outside)
        state = self.src / "limn-state"
        state.mkdir()
        (state / "plan.md").write_text("# State\n", encoding="utf-8")
        cases = {
            "outside": (outside, "file_outside_manuscript"),
            "dot folder": (hidden, "file_outside_manuscript"),
            "link out": (link, "file_outside_manuscript"),
            "state folder": (state / "plan.md", "file_outside_manuscript"),
            "missing": (self.src / "notes" / "gone.md", "file_not_found"),
        }
        for name, (path, reason) in cases.items():
            with self.subTest(name):
                if name == "state folder":
                    set_config(state=state)
                    self.addCleanup(set_config, state=self.src.parent / "state")
                self.serve(path, ps.APP.C.paths)
                code, body = self.source()
                self.assertEqual((code, body.get("reason")), (400, reason), body)
                snippet = self.call("GET", "/api/snippet?doc=ms&lo=1&hi=1&file=" + quote(str(path)))
                self.assertEqual((code, body), snippet)

    def test_a_source_that_is_not_utf8_is_refused(self):
        """Bytes that do not decode as UTF-8: 422 source_not_utf8, no lines."""
        self.md.write_bytes(b"# Title\n\xff\xfe broken\n")
        code, body = self.source()
        self.assertEqual((code, body["reason"]), (422, "source_not_utf8"), body)
        self.assertNotIn("lines", body)

    def test_every_admitted_principal_reads_it_and_the_rest_are_refused_alike(self):
        """The route is a declared read with the role rule of every read: owner, editor and viewer over the tailnet, the
        agent's token and the headerless loopback agent get 200; headerless over the tailnet 403, an unidentified tailnet
        peer 401, a foreign Host or Origin 403."""
        want = {
            "owner": (dict(headers=dict(ALICE, Host=TS_HOST)), 200),
            "editor": (dict(headers=dict(BOB, Host=TS_HOST)), 200),
            "viewer": (dict(headers=dict(CAROL, Host=TS_HOST)), 200),
            "agent token": (dict(token=self.token, headers={"Host": TS_HOST}), 200),
            "loopback agent": ({}, 200),
            "tailnet headerless": (dict(headers={"Host": TS_HOST}), 403),
            "unidentified peer": (dict(peer="100.64.0.9"), 401),
            "foreign host": (dict(headers=dict(ALICE, Host="evil.example")), 403),
            "foreign origin": (dict(headers=dict(ALICE, Host=TS_HOST, Origin="https://evil.example")), 403),
        }
        for who, (kw, code) in want.items():
            with self.subTest(who=who):
                self.assertEqual(self.source(**kw)[0], code)

    def test_an_edit_reaches_the_light_poll_and_the_next_read(self):
        """The light poll's src_mtime is the stamp the route sends. After an edit - and the 2-second memo the light poll
        outlives (it runs every 5 seconds) - the light poll's src_mtime and src_sig move to the new stamp and the route
        answers the new lines with it."""
        _, first = self.source()
        _, light = self.call("GET", "/api/meta?light=1&doc=nt")
        self.assertEqual(light["src_mtime"], first["src_mtime"])
        ahead = time.time() + 30
        self.md.write_text("# Plan\n\nRewritten.\n", encoding="utf-8")
        os.utime(self.md, (ahead, ahead))
        limn_build.expire_src_mtime(self.nt)
        _, after = self.call("GET", "/api/meta?light=1&doc=nt")
        _, second = self.source()
        self.assertEqual(second["lines"], ["# Plan", "", "Rewritten."])
        self.assertEqual(after["src_mtime"], second["src_mtime"])
        self.assertAlmostEqual(second["src_mtime"], ahead, places=3)
        self.assertNotEqual(after["src_sig"], light["src_sig"])

    def test_no_request_writes_the_manuscript(self):
        """Every answer of the route - lines, 413, not UTF-8, a refused path, a page document - leaves every file of the
        manuscript tree as it was, bytes and mtime."""

        def tree() -> dict[str, tuple[bytes, int]]:
            return {
                str(p.relative_to(self.src)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(self.src.rglob("*"))
                if p.is_file()
            }

        (self.src / "big.md").write_bytes(b"x" * (SOURCE_MAX_BYTES + 1))
        (self.src / "latin1.md").write_bytes(b"caf\xe9\n")
        before = tree()
        answers = [self.source()[0]]
        for name in ("big.md", "latin1.md", ".hidden.md"):
            self.serve(self.src / name, ps.APP.C.paths)
            answers.append(self.source()[0])
        answers.append(self.call("GET", "/api/source?doc=ms")[0])
        self.assertEqual(answers, [200, 413, 422, 400, 400])
        self.assertEqual(tree(), before)
