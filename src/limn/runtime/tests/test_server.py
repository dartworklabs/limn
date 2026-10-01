"""server.py - the composition root and the wired handler, driven over a socketpair (no port is opened).

What stays here is what only server.py can answer: its own functions and bindings (app_version, the page it serves
and its favicon, an import that reads no file, parse_record - the store's record parser as server.py binds it,
default_pdfjs_dir, main() as the one exit),
the build response's log diet the handler applies (ResponseDiet: limn.builds.answer.diet_log, kept here beside the
rebuild route's RebuildLogDiet), the requests end to end through the handler and the server's
wiring (smuggling and origin checks, the static routes, /pins.md, the build responses, several documents), and the
HTTP routes of claims with an estimate, pin kinds and threads, review and overlaps (their rules, stored fields and
pins.md lines are tested in the modules' files). A test whose subject is one module lives in that module's file
(the matching responsibility folder under tests/), a feature that crosses modules in the feature's file (test_reply.py, test_trash.py,
test_notifications.py, test_access_paths.py); the viewer's scripts and page are src/limn/viewer/tests/test_viewer.py. The shared
fixtures are tests/support/helpers.py.

Run: uv run pytest src/limn/runtime/tests/test_server.py
"""

import dataclasses
import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn.administration import serve_documents as startup_documents
from limn.builds import artifacts as limn_build, engine as build_engine
from limn.builds.answer import diet_log
from limn.builds.artifacts import BuildAborted, BuildBusy, BuildOk, BuildOkWithErrors, BuildStarted
from limn.builds.figure_map import FigureMap, MapRejected
from limn.pins.editing import input as editing_input
from limn.pins.lifecycle import input as lifecycle_input
from limn.pins.lifecycle.rules import CloseRequest
from limn.pins.listing.projection import pin_state
from limn.pins.location import source as pick_source
from limn.platform import files
from limn.runtime import startup
from limn.runtime.startup import StartupRefused
from limn.security.access import LOCAL_ACTOR
from limn.sync import run as gitsync
from limn.sync.rules import UpToDate
from limn.viewer import assemble as viewer_assemble
from limn.web.errors import HTTPError, InputRejected

import helpers_figure
from helpers import (
    DOCS_DIR,
    MINI_PDF,
    PKG,
    SKILL_KO,
    SKILL_MD,
    TEX,
    Base,
    add_pin,
    edit_pin,
    fits,
    jreq,
    needs_tex,
    page_for,
    pick,
    ps,
    record_of,
    records,
    req,
    run_config,
    set_config,
    shut_wr,
    split_resp,
)
from helpers_access import BOB_ACTOR
from helpers_authority import post_authority


class Smuggling(Base):
    """Request framing rejects ambiguous bodies without dispatching a second request."""

    def test_403_body_is_not_parsed_as_next_request(self):
        pid = self.add()
        set_config(allow=frozenset({"ok@example.com"}))
        inner = req("POST", "/api/pins/%d/close" % pid)
        out = self.talk(
            req(
                "POST",
                "/api/pin",
                inner,
                {"Tailscale-User-Login": "evil@example.com", "Content-Type": "application/json"},
            )
        )
        self.assertIn(b" 403 ", out)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_get_body_is_drained(self):
        pid = self.add()
        inner = req("POST", "/api/pins/%d/close" % pid)
        out = self.talk(req("GET", "/api/meta", inner, {"Tailscale-User-Login": "bob@example.com"}))
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertIn(b" 200 ", out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_transfer_encoding_rejected(self):
        pid = self.add()
        body = req("POST", "/api/pins/%d/close" % pid)  # a server that ignores TE would read this as the next request
        raw = (
            b"POST /api/pins/%d/reopen HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nTransfer-Encoding: chunked\r\n\r\n" % pid
            + body
        )
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_short_body_does_nothing(self):
        self.add()
        # cut off without a body
        raw = b"POST /api/clear HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: 5\r\n\r\n"
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        self.assertEqual(len(ps.APP.snapshot_pins()), 1)
        self.assertEqual(list(ps.APP.C.state.glob("pins_*.jsonl.bak")), [])


class CrossOrigin(Base):
    """Browser writes require an allowed origin, host, and content type."""

    def test_foreign_origin_rejected(self):
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(
            req("POST", "/api/pin", body, {"Origin": "https://evil.example", "Content-Type": "application/json"})
        )
        self.assertIn(b" 403 ", out)
        self.assertEqual(ps.APP.snapshot_pins(), [])

    def test_text_plain_rejected(self):
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "text/plain"}))
        self.assertIn(b" 415 ", out)

    def test_rebinding_host_rejected(self):
        out = self.talk(req("GET", "/api/meta", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)

    def test_own_origin_and_curl_allowed(self):
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(
            req("POST", "/api/pin", body, {"Origin": "http://127.0.0.1:18999", "Content-Type": "application/json"})
        )
        self.assertIn(b" 200 ", out)
        pid = ps.APP.snapshot_pins()[0].core.id
        out = self.talk(req("POST", "/api/pins/%d/close" % pid))  # curl-shaped: no body, no Origin
        self.assertIn(b" 200 ", out)
        out = self.talk(
            req(
                "GET",
                "/api/meta",
                headers={
                    "Host": "box.tail1234.ts.net",
                    "Origin": "https://box.tail1234.ts.net",
                    "Tailscale-User-Login": "bob@example.com",
                },
            )
        )
        self.assertIn(b" 200 ", out)

    def test_rebinding_with_forged_tailscale_header_rejected(self):
        # a rebinding page can attach Tailscale-User-Login to a same-origin GET without a preflight.
        pid = self.add(note="secret-note")
        h = {"Host": "evil.example:18999", "Tailscale-User-Login": "x@y"}
        for path in ("/api/pins", "/api/meta", "/api/snippet?file=main.tex&lo=4&hi=4"):
            out = self.talk(req("GET", path, headers=h))
            self.assertIn(b" 403 ", out, path)
            self.assertNotIn(b"secret-note", out)
            self.assertNotIn(b"rarewordalpha", out)
        out = self.talk(req("POST", "/api/pins/%d/drop" % pid, headers=h))  # POST without Origin
        self.assertIn(b" 403 ", out)
        self.assertIsNotNone(self.pin(pid))

    def test_host_ok_ignores_loopback_port_ssh_forward(self):
        # bug: host_ok used to require the port to equal C.port even for a loopback name — forwarding
        # through SSH -L to a different local port (Host: localhost:9000, server on 18999) got 403'd.
        self.assertTrue(ps.APP.host_ok("localhost:9000"))
        self.assertTrue(ps.APP.host_ok("127.0.0.1:1"))
        self.assertTrue(ps.APP.host_ok("[::1]:9000"))
        self.assertTrue(ps.APP.host_ok("localhost"))  # no port is still allowed

    def test_host_ok_still_rejects_non_loopback_non_tailnet(self):
        self.assertFalse(ps.APP.host_ok("evil.example"))
        # mimicking the server port doesn't help if the name is wrong
        self.assertFalse(ps.APP.host_ok("evil.example:18999"))

    def test_host_ok_tailnet_unaffected(self):
        self.assertTrue(ps.APP.host_ok("box.tail1234.ts.net"))
        self.assertTrue(ps.APP.host_ok("box.tail1234.ts.net:443"))

    def test_origin_ok_loopback_host_accepts_any_loopback_port(self):
        # design: if Host is loopback, Origin only needs to be loopback too (port doesn't
        # matter — with SSH -L, Host/Origin ports differ from the server's bound port. Observed: after
        # forwarding 18110->18106, every POST got 403).
        self.assertTrue(ps.APP.origin_ok("http://127.0.0.1:9000", "localhost:9000"))
        self.assertTrue(ps.APP.origin_ok("http://localhost:18999", "127.0.0.1:18999"))
        self.assertTrue(ps.APP.origin_ok("http://127.0.0.1:18110", "localhost:18106"))
        self.assertTrue(ps.APP.origin_ok("http://[::1]:9000", "[::1]:9000"))
        self.assertTrue(ps.APP.origin_ok("http://127.0.0.1:18999", None))
        self.assertFalse(ps.APP.origin_ok("http://evil.example:18999", "localhost:18999"))
        self.assertFalse(ps.APP.origin_ok("null", "localhost:18999"))

    def test_origin_ok_loopback_host_rejects_tailnet_origin(self):
        # bug (should -> design 3): a loopback Host accepted a *.ts.net Origin, so a public Funnel page
        # from another tailnet could send a body-less POST (close/clear) via the local user's browser
        # without a preflight (observed: 200).
        self.assertFalse(ps.APP.origin_ok("https://evil-funnel.tailabcd.ts.net", "127.0.0.1:18999"))
        self.assertFalse(ps.APP.origin_ok("https://box.tail1234.ts.net", "localhost:18999"))
        self.assertFalse(ps.APP.origin_ok("https://box.tail1234.ts.net", None))

    def test_origin_ok_tailnet_host_requires_same_host_and_port(self):
        self.assertTrue(ps.APP.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net"))
        # default-port normalization
        self.assertTrue(ps.APP.origin_ok("https://box.tail1234.ts.net:443", "box.tail1234.ts.net"))
        self.assertTrue(ps.APP.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net:443"))
        self.assertTrue(ps.APP.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net:8443"))
        self.assertFalse(ps.APP.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net"))
        self.assertFalse(ps.APP.origin_ok("https://evil.tailabcd.ts.net", "box.tail1234.ts.net"))
        self.assertFalse(ps.APP.origin_ok("http://127.0.0.1:18999", "box.tail1234.ts.net"))
        self.assertFalse(ps.APP.origin_ok("https://box.tail1234.ts.net:99999", "box.tail1234.ts.net"))  # wrong port

    def test_funnel_csrf_on_loopback_host_is_403_end_to_end(self):
        pid = self.add()
        out = self.talk(
            req("POST", "/api/pins/%d/close" % pid, headers={"Origin": "https://evil-funnel.tailabcd.ts.net"})
        )
        self.assertIn(b" 403 ", out)
        self.assertFalse(self.pin(pid).get("done"))
        out = self.talk(req("POST", "/api/clear", headers={"Origin": "https://evil-funnel.tailabcd.ts.net"}))
        self.assertIn(b" 403 ", out)
        self.assertIsNotNone(self.pin(pid))

    def test_ssh_forwarded_port_request_allowed_end_to_end(self):
        # shape of what a browser sends behind SSH -L 9000:127.0.0.1:18999: Host is the forwarded port,
        # and Origin is either absent (direct address-bar access) or, if present, points at the actual
        # server port (the port the browser connected to is Origin's port — this test checks the most
        # common case, a curl-shaped request with no Origin).
        out = self.talk(req("GET", "/api/meta", headers={"Host": "localhost:9000"}))
        self.assertIn(b" 200 ", out)

    def test_ssh_forwarded_port_post_with_matching_origin_allowed(self):
        # shape of what a real browser sends behind forwarding (Host and Origin both the forwarded port) —
        # before the fix, only GET passed and the first drag (POST /api/pick etc.) always got 403,
        # making the viewer view-only.
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(
            req(
                "POST",
                "/api/pin",
                body,
                {"Host": "localhost:9000", "Origin": "http://localhost:9000", "Content-Type": "application/json"},
            )
        )
        self.assertIn(b" 200 ", out)
        self.assertEqual(len(ps.APP.snapshot_pins()), 1)

    def test_ssh_forwarded_non_loopback_origin_still_rejected(self):
        # a non-loopback origin is still blocked even behind forwarding (only the port is ignored, not the name).
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(
            req(
                "POST",
                "/api/pin",
                body,
                {"Host": "localhost:9000", "Origin": "http://evil.example:9000", "Content-Type": "application/json"},
            )
        )
        self.assertIn(b" 403 ", out)
        self.assertEqual(ps.APP.snapshot_pins(), [])

    def test_forged_host_plus_identity_header_still_403(self):
        # whether relaxing Host breaks rebinding defense — a non-loopback name is still rejected.
        pid = self.add(note="secret-note-2")
        out = self.talk(req("GET", "/api/pins", headers={"Host": "evil.example", "Tailscale-User-Login": "x@y"}))
        self.assertIn(b" 403 ", out)
        self.assertNotIn(b"secret-note-2", out)
        self.assertIsNotNone(self.pin(pid))

    def test_no_origin_check_switch(self):
        set_config(origin_check=False)
        out = self.talk(
            req("GET", "/api/meta", headers={"Host": "box.example.com", "Tailscale-User-Login": "ok@example.com"})
        )
        self.assertIn(b" 200 ", out)
        # v0.2.1: an unexpected Host is accepted, but a headerless request under it is not the loopback agent
        self.assertIn(b" 403 ", self.talk(req("GET", "/api/meta", headers={"Host": "box.example.com"})))

    def test_allow_rejects_headerless_tailnet_request(self):
        set_config(allow=frozenset({"ok@example.com"}))
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net"}))  # tag-device shape
        self.assertIn(b" 403 ", out)
        out = self.talk(req("GET", "/api/meta"))  # loopback curl
        self.assertIn(b" 200 ", out)
        out = self.talk(
            req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net", "Tailscale-User-Login": "ok@example.com"})
        )
        self.assertIn(b" 200 ", out)

    def test_non_ascii_content_length_is_400(self):
        raw = b"POST /api/pin HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: \xb2\r\n\r\n"
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        out = self.talk(b"GET /api/meta HTTP/1.1\r\nHost: 127.0.0.1:\xb2\r\n\r\n")  # same trap for the Host port
        self.assertIn(b" 403 ", out)

    def test_deep_json_is_400(self):
        body = b"[" * 100000 + b"]" * 100000
        out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)


VENDOR = PKG / "vendor" / "pdfjs"


class ApiVersion(Base):
    """GET /api/version — which Limn build is serving (no writes)."""

    def test_reports_name_and_package_version(self):
        code, h, body = split_resp(self.talk(req("GET", "/api/version")))
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "application/json; charset=utf-8")
        init = (PKG / "__init__.py").read_text(encoding="utf-8")
        want = re.search(r'^__version__ = "([^"]+)"', init, re.M).group(1)
        self.assertEqual(json.loads(body), {"name": "limn", "version": want})
        self.assertEqual(ps.app_version(), want)


class VendorPdfjs(Base):
    """GET /vendor/pdfjs/<file> — static serving of PDF.js for vector rendering (MIME/cache/path traversal/Host checks)."""

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_serves_both_modules_as_javascript(self):
        for name in ("pdf.min.mjs", "pdf.worker.min.mjs"):
            code, h, body = self.get("/vendor/pdfjs/%s?v=%s" % (name, viewer_assemble.PDFJS_VERSION))
            self.assertEqual(code, 200, name)
            # a module script only runs with the JS MIME type
            self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
            self.assertEqual(h["x-content-type-options"], "nosniff")
            self.assertEqual(h["cache-control"], "public, max-age=86400")
            self.assertEqual(body, (VENDOR / name).read_bytes())

    def test_traversal_and_non_module_names_are_404(self):
        for path in (
            "/vendor/pdfjs/../../server.py",
            "/vendor/pdfjs/..%2f..%2fserver.py",
            "/vendor/pdfjs/%2e%2e/%2e%2e/server.py",
            "/vendor/pdfjs/sub/pdf.min.mjs",
            "/vendor/pdfjs/LICENSE",
            "/vendor/pdfjs/README.md",
            "/vendor/pdfjs/.pdf.min.mjs",
            "/vendor/pdfjs/..mjs",
            "/vendor/pdfjs/",
            "/vendor/pdfjs//etc/passwd",
            "/vendor/pdfjs/pdf.min.mjs/",
            "/vendor/pdfjs/pdf.min.mjs%00.png",
        ):
            code, h, body = self.get(path)
            self.assertEqual(code, 404, path)
            self.assertNotIn(b"argparse", body)
            self.assertNotIn(b"Apache License", body)
            self.assertEqual(h["cache-control"], "no-store")

    def test_symlink_out_of_vendor_dir_is_404(self):
        d = Path(self.tmp.name) / "vend"
        d.mkdir()
        secret = Path(self.tmp.name) / "secret.mjs"
        secret.write_text("secret-module", encoding="utf-8")
        (d / "evil.mjs").symlink_to(secret)
        (d / "ok.mjs").write_text("export const ok=1;", encoding="utf-8")
        set_config(pdfjs_dir=d)
        self.assertEqual(self.get("/vendor/pdfjs/ok.mjs")[0], 200)
        code, _h, body = self.get("/vendor/pdfjs/evil.mjs")
        self.assertEqual(code, 404)
        self.assertNotIn(b"secret-module", body)

    def test_missing_vendor_dir_is_404_not_500(self):
        set_config(pdfjs_dir=Path(self.tmp.name) / "nowhere")
        code, h, _ = self.get("/vendor/pdfjs/pdf.min.mjs")
        self.assertEqual(code, 404)  # the viewer sees this and falls back to PNG

    def test_host_and_origin_checked_like_other_gets(self):
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(
            self.get(
                "/vendor/pdfjs/pdf.min.mjs",
                {"Host": "box.tail1234.ts.net", "Origin": "https://box.tail1234.ts.net", "Tailscale-User-Login": "a@b"},
            )[0],
            200,
        )

    def test_version_pinned_in_vendor_html_and_readme(self):
        head = (VENDOR / "pdf.min.mjs").read_bytes()[:2000].decode("utf-8")
        self.assertIn("pdfjsVersion = %s" % viewer_assemble.PDFJS_VERSION, head)
        whead = (VENDOR / "pdf.worker.min.mjs").read_bytes()[:2000].decode("utf-8")
        self.assertIn("pdfjsVersion = %s" % viewer_assemble.PDFJS_VERSION, whead)
        readme = (VENDOR / "README.md").read_text(encoding="utf-8")
        self.assertIn("pdfjs-dist@%s" % viewer_assemble.PDFJS_VERSION, readme)
        self.assertIn("Apache License", (VENDOR / "LICENSE").read_text(encoding="utf-8"))

    def test_readme_sha256_matches_files(self):
        import hashlib

        readme = (VENDOR / "README.md").read_text(encoding="utf-8")
        for name in ("pdf.min.mjs", "pdf.worker.min.mjs", "LICENSE"):
            data = (VENDOR / name).read_bytes()
            m = re.search(r"\| `%s` \| ([\d,]+) \| `([0-9a-f]{64})` \|" % re.escape(name), readme)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1).replace(",", "")), len(data), name)
            self.assertEqual(m.group(2), hashlib.sha256(data).hexdigest(), name)

    def test_default_dir_finds_repo_vendor(self):
        self.assertEqual(ps.default_pdfjs_dir().resolve(), VENDOR.resolve())


class PdfRoute(Base):
    """GET /pdf?build=<pages_build> — only serves the PDF from the same build as the page images."""

    def setUp(self):
        super().setUp()
        self.old, self.new = "pages-20250101000000", "pages-20260101000000"
        for name, body in ((self.old, b"%PDF-old"), (self.new, b"%PDF-new")):
            d = ps.APP.C.state / name
            d.mkdir()
            (d / "main.pdf").write_bytes(body)
        files.atomic_write(ps.APP.C.pages_ptr, self.new)
        ps.APP.C.build.mkdir(parents=True, exist_ok=True)
        (ps.APP.C.build / "main.pdf").write_bytes(b"%PDF-build-dir")

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_named_build_served_as_pdf(self):
        for name, body in ((self.new, b"%PDF-new"), (self.old, b"%PDF-old")):
            code, h, got = self.get("/pdf?build=%s&v=x" % name)
            self.assertEqual(code, 200)
            self.assertEqual(h["content-type"], "application/pdf")
            # a URL naming its build always means the same bytes: cached privately for a year (docs/handbook/api.md)
            self.assertEqual(h["cache-control"], "private, max-age=31536000, immutable")
            # asking for the previous build gets the previous build — not swapped for the current one
            self.assertEqual(got, body)

    def test_no_build_means_current(self):
        self.assertEqual(self.get("/pdf")[2], b"%PDF-new")

    def test_gone_or_bad_build_is_404_with_current_build(self):
        for name in ("pages-20990101000000", "../../etc", "pages", "pages-1"):
            code, _h, body = self.get("/pdf?build=%s" % name)
            self.assertEqual(code, 404, name)
            d = json.loads(body)
            self.assertTrue(d["pdf_build_gone"])
            self.assertEqual(d["pages_build"], self.new)
            self.assertNotIn(b"%PDF", body)

    def test_does_not_fall_back_to_build_dir(self):
        # if the page directory has no matching PDF, don't fall back to build/
        (ps.APP.C.state / self.new / "main.pdf").unlink()
        code, _h, body = self.get("/pdf?build=%s" % self.new)
        self.assertEqual(code, 404)
        self.assertNotIn(b"%PDF-build-dir", body)
        self.assertEqual(self.get("/pdf")[0], 404)

    def test_host_and_origin_checked(self):
        self.assertEqual(self.get("/pdf?build=%s" % self.new, {"Host": "evil.example"})[0], 403)
        self.assertEqual(
            self.get("/pdf?build=%s" % self.new, {"Host": "evil.example:18999", "Tailscale-User-Login": "x@y"})[0], 403
        )
        self.assertEqual(self.get("/pdf?build=%s" % self.new, {"Origin": "https://evil.example"})[0], 403)
        code, _h, body = self.get(
            "/pdf?build=%s" % self.new, {"Host": "box.tail1234.ts.net", "Tailscale-User-Login": "a@b"}
        )
        self.assertEqual((code, body), (200, b"%PDF-new"))

    def test_pages_build_in_meta_matches_pdf_route(self):
        m = ps.APP.document_views.meta(ps.APP.docs[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m["pages_build"], self.new)
        self.assertEqual(self.get("/pdf?build=%s" % m["pages_build"])[2], b"%PDF-new")


# ---------------------------------------------------------------- overlaps over HTTP (docs/handbook/api.md §겹친 핀과 덧붙이기)


class OverlapRoutes(Base):
    """Pick and overlap routes report source ranges and their live pin relationships."""

    @needs_tex("latexmk", "pdftoppm", "pdftotext", "synctex")
    def test_pick_end_to_end_includes_quote_and_overlaps(self):
        """With the real build: a pick over the first page's top returns the quote, the overlaps and the build it
        resolved against, also for an older build still on screen; a vanished build is flagged, a bad name refused."""
        res = ps.APP.build_requests.build_all(ps.APP.docs[0])
        self.assertIsInstance(res, BuildOk)
        pages = limn_build.page_list(limn_build.cur_pages(ps.APP.docs[0]), ps.APP.C.dpi)
        self.assertTrue(pages)
        p = pages[0]
        d = pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4})
        self.assertNotIn("error", d)
        self.assertIn("quote", d)
        self.assertIn("overlaps", d)
        self.assertEqual(d["pdf_build"], limn_build.cur_pages(ps.APP.docs[0]).name)
        # if the screen shows an old build, it's resolved against that build and its name is returned (a drag made right after a rebuild, before the screen updates).
        b1 = limn_build.cur_pages(ps.APP.docs[0]).name
        # a forced rebuild (an unchanged one keeps the build on screen) within the same second still gets a page
        # directory of its own (test_build.Outcomes)
        self.assertEqual(type(ps.APP.build_requests.build_all(ps.APP.docs[0], force=True)), BuildOk)
        self.assertNotEqual(limn_build.cur_pages(ps.APP.docs[0]).name, b1)
        d2 = pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4, "pdf_build": b1})
        self.assertEqual(d2["pdf_build"], b1)
        gone = pick({"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "pdf_build": "pages-19990101000000"})
        self.assertTrue(gone.get("pdf_build_gone"))
        with self.assertRaises(HTTPError):
            pick({"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "pdf_build": "../x"})

    def test_get_pins_includes_rel_field(self):
        p1 = self.add(4, 9)
        p2 = self.add(4, 5)
        out = self.talk(req("GET", "/api/pins?all=1"))
        rows = json.loads(out.split(b"\r\n\r\n", 1)[1])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[p2]["rel"], [{"id": p1, "rel": "inside"}])

    def test_overlaps_endpoint_recomputes_for_arbitrary_range(self):
        # must-1: when CUR.lo/hi changes via level switching (useLevel) or up/down (nudge), we
        # can't call /api/pick again (it needs coordinates) — there must be a lightweight endpoint that
        # re-asks using only the range so the banner keeps up.
        pid = self.add(4, 9, note="outer")
        out = self.talk(req("GET", "/api/overlaps?file=%s&lo=4&hi=5" % str(self.main)))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(data["overlaps"], [{"id": pid, "lo": 4, "hi": 9, "rel": "inside"}])

    def test_overlaps_endpoint_range_out_of_file_is_400(self):
        out = self.talk(req("GET", "/api/overlaps?file=%s&lo=1&hi=99999" % str(self.main)))
        self.assertIn(b" 400 ", out)


# ---------------------------------------------------------------- GET /pins.md (docs/handbook/api.md §원격 에이전트 진입점 (`GET /pins.md`))


class RemotePinsMd(Base):
    """The work-list endpoint chooses its public base from the accepted request host."""

    def test_loopback_host_uses_loopback_base(self):
        self.add()
        out = self.talk(req("GET", "/pins.md"))
        self.assertIn(b" 200 ", out)
        self.assertIn(b"text/markdown", out)
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("http://127.0.0.1:18999/api/pins/N/close", body)
        self.assertNotIn("원격:", body)

    def test_tailnet_host_rewrites_base_to_https_host_verbatim(self):
        self.add()
        # through tailscale serve a request carries a person's identity (or a token) - headerless is 403 since v0.2.1
        out = self.talk(
            req(
                "GET",
                "/pins.md",
                headers={
                    "Host": "x.tail1234.ts.net:18004",
                    "Tailscale-User-Login": "ok@example.com",
                    "X-Forwarded-For": "100.64.0.9",
                },
            )
        )
        self.assertIn(b" 200 ", out)
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("https://x.tail1234.ts.net:18004/api/pins/N/close", body)
        self.assertIn("원격: `curl -s https://x.tail1234.ts.net:18004/pins.md`", body)

    def test_disk_pins_md_always_uses_loopback_base(self):
        self.add()
        self.talk(req("GET", "/pins.md", headers={"Host": "x.tail1234.ts.net:18004"}))
        disk = ps.APP.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:18999", disk)
        self.assertNotIn("x.tail1234.ts.net", disk)

    def test_pins_md_endpoint_syncs_like_api_pins(self):
        # must take the same sync path as GET /api/pins — if editing the manuscript shifted lines, it must be reflected.
        pid = self.add(lo=7, hi=7, note="n")
        # one blank line up front — everything shifts down by one line
        self.main.write_text("\n" + TEX, encoding="utf-8")
        out = self.talk(req("GET", "/pins.md"))
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("L8-L8", body)
        self.assertEqual(self.pin(pid)["lo"], 8)

    def test_pins_md_endpoint_respects_origin_check(self):
        out = self.talk(req("GET", "/pins.md", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)


# ---------------------------------------------------------------- trimming agent responses (docs/handbook/build-sync.md §에이전트 응답 다이어트)


class ResponseDiet(unittest.TestCase):
    """Build responses trim logs unless the caller explicitly requests full detail."""

    def test_ok_drops_log_and_log_tail(self):
        out = diet_log({"state": "ok", "log": "x" * 5000, "log_tail": "y" * 10, "pages": 3}, full=False)
        self.assertNotIn("log", out)
        self.assertNotIn("log_tail", out)
        self.assertEqual(out["pages"], 3)

    def test_ok_errors_trims_log_tail_to_40_lines(self):
        big = "\n".join("line%d" % i for i in range(100))
        out = diet_log({"state": "ok_errors", "log_tail": big}, full=False)
        self.assertEqual(out["log_tail"].splitlines(), big.splitlines()[-40:])

    def test_fail_trims_log_to_40_lines(self):
        big = "\n".join(str(i) for i in range(60))
        out = diet_log({"state": "fail", "log": big}, full=False)
        self.assertEqual(len(out["log"].splitlines()), 40)
        self.assertEqual(out["log"].splitlines(), big.splitlines()[-40:])

    def test_full_flag_bypasses_diet_entirely(self):
        payload = {"state": "ok", "log": "keep-me-fully"}
        out = diet_log(payload, full=True)
        self.assertEqual(out, payload)

    def test_existing_fields_are_kept(self):
        out = diet_log(
            {"ok": True, "state": "ok", "errors": [], "elapsed_s": 1.2, "pages": 2, "head": "abc1234", "log": "x"},
            full=False,
        )
        for k in ("ok", "state", "errors", "elapsed_s", "pages", "head"):
            self.assertIn(k, out)


class RebuildLogDiet(Base):
    """Synchronous rebuild and build-status routes apply the same log-size contract."""

    def tearDown(self):
        if ps.APP.docs[0].lock.locked():
            ps.APP.docs[0].lock.release()
        super().tearDown()

    def test_sync_rebuild_ok_omits_log(self):
        def fake_build(D=None, force=False):
            return BuildOk("font path\n" * 200, 0.01, None, 1.0, None, "abc1234", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log", body)
        self.assertEqual(body["state"], "ok")
        self.assertEqual(body["head"], "abc1234")

    def test_sync_rebuild_ok_errors_trims_log_to_40_lines(self):
        def fake_build(D=None, force=False):
            return BuildOkWithErrors(
                [{"line": 1, "msg": "x"}], "\n".join("l%d" % i for i in range(200)), 0.01, None, 1.0, None, "-", "", 1
            )

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(body["log"].splitlines()), 40)

    def test_sync_rebuild_log1_query_bypasses_diet(self):
        def fake_build(D=None, force=False):
            return BuildOk("keep-full", 0.01, None, 1.0, None, "-", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["log"], "keep-full")

    def test_get_api_build_applies_same_diet_and_log1_bypasses(self):
        def fake_build(D=None, force=False):
            return BuildOk("font path\n" * 200, 0.01, None, 1.0, None, "-", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build):
            ps.APP.build_requests.build_all(ps.APP.docs[0])
        out = self.talk(req("GET", "/api/build"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log_tail", body)
        out = self.talk(req("GET", "/api/build?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn("log_tail", body)

    def test_rebuild_response_shrinks_on_success(self):
        # same axis as the live measurement (the live check) — mocking confirms the same conclusion quickly.
        big_log = "font path\n" * 300

        def fake_build_before(D=None, force=False):
            return BuildOk(big_log, 0.01, None, 1.0, None, "-", "", 1)

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=fake_build_before):
            before = self.talk(req("POST", "/api/rebuild?log=1"))
            after = self.talk(req("POST", "/api/rebuild"))
        self.assertGreater(len(before), len(after))


class StartupRefusals(unittest.TestCase):
    """A startup step that cannot go on returns a StartupRefused; main() is the one place the process exits (R3)."""

    def test_only_main_exits(self):
        """No function of server.py but main() calls sys.exit: every other step hands its refusal back."""
        import ast

        tree = ast.parse(Path(ps.__file__).read_text(encoding="utf-8"))
        callers = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                f = call.func
                if isinstance(f, ast.Attribute) and f.attr == "exit" and getattr(f.value, "id", None) == "sys":
                    callers.add(fn.name)
        self.assertEqual(callers, {"main"})

    def test_main_file_and_port_refusals_are_values(self):
        """No or several top-level .tex files, and no free port, are refusals with the message main() prints."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            refused = startup_documents.detect_main(root)
            self.assertEqual(
                refused,
                StartupRefused(
                    "%s: found none top-level .tex files under %s. Specify one with "
                    "--main.\n  (none)" % (startup.APP_NAME, root)
                ),
            )
            (root / "a.tex").write_text("\\documentclass{article}\n")
            self.assertEqual(startup_documents.detect_main(root), root / "a.tex")
            (root / "b.tex").write_text("\\documentclass{article}\n")
            self.assertTrue(startup_documents.detect_main(root).message.endswith("\n  - a.tex\n  - b.tex"))
        with mock.patch.object(startup.socket, "socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 0  # every port answers: all taken
            self.assertEqual(
                startup.free_port(18300, 18302),
                StartupRefused("No free port in the 18300-18302 range. Specify one with --port."),
            )


class BuildHtmlSubstitution(unittest.TestCase):
    """Viewer HTML substitutes escaped branding next to the Limn logo."""

    def test_label_and_accent_appear_in_output(self):
        """The served page (limn.viewer.assemble.run_page over the template) fills the label (title, identity crumb
        after the Limn mark), the accent stripe and every placeholder."""
        out = page_for("A-DEMO", "#1d4ed8")
        self.assertIn("<title>Limn · A-DEMO</title>", out)
        # the Limn mark (test_brand.py)
        self.assertIn('id="paper-identity-mark" aria-hidden="true"><svg class="limn-mark"', out)
        # the instance's own name is never translated (translate="no")
        self.assertIn('</svg></span><span translate="no">A-DEMO</span>', out)
        self.assertNotIn('id="brand-chip"', out)
        self.assertIn('id="brand-stripe" style="background:#1d4ed8"', out)
        self.assertNotIn("__LABEL__", out)
        self.assertNotIn("__LIMN_", out)
        self.assertNotIn("__ICON_KEY__", out)
        self.assertNotIn("__ACCENT__", out)

    def test_label_is_html_escaped(self):
        out = page_for("<script>alert(1)</script>", "#1d4ed8")
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_the_label_never_reaches_the_favicon_links(self):
        """The favicons are the vendored brand files (test_brand.py): the <head> links are the same bytes for any
        label or accent, so no label character can break them."""
        links = lambda page: page[page.index("<title>") : page.index("<style>")].split("</title>", 1)[1]  # noqa: E731
        self.assertEqual(links(page_for('<a href="x">', "#1d4ed8")), links(page_for("A-DEMO", "#be123c")))


class ImportReadsNoFile(unittest.TestCase):
    """Importing server.py reads no data file: the viewer package (~49 files) is read by start(), never at import."""

    def test_loading_the_module_opens_only_python_sources(self):
        """Load server.py by path in a fresh interpreter with an audit hook on `open`: every file opened under
        src/limn while the module loads is Python source or bytecode - no viewer part, ui_en.json or sw.js."""
        code = (
            "import importlib.util, sys\n"
            "seen = []\n"
            "sys.addaudithook(lambda ev, args: seen.append(str(args[0])) if ev == 'open' and args else None)\n"
            "spec = importlib.util.spec_from_file_location('s', %r)\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "print('\\n'.join(p for p in seen if p.startswith(%r) and not p.endswith(('.py', '.pyc'))))\n"
        ) % (str(PKG / "server.py"), str(PKG))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), [])


class ProcessRuntime(Base):
    """new_runtime / Runtime: the per-process resources are one value made fresh for each start, and stop() ends the
    long-lived threads it started."""

    def runtime(self):
        """A fresh Runtime serving a stand-in viewer."""
        return ps.new_runtime(viewer_assemble.ServedViewer("<p></p>", "", {}))

    def test_each_runtime_owns_fresh_resources(self):
        """Two runtimes share no lock, cache, registry or status object, and a new one has no thread and is not
        stopping - so a restart (or a test) starts from nothing held over."""
        a, b = self.runtime(), self.runtime()
        shared = [
            f.name for f in dataclasses.fields(a) if f.name != "viewer" and getattr(a, f.name) is getattr(b, f.name)
        ]
        self.assertEqual(shared, [])
        self.assertEqual((a.threads, a.stopping.is_set()), ([], False))

    def test_stop_ends_both_watch_threads(self):
        """The view-only PDF watch and the remote-main watch, started as prepare() starts them, end on stop(); a second
        stop() is harmless."""
        rt = self.runtime()
        rounds = []
        with mock.patch.object(ps.APP, "docs", []):
            rt.start_thread(ps.APP.build_requests.watch_pdf_docs, rt.stopping, 0.01)
            rt.start_thread(rt.sync_watch.watch, rt.stopping, 0.01, lambda: rounds.append(1) or {}, lambda: "t")
            self.assertTrue(all(t.is_alive() for t in rt.threads))
            rt.stop(timeout=5)
        self.assertEqual([t.is_alive() for t in rt.threads], [False, False])
        self.assertGreater(len(rounds), 0)
        rt.stop(timeout=0)

    def test_failed_watch_start_does_not_mask_error_during_cleanup(self):
        """A second watch that cannot start is not joined, while the first started watch still stops."""
        rt = self.runtime()
        rt.start_thread(rt.stopping.wait)
        with (
            mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start watch")),
            self.assertRaisesRegex(RuntimeError, "cannot start watch"),
        ):
            rt.start_thread(rt.stopping.wait)
        rt.stop()
        self.assertEqual(len(rt.threads), 1)
        self.assertFalse(rt.threads[0].is_alive())

    def test_two_starts_in_one_module_keep_http_apps_and_runtimes_separate(self):
        """Starting a second listener cannot replace the first listener's HTTP app or cleanup target."""
        first_config = run_config(self.src, self.main, self.src.parent / "first", label="First", port=0)
        second_config = run_config(self.src, self.main, self.src.parent / "second", label="Second", port=0)

        def prepare(app, _docs, _no_build):
            """Give each real listener a document and a watch thread without building LaTeX."""
            app.environment.docs[:] = [
                ps.Doc(
                    app.environment.C.label.lower(), app.environment.C.label, legacy=True, paths=app.environment.C.paths
                )
            ]
            app.environment.RT.start_thread(app.environment.RT.stopping.wait)
            return None

        def get(started, path):
            """Read one response through the listener's actual TCP socket and bound handler."""
            conn = http.client.HTTPConnection(*started.server.server_address[:2], timeout=5)
            try:
                conn.request("GET", path)
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                return response.read()
            finally:
                conn.close()

        started = []
        threads = []
        fixture_app = ps.Handler.app
        with (
            mock.patch.object(ps.startup, "access_options", return_value=first_config.access),
            mock.patch.object(
                ps, "configure_run", side_effect=[ps.RunStart(first_config, None), ps.RunStart(second_config, None)]
            ),
            mock.patch.object(ps, "read_viewer"),
            mock.patch.object(
                ps,
                "serve_viewer",
                side_effect=lambda _, label, _accent, _ui_lang: viewer_assemble.ServedViewer(f"<p>{label}</p>", "", {}),
            ),
            mock.patch.object(ps, "prepare", autospec=True, side_effect=prepare),
            mock.patch.object(ps, "report"),
        ):
            try:
                for _ in range(2):
                    result = ps.start(mock.Mock(port=0, no_build=True))
                    self.assertNotIsInstance(result, StartupRefused)
                    started.append(result)
                    thread = threading.Thread(target=result.server.serve_forever, daemon=True)
                    thread.start()
                    threads.append(thread)

                first, second = started
                self.assertIsNot(first.app, second.app)
                self.assertIsNot(first.server.RequestHandlerClass, second.server.RequestHandlerClass)
                self.assertIs(first.server.RequestHandlerClass.app, first.app)
                self.assertIs(second.server.RequestHandlerClass.app, second.app)
                self.assertIs(ps.Handler.app, fixture_app)
                self.assertIsNot(first.runtime.pin_lock, second.runtime.pin_lock)
                self.assertEqual(get(first, "/"), b"<p>First</p>")
                self.assertEqual(get(second, "/"), b"<p>Second</p>")
                self.assertEqual(json.loads(get(first, "/api/docs"))["docs"][0]["name"], "First")
                self.assertEqual(json.loads(get(second, "/api/docs"))["docs"][0]["name"], "Second")
                self.assertFalse(first.runtime.stopping.is_set())
                first.runtime.stop()
                self.assertFalse(second.runtime.stopping.is_set())
                self.assertEqual(get(second, "/"), b"<p>Second</p>")
            finally:
                for index, result in enumerate(started):
                    server = result.server if hasattr(result, "server") else result
                    if index < len(threads):
                        server.shutdown()
                    server.server_close()
                    runtime = result.runtime if hasattr(result, "runtime") else ps.APP.RT
                    runtime.stop()
                for thread in threads:
                    thread.join(5)

    def test_failed_second_start_stops_only_its_own_watch(self):
        """A later startup failure cleans its own watch without ending an earlier run's watch."""
        config = run_config(self.src, self.main, self.src.parent / "run", port=0)
        apps = []

        def prepare(app, _docs, _no_build):
            """Register a real waiting thread in each app so cleanup has an observable target."""
            apps.append(app)
            app.environment.RT.start_thread(app.environment.RT.stopping.wait)
            return None

        with (
            mock.patch.object(ps.startup, "access_options", return_value=config.access),
            mock.patch.object(ps, "configure_run", return_value=ps.RunStart(config, None)),
            mock.patch.object(ps, "read_viewer"),
            mock.patch.object(ps, "serve_viewer", return_value=viewer_assemble.ServedViewer("", "", {})),
            mock.patch.object(ps, "prepare", autospec=True, side_effect=prepare),
            mock.patch.object(ps, "report"),
            mock.patch.object(ps, "listen", side_effect=[mock.Mock(), OSError("listen failed")]),
        ):
            first = ps.start(mock.Mock(port=0, no_build=True))
            try:
                self.assertIsInstance(first, ps.StartedServer)
                with self.assertRaisesRegex(OSError, "listen failed"):
                    ps.start(mock.Mock(port=0, no_build=True))
                self.assertIs(first.app, apps[0].web)
                self.assertFalse(apps[0].environment.RT.stopping.is_set())
                self.assertTrue(apps[0].environment.RT.threads[0].is_alive())
                self.assertTrue(apps[1].environment.RT.stopping.is_set())
                self.assertFalse(apps[1].environment.RT.threads[0].is_alive())
            finally:
                apps[0].environment.RT.stop()

    def cleanup_run(self, serving_error=None):
        """Create a real listener/watch pair; stop serving normally or at its next poll.

        The faulting server still runs the standard library's real polling loop.
        Cleanup callbacks bound all resources even if the behavior under test fails.
        """

        class FaultingServer(ps.Server):
            """Inject a serving failure after a real poll, without replacing cleanup."""

            def service_actions(self):
                """End serving with the requested failure after the listener was polled."""
                raise serving_error

        server_type = ps.Server if serving_error is None else FaultingServer
        server = server_type(("127.0.0.1", 0), ps.Handler)
        rt = self.runtime()
        rt.start_thread(rt.stopping.wait)
        self.addCleanup(server.server_close)
        self.addCleanup(rt.stop)
        if serving_error is None:
            stopper = threading.Thread(target=server.shutdown, daemon=True)
            stopper.start()
            self.addCleanup(stopper.join, 5)
        return ps.StartedServer(server, ps.assemble_application(ps.APP.C, rt).web, rt)

    def assert_run_released(self, started):
        """The listener descriptor and all real watch threads are released."""
        self.assertEqual(started.server.socket.fileno(), -1)
        self.assertTrue(started.runtime.stopping.is_set())
        self.assertTrue(all(not thread.is_alive() for thread in started.runtime.threads))

    def close_failure(self):
        """Inject a socket API failure after its descriptor is actually released."""
        close = socket.socket.close

        def fail(sock):
            """Release the OS resource before reporting the requested close failure."""
            close(sock)
            raise OSError("cannot close socket")

        return mock.patch.object(socket.socket, "close", fail)

    def join_failure(self):
        """Inject a threading boundary failure after the watch actually terminates."""
        join = threading.Thread.join

        def fail(thread, timeout=None):
            """Wait for real termination before reporting the requested join failure."""
            join(thread, timeout)
            raise OSError("cannot stop runtime")

        return mock.patch.object(threading.Thread, "join", fail)

    def test_main_stops_the_runtime_when_serving_ends(self):
        """Ctrl-C propagates while the actual listener and its watch are released."""
        started = self.cleanup_run(KeyboardInterrupt())
        fixture_runtime = ps.APP.RT
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
            self.assertRaises(KeyboardInterrupt),
        ):
            ps.main()
        self.assert_run_released(started)
        self.assertFalse(fixture_runtime.stopping.is_set())

    def test_main_closes_server_after_normal_serve_return(self):
        """Normal shutdown closes the real listener and joins its watch thread."""
        started = self.cleanup_run()
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
        ):
            ps.main()
        self.assert_run_released(started)

    def test_main_stops_runtime_even_when_server_close_fails(self):
        """A socket API failure cannot leave the real watch running after serving ends."""
        started = self.cleanup_run()
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
            self.close_failure(),
            self.assertRaisesRegex(OSError, "cannot close socket"),
        ):
            ps.main()
        self.assert_run_released(started)

    def test_main_preserves_serving_error_when_cleanup_also_fails(self):
        """Serving failure wins over socket/join failures while both resources end."""
        started = self.cleanup_run(RuntimeError("serving failed"))
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
            self.close_failure(),
            self.join_failure(),
            self.assertRaisesRegex(RuntimeError, "serving failed"),
        ):
            ps.main()
        self.assert_run_released(started)

    def test_main_reports_secondary_cleanup_error_after_normal_return(self):
        """Socket failure propagates and the secondary join failure is reported."""
        started = self.cleanup_run()
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
            self.close_failure(),
            self.join_failure(),
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            self.assertRaisesRegex(OSError, "cannot close socket"),
        ):
            ps.main()
        self.assert_run_released(started)
        self.assertIn("cannot stop runtime", stderr.getvalue())

    def test_main_does_not_treat_callers_error_as_serving_error(self):
        """An outer handled error cannot suppress a new cleanup failure or leak watches."""
        started = self.cleanup_run()
        with (
            mock.patch.object(ps, "build_arg_parser"),
            mock.patch.object(ps, "start", return_value=started),
            self.close_failure(),
        ):
            try:
                raise ValueError("outer error")
            except ValueError:
                with self.assertRaisesRegex(OSError, "cannot close socket"):
                    ps.main()
        self.assert_run_released(started)

    def test_start_stops_watch_when_listen_refuses(self):
        """A port lost after the probe cannot leave a watch thread running after startup refuses."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = run_config(root, root / "main.tex", root / "state")
            rt = self.runtime()
            refusal = StartupRefused("port taken")
            with (
                mock.patch.object(ps.startup, "access_options", return_value=cfg.access),
                mock.patch.object(ps, "configure_run", return_value=ps.RunStart(cfg, None)),
                mock.patch.object(ps, "read_viewer"),
                mock.patch.object(ps, "serve_viewer", return_value=rt.viewer),
                mock.patch.object(ps, "new_runtime", return_value=rt),
                mock.patch.object(ps, "prepare", side_effect=lambda *_: rt.start_thread(rt.stopping.wait)),
                mock.patch.object(ps, "report"),
                mock.patch.object(ps, "listen", return_value=refusal),
            ):
                self.assertEqual(ps.start(mock.Mock(port=0, no_build=True)), refusal)
            self.assertTrue(rt.stopping.is_set())
            self.assertEqual([t.is_alive() for t in rt.threads], [False])


# ---------------------------------------------------------------- §Multiple documents (--doc) — switching documents inside one viewer


class FigureMapLookups(Base):
    """ServerApplication.figure_map and doc_figure_map, the composition root's lookups of a figure build's element map
    over the run's one BuildMapCache (RT.figure_maps): documents ms (a LaTeX body) and fig (figs/, builds BUILD1 and
    BUILD2 whose July cells differ), and what document_facts hands the pin parsers."""

    def setUp(self):
        """The two documents served, fig with BUILD1 then BUILD2 written (BUILD2 on screen)."""
        super().setUp()
        self.ms = ps.Doc("ms", "본문", "tex", self.src, self.main, paths=ps.APP.C.paths)
        self.fig = helpers_figure.figure_doc(self.src, ps.APP.C.paths)
        ps.APP.set_docs([self.ms, self.fig])
        helpers_figure.write_build(self.fig, helpers_figure.BUILD1, helpers_figure.b2_map())
        helpers_figure.write_build(self.fig, helpers_figure.BUILD2, helpers_figure.b2_map(july=(0.4, 0.18, 0.07, 0.12)))

    def tearDown(self):
        """Back to the single document before the fixture removes the manuscript."""
        ps.APP.set_docs(None)
        super().tearDown()

    def july(self, fmap):
        """The July cell's box of the parsed map fmap."""
        return fmap("B2/calendar/m07", 1, (0.47, 0.18, 0.07, 0.12)).frac

    def test_a_figure_builds_map_is_parsed_once_in_the_run_and_is_that_builds_own(self):
        """figure_map gives each build its own map, the same parsed value on a second ask, out of RT.figure_maps."""
        first, second = (
            ps.APP.RT.figure_maps.get(self.fig, helpers_figure.BUILD1),
            ps.APP.RT.figure_maps.get(self.fig, helpers_figure.BUILD2),
        )
        self.assertEqual(
            (first.find("B2/calendar/m07")[1].frac, second.find("B2/calendar/m07")[1].frac),
            ((0.47, 0.18, 0.07, 0.12), (0.4, 0.18, 0.07, 0.12)),
        )
        self.assertIs(ps.APP.RT.figure_maps.get(self.fig, helpers_figure.BUILD1), first)
        self.assertIs(ps.APP.RT.figure_maps.get(self.fig, helpers_figure.BUILD1), first)

    def test_a_document_without_an_element_map_has_none_and_nothing_is_read(self):
        """A LaTeX document has no map even when a file of the map's name sits in its page directory, and the cache
        was not asked."""
        (self.ms.dir / "pages-20260926100000").mkdir(parents=True)
        (self.ms.dir / "pages-20260926100000" / limn_build.FIGMAP_NAME).write_text(
            json.dumps(helpers_figure.b2_map()), encoding="utf-8"
        )
        self.assertIsNone(ps.APP.assembly.builds.pins.elements(self.ms))
        self.assertEqual(ps.APP.RT.figure_maps.held(), 0)

    def test_a_build_without_a_copy_or_a_name_that_is_no_build_has_none(self):
        """A build the figure document does not have and a name that is a path answer None."""
        self.assertIsNone(ps.APP.RT.figure_maps.get(self.fig, "pages-20990101000000"))
        self.assertIsNone(ps.APP.RT.figure_maps.get(self.fig, "../state"))

    def test_the_map_of_the_build_on_screen_follows_the_pointer(self):
        """doc_figure_map gives the map of the build pages.cur names now: BUILD2's, then BUILD1's once the pointer
        moves back."""
        self.assertEqual(self.july(ps.APP.element_follower("fig")), (0.4, 0.18, 0.07, 0.12))
        files.atomic_write(self.fig.dir / "pages.cur", helpers_figure.BUILD1)
        self.assertEqual(self.july(ps.APP.element_follower("fig")), (0.47, 0.18, 0.07, 0.12))

    def test_a_key_that_has_no_loadable_map_on_screen_has_none(self):
        """An unknown key, a LaTeX document, a figure whose build on screen has no copy and one whose copy the parser
        refuses all answer None (a refusal is not a map)."""
        self.assertIsNone(ps.APP.element_follower("nope"))
        self.assertIsNone(ps.APP.element_follower("ms"))
        helpers_figure.write_build(self.fig, "pages-20260926120000", None)
        self.assertIsNone(ps.APP.element_follower("fig"))
        (self.fig.dir / "pages-20260926120000" / limn_build.FIGMAP_NAME).write_text("not json", encoding="utf-8")
        self.assertIsInstance(ps.APP.RT.figure_maps.get(self.fig, "pages-20260926120000"), MapRejected)
        self.assertIsNone(ps.APP.element_follower("fig"))

    def test_the_pdf_a_region_pin_records_is_read_through_the_runs_cache(self):
        """Two document_facts of the figure document (one per request) name the map's PDF with one parse of the copy
        between them: the run's cache is what they read the map through."""
        with mock.patch.object(limn_build, "parse_map", wraps=limn_build.parse_map) as parsed:
            first = ps.APP.document_facts(self.fig).pdf
            second = ps.APP.document_facts(self.fig).pdf
        self.assertEqual(first, (self.src / "figs" / "out" / "figures.pdf").resolve())
        self.assertEqual(second, first)
        self.assertEqual(parsed.call_count, 1)
        self.assertIsInstance(ps.APP.RT.figure_maps.get(self.fig, helpers_figure.BUILD2), FigureMap)


class FigurePickFeedsTheViewer(Base):
    """A figure document's pick carries what the viewer draws without asking again (index §Pick answer, P1c): the
    chosen element and every rung's element with its box, so the composer snaps its pending box to the element and the
    range ladder moves it client-side. The viewer's side of P1b's answer, run end to end through the handler."""

    def setUp(self):
        """The manuscript, the figure and the view-only PDF of helpers_figure.viewer_docs, each with a finished build."""
        super().setUp()
        self.ms, self.fig, self.rv = helpers_figure.viewer_docs(ps.APP, self.src)

    def tearDown(self):
        """Back to the single document the next test expects."""
        ps.APP.set_docs(None)
        super().tearDown()

    def pick_figure(self, drag):
        """POST /api/pick over drag [x, y, w, h] on page 1 of the figure's current build; the decoded 200 body."""
        code, _, raw = split_resp(self.talk(req("GET", "/api/meta?doc=" + helpers_figure.FIG)))
        self.assertEqual(code, 200, raw)
        page = json.loads(raw)["pages"][0]
        x, y, w, h = drag
        body = {
            "doc": helpers_figure.FIG,
            "page": 1,
            "x0": x * page["pt_w"],
            "y0": y * page["pt_h"],
            "x1": (x + w) * page["pt_w"],
            "y1": (y + h) * page["pt_h"],
            "frac": list(drag),
            "pdf_build": helpers_figure.BUILD1,
        }
        code, _, raw = split_resp(self.talk(jreq("POST", "/api/pick", body)))
        self.assertEqual(code, 200, raw)
        return json.loads(raw)

    def assert_box(self, got, want):
        """A frac equal to want within float noise."""
        self.assertEqual(len(got), 4, got)
        for g, w in zip(got, want, strict=True):
            self.assertAlmostEqual(g, w, places=6)

    def test_a_drag_in_the_july_cell_answers_every_rung_with_its_element_box(self):
        """The map chooses the cell; the rungs el/el2/fig carry the cell, the strip and the figure, each with its lines
        and its box from the build's map, and the answer's own el is the cell with its box."""
        d = self.pick_figure(helpers_figure.CELL_DRAG)
        self.assertEqual((d["via"], d["default_level"], d["el"]["id"]), ("map", "el", helpers_figure.CELL_ID))
        self.assertEqual(d["el"]["path"], [helpers_figure.ROOT_ID, helpers_figure.STRIP_ID, helpers_figure.CELL_ID])
        self.assert_box(d["el"]["frac"], helpers_figure.JULY)
        rungs = {lv["level"]: lv for lv in d["levels"]}
        want = {
            "el": (helpers_figure.CELL_ID, helpers_figure.JULY, 88, 95),
            "el2": (helpers_figure.STRIP_ID, helpers_figure.STRIP_FRAC, 80, 97),
            "fig": (helpers_figure.ROOT_ID, (0, 0, 1, 1), 12, 140),
        }
        self.assertEqual(sorted(rungs), sorted(want))
        for level, (eid, box, lo, hi) in want.items():
            with self.subTest(level=level):
                self.assertEqual((rungs[level]["el"]["id"], rungs[level]["lo"], rungs[level]["hi"]), (eid, lo, hi))
                self.assert_box(rungs[level]["el"]["frac"], box)


class MultiDoc(Base):
    """Three documents: ms (본문, key not main), rr (답변서, a different folder), rv (view-only PDF)."""

    def setUp(self):
        super().setUp()
        (self.src / "rr").mkdir()
        self.rr = self.src / "rr" / "rr.tex"
        self.rr.write_text(TEX, encoding="utf-8")
        self.pdf = self.src / "review.pdf"
        self.pdf.write_bytes(MINI_PDF)
        self.docs = startup_documents.make_docs(
            ["ms=본문:main.tex", "rr=답변서:rr/rr.tex", "rv=리뷰어 코멘트:review.pdf"], self.src, ps.APP.C
        )
        ps.APP.set_docs(self.docs)
        self.ms, self.rrd, self.rv = self.docs

    def tearDown(self):
        ps.APP.set_docs(None)
        super().tearDown()

    def fake_pages(self, D, name="pages-20260101000000", n=1):
        """Place a single page directory on that document without a real build (1x1 PNG header + a PDF copy)."""
        d = D.dir / name
        d.mkdir(parents=True, exist_ok=True)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + (417).to_bytes(4, "big")
            + (417).to_bytes(4, "big")
            + b"\x08\x02\x00\x00\x00"
        )
        for i in range(1, n + 1):
            (d / ("page-%d.png" % i)).write_bytes(png)
        (d / D.pdf_name).write_bytes(MINI_PDF)
        files.atomic_write(D.dir / "pages.cur", name)
        return d

    def test_state_layout_per_doc(self):
        self.assertEqual(self.ms.dir, ps.APP.C.state / "docs" / "ms")
        self.assertEqual(self.rv.dir, ps.APP.C.state / "docs" / "rv")
        self.assertEqual(limn_build.cur_pages(self.rrd), ps.APP.C.state / "docs" / "rr" / "pages")
        self.assertEqual(ps.APP.C.pins_jsonl, ps.APP.C.state / "pins.jsonl")  # one pin store shared across documents

    def test_single_doc_mode_keeps_legacy_paths(self):
        ps.APP.set_docs(None)
        self.assertEqual(len(ps.APP.docs), 1)
        self.assertTrue(ps.APP.docs[0].legacy)
        self.assertEqual(limn_build.cur_pages(ps.APP.docs[0]), ps.APP.C.state / "pages")
        self.assertEqual(ps.APP.docs[0].build, ps.APP.C.build)
        self.assertEqual(ps.APP.docs[0].paths, ps.APP.C.paths)  # the frozen run paths it was made with
        pid = self.add()
        self.assertEqual(self.pin(pid)["doc"], "main")
        md = ps.APP.pin_markdown.pins_md_text(ps.APP.snapshot_pins())
        self.assertNotIn("## ", md)  # the old look, no subsections
        self.assertIn("| # | 쪽 | 위치 | 범위 | 메모 |", md)

    def test_old_pin_without_doc_reads_as_first_doc_without_rewrite(self):
        rec = {
            "id": 1,
            "file": str(self.main),
            "lo": 4,
            "hi": 5,
            "page": 1,
            "note": "옛 핀",
            "at": "2026-09-01 10:00:00",
        }
        ps.APP.C.pins_jsonl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = ps.APP.pin_listing.pins_payload(ps.APP.read_pins()[0], True)
        self.assertEqual(rows[0]["doc"], "ms")  # the first document
        self.assertNotIn('"doc"', ps.APP.C.pins_jsonl.read_text(encoding="utf-8"))  # no migration write occurs
        self.assertEqual(ps.APP.document_views.docs_payload()["docs"][0]["n_open"], 1)

    def test_api_docs_lists_kind_and_counts(self):
        add_pin({"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr"}, dict(LOCAL_ACTOR)).record["id"]
        add_pin({"file": str(self.rr), "lo": 8, "hi": 8, "page": 1}, dict(LOCAL_ACTOR), doc=self.rrd).record["id"]
        code, _, body = split_resp(self.talk(req("GET", "/api/docs")))
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertTrue(d["multi"])
        self.assertEqual(
            [(x["key"], x["kind"], x["view_only"], x["n_open"]) for x in d["docs"]],
            [("ms", "tex", False, 0), ("rr", "tex", False, 2), ("rv", "pdf", True, 0)],
        )
        self.assertEqual(d["docs"][1]["path"], "rr/rr.tex")

    def test_meta_and_pages_follow_doc_param(self):
        self.fake_pages(self.rrd, n=2)
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=rr")))
        m = json.loads(body)
        self.assertEqual(
            (m["doc"], m["main"], len(m["pages"]), m["kind"], m["multi"]), ("rr", "rr.tex", 2, "tex", True)
        )
        self.assertEqual([x["key"] for x in m["docs"]], ["ms", "rr", "rv"])
        self.assertIn("rr=", m["src_sig"])
        code, _, _ = split_resp(self.talk(req("GET", "/pages/page-2.png?doc=rr")))
        self.assertEqual(code, 200)
        code, _, _ = split_resp(self.talk(req("GET", "/pages/page-2.png?doc=ms")))  # ms has no pages
        self.assertEqual(code, 404)
        code, hdrs, _ = split_resp(self.talk(req("GET", "/pdf?doc=rr")))
        self.assertEqual((code, hdrs["content-type"]), (200, "application/pdf"))
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=nope")))
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["docs"], ["ms", "rr", "rv"])

    def test_pin_doc_is_inferred_from_file_and_body_query_must_agree(self):
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "rr/rr.tex", "lo": 4, "hi": 5})))
        self.assertEqual(code, 200)
        self.assertEqual(self.pin(json.loads(body)["id"])["doc"], "rr")  # agent curl — inferred from file
        code, _, _ = split_resp(
            self.talk(jreq("POST", "/api/pin?doc=ms", {"file": "main.tex", "lo": 4, "hi": 5, "doc": "rr"}))
        )
        self.assertEqual(code, 400)
        code, _, body = split_resp(self.talk(jreq("GET", "/api/pins?doc=rr")))
        self.assertEqual([p["doc"] for p in json.loads(body)], ["rr"])

    WENDY = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def _notices(self, since=0):
        """The (type, doc) of every events.jsonl record after the first `since` ones, in order."""
        return [(e["type"], e["doc"]) for e in ps.APP.notices.read()[0][since:]]

    def test_new_line_pin_notices_name_the_pins_own_document(self):
        """A new line pin in the second document queues its mention and assigned notices with that document's key.

        Regression: the notices were built before the record had its doc, so pin_doc_key read the first document (ms)
        and the viewer opened a notice about a pin in rr on the wrong document.
        """
        ps.APP.people_directory.record(dict(self.WENDY))
        pin = add_pin(
            {
                "file": str(self.rr),
                "lo": 4,
                "hi": 5,
                "page": 1,
                "doc": "rr",
                "note": "@Wendy Kim 이 정의 확인",
                "assignee": self.WENDY["login"],
            },
            dict(BOB_ACTOR),
        )
        self.assertEqual(pin.record["doc"], "rr")
        self.assertEqual(self._notices(), [("mention", "rr"), ("assigned", "rr")])

    def test_later_notices_about_a_pin_name_its_document(self):
        """Edit, reply, close and reopen notices about a pin in the second document carry that document's key: they
        are made from the stored record, which has its doc."""
        ps.APP.people_directory.record(dict(self.WENDY))
        pid = add_pin(
            {"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr", "note": "정의 확인"}, dict(BOB_ACTOR)
        ).record["id"]
        n = len(ps.APP.notices.read()[0])
        edit = {"base_rev": 0, "note": "@Wendy Kim 정의 확인", "assignee": self.WENDY["login"]}
        self.assertEqual(edit_pin(pid, edit, dict(BOB_ACTOR)).record["doc"], "rr")
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/reply" % pid, {"text": "봤어요"})))[0], 200)
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/close" % pid, {"reply": "고침"})))[0], 200)
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/reopen" % pid, {"reason": "아직"})))[0], 200)
        self.assertEqual(
            self._notices(n),
            [("mention", "rr"), ("assigned", "rr"), ("replied", "rr"), ("review_requested", "rr"), ("reopened", "rr")],
        )

    def test_view_only_pick_returns_region_without_synctex(self):
        self.fake_pages(self.rv)
        with (
            mock.patch.object(pick_source, "region_text", return_value="Reviewer   one\n comment"),
            mock.patch.object(pick_source, "by_synctex", side_effect=AssertionError("SyncTeX must not be called")),
        ):
            code, _, body = split_resp(
                self.talk(jreq("POST", "/api/pick", {"doc": "rv", "page": 1, "x0": 10, "y0": 20, "x1": 110, "y1": 60}))
            )
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual(
            (d["kind"], d["view_only"], d["page"], d["quote"], d["pdf"]),
            ("region", True, 1, "Reviewer one comment", "review.pdf"),
        )
        self.assertNotIn("lo", d)
        self.assertEqual(len(d["frac"]), 4)  # even without frac in the request, it's built from coordinates

    def test_view_only_pin_save_validation_and_pins_md(self):
        self.fake_pages(self.rv, n=3)
        ok = {"doc": "rv", "page": 2, "frac": [0.1, 0.2, 0.5, 0.1], "note": "R1 코멘트 답변", "quote": "Reviewer one"}
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", ok)))
        self.assertEqual(code, 200, body)
        pid = json.loads(body)["id"]
        rec = self.pin(pid)
        self.assertEqual(
            (rec["doc"], rec["kind"], rec["page"], rec["pdf"]), ("rv", "region", 2, str(self.pdf.resolve()))
        )
        self.assertNotIn("file", rec)
        self.assertNotIn("lo", rec)
        self.assertTrue(fits(rec))
        for bad in (
            {"lo": 3, "hi": 4},
            {"file": "main.tex"},
            {"frac": [0.9, 0.2, 0.5, 0.1]},
            {"frac": [0.1, 0.2, 0, 0.1]},
            {"frac": [0.1, 0.2, 10**400, 0.1]},
            {"frac": None},
            {"page": 9},
        ):
            code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", dict(ok, **bad))))
            self.assertEqual(code, 400, bad)
        # validation for LaTeX documents is unchanged — a pin without lo/hi is 400
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", {"doc": "rr", "file": "rr/rr.tex", "page": 1})))
        self.assertEqual(code, 400)
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "doc": "ms"}, dict(LOCAL_ACTOR)).record["id"]
        md = ps.APP.pin_markdown.pins_md_text(ps.APP.snapshot_pins())
        self.assertIn("## 본문 · `ms` · `main.tex`", md)
        self.assertIn("## 리뷰어 코멘트 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", md)
        self.assertIn(
            "| %d | 2 | 쪽 2, 영역 가로 10–60%% 세로 20–30%% | 영역 | «Reviewer one» R1 코멘트 답변 |" % pid, md
        )
        self.assertIn("문서: 본문(`ms`) 1건 · 답변서(`rr`) 0건 · 리뷰어 코멘트(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("## 답변서", md)  # a document with no open pins gets no subsection
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)
        for line in md.splitlines():
            if line.startswith("| ") and not line.startswith("|---"):
                self.assertEqual(line.count(" | ") + 2, 6, line)  # still a 5-column table

    def test_build_stamp_word_follows_builds_from_source_through_the_listing_path(self):
        """The '기준: ... 빌드|그림' stamp for real Doc objects, not a hand-built DocHeading: with head.txt and
        built_at.txt actually on disk, the LaTeX document's stamp says '빌드' and the view-only PDF's says '그림',
        both read through the real listing path (PinMarkdown.pins_md_text -> pins_md_input -> DocHeading)."""
        self.fake_pages(self.rv)
        for D, head, built_at in ((self.ms, "aaa1111", "2026-09-25 08:00"), (self.rv, "bbb2222", "2026-09-25 09:00")):
            D.dir.mkdir(parents=True, exist_ok=True)
            (D.dir / "head.txt").write_text(head, encoding="utf-8")
            (D.dir / "built_at.txt").write_text(built_at, encoding="utf-8")
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "doc": "ms"}, dict(LOCAL_ACTOR))
        add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "n"}, dict(LOCAL_ACTOR), doc=self.rv)
        md = ps.APP.pin_markdown.pins_md_text(ps.APP.snapshot_pins())
        self.assertIn("## 본문 · `ms` · `main.tex`\n기준: aaa1111 · 빌드 2026-09-25 08:00", md, msg=md)
        self.assertIn(
            "## 리뷰어 코멘트 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)\n기준: bbb2222 · 그림 2026-09-25 09:00",
            md,
            msg=md,
        )

    def test_view_only_pin_edit_note_and_region_only(self):
        """A view-only document's pin takes a note and a region only; lines are refused (no_source_lines)."""
        self.fake_pages(self.rv)
        pid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "a"}, dict(LOCAL_ACTOR), doc=self.rv).record[
            "id"
        ]
        rev = self.pin(pid)["rev"]
        self.assertEqual(
            edit_pin(pid, {"lo": 2, "hi": 3, "base_rev": rev}, dict(LOCAL_ACTOR)),
            InputRejected(editing_input.REGION_EDIT_REFUSAL, "no_source_lines"),
        )
        # even without doc in the request, it resolves via the pin's own document
        p = record_of(edit_pin(pid, {"note": "b", "base_rev": rev}, dict(LOCAL_ACTOR)))
        self.assertEqual(p["note"], "b")
        p = record_of(
            edit_pin(
                pid,
                {"loc": {"page": 1, "frac": [0.3, 0.3, 0.2, 0.2], "quote": "new"}, "base_rev": p["rev"]},
                dict(LOCAL_ACTOR),
            )
        )
        self.assertEqual((p["frac"][0], p["quote"], p["pdf_build"]), (0.3, "new", "pages-20260101000000"))
        self.assertTrue(fits(self.pin(pid)))
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid), CloseRequest()
        )  # close/drop are resolved by id, independent of document
        self.assertTrue(self.pin(pid)["done"])

    def test_region_record_validation_is_by_shape(self):
        base = {"id": 1, "pdf": str(self.pdf), "page": 1, "frac": [0, 0, 0.5, 0.5], "kind": "region", "doc": "gone"}
        self.assertTrue(fits(base))  # even a document removed from config isn't a broken row
        self.assertFalse(fits(dict(base, lo=1, hi=2)))
        self.assertFalse(fits(dict(base, frac=None)))
        self.assertFalse(fits(dict(base, pdf="review.pdf")))  # relative path
        self.assertFalse(fits(dict(base, doc="Bad Key")))
        # a pin for a document not in config surfaces separately in pins.md (it's not hidden)
        ps.APP.C.pins_jsonl.write_text(json.dumps(base) + "\n")
        md = ps.APP.pin_markdown.pins_md_text(ps.APP.read_pins()[0])
        self.assertIn("## 설정에 없는 문서 · `gone`", md)

    def test_sync_and_overlaps_skip_region_pins(self):
        self.fake_pages(self.rv)
        rid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}, dict(LOCAL_ACTOR), doc=self.rv).record["id"]
        tid = self.add(4, 5)
        self.main.write_text("\n" + TEX, encoding="utf-8")  # lines shift down
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        rows = ps.APP.pin_listing.pins_payload(ps.APP.snapshot_pins(), False)
        by = {r["id"]: r for r in rows}
        self.assertEqual((by[tid]["lo"], by[tid]["hi"]), (5, 6))
        self.assertEqual(by[rid]["rel"], [])
        self.assertNotIn("lo", by[rid])

    def test_view_only_rebuild_is_refused_and_pick_snippet_guarded(self):
        code, _, body = split_resp(self.talk(req("POST", "/api/rebuild?doc=rv")))
        self.assertEqual(code, 400)
        code, _, _ = split_resp(self.talk(req("GET", "/api/snippet?doc=rv&file=main.tex&lo=1&hi=2")))
        self.assertEqual(code, 400)

    def test_build_lock_is_per_doc(self):
        gate = threading.Event()

        def slow_build(D=None, force=False):
            gate.wait(5)
            return BuildAborted("crashed", "x")

        with mock.patch.object(ps.APP.build_requests, "compile", side_effect=slow_build):
            self.assertEqual(ps.APP.build_requests.build_async(self.ms), BuildStarted())
            self.assertEqual(
                ps.APP.build_requests.build_async(self.ms), BuildBusy()
            )  # the same document allows only one build at a time
            self.assertEqual(ps.APP.build_requests.build_all(self.ms), BuildBusy())
            self.assertEqual(
                ps.APP.build_requests.build_async(self.rrd), BuildStarted()
            )  # different documents run concurrently
            self.assertTrue(self.ms.lock.locked() and self.rrd.lock.locked())
            gate.set()
            for _ in range(100):
                if not (self.ms.lock.locked() or self.rrd.lock.locked()):
                    break
                time.sleep(0.05)
        self.assertFalse(self.ms.lock.locked() or self.rrd.lock.locked())
        self.assertEqual(limn_build.state_snapshot(self.ms)["state"], "fail")
        self.assertEqual(limn_build.state_snapshot(self.rv)["state"], "idle")  # build state is per-document too

    def test_git_pull_is_shared_across_docs(self):
        """With several documents one pull serves the builds within the share window (shared=True); a single document
        pulls on every build."""
        calls = []

        def fake_pull(m, main_only, git):
            """Count the pull; it finds nothing new."""
            calls.append(m)
            return UpToDate(None)

        with mock.patch.object(gitsync, "pull", side_effect=fake_pull):  # the fresh Runtime's pull share (Base)
            a = ps.APP.sync_service.repo_pull()
            b = ps.APP.sync_service.repo_pull()
        self.assertEqual(len(calls), 1)  # once per repository
        self.assertNotIn("shared", a)
        self.assertTrue(b["shared"])
        ps.APP.set_docs(None)
        with mock.patch.object(gitsync, "pull", side_effect=fake_pull):
            ps.APP.sync_service.repo_pull(), ps.APP.sync_service.repo_pull()
        self.assertEqual(len(calls), 3)  # single document: once per build (unchanged from before)

    @needs_tex("pdftoppm")
    def test_view_only_pdf_renders_and_rerenders_on_change(self):
        rv = self.rv
        self.assertTrue(build_engine.pdf_changed(rv))  # not rendered yet
        res = ps.APP.build_requests.tracked(rv)
        self.assertIsInstance(res, BuildOk, res)
        first = limn_build.cur_pages(rv).name
        self.assertTrue((limn_build.cur_pages(rv) / "review.pdf").is_file())
        self.assertFalse(build_engine.pdf_changed(rv))
        self.assertFalse(
            build_engine.refresh_pdf_doc(rv, ps.APP.build_requests.build_async)
        )  # unchanged, so it doesn't redraw
        self.pdf.write_bytes(MINI_PDF.replace(b"Reviewer one", b"Reviewer two"))
        os.utime(self.pdf, (time.time() + 3, time.time() + 3))
        self.assertTrue(build_engine.pdf_changed(rv))
        # a render within the same second still gets a page directory of its own (test_build.Outcomes)
        res = ps.APP.build_requests.tracked(rv)
        self.assertIsInstance(res, BuildOk)
        self.assertNotEqual(limn_build.cur_pages(rv).name, first)
        self.assertEqual(limn_build.state_snapshot(rv)["seq"], 2)
        b = limn_build.load_builds(rv)["by"]
        # the source of location estimation
        self.assertNotEqual(b[first]["src_hash"], b[limn_build.cur_pages(rv).name]["src_hash"])


# ---------------------------------------------------------------- estimated time to finish (eta_min) — server/pins.md/viewer display
# '⏳ 처리 중 · ~04:02' read like an expected completion time, but it was actually the claim's
# auto-release time (another session claimed 23 items at once with a 480-minute ttl, 2026-09-23). Now
# the agent supplies an estimate (eta_min), and the screen shows it rounded up to the nearest 5 minutes,
# as '약 15분 · 20:40쯤'. The claim lock remains only a safety net, capped at 120 minutes.
class ClaimEta(Base):
    """Claim requests carry ETA values while clamping older clients' oversized input."""

    A = {"login": "alice@example.com", "name": "Wendy"}
    B = {"login": "bob@example.com", "name": "Bob"}

    def test_http_claim_with_eta(self):
        pid = self.add()
        hj = {"Content-Type": "application/json"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, json.dumps({"eta_min": 15}).encode(), hj))
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)
        pin = json.loads(body)["pin"]
        self.assertAlmostEqual(pin["eta_ts"] - pin["claim_ts"], 900, delta=2)
        self.assertEqual(json.loads(body)["ttl_min_applied"], 30)
        self.assertEqual(json.loads(body)["eta_min_applied"], 15)
        for bad in ({"eta_min": 0}, {"eta_min": "15"}, {"ttl_min": 0}, {"ttl_min": "480"}):
            out = self.talk(req("POST", "/api/pins/%d/claim" % pid, json.dumps(bad).encode(), hj))
            self.assertEqual(split_resp(out)[0], 400, bad)

    def test_http_claim_clamps_over_limit_values_for_old_agents(self):
        """An agent that claims with ttl_min=480 (the old skill procedure) gets 200 with 120 applied, and extending with
        the same values clamps eta_min to 240; deadlines are measured from the frozen clock, so they are exact."""
        pid = self.add()
        hj = {"Content-Type": "application/json"}
        t0 = 1790384400.0  # 2026-09-26 10:00:00 +09:00
        with mock.patch("time.time", return_value=t0):
            out = self.talk(req("POST", "/api/pins/%d/claim" % pid, json.dumps({"ttl_min": 480}).encode(), hj))
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)
        got = json.loads(body)
        self.assertEqual(got["ttl_min_applied"], 120)
        self.assertNotIn("eta_min_applied", got)
        self.assertEqual(got["pin"]["claim_until"], t0 + 120 * 60)
        with mock.patch("time.time", return_value=t0):
            out = self.talk(
                req("POST", "/api/pins/%d/claim" % pid, json.dumps({"ttl_min": 480, "eta_min": 300}).encode(), hj)
            )
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)  # extending under the same identity (no header = local/agent)
        got = json.loads(body)
        self.assertEqual((got["ttl_min_applied"], got["eta_min_applied"]), (120, 240))
        self.assertEqual(got["pin"]["eta_ts"], t0 + 240 * 60)


class ClaimEtaDocs(unittest.TestCase):
    """Whether SKILL.md's pin-handling procedure teaches "claim only that pin right before fixing it, estimate via eta_min"."""

    def test_skill_claim_step_teaches_single_pin_and_estimate(self):
        en, ko = SKILL_MD.read_text(encoding="utf-8"), SKILL_KO.read_text(encoding="utf-8")
        self.assertIn("claim only that pin, right before you edit it", en)
        self.assertIn("고치기 직전에 그 핀만 claim", ko)
        for skill, rows in (
            (
                en,
                (
                    "| Typo or single word | 5 |",
                    "| One sentence | 5–10 |",
                    "| Rewrite a paragraph | 10–20 |",
                    "| Restructure / several places | 20–40 |",
                ),
            ),
            (
                ko,
                (
                    "| 오타·단어 | 5 |",
                    "| 문장 하나 | 5–10 |",
                    "| 문단 다시 쓰기 | 10–20 |",
                    "| 구조 변경·여러 곳 | 20–40 |",
                ),
            ),
        ):
            self.assertIn('"eta_min"', skill)
            for row in rows:
                self.assertIn(row, skill)
            self.assertNotIn("⏳", skill)
        api = (DOCS_DIR / "api.md").read_text(encoding="utf-8")
        self.assertIn("`eta_min` | 1..240", api)
        self.assertIn("`ttl_min` | 1..120", api)
        self.assertIn("min(120, max(30, eta_min×2))", api)

    def test_epoch_claim_fields_are_valid_record_fields(self):
        base = {"id": 1, "file": "/x.tex", "lo": 1, "hi": 2, "claim_ts": 1.5, "eta_ts": 2.5, "claim_until": 3.0}
        self.assertTrue(fits(base))
        self.assertFalse(fits(dict(base, eta_ts="soon")))
        self.assertFalse(fits(dict(base, claim_ts="20:02")))


# ---------------------------------------------------------------- pin kind (fix request / question) · thread · reply (docs/handbook/api.md §스레드)
# 10 of 42 pins (24%) in A-DEMO were questions rather than fix requests (#30 "what does it mean for the
# interval to include 0?", etc.). With only a single close-reason field to answer in, there was no way to
# ask a follow-up. kind_req now distinguishes the kind, and each pin has a thread so people and agents can
# go back and forth. All new fields are optional.
class KindAndThread(Base):
    """Pin routes preserve reply identity, thread validation, and bodyless close behavior."""

    S = {"login": "bob@example.com", "name": "Bob Park"}

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        out = self.talk(req("POST", path, json.dumps(body).encode(), h))
        code, _, raw = split_resp(out)
        return code, json.loads(raw)

    def test_reply_endpoint_appends_message_with_header_identity(self):
        pid = self.add()
        code, d = self.post(
            "/api/pins/%d/reply" % pid,
            {"text": "  0 은 전 구간 평균입니다\r\n두 번째 줄 "},
            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]},
        )
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(d["msg"]["id"], 1)
        # CRLF -> LF, leading/trailing whitespace stripped
        self.assertEqual(d["msg"]["text"], "0 은 전 구간 평균입니다\n두 번째 줄")
        self.assertEqual(d["msg"]["by"], {"login": self.S["login"], "name": self.S["name"]})
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "에이전트 답"})
        self.assertEqual(d["msg"]["id"], 2)
        self.assertEqual(d["msg"]["by"]["login"], "local")
        p = self.pin(pid)
        self.assertEqual([m["id"] for m in p["thread"]], [1, 2])
        self.assertFalse(p.get("done"))  # a reply doesn't change the status
        self.assertEqual(p["rev"], 2)

    def test_reply_validation(self):
        pid = self.add()
        for body in (
            {},
            {"text": ""},
            {"text": "   "},
            {"text": 5},
            {"text": "x" * (lifecycle_input.THREAD_TEXT_MAX + 1)},
        ):
            code, d = self.post("/api/pins/%d/reply" % pid, body)
            self.assertEqual(code, 400, body)
        self.assertNotIn("thread", self.pin(pid))
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "x" * lifecycle_input.THREAD_TEXT_MAX})
        self.assertEqual(code, 200)
        code, d = self.post("/api/pins/999/reply", {"text": "없음"})
        # a nonexistent id follows the same convention as other routes
        self.assertEqual((code, d["ok"], d["pin"]), (200, False, None))

    def test_bodyless_close_still_works_and_records_event(self):
        pid = self.add()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out)
        th = self.pin(pid)["thread"]
        self.assertEqual([(m.get("ev"), m["text"]) for m in th], [("close", "")])

    def test_single_pin_route_and_state_field(self):
        """Single-pin responses expose computed state and missing-id status without storing the API-only state field."""
        pid = self.add()
        code, _, raw = split_resp(self.talk(req("GET", "/api/pins/%d" % pid)))
        d = json.loads(raw)
        self.assertEqual((code, d["pin"]["id"], d["pin"]["state"]), (200, pid, "open"))
        code, _, _ = split_resp(self.talk(req("GET", "/api/pins/999")))
        self.assertEqual(code, 404)
        ps.APP.pin_lifecycle.close_pin(
            pid, post_authority(ps.APP.pin_lifecycle.context().store, dict(self.S), "close", pid), CloseRequest()
        )
        rows = ps.APP.pin_listing.pins_payload(ps.APP.snapshot_pins(), True)
        self.assertEqual(rows[0]["state"], "done")
        self.assertNotIn("state", records(ps.APP.read_pins()[0])[0])  # a computed field — not stored


# ---------------------------------------------------------------- awaiting review (docs/handbook/api.md §검토 대기)
# an author reopened a pin an agent had closed in 2 of 42 cases (#28, #42), and there was no record that
# a human had seen the result. When an agent (no identity header) closes a pin, it's done=true·
# review=true (awaiting review); when a tailnet human closes it, it's done right away. A legacy
# done:true with no review field is still just done.
class ReviewState(Base):
    """HTTP review transitions distinguish agent closure from human confirmation."""

    S = {"login": "bob@example.com", "name": "Bob Park"}
    W = {"login": "wendy@example.com", "name": "Wendy Kim"}

    def post(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        out = self.talk(req("POST", path, json.dumps(body).encode() if body is not None else b"", h))
        code, _, raw = split_resp(out)
        return code, json.loads(raw)

    def test_agent_close_goes_to_review_human_close_to_done(self):
        a, b = self.add(), self.add(note="m")
        code, d = self.post("/api/pins/%d/close" % a, {"reply": "고침", "ref": "PR #9"})
        self.assertEqual((code, d["state"], d["pin"]["review"], d["pin"]["done"]), (200, "review", True, True))
        code, d = self.post("/api/pins/%d/close" % b, None, {"Tailscale-User-Login": self.S["login"]})
        self.assertEqual(d["state"], "done")
        self.assertNotIn("review", d["pin"])

    def test_explicit_review_flag_wins(self):
        a, b = self.add(), self.add(note="m")
        code, d = self.post("/api/pins/%d/close" % a, {"review": True}, {"Tailscale-User-Login": self.S["login"]})
        self.assertEqual(d["state"], "review")  # a remote agent closing via a tailnet address
        code, d = self.post("/api/pins/%d/close" % b, {"review": False})
        self.assertEqual(d["state"], "done")
        code, d = self.post("/api/pins/%d/close" % self.add(), {"review": "yes"})
        self.assertEqual(code, 400)

    def test_confirm_and_idempotence(self):
        """Human confirmation records attribution once, preserves revision on retries, and refuses still-open pins."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        W = {"Tailscale-User-Login": self.W["login"], "Tailscale-User-Name": self.W["name"]}
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["state"]), (200, "done"))
        p = self.pin(pid)
        self.assertEqual(p["confirmed_by"], self.W)  # confirmation doesn't require being the author
        self.assertTrue(p["confirmed_at"])
        self.assertEqual(p["thread"][-1]["ev"], "confirm")
        rev = p["rev"]
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["ok"], self.pin(pid)["rev"]), (200, True, rev))  # already done — unchanged
        code, d = self.post("/api/pins/%d/confirm" % self.add(), None, W)
        self.assertEqual((code, d["error"]), (409, "open"))
        code, d = self.post("/api/pins/999/confirm", None, W)
        self.assertEqual((code, d["ok"]), (200, False))

    def test_agent_cannot_confirm(self):
        """Agents cannot obtain confirmation authority or mark their own work as human-reviewed."""
        # observed bug: a request without an identity header (agent/local curl) could succeed at /confirm —
        # awaiting review is a record that "a human saw this," so an agent confirming its own work defeats the purpose.
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        code, d = self.post("/api/pins/%d/confirm" % pid)  # no header = agent
        self.assertEqual(code, 403)
        self.assertIn("확인은 사람이 합니다", d.get("error", ""))
        self.assertEqual(pin_state(self.pin(pid)), "review")  # the status doesn't change
        with self.assertRaises(HTTPError) as refused:
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "confirm", pid)
        self.assertEqual((refused.exception.code, refused.exception.body["reason"]), (403, "confirm_by_human"))
        self.assertEqual(pin_state(self.pin(pid)), "review")

    def test_reopen_with_reason_appends_to_thread_and_clears_review(self):
        """Reopening records the reason and clears review; legacy repeats leave the thread unchanged."""
        pid = self.add()
        ps.APP.pin_lifecycle.close_pin(
            pid,
            post_authority(ps.APP.pin_lifecycle.context().store, dict(LOCAL_ACTOR), "close", pid),
            CloseRequest(reply="고침"),
        )
        code, d = self.post(
            "/api/pins/%d/reopen" % pid,
            {"reason": "식 번호가 아직 틀림"},
            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]},
        )
        self.assertEqual(d["state"], "open")
        p = self.pin(pid)
        self.assertNotIn("review", p)
        self.assertEqual(
            [(m.get("ev"), m["text"]) for m in p["thread"]], [("close", "고침"), ("reopen", "식 번호가 아직 틀림")]
        )
        md = ps.APP.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀림", row)
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "x" * (lifecycle_input.THREAD_TEXT_MAX + 1)})
        self.assertEqual(code, 400)
        # a body-less legacy reopen still works too (already open — thread unchanged)
        code, d = self.post("/api/pins/%d/reopen" % pid)
        self.assertEqual(code, 200)
        self.assertEqual(len(self.pin(pid)["thread"]), 2)


class SocketHarness(unittest.TestCase):
    """The socketpair helpers every handler test goes through must not fail on their own races."""

    def test_half_close_is_harmless_when_the_handler_already_closed(self):
        """An early answer closes the server end first; shut_wr() then returns instead of raising ENOTCONN."""
        a, b = socket.socketpair()
        b.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        b.close()
        try:
            shut_wr(a)
            self.assertEqual(a.recv(64), b"HTTP/1.1 400 Bad Request\r\n\r\n")
        finally:
            a.close()


if __name__ == "__main__":
    unittest.main()
