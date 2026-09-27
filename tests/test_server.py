"""server.py - the composition root and the wired handler, driven over a socketpair (no port is opened).

What stays here is what only server.py can answer: its own functions and bindings (app_version, build_html,
favicon_href, valid_rec - the store's record check as server.py binds it, default_pdfjs_dir, main() as the one exit),
the build response's log diet the handler applies (ResponseDiet: limn.web.answers.diet_log, kept here beside the
rebuild route's RebuildLogDiet), the requests end to end through the handler and the server's
wiring (smuggling and origin checks, the static routes, /pins.md, the build responses, several documents), and the
HTTP routes of claims with an estimate, pin kinds and threads, review and overlaps (their rules, stored fields and
pins.md lines are tested in the modules' files). A test whose subject is one module lives in that module's file
(tests/test_<module>.py), a feature that crosses modules in the feature's file (test_reply.py, test_trash.py,
test_notifications.py, test_access_paths.py); the viewer's scripts and page are tests/test_viewer.py. The shared
fixtures are tests/helpers.py.

Run: uv run pytest tests/test_server.py
"""

import json
import os
import re
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import build as limn_build, files, gitsync, locate, startup
from limn.access import LOCAL_ACTOR
from limn.pins.lifecycle import AgentCannotConfirm
from limn.pins.view import pin_state
from limn.pull import UpToDate
from limn.startup import StartupRefused
from limn.viewer import assemble as viewer_assemble
from limn.web import parse
from limn.web.answers import diet_log
from limn.web.errors import HTTPError, InputRejected

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
    jreq,
    pick,
    ps,
    record_of,
    req,
    shut_wr,
    split_resp,
)
from helpers_access import BOB_ACTOR


class Smuggling(Base):
    def test_403_body_is_not_parsed_as_next_request(self):
        pid = self.add()
        ps.C.allow = frozenset({"ok@example.com"})
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
        self.assertEqual(len(ps.snapshot_pins()), 1)
        self.assertEqual(list(ps.C.state.glob("pins_*.jsonl.bak")), [])


class CrossOrigin(Base):
    def test_foreign_origin_rejected(self):
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(
            req("POST", "/api/pin", body, {"Origin": "https://evil.example", "Content-Type": "application/json"})
        )
        self.assertIn(b" 403 ", out)
        self.assertEqual(ps.snapshot_pins(), [])

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
        pid = ps.snapshot_pins()[0]["id"]
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
        self.assertTrue(ps.host_ok("localhost:9000"))
        self.assertTrue(ps.host_ok("127.0.0.1:1"))
        self.assertTrue(ps.host_ok("[::1]:9000"))
        self.assertTrue(ps.host_ok("localhost"))  # no port is still allowed

    def test_host_ok_still_rejects_non_loopback_non_tailnet(self):
        self.assertFalse(ps.host_ok("evil.example"))
        # mimicking the server port doesn't help if the name is wrong
        self.assertFalse(ps.host_ok("evil.example:18999"))

    def test_host_ok_tailnet_unaffected(self):
        self.assertTrue(ps.host_ok("box.tail1234.ts.net"))
        self.assertTrue(ps.host_ok("box.tail1234.ts.net:443"))

    def test_origin_ok_loopback_host_accepts_any_loopback_port(self):
        # design: if Host is loopback, Origin only needs to be loopback too (port doesn't
        # matter — with SSH -L, Host/Origin ports differ from the server's bound port. Observed: after
        # forwarding 18110->18106, every POST got 403).
        self.assertTrue(ps.origin_ok("http://127.0.0.1:9000", "localhost:9000"))
        self.assertTrue(ps.origin_ok("http://localhost:18999", "127.0.0.1:18999"))
        self.assertTrue(ps.origin_ok("http://127.0.0.1:18110", "localhost:18106"))
        self.assertTrue(ps.origin_ok("http://[::1]:9000", "[::1]:9000"))
        self.assertTrue(ps.origin_ok("http://127.0.0.1:18999", None))
        self.assertFalse(ps.origin_ok("http://evil.example:18999", "localhost:18999"))
        self.assertFalse(ps.origin_ok("null", "localhost:18999"))

    def test_origin_ok_loopback_host_rejects_tailnet_origin(self):
        # bug (should -> design 3): a loopback Host accepted a *.ts.net Origin, so a public Funnel page
        # from another tailnet could send a body-less POST (close/clear) via the local user's browser
        # without a preflight (observed: 200).
        self.assertFalse(ps.origin_ok("https://evil-funnel.tailabcd.ts.net", "127.0.0.1:18999"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net", "localhost:18999"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net", None))

    def test_origin_ok_tailnet_host_requires_same_host_and_port(self):
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net"))
        # default-port normalization
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:443", "box.tail1234.ts.net"))
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net:443"))
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net:8443"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://evil.tailabcd.ts.net", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("http://127.0.0.1:18999", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:99999", "box.tail1234.ts.net"))  # wrong port

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
        self.assertEqual(len(ps.snapshot_pins()), 1)

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
        self.assertEqual(ps.snapshot_pins(), [])

    def test_forged_host_plus_identity_header_still_403(self):
        # whether relaxing Host breaks rebinding defense — a non-loopback name is still rejected.
        pid = self.add(note="secret-note-2")
        out = self.talk(req("GET", "/api/pins", headers={"Host": "evil.example", "Tailscale-User-Login": "x@y"}))
        self.assertIn(b" 403 ", out)
        self.assertNotIn(b"secret-note-2", out)
        self.assertIsNotNone(self.pin(pid))

    def test_no_origin_check_switch(self):
        ps.C.origin_check = False
        out = self.talk(
            req("GET", "/api/meta", headers={"Host": "box.example.com", "Tailscale-User-Login": "ok@example.com"})
        )
        self.assertIn(b" 200 ", out)
        # v0.2.1: an unexpected Host is accepted, but a headerless request under it is not the loopback agent
        self.assertIn(b" 403 ", self.talk(req("GET", "/api/meta", headers={"Host": "box.example.com"})))

    def test_allow_rejects_headerless_tailnet_request(self):
        ps.C.allow = frozenset({"ok@example.com"})
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
        ps.C.pdfjs_dir = d
        self.assertEqual(self.get("/vendor/pdfjs/ok.mjs")[0], 200)
        code, _h, body = self.get("/vendor/pdfjs/evil.mjs")
        self.assertEqual(code, 404)
        self.assertNotIn(b"secret-module", body)

    def test_missing_vendor_dir_is_404_not_500(self):
        ps.C.pdfjs_dir = Path(self.tmp.name) / "nowhere"
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
            d = ps.C.state / name
            d.mkdir()
            (d / "main.pdf").write_bytes(body)
        files.atomic_write(ps.C.pages_ptr, self.new)
        ps.C.build.mkdir(parents=True, exist_ok=True)
        (ps.C.build / "main.pdf").write_bytes(b"%PDF-build-dir")

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_named_build_served_as_pdf(self):
        for name, body in ((self.new, b"%PDF-new"), (self.old, b"%PDF-old")):
            code, h, got = self.get("/pdf?build=%s&v=x" % name)
            self.assertEqual(code, 200)
            self.assertEqual(h["content-type"], "application/pdf")
            self.assertEqual(h["cache-control"], "private, max-age=600")
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
        (ps.C.state / self.new / "main.pdf").unlink()
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
        m = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m["pages_build"], self.new)
        self.assertEqual(self.get("/pdf?build=%s" % m["pages_build"])[2], b"%PDF-new")


# ---------------------------------------------------------------- overlaps over HTTP (docs/handbook/api.md §겹친 핀과 덧붙이기)


class OverlapRoutes(Base):
    def test_pick_end_to_end_includes_quote_and_overlaps(self):
        import shutil as _sh

        if not (_sh.which("latexmk") and _sh.which("pdftoppm") and _sh.which("pdftotext")):
            self.skipTest("latex tools not available")
        res = ps.build_all(ps.DOCS[0])
        self.assertEqual(res["state"], "ok")
        pages = limn_build.page_list(limn_build.cur_pages(ps.DOCS[0]), ps.C.dpi)
        self.assertTrue(pages)
        p = pages[0]
        d = pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4})
        self.assertNotIn("error", d)
        self.assertIn("quote", d)
        self.assertIn("overlaps", d)
        self.assertEqual(d["pdf_build"], limn_build.cur_pages(ps.DOCS[0]).name)
        # if the screen shows an old build, it's resolved against that build and its name is returned (a drag made right after a rebuild, before the screen updates).
        b1 = limn_build.cur_pages(ps.DOCS[0]).name
        time.sleep(1.1)
        self.assertEqual(ps.build_all(ps.DOCS[0])["state"], "ok")
        self.assertNotEqual(limn_build.cur_pages(ps.DOCS[0]).name, b1)
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
        disk = ps.C.pins_md.read_text(encoding="utf-8")
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
    def tearDown(self):
        if ps.BUILD_LOCK.locked():
            ps.BUILD_LOCK.release()
        super().tearDown()

    def test_sync_rebuild_ok_omits_log(self):
        def fake_build(D=None):
            return {
                "ok": True,
                "state": "ok",
                "errors": [],
                "log": "font path\n" * 200,
                "elapsed_s": 0.01,
                "pages": 1,
                "head": "abc1234",
            }

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log", body)
        self.assertEqual(body["state"], "ok")
        self.assertEqual(body["head"], "abc1234")

    def test_sync_rebuild_ok_errors_trims_log_to_40_lines(self):
        def fake_build(D=None):
            return {
                "ok": True,
                "state": "ok_errors",
                "errors": [{"line": 1, "msg": "x"}],
                "log": "\n".join("l%d" % i for i in range(200)),
                "elapsed_s": 0.01,
                "pages": 1,
            }

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(body["log"].splitlines()), 40)

    def test_sync_rebuild_log1_query_bypasses_diet(self):
        def fake_build(D=None):
            return {"ok": True, "state": "ok", "errors": [], "log": "keep-full", "elapsed_s": 0.01, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["log"], "keep-full")

    def test_get_api_build_applies_same_diet_and_log1_bypasses(self):
        def fake_build(D=None):
            return {"ok": True, "state": "ok", "errors": [], "log": "font path\n" * 200, "elapsed_s": 0.01, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all(ps.DOCS[0])
        out = self.talk(req("GET", "/api/build"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log_tail", body)
        out = self.talk(req("GET", "/api/build?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn("log_tail", body)

    def test_rebuild_response_shrinks_on_success(self):
        # same axis as the live measurement (the live check) — mocking confirms the same conclusion quickly.
        big_log = "font path\n" * 300

        def fake_build_before(D=None):
            return {"ok": True, "state": "ok", "errors": [], "log": big_log, "elapsed_s": 0.01, "pages": 1}

        with mock.patch.object(ps, "_build", side_effect=fake_build_before):
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
            refused = startup.detect_main(root)
            self.assertEqual(
                refused,
                StartupRefused(
                    "%s: found none top-level .tex files under %s. Specify one with "
                    "--main.\n  (none)" % (startup.APP_NAME, root)
                ),
            )
            (root / "a.tex").write_text("\\documentclass{article}\n")
            self.assertEqual(startup.detect_main(root), root / "a.tex")
            (root / "b.tex").write_text("\\documentclass{article}\n")
            self.assertTrue(startup.detect_main(root).message.endswith("\n  - a.tex\n  - b.tex"))
        with mock.patch.object(startup.socket, "socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 0  # every port answers: all taken
            self.assertEqual(
                startup.free_port(18300, 18302),
                StartupRefused("No free port in the 18300-18302 range. Specify one with --port."),
            )


class BuildHtmlSubstitution(unittest.TestCase):
    def test_label_and_accent_appear_in_output(self):
        """build_html fills the label (title, identity crumb after the Limn mark), the accent stripe and every placeholder."""
        out = ps.build_html("A-DEMO", "#1d4ed8")
        self.assertIn("<title>Limn · A-DEMO</title>", out)
        # the Limn mark (test_brand.py)
        self.assertIn('id="paper-identity-mark" aria-hidden="true"><svg class="limn-mark"', out)
        self.assertIn("</svg></span><span>A-DEMO</span>", out)
        self.assertNotIn('id="brand-chip"', out)
        self.assertIn('id="brand-stripe" style="background:#1d4ed8"', out)
        self.assertNotIn("__LABEL__", out)
        self.assertNotIn("__LIMN_MARK__", out)
        self.assertNotIn("__ACCENT_KEY__", out)
        self.assertNotIn("__ACCENT__", out)
        self.assertNotIn("__FAVICON_HREF__", out)

    def test_label_is_html_escaped(self):
        out = ps.build_html("<script>alert(1)</script>", "#1d4ed8")
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_favicon_is_data_svg_of_the_mark_in_the_accent(self):
        """The favicon is the Limn mark in the accent (since 0.3.4; it used to be the label's first letter). The label
        never reaches the SVG, so no label character can break it; a non-#rrggbb accent is refused."""
        out = ps.favicon_href("#1d4ed8")
        self.assertTrue(out.startswith("data:image/svg+xml,"))
        from urllib.parse import unquote

        self.assertIn('fill="#1d4ed8"', unquote(out))
        with self.assertRaises(ValueError):
            ps.favicon_href('#1d4ed8"/><script>')


# ---------------------------------------------------------------- §Multiple documents (--doc) — switching documents inside one viewer


class MultiDoc(Base):
    """Three documents: ms (본문, key not main), rr (답변서, a different folder), rv (view-only PDF)."""

    def setUp(self):
        super().setUp()
        (self.src / "rr").mkdir()
        self.rr = self.src / "rr" / "rr.tex"
        self.rr.write_text(TEX, encoding="utf-8")
        self.pdf = self.src / "review.pdf"
        self.pdf.write_bytes(MINI_PDF)
        self.docs = startup.make_docs(
            ["ms=본문:main.tex", "rr=답변서:rr/rr.tex", "rv=리뷰어 코멘트:review.pdf"], self.src, ps.C
        )
        ps.set_docs(self.docs)
        self.ms, self.rrd, self.rv = self.docs

    def tearDown(self):
        ps.set_docs(None)
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
        self.assertEqual(self.ms.dir, ps.C.state / "docs" / "ms")
        self.assertEqual(self.rv.dir, ps.C.state / "docs" / "rv")
        self.assertEqual(limn_build.cur_pages(self.rrd), ps.C.state / "docs" / "rr" / "pages")
        self.assertEqual(ps.C.pins_jsonl, ps.C.state / "pins.jsonl")  # one pin store shared across documents

    def test_single_doc_mode_keeps_legacy_paths(self):
        ps.set_docs(None)
        self.assertFalse(ps.multi_doc())
        self.assertIs(ps.DOCS[0], ps.LEGACY_DOC)
        self.assertEqual(limn_build.cur_pages(ps.DOCS[0]), ps.C.state / "pages")
        self.assertEqual(ps.LEGACY_DOC.build, ps.C.build)
        self.assertIs(ps.LEGACY_DOC.lock, ps.BUILD_LOCK)  # the old global lock/state IS this document's
        self.assertIs(ps.LEGACY_DOC.bstate, ps.BUILD_STATE)
        pid = self.add()
        self.assertEqual(self.pin(pid)["doc"], "main")
        md = ps.pins_md_text(ps.snapshot_pins())
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
        ps.C.pins_jsonl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = ps.pins_payload(ps.read_pins()[0], True)
        self.assertEqual(rows[0]["doc"], "ms")  # the first document
        self.assertNotIn('"doc"', ps.C.pins_jsonl.read_text(encoding="utf-8"))  # no migration write occurs
        self.assertEqual(ps.docs_payload()["docs"][0]["n_open"], 1)

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
        return [(e["type"], e["doc"]) for e in ps._read_events()[0][since:]]

    def test_new_line_pin_notices_name_the_pins_own_document(self):
        """A new line pin in the second document queues its mention and assigned notices with that document's key.

        Regression: the notices were built before the record had its doc, so pin_doc_key read the first document (ms)
        and the viewer opened a notice about a pin in rr on the wrong document.
        """
        ps._EVENTS_CACHE.clear()
        ps.record_person(dict(self.WENDY))
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
        ps._EVENTS_CACHE.clear()
        ps.record_person(dict(self.WENDY))
        pid = add_pin(
            {"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr", "note": "정의 확인"}, dict(BOB_ACTOR)
        ).record["id"]
        n = len(ps._read_events()[0])
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
            mock.patch.object(locate, "region_text", return_value="Reviewer   one\n comment"),
            mock.patch.object(locate, "by_synctex", side_effect=AssertionError("SyncTeX must not be called")),
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
        self.assertTrue(ps.valid_rec(rec))
        for bad in (
            {"lo": 3, "hi": 4},
            {"file": "main.tex"},
            {"frac": [0.9, 0.2, 0.5, 0.1]},
            {"frac": [0.1, 0.2, 0, 0.1]},
            {"frac": None},
            {"page": 9},
        ):
            code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", dict(ok, **bad))))
            self.assertEqual(code, 400, bad)
        # validation for LaTeX documents is unchanged — a pin without lo/hi is 400
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", {"doc": "rr", "file": "rr/rr.tex", "page": 1})))
        self.assertEqual(code, 400)
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "doc": "ms"}, dict(LOCAL_ACTOR)).record["id"]
        md = ps.pins_md_text(ps.snapshot_pins())
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

    def test_view_only_pin_edit_note_and_region_only(self):
        """A view-only document's pin takes a note and a region only; lines are refused (no_source_lines)."""
        self.fake_pages(self.rv)
        pid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "a"}, dict(LOCAL_ACTOR), doc=self.rv).record[
            "id"
        ]
        rev = self.pin(pid)["rev"]
        self.assertEqual(
            edit_pin(pid, {"lo": 2, "hi": 3, "base_rev": rev}, dict(LOCAL_ACTOR)),
            InputRejected(parse.REGION_EDIT_REFUSAL, "no_source_lines"),
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
        self.assertTrue(ps.valid_rec(self.pin(pid)))
        ps.set_done(pid, True, dict(LOCAL_ACTOR))  # close/drop are resolved by id, independent of document
        self.assertTrue(self.pin(pid)["done"])

    def test_region_record_validation_is_by_shape(self):
        base = {"id": 1, "pdf": str(self.pdf), "page": 1, "frac": [0, 0, 0.5, 0.5], "kind": "region", "doc": "gone"}
        self.assertTrue(ps.valid_rec(base))  # even a document removed from config isn't a broken row
        self.assertFalse(ps.valid_rec(dict(base, lo=1, hi=2)))
        self.assertFalse(ps.valid_rec(dict(base, frac=None)))
        self.assertFalse(ps.valid_rec(dict(base, pdf="review.pdf")))  # relative path
        self.assertFalse(ps.valid_rec(dict(base, doc="Bad Key")))
        # a pin for a document not in config surfaces separately in pins.md (it's not hidden)
        ps.C.pins_jsonl.write_text(json.dumps(base) + "\n")
        md = ps.pins_md_text(ps.read_pins()[0])
        self.assertIn("## 설정에 없는 문서 · `gone`", md)

    def test_sync_and_overlaps_skip_region_pins(self):
        self.fake_pages(self.rv)
        rid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}, dict(LOCAL_ACTOR), doc=self.rv).record["id"]
        tid = self.add(4, 5)
        self.main.write_text("\n" + TEX, encoding="utf-8")  # lines shift down
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        rows = ps.pins_payload(ps.snapshot_pins(), False)
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

        def slow_build(D=None):
            gate.wait(5)
            return {"ok": False, "state": "fail", "errors": [], "log": "x", "elapsed_s": 0.0}

        with mock.patch.object(ps, "_build", side_effect=slow_build):
            self.assertEqual(ps.build_async(self.ms), {"state": "running"})
            self.assertTrue(ps.build_async(self.ms).get("busy"))  # the same document allows only one build at a time
            self.assertTrue(ps.build_all(self.ms).get("busy"))
            self.assertEqual(ps.build_async(self.rrd), {"state": "running"})  # different documents run concurrently
            self.assertTrue(self.ms.lock.locked() and self.rrd.lock.locked())
            self.assertFalse(ps.BUILD_LOCK.locked())  # the single-document global lock is left untouched
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

        with (
            mock.patch.object(gitsync, "pull", side_effect=fake_pull),
            mock.patch.object(ps, "PULL_SHARE", gitsync.PullShare()),
        ):
            a = ps.repo_pull()
            b = ps.repo_pull()
        self.assertEqual(len(calls), 1)  # once per repository
        self.assertNotIn("shared", a)
        self.assertTrue(b["shared"])
        ps.set_docs(None)
        with mock.patch.object(gitsync, "pull", side_effect=fake_pull):
            ps.repo_pull(), ps.repo_pull()
        self.assertEqual(len(calls), 3)  # single document: once per build (unchanged from before)

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm not available")
    def test_view_only_pdf_renders_and_rerenders_on_change(self):
        rv = self.rv
        self.assertTrue(limn_build.pdf_changed(rv))  # not rendered yet
        res = ps._build_tracked(rv)
        self.assertEqual(res["state"], "ok", res.get("log"))
        first = limn_build.cur_pages(rv).name
        self.assertTrue((limn_build.cur_pages(rv) / "review.pdf").is_file())
        self.assertFalse(limn_build.pdf_changed(rv))
        self.assertFalse(limn_build.refresh_pdf_doc(rv, ps.build_async))  # unchanged, so it doesn't redraw
        self.pdf.write_bytes(MINI_PDF.replace(b"Reviewer one", b"Reviewer two"))
        os.utime(self.pdf, (time.time() + 3, time.time() + 3))
        self.assertTrue(limn_build.pdf_changed(rv))
        time.sleep(1.1)  # page directory names are second-granularity
        res = ps._build_tracked(rv)
        self.assertEqual(res["state"], "ok")
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
        # an agent that claimed with ttl_min=480 per the old skill procedure doesn't break when extending with the same value (200, applied as 120).
        pid = self.add()
        hj = {"Content-Type": "application/json"}
        t0 = time.time()
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, json.dumps({"ttl_min": 480}).encode(), hj))
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)
        got = json.loads(body)
        self.assertEqual(got["ttl_min_applied"], 120)
        self.assertNotIn("eta_min_applied", got)
        self.assertAlmostEqual(got["pin"]["claim_until"], t0 + 120 * 60, delta=5)
        out = self.talk(
            req("POST", "/api/pins/%d/claim" % pid, json.dumps({"ttl_min": 480, "eta_min": 300}).encode(), hj)
        )
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)  # extending under the same identity (no header = local/agent)
        got = json.loads(body)
        self.assertEqual((got["ttl_min_applied"], got["eta_min_applied"]), (120, 240))
        self.assertAlmostEqual(got["pin"]["eta_ts"], time.time() + 240 * 60, delta=5)


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
        self.assertTrue(ps.valid_rec(base))
        self.assertFalse(ps.valid_rec(dict(base, eta_ts="soon")))
        self.assertFalse(ps.valid_rec(dict(base, claim_ts="20:02")))


# ---------------------------------------------------------------- pin kind (fix request / question) · thread · reply (docs/handbook/api.md §스레드)
# 10 of 42 pins (24%) in A-DEMO were questions rather than fix requests (#30 "what does it mean for the
# interval to include 0?", etc.). With only a single close-reason field to answer in, there was no way to
# ask a follow-up. kind_req now distinguishes the kind, and each pin has a thread so people and agents can
# go back and forth. All new fields are optional.
class KindAndThread(Base):
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
        for body in ({}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "x" * (parse.THREAD_TEXT_MAX + 1)}):
            code, d = self.post("/api/pins/%d/reply" % pid, body)
            self.assertEqual(code, 400, body)
        self.assertNotIn("thread", self.pin(pid))
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "x" * parse.THREAD_TEXT_MAX})
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
        pid = self.add()
        code, _, raw = split_resp(self.talk(req("GET", "/api/pins/%d" % pid)))
        d = json.loads(raw)
        self.assertEqual((code, d["pin"]["id"], d["pin"]["state"]), (200, pid, "open"))
        code, _, _ = split_resp(self.talk(req("GET", "/api/pins/999")))
        self.assertEqual(code, 404)
        ps.set_done(pid, True, dict(self.S))
        rows = ps.pins_payload(ps.snapshot_pins(), True)
        self.assertEqual(rows[0]["state"], "done")
        self.assertNotIn("state", ps.read_pins()[0][0])  # a computed field — not stored


# ---------------------------------------------------------------- awaiting review (docs/handbook/api.md §검토 대기)
# an author reopened a pin an agent had closed in 2 of 42 cases (#28, #42), and there was no record that
# a human had seen the result. When an agent (no identity header) closes a pin, it's done=true·
# review=true (awaiting review); when a tailnet human closes it, it's done right away. A legacy
# done:true with no review field is still just done.
class ReviewState(Base):
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
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
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
        # observed bug: a request without an identity header (agent/local curl) could succeed at /confirm —
        # awaiting review is a record that "a human saw this," so an agent confirming its own work defeats the purpose.
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        code, d = self.post("/api/pins/%d/confirm" % pid)  # no header = agent
        self.assertEqual(code, 403)
        self.assertIn("확인은 사람이 합니다", d.get("error", ""))
        self.assertEqual(pin_state(self.pin(pid)), "review")  # the status doesn't change
        self.assertEqual(ps.confirm_pin(pid, dict(LOCAL_ACTOR)), AgentCannotConfirm())  # a value, answered 403 above

    def test_reopen_with_reason_appends_to_thread_and_clears_review(self):
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
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
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀림", row)
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "x" * (parse.THREAD_TEXT_MAX + 1)})
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
