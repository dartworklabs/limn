"""GET /api/asset: an image of the manuscript tree that a Markdown document shows (docs/adr/0030-markdown-tree-images-and-document-links.md).

AssetPathRule holds the path the route takes to what the viewer sends: tree-relative, normalized, an image suffix - anything
to repair is refused, not repaired. AssetKind holds each format to its signature, and SVG to an <svg> root without an
internal DTD subset. AssetRoute drives the route through the handler on a Markdown document: its answer and headers (the
asset's own policy, Cross-Origin-Resource-Policy, nosniff, a content ETag and its 304), every way out of the tree a path
can try (traversal, encoded traversal once and twice, backslash, absolute, a link out of the tree for a file or a folder,
a dot-named folder, the state folder), files that are not images (no regular file, wrong content), the size limit at its
edge, who may read it, and that no answer writes anything. That an SVG opened on its own runs nothing is a browser test
(src/limn/viewer/tests/test_viewer_markdown_assets.py).

Run: uv run pytest -q src/limn/documents/tests/test_assets.py
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

from limn.documents.assets import (
    ASSET_MAX_BYTES,
    ASSET_POLICY,
    ASSET_TYPES,
    AssetPath,
    AssetPathRefused,
    asset_kind,
    asset_path,
)
from limn.runtime.documents import Doc

from helpers import blank_png, ps, req, set_config, split_resp
from helpers_access import ALICE, BOB, CAROL, TS_HOST, AccessBase, talk_to, token_create

PNG = blank_png(4, 3)
SVG = (
    b'<?xml version="1.0"?>\n<!-- drawn -->\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" '
    b"onload=\"fetch('/api/meta')\"><script>fetch('/api/pins')</script><rect width='10' height='10'/></svg>\n"
)


class AssetPathRule(unittest.TestCase):
    """asset_path takes only the normalized tree-relative image path the viewer builds."""

    def test_a_normalized_image_path_is_taken_with_its_suffix(self):
        """A path in a folder, a name with spaces and Hangul, an upper-case suffix: taken, the suffix in lower case."""
        for raw, suffix in (
            ("docs/img/a.png", ".png"),
            ("그림 1.JPG", ".jpg"),
            ("x.jpeg", ".jpeg"),
            ("f/flow.svg", ".svg"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(asset_path(raw), AssetPath(raw, suffix))

    def test_anything_to_normalize_or_outside_the_allowlist_is_refused(self):
        """Empty, too long, absolute, backslash, control characters, empty / '.' / '..' / dot-named parts, a name that is
        only a suffix, a suffix not served, no suffix, not a string."""
        bad = [
            "",
            "a" * 1021 + ".png",
            "/etc/x.png",
            "a\\b.png",
            "..\\x.png",
            "a\x00.png",
            "a\nb.png",
            "../x.png",
            "a/../b.png",
            "./a.png",
            "a//b.png",
            "a/./b.png",
            ".git/logo.png",
            "a/.hidden.png",
            ".png",
            "a/.png",
            "notes.txt",
            "page.html",
            "x.svgz",
            "folder/",
            "noext",
            None,
            ["a.png"],
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                self.assertIsInstance(asset_path(raw), AssetPathRefused)

    def test_the_served_types_are_the_raster_four_and_svg(self):
        """PNG, JPEG (two suffixes), GIF, WebP and SVG - each with its own media type and nothing else."""
        self.assertEqual(
            dict(ASSET_TYPES),
            {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".svg": "image/svg+xml",
            },
        )


class AssetKind(unittest.TestCase):
    """asset_kind: the bytes start as the suffix's format starts."""

    def test_each_format_by_its_signature(self):
        """Each format's signature is that format and no other."""
        heads = {
            ".png": PNG,
            ".jpg": b"\xff\xd8\xff\xe0rest",
            ".gif": b"GIF89a....",
            ".webp": b"RIFF\x10\x00\x00\x00WEBPVP8 ",
            ".svg": SVG,
        }
        for suffix in heads:
            for other in heads:
                with self.subTest(suffix=suffix, bytes_of=other):
                    self.assertEqual(asset_kind(heads[other], suffix), suffix == other)
        self.assertTrue(asset_kind(heads[".jpg"], ".jpeg"))

    def test_an_svg_is_utf8_text_whose_first_element_is_svg_without_an_internal_subset(self):
        """A byte-order mark, a declaration, comments and a plain DOCTYPE may come first; an HTML page, a DOCTYPE with an
        internal subset (entity definitions), text that is not UTF-8, or an <svg> after other markup is not an SVG."""
        good = [
            b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            '﻿<?xml version="1.0"?><svg>'.encode(),
            b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd">\n<svg viewBox="0 0 1 1"></svg>',
        ]
        bad = [
            b"<html><svg></svg></html>",
            b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>',
            b"\xff\xfe<\x00s\x00v\x00g\x00",
            b"<svgx/>",
            b"plain text",
        ]
        for data in good:
            with self.subTest(good=data):
                self.assertTrue(asset_kind(data, ".svg"))
        for data in bad:
            with self.subTest(bad=data):
                self.assertFalse(asset_kind(data, ".svg"))

    def test_the_svg_check_is_linear_on_adversarial_heads(self):
        """Heads built to make a backtracking matcher repartition them - repeated comments before text that is no SVG,
        comments that look nested, an unterminated comment or declaration reaching the cut, a cut full of '<!--' - are all
        refused, and an SVG after a full cut of comments is still found; the lot runs in a child interpreter that must end
        within 20 s, so a regression fails here instead of hanging the suite (the regular expression this replaced took
        longer than 2 s on the first, 286 bytes)."""
        cases = [
            (b"<!--x-->" * 35 + b"NOTSVG", False),
            (b"<!--x-->" * 1000 + b"NOTSVG", False),
            (b"<!-- <!-- -->" * 600 + b"-->NOTSVG", False),
            (b"<!-- --" * 1200 + b">", False),
            (b"<!--" + b"-" * 8188, False),
            (b"<!--x-->" * 1023 + b"<!--", False),
            (b"<!--" * 2048, False),
            (b"<?xml " + b"?" * 8186, False),
            (b"<!DOCTYPE svg " + b"<!--" * 2044, False),
            (b"<!--x-->" * 1000 + b"<svg/>", True),
            (b"<?xml version='1.0'?><?xml-stylesheet href='a'?>\n<!--a--><!DOCTYPE svg><svg/>", True),
            (b"<!--x-->" * 1024 + b"<svg/>", False),
        ]
        code = (
            "import sys\nfrom limn.documents.assets import asset_kind\n"
            "cases = %r\n"
            "sys.exit(0 if [asset_kind(d, '.svg') for d, _ in cases] == [w for _, w in cases] else 3)\n"
        ) % (cases,)
        try:
            done = subprocess.run([sys.executable, "-c", code], timeout=20, capture_output=True, check=False)
        except subprocess.TimeoutExpired:
            self.fail("asset_kind(.svg) did not end within 20 s on an adversarial head")
        self.assertEqual(done.returncode, 0, done.stderr.decode(errors="replace"))


class AssetRoute(AccessBase):
    """The route over a manuscript tree holding notes/plan.md (a Markdown document nt) and images beside it."""

    def setUp(self):
        """A tree with a PNG and an SVG in notes/img, a fake PNG (HTML), an image outside the tree, a file link and a folder
        link that lead out of it, an image under .git; owner Alice, editor Bob and viewer Carol; an agent token."""
        super().setUp()
        (self.src / "notes" / "img").mkdir(parents=True)
        self.md = self.src / "notes" / "plan.md"
        self.md.write_text("# Plan\n\n![a](img/a.png)\n", encoding="utf-8")
        (self.src / "notes" / "img" / "a.png").write_bytes(PNG)
        (self.src / "notes" / "img" / "flow.svg").write_bytes(SVG)
        (self.src / "notes" / "img" / "fake.png").write_bytes(b"<html><script>alert(1)</script></html>")
        self.outside = self.src.parent / "outside"
        self.outside.mkdir()
        (self.outside / "secret.png").write_bytes(PNG)
        (self.src / "notes" / "img" / "leak.png").symlink_to(self.outside / "secret.png")
        (self.src / "notes" / "out").symlink_to(self.outside, target_is_directory=True)
        (self.src / "notes" / "img" / "same.png").symlink_to(self.src / "notes" / "img" / "a.png")
        (self.src / ".git").mkdir(exist_ok=True)
        (self.src / ".git" / "logo.png").write_bytes(PNG)
        self.serve()
        self.set_people(
            [
                {"login": "alice@example.com", "name": "Alice", "role": "owner"},
                {"login": "bob@example.com", "name": "Bob", "role": "editor"},
                {"login": "carol@example.com", "name": "Carol", "role": "viewer"},
            ]
        )
        _, self.token = token_create(ps.APP.C.state, "ci")

    def serve(self) -> None:
        """Serve ms over the manuscript and nt (Markdown, made directly) at notes/plan.md with the run paths now."""
        nt = Doc("nt", "계획", "markdown", self.md.parent, self.md, paths=ps.APP.C.paths)
        ps.APP.set_docs([Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths), nt])
        self.addCleanup(ps.APP.set_docs, None)

    def raw(self, path: str, quoted: bool = True, headers=None, **kw):
        """GET /api/asset?doc=nt&path=<path> (percent-encoded once unless quoted is False) as the loopback agent unless
        keywords say otherwise: (status, lower-case headers, body bytes)."""
        q = quote(path, safe="") if quoted else path
        if kw:
            code, body = self.call("GET", "/api/asset?doc=nt&path=" + q, headers=headers, **kw)
            return code, self.last_headers, body
        return split_resp(talk_to(ps, req("GET", "/api/asset?doc=nt&path=" + q, b"", headers)))

    def test_an_image_is_sent_as_its_suffix_says_with_the_assets_own_headers(self):
        """200, the PNG's bytes, image/png, private no-cache, an ETag, the asset policy (sandboxed, nothing fetched, no
        framing), Cross-Origin-Resource-Policy same-origin, nosniff; the SVG as image/svg+xml with the same headers."""
        for path, data, media in (("notes/img/a.png", PNG, "image/png"), ("notes/img/flow.svg", SVG, "image/svg+xml")):
            with self.subTest(path=path):
                code, hdrs, body = self.raw(path)
                self.assertEqual((code, body), (200, data))
                self.assertEqual(hdrs["content-type"], media)
                self.assertEqual(hdrs["cache-control"], "private, no-cache")
                self.assertEqual(hdrs["content-security-policy"], ASSET_POLICY)
                self.assertIn("sandbox", hdrs["content-security-policy"].split("; "))
                self.assertIn("default-src 'none'", hdrs["content-security-policy"])
                self.assertEqual(hdrs["cross-origin-resource-policy"], "same-origin")
                self.assertEqual(hdrs["x-content-type-options"], "nosniff")
                self.assertTrue(hdrs["etag"].startswith('"'))

    def test_a_matching_etag_is_a_304_and_a_changed_image_a_new_etag(self):
        """If-None-Match with the ETag: 304, no body, the resource policy kept. The image rewritten in place: a new ETag."""
        _, hdrs, _ = self.raw("notes/img/a.png")
        code, again, body = self.raw("notes/img/a.png", headers={"If-None-Match": hdrs["etag"]})
        self.assertEqual((code, body), (304, b""))
        self.assertEqual(again["cross-origin-resource-policy"], "same-origin")
        (self.src / "notes" / "img" / "a.png").write_bytes(blank_png(5, 3))
        _, after, _ = self.raw("notes/img/a.png")
        self.assertNotEqual(after["etag"], hdrs["etag"])

    def test_no_path_leaves_the_tree(self):
        """Every way out answers 400 and never the file's bytes: traversal plain, percent-encoded once (the query decodes it
        to the plain one) and twice (a literal name with '%' that is no file), a backslash, an absolute path (also the
        outside file's own), .git, a file link and a folder link that lead out of the tree. A link that stays inside the
        tree is the file it names."""
        cases = {
            "../outside/secret.png": "bad_asset_path",
            "notes/../../outside/secret.png": "bad_asset_path",
            "%2e%2e%2foutside%2fsecret.png": "file_not_found",
            "..\\outside\\secret.png": "bad_asset_path",
            str(self.outside / "secret.png"): "bad_asset_path",
            "/notes/img/a.png": "bad_asset_path",
            ".git/logo.png": "bad_asset_path",
            "notes/img/leak.png": "file_outside_manuscript",
            "notes/out/secret.png": "file_outside_manuscript",
        }
        for path, reason in cases.items():
            with self.subTest(path=path):
                code, _, body = self.raw(path)
                self.assertEqual(code, 400, body)
                self.assertNotIn(PNG, body)
                self.assertIn(reason.encode(), body)
        # The encoded traversal arrives as the plain one once the query is decoded.
        code, _, body = self.raw("..%2Foutside%2Fsecret.png", quoted=False)
        self.assertEqual(code, 400)
        self.assertIn(b"bad_asset_path", body)
        code, _, body = self.raw("%252e%252e%252foutside%252fsecret.png", quoted=False)
        self.assertEqual(code, 400)
        self.assertNotIn(PNG, body)
        self.assertEqual(self.raw("notes/img/same.png")[::2], (200, PNG))

    def test_the_state_folder_inside_the_tree_is_refused(self):
        """A state folder under --manuscript holds people and token records, never manuscript images: 400
        file_outside_manuscript, as for every file route."""
        state = self.src / "limn-state"
        state.mkdir()
        (state / "x.png").write_bytes(PNG)
        set_config(state=state)
        self.addCleanup(set_config, state=self.src.parent / "state")
        self.serve()
        code, _, body = self.raw("limn-state/x.png")
        self.assertEqual(code, 400)
        self.assertIn(b"file_outside_manuscript", body)

    def test_what_is_not_an_image_file_is_refused(self):
        """No such file, a folder named like an image and a FIFO: 400 file_not_found; HTML named .png and text named .svg:
        415 asset_not_image; a suffix not served: 400 bad_asset_path - and never the bytes."""
        (self.src / "notes" / "dir.png").mkdir()
        os.mkfifo(self.src / "notes" / "pipe.png")
        (self.src / "notes" / "img" / "note.svg").write_text("not a picture", encoding="utf-8")
        (self.src / "notes" / "page.html").write_text("<p>x</p>", encoding="utf-8")
        cases = {
            "notes/img/gone.png": (400, "file_not_found"),
            "notes/dir.png": (400, "file_not_found"),
            "notes/pipe.png": (400, "file_not_found"),
            "notes/img/fake.png": (415, "asset_not_image"),
            "notes/img/note.svg": (415, "asset_not_image"),
            "notes/page.html": (400, "bad_asset_path"),
            "notes/plan.md": (400, "bad_asset_path"),
        }
        for path, (want, reason) in cases.items():
            with self.subTest(path=path):
                code, hdrs, body = self.raw(path)
                self.assertEqual(code, want, body)
                self.assertIn(reason.encode(), body)
                self.assertTrue(hdrs["content-type"].startswith("application/json"))

    def test_the_size_limit_holds_at_its_edge(self):
        """Exactly ASSET_MAX_BYTES (8 MiB) of PNG: 200. One byte more: 413 asset_too_large with the size and the limit."""
        self.assertEqual(ASSET_MAX_BYTES, 8 * 1024 * 1024)
        big = self.src / "notes" / "img" / "big.png"
        big.write_bytes(PNG + b"\0" * (ASSET_MAX_BYTES - len(PNG)))
        code, _, body = self.raw("notes/img/big.png")
        self.assertEqual((code, len(body)), (200, ASSET_MAX_BYTES))
        with open(big, "ab") as fh:
            fh.write(b"\0")
        code, body = self.call("GET", "/api/asset?doc=nt&path=notes%2Fimg%2Fbig.png")
        self.assertEqual(code, 413)
        self.assertEqual(
            (body["reason"], body["bytes"], body["limit"]), ("asset_too_large", ASSET_MAX_BYTES + 1, ASSET_MAX_BYTES)
        )

    def test_every_admitted_principal_reads_it_and_the_rest_are_refused_alike(self):
        """The same role rule as GET /api/source: owner, editor and viewer over the tailnet, the agent's token and the
        headerless loopback agent get 200; headerless over the tailnet 403, an unidentified tailnet peer 401, a foreign
        Host or Origin 403."""
        want = {
            "owner": (dict(headers=dict(ALICE, Host=TS_HOST)), 200),
            "editor": (dict(headers=dict(BOB, Host=TS_HOST)), 200),
            "viewer": (dict(headers=dict(CAROL, Host=TS_HOST)), 200),
            "agent token": (dict(token=self.token, headers={"Host": TS_HOST}), 200),
            "loopback agent": (dict(peer="127.0.0.1"), 200),
            "tailnet headerless": (dict(headers={"Host": TS_HOST}), 403),
            "unidentified peer": (dict(peer="100.64.0.9"), 401),
            "foreign host": (dict(headers=dict(ALICE, Host="evil.example")), 403),
            "foreign origin": (dict(headers=dict(ALICE, Host=TS_HOST, Origin="https://evil.example")), 403),
        }
        for who, (kw, code) in want.items():
            with self.subTest(who=who):
                self.assertEqual(self.raw("notes/img/a.png", **kw)[0], code)

    def test_no_answer_writes_anything(self):
        """Every answer - an image, a 304, each refusal, the size limit - leaves every file of the tree and of the state
        folder as it was, bytes and mtime (docs/adr/0027-get-write-guard.md)."""

        def files(root: Path) -> dict[str, tuple[bytes, int]]:
            return {
                str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(root.rglob("*"))
                if p.is_file() and not p.is_symlink()
            }

        (self.src / "notes" / "img" / "big.png").write_bytes(PNG + b"\0" * ASSET_MAX_BYTES)
        state = Path(ps.APP.C.state)
        before = (files(self.src), files(state), files(self.outside))
        _, hdrs, _ = self.raw("notes/img/a.png")
        answers = [self.raw(p)[0] for p in ("notes/img/a.png", "notes/img/flow.svg", "../x.png", "notes/img/leak.png")]
        answers += [self.raw(p)[0] for p in ("notes/img/fake.png", "notes/img/big.png", "notes/img/gone.png")]
        answers.append(self.raw("notes/img/a.png", headers={"If-None-Match": hdrs["etag"]})[0])
        self.assertEqual(answers, [200, 200, 400, 400, 415, 413, 400, 304])
        self.assertEqual((files(self.src), files(state), files(self.outside)), before)
