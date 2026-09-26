"""server.py - the composition root and the wired handler, driven over a socketpair (no port is opened).

What stays here is what only server.py can answer: its own functions (app_version, build_html, favicon_href, diet_log,
valid_rec, default_pdfjs_dir, main() as the one exit), the requests end to end through the handler and the server's
wiring (smuggling and origin checks, the static routes, /pins.md, the build responses, several documents), and the
feature classes whose tests span the API, pins.md and the viewer together (claims with an estimate, pin kinds and
threads, review, @-tags and notices, overlaps). A test whose subject is one module lives in that module's file
(tests/test_<module>.py); the viewer's scripts and page are tests/test_viewer.py. The shared fixtures are tests/helpers.py.

Run: uv run pytest tests/test_server.py
"""
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from limn import files, gitsync, locate, mapping, mentions, startup
from limn import build as limn_build
from limn.access import LOCAL_ACTOR
from limn.events import NOTIFY_TYPES
from limn.pins import render as md_render
from limn.pins import position
from limn.pins.edit import NOTE_MAX, NoteTooLong
from limn.pins.lifecycle import AgentCannotConfirm, CLAIM_FIELDS, ClaimClosedPin, ClaimedByOther, ThreadFull
from limn.pins.view import pin_state
from limn.pull import UpToDate
from limn.startup import StartupRefused
from limn.store import find_pin
from limn.viewer import assemble as viewer_assemble
from limn.web import parse
from limn.web.errors import HTTPError, InputRejected

from helpers import (
    add_pin, Base, DOCS_DIR, edit_pin, extract_js_fn, jreq, js_i18n, MINI_PDF, pick, PKG, ps, record_of, req, run_node,
    shut_wr, SKILL_KO, SKILL_MD, split_resp, TEX,
)


class Smuggling(Base):
    def test_403_body_is_not_parsed_as_next_request(self):
        pid = self.add()
        ps.C.allow = frozenset({"ok@x.com"})
        inner = req("POST", "/api/pins/%d/close" % pid)
        out = self.talk(req("POST", "/api/pin", inner, {"Tailscale-User-Login": "evil@x.com",
                                                          "Content-Type": "application/json"}))
        self.assertIn(b" 403 ", out)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_get_body_is_drained(self):
        pid = self.add()
        inner = req("POST", "/api/pins/%d/close" % pid)
        out = self.talk(req("GET", "/api/meta", inner, {"Tailscale-User-Login": "bob@x.com"}))
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertIn(b" 200 ", out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_transfer_encoding_rejected(self):
        pid = self.add()
        body = req("POST", "/api/pins/%d/close" % pid)   # a server that ignores TE would read this as the next request
        raw = (b"POST /api/pins/%d/reopen HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nTransfer-Encoding: chunked\r\n\r\n"
               % pid + body)
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_short_body_does_nothing(self):
        self.add()
        raw = b"POST /api/clear HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: 5\r\n\r\n"   # cut off without a body
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        self.assertEqual(len(ps.snapshot_pins()), 1)
        self.assertEqual(list(ps.C.state.glob("pins_*.jsonl.bak")), [])


class CrossOrigin(Base):
    def test_foreign_origin_rejected(self):
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Origin": "https://evil.example",
                                                         "Content-Type": "application/json"}))
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
        out = self.talk(req("POST", "/api/pin", body, {"Origin": "http://127.0.0.1:18999",
                                                         "Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        pid = ps.snapshot_pins()[0]["id"]
        out = self.talk(req("POST", "/api/pins/%d/close" % pid))           # curl-shaped: no body, no Origin
        self.assertIn(b" 200 ", out)
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net",
                                                         "Origin": "https://box.tail1234.ts.net",
                                                         "Tailscale-User-Login": "bob@x.com"}))
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
        out = self.talk(req("POST", "/api/pins/%d/drop" % pid, headers=h))   # POST without Origin
        self.assertIn(b" 403 ", out)
        self.assertIsNotNone(self.pin(pid))

    def test_host_ok_ignores_loopback_port_ssh_forward(self):
        # bug: host_ok used to require the port to equal C.port even for a loopback name — forwarding
        # through SSH -L to a different local port (Host: localhost:9000, server on 18999) got 403'd.
        self.assertTrue(ps.host_ok("localhost:9000"))
        self.assertTrue(ps.host_ok("127.0.0.1:1"))
        self.assertTrue(ps.host_ok("[::1]:9000"))
        self.assertTrue(ps.host_ok("localhost"))              # no port is still allowed

    def test_host_ok_still_rejects_non_loopback_non_tailnet(self):
        self.assertFalse(ps.host_ok("evil.example"))
        self.assertFalse(ps.host_ok("evil.example:18999"))    # mimicking the server port doesn't help if the name is wrong

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
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:443", "box.tail1234.ts.net"))   # default-port normalization
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net:443"))
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net:8443"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://evil.tailabcd.ts.net", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("http://127.0.0.1:18999", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:99999", "box.tail1234.ts.net"))   # wrong port

    def test_funnel_csrf_on_loopback_host_is_403_end_to_end(self):
        pid = self.add()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid,
                            headers={"Origin": "https://evil-funnel.tailabcd.ts.net"}))
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
        out = self.talk(req("POST", "/api/pin", body, {"Host": "localhost:9000",
                                                         "Origin": "http://localhost:9000",
                                                         "Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        self.assertEqual(len(ps.snapshot_pins()), 1)

    def test_ssh_forwarded_non_loopback_origin_still_rejected(self):
        # a non-loopback origin is still blocked even behind forwarding (only the port is ignored, not the name).
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Host": "localhost:9000",
                                                         "Origin": "http://evil.example:9000",
                                                         "Content-Type": "application/json"}))
        self.assertIn(b" 403 ", out)
        self.assertEqual(ps.snapshot_pins(), [])

    def test_forged_host_plus_identity_header_still_403(self):
        # whether relaxing Host breaks rebinding defense — a non-loopback name is still rejected.
        pid = self.add(note="secret-note-2")
        out = self.talk(req("GET", "/api/pins", headers={"Host": "evil.example",
                                                          "Tailscale-User-Login": "x@y"}))
        self.assertIn(b" 403 ", out)
        self.assertNotIn(b"secret-note-2", out)
        self.assertIsNotNone(self.pin(pid))

    def test_no_origin_check_switch(self):
        ps.C.origin_check = False
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.example.com", "Tailscale-User-Login": "ok@x.com"}))
        self.assertIn(b" 200 ", out)
        # v0.2.1: an unexpected Host is accepted, but a headerless request under it is not the loopback agent
        self.assertIn(b" 403 ", self.talk(req("GET", "/api/meta", headers={"Host": "box.example.com"})))

    def test_allow_rejects_headerless_tailnet_request(self):
        ps.C.allow = frozenset({"ok@x.com"})
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net"}))   # tag-device shape
        self.assertIn(b" 403 ", out)
        out = self.talk(req("GET", "/api/meta"))                                          # loopback curl
        self.assertIn(b" 200 ", out)
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net",
                                                         "Tailscale-User-Login": "ok@x.com"}))
        self.assertIn(b" 200 ", out)

    def test_non_ascii_content_length_is_400(self):
        raw = b"POST /api/pin HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: \xb2\r\n\r\n"
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        out = self.talk(b"GET /api/meta HTTP/1.1\r\nHost: 127.0.0.1:\xb2\r\n\r\n")   # same trap for the Host port
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
            self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")   # a module script only runs with the JS MIME type
            self.assertEqual(h["x-content-type-options"], "nosniff")
            self.assertEqual(h["cache-control"], "public, max-age=86400")
            self.assertEqual(body, (VENDOR / name).read_bytes())

    def test_traversal_and_non_module_names_are_404(self):
        for path in ("/vendor/pdfjs/../../server.py", "/vendor/pdfjs/..%2f..%2fserver.py",
                     "/vendor/pdfjs/%2e%2e/%2e%2e/server.py", "/vendor/pdfjs/sub/pdf.min.mjs",
                     "/vendor/pdfjs/LICENSE", "/vendor/pdfjs/README.md", "/vendor/pdfjs/.pdf.min.mjs",
                     "/vendor/pdfjs/..mjs", "/vendor/pdfjs/", "/vendor/pdfjs//etc/passwd",
                     "/vendor/pdfjs/pdf.min.mjs/", "/vendor/pdfjs/pdf.min.mjs%00.png"):
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
        self.assertEqual(code, 404)                        # the viewer sees this and falls back to PNG

    def test_host_and_origin_checked_like_other_gets(self):
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Host": "box.tail1234.ts.net",
                                                                "Origin": "https://box.tail1234.ts.net",
                                                                "Tailscale-User-Login": "a@b"})[0], 200)

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
            self.assertEqual(got, body)                   # asking for the previous build gets the previous build — not swapped for the current one

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
        (ps.C.state / self.new / "main.pdf").unlink()   # if the page directory has no matching PDF, don't fall back to build/
        code, _h, body = self.get("/pdf?build=%s" % self.new)
        self.assertEqual(code, 404)
        self.assertNotIn(b"%PDF-build-dir", body)
        self.assertEqual(self.get("/pdf")[0], 404)

    def test_host_and_origin_checked(self):
        self.assertEqual(self.get("/pdf?build=%s" % self.new, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get("/pdf?build=%s" % self.new, {"Host": "evil.example:18999",
                                                               "Tailscale-User-Login": "x@y"})[0], 403)
        self.assertEqual(self.get("/pdf?build=%s" % self.new, {"Origin": "https://evil.example"})[0], 403)
        code, _h, body = self.get("/pdf?build=%s" % self.new, {"Host": "box.tail1234.ts.net",
                                                               "Tailscale-User-Login": "a@b"})
        self.assertEqual((code, body), (200, b"%PDF-new"))

    def test_pages_build_in_meta_matches_pdf_route(self):
        m = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR), light=True)
        self.assertEqual(m["pages_build"], self.new)
        self.assertEqual(self.get("/pdf?build=%s" % m["pages_build"])[2], b"%PDF-new")


# ---------------------------------------------------------------- overlaps and note_append (docs/handbook/api.md §겹친 핀과 덧붙이기)

class Overlaps(Base):
    def test_inside_and_contains_pair(self):
        p1 = self.add(4, 9, note="outer")     # the first two paragraphs (not blank-line-free — lo/hi adjusted to overlap generously)
        p2 = self.add(4, 5, note="inner")
        rows = ps.snapshot_pins()
        rel = ps.overlaps_by_id(rows)
        self.assertEqual(rel[p2], [{"id": p1, "rel": "inside"}])
        self.assertEqual(rel[p1], [{"id": p2, "rel": "contains"}])

    def test_partial_overlap(self):
        p1 = self.add(4, 5)
        p2 = self.add(5, 6)
        rel = ps.overlaps_by_id(ps.snapshot_pins())
        self.assertEqual(rel[p1], [{"id": p2, "rel": "partial"}])
        self.assertEqual(rel[p2], [{"id": p1, "rel": "partial"}])

    def test_no_overlap_is_empty(self):
        p1 = self.add(4, 5)
        p2 = self.add(8, 9)
        rel = ps.overlaps_by_id(ps.snapshot_pins())
        self.assertEqual(rel[p1], [])
        self.assertEqual(rel[p2], [])

    def test_overlaps_for_range_matches_pick_semantics(self):
        self.add(4, 9, note="outer")
        ov = ps.overlaps_for_range(str(self.main), 4, 5)
        self.assertEqual(len(ov), 1)
        self.assertEqual(ov[0]["rel"], "inside")

    def test_overlaps_for_range_same_range_is_equal(self):
        # design 2: an identical range is reported separately as 'equal' — the viewer states "same range" and shows a banner.
        pid = self.add(4, 9, note="first")
        ov = ps.overlaps_for_range(str(self.main), 4, 9)
        self.assertEqual(ov, [{"id": pid, "lo": 4, "hi": 9, "rel": "equal"}])

    def test_selection_rel_all_four_relations(self):
        self.assertEqual(position.selection_rel(4, 9, 4, 9), "equal")
        self.assertEqual(position.selection_rel(5, 6, 4, 9), "inside")
        self.assertEqual(position.selection_rel(3, 10, 4, 9), "contains")
        self.assertEqual(position.selection_rel(8, 12, 4, 9), "partial")
        self.assertIsNone(position.selection_rel(10, 12, 4, 9))

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

    def test_note_append_then_undo(self):
        pid = self.add(note="원본")
        p0 = self.pin(pid)
        p1 = record_of(edit_pin(pid, {"note_append": "추가 텍스트"}, dict(LOCAL_ACTOR)))
        self.assertIn("추가 텍스트", p1["note"])
        self.assertIn("(추가 ", p1["note"])
        self.assertEqual(len(ps.C.pins_jsonl.read_text().splitlines()), 1)   # line count unchanged
        undone = record_of(edit_pin(pid, {"note": p0["note"], "base_rev": p1["rev"]}, dict(LOCAL_ACTOR)))
        self.assertEqual(undone["note"], p0["note"])

    def test_note_append_does_not_need_base_rev(self):
        pid = self.add()
        p = record_of(edit_pin(pid, {"note_append": "x"}, dict(LOCAL_ACTOR)))
        self.assertIn("x", p["note"])

    def test_note_append_empty_string_rejected(self):
        """An empty note_append is refused (note_append_empty) and changes nothing."""
        pid = self.add(note="원본")
        empty = InputRejected("덧붙일 메모가 비어 있습니다.", "note_append_empty")
        self.assertEqual(edit_pin(pid, {"note_append": ""}, dict(LOCAL_ACTOR)), empty)
        self.assertEqual(edit_pin(pid, {"note_append": "   "}, dict(LOCAL_ACTOR)), empty)   # whitespace only too
        self.assertEqual(self.pin(pid)["note"], "원본")        # unchanged since it was rejected

    def test_note_append_over_note_max_combined_is_rejected(self):
        pid = self.add(note="x" * (NOTE_MAX - 20))          # only 20 chars of headroom
        refused = edit_pin(pid, {"note_append": "y" * 100}, dict(LOCAL_ACTOR))   # under the per-field cap (2000), over it once combined
        self.assertIsInstance(refused, NoteTooLong)
        self.assertEqual(refused.limit, NOTE_MAX)
        self.assertEqual(len(self.pin(pid)["note"]), NOTE_MAX - 20)          # unchanged length since it was rejected
        self.assertEqual(self.pin(pid)["rev"], 0)                                # rev doesn't bump either

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
        out = self.talk(req("GET", "/pins.md", headers={"Host": "x.tail1234.ts.net:18004", "Tailscale-User-Login": "ok@x.com",
                                                        "X-Forwarded-For": "100.64.0.9"}))
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
        self.main.write_text("\n" + TEX, encoding="utf-8")   # one blank line up front — everything shifts down by one line
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
        out = ps.diet_log({"state": "ok", "log": "x" * 5000, "log_tail": "y" * 10, "pages": 3}, full=False)
        self.assertNotIn("log", out)
        self.assertNotIn("log_tail", out)
        self.assertEqual(out["pages"], 3)

    def test_ok_errors_trims_log_tail_to_40_lines(self):
        big = "\n".join("line%d" % i for i in range(100))
        out = ps.diet_log({"state": "ok_errors", "log_tail": big}, full=False)
        self.assertEqual(out["log_tail"].splitlines(), big.splitlines()[-40:])

    def test_fail_trims_log_to_40_lines(self):
        big = "\n".join(str(i) for i in range(60))
        out = ps.diet_log({"state": "fail", "log": big}, full=False)
        self.assertEqual(len(out["log"].splitlines()), 40)
        self.assertEqual(out["log"].splitlines(), big.splitlines()[-40:])

    def test_full_flag_bypasses_diet_entirely(self):
        payload = {"state": "ok", "log": "keep-me-fully"}
        out = ps.diet_log(payload, full=True)
        self.assertEqual(out, payload)

    def test_existing_fields_are_kept(self):
        out = ps.diet_log({"ok": True, "state": "ok", "errors": [], "elapsed_s": 1.2, "pages": 2,
                           "head": "abc1234", "log": "x"}, full=False)
        for k in ("ok", "state", "errors", "elapsed_s", "pages", "head"):
            self.assertIn(k, out)


class RebuildLogDiet(Base):
    def tearDown(self):
        if ps.BUILD_LOCK.locked():
            ps.BUILD_LOCK.release()
        super().tearDown()

    def test_sync_rebuild_ok_omits_log(self):
        def fake_build(D=None):
            return {"ok": True, "state": "ok", "errors": [], "log": "font path\n" * 200,
                    "elapsed_s": 0.01, "pages": 1, "head": "abc1234"}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log", body)
        self.assertEqual(body["state"], "ok")
        self.assertEqual(body["head"], "abc1234")

    def test_sync_rebuild_ok_errors_trims_log_to_40_lines(self):
        def fake_build(D=None):
            return {"ok": True, "state": "ok_errors", "errors": [{"line": 1, "msg": "x"}],
                    "log": "\n".join("l%d" % i for i in range(200)), "elapsed_s": 0.01, "pages": 1}
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
            return {"ok": True, "state": "ok", "errors": [], "log": "font path\n" * 200,
                    "elapsed_s": 0.01, "pages": 1}
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
            self.assertEqual(refused, StartupRefused("%s: found none top-level .tex files under %s. Specify one with "
                                                        "--main.\n  (none)" % (startup.APP_NAME, root)))
            (root / "a.tex").write_text("\\documentclass{article}\n")
            self.assertEqual(startup.detect_main(root), root / "a.tex")
            (root / "b.tex").write_text("\\documentclass{article}\n")
            self.assertTrue(startup.detect_main(root).message.endswith("\n  - a.tex\n  - b.tex"))
        with mock.patch.object(startup.socket, "socket") as sock:
            sock.return_value.__enter__.return_value.connect_ex.return_value = 0      # every port answers: all taken
            self.assertEqual(startup.free_port(18300, 18302),
                             StartupRefused("No free port in the 18300-18302 range. Specify one with --port."))


class BuildHtmlSubstitution(unittest.TestCase):
    def test_label_and_accent_appear_in_output(self):
        """build_html fills the label (title, identity crumb after the Limn mark), the accent stripe and every placeholder."""
        out = ps.build_html("A-DEMO", "#1d4ed8")
        self.assertIn("<title>Limn · A-DEMO</title>", out)
        self.assertIn('id="paper-identity-mark" aria-hidden="true"><svg class="limn-mark"', out)   # the Limn mark (test_brand.py)
        self.assertIn('</svg></span><span>A-DEMO</span>', out)
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
        self.docs = startup.make_docs(["ms=본문:main.tex", "rr=답변서:rr/rr.tex", "rv=리뷰어 코멘트:review.pdf"], self.src, ps.C)
        ps.set_docs(self.docs)
        self.ms, self.rrd, self.rv = self.docs

    def tearDown(self):
        ps.set_docs(None)
        super().tearDown()

    def fake_pages(self, D, name="pages-20260101000000", n=1):
        """Place a single page directory on that document without a real build (1x1 PNG header + a PDF copy)."""
        d = D.dir / name
        d.mkdir(parents=True, exist_ok=True)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (417).to_bytes(4, "big") + (417).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
        for i in range(1, n + 1):
            (d / ("page-%d.png" % i)).write_bytes(png)
        (d / D.pdf_name).write_bytes(MINI_PDF)
        files.atomic_write(D.dir / "pages.cur", name)
        return d

    def test_state_layout_per_doc(self):
        self.assertEqual(self.ms.dir, ps.C.state / "docs" / "ms")
        self.assertEqual(self.rv.dir, ps.C.state / "docs" / "rv")
        self.assertEqual(limn_build.cur_pages(self.rrd), ps.C.state / "docs" / "rr" / "pages")
        self.assertEqual(ps.C.pins_jsonl, ps.C.state / "pins.jsonl")          # one pin store shared across documents

    def test_single_doc_mode_keeps_legacy_paths(self):
        ps.set_docs(None)
        self.assertFalse(ps.multi_doc())
        self.assertIs(ps.DOCS[0], ps.LEGACY_DOC)
        self.assertEqual(limn_build.cur_pages(ps.DOCS[0]), ps.C.state / "pages")
        self.assertEqual(ps.LEGACY_DOC.build, ps.C.build)
        self.assertIs(ps.LEGACY_DOC.lock, ps.BUILD_LOCK)                        # the old global lock/state IS this document's
        self.assertIs(ps.LEGACY_DOC.bstate, ps.BUILD_STATE)
        pid = self.add()
        self.assertEqual(self.pin(pid)["doc"], "main")
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertNotIn("## ", md)                                             # the old look, no subsections
        self.assertIn("| # | 쪽 | 위치 | 범위 | 메모 |", md)

    def test_old_pin_without_doc_reads_as_first_doc_without_rewrite(self):
        rec = {"id": 1, "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "옛 핀", "at": "2026-09-01 10:00:00"}
        ps.C.pins_jsonl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = ps.pins_payload(ps.read_pins()[0], True)
        self.assertEqual(rows[0]["doc"], "ms")                                  # the first document
        self.assertNotIn('"doc"', ps.C.pins_jsonl.read_text(encoding="utf-8"))  # no migration write occurs
        self.assertEqual(ps.docs_payload()["docs"][0]["n_open"], 1)

    def test_api_docs_lists_kind_and_counts(self):
        add_pin({"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr"}, dict(LOCAL_ACTOR)).record["id"]
        add_pin({"file": str(self.rr), "lo": 8, "hi": 8, "page": 1}, dict(LOCAL_ACTOR), doc=self.rrd).record["id"]
        code, _, body = split_resp(self.talk(req("GET", "/api/docs")))
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertTrue(d["multi"])
        self.assertEqual([(x["key"], x["kind"], x["view_only"], x["n_open"]) for x in d["docs"]],
                         [("ms", "tex", False, 0), ("rr", "tex", False, 2), ("rv", "pdf", True, 0)])
        self.assertEqual(d["docs"][1]["path"], "rr/rr.tex")

    def test_meta_and_pages_follow_doc_param(self):
        self.fake_pages(self.rrd, n=2)
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=rr")))
        m = json.loads(body)
        self.assertEqual((m["doc"], m["main"], len(m["pages"]), m["kind"], m["multi"]), ("rr", "rr.tex", 2, "tex", True))
        self.assertEqual([x["key"] for x in m["docs"]], ["ms", "rr", "rv"])
        self.assertIn("rr=", m["src_sig"])
        code, _, _ = split_resp(self.talk(req("GET", "/pages/page-2.png?doc=rr")))
        self.assertEqual(code, 200)
        code, _, _ = split_resp(self.talk(req("GET", "/pages/page-2.png?doc=ms")))   # ms has no pages
        self.assertEqual(code, 404)
        code, hdrs, _ = split_resp(self.talk(req("GET", "/pdf?doc=rr")))
        self.assertEqual((code, hdrs["content-type"]), (200, "application/pdf"))
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=nope")))
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["docs"], ["ms", "rr", "rv"])

    def test_pin_doc_is_inferred_from_file_and_body_query_must_agree(self):
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "rr/rr.tex", "lo": 4, "hi": 5})))
        self.assertEqual(code, 200)
        self.assertEqual(self.pin(json.loads(body)["id"])["doc"], "rr")     # agent curl — inferred from file
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin?doc=ms", {"file": "main.tex", "lo": 4, "hi": 5, "doc": "rr"})))
        self.assertEqual(code, 400)
        code, _, body = split_resp(self.talk(jreq("GET", "/api/pins?doc=rr")))
        self.assertEqual([p["doc"] for p in json.loads(body)], ["rr"])

    BOB = {"login": "bob@example.com", "name": "Bob Park"}
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
        pin = add_pin({"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr",
                          "note": "@Wendy Kim 이 정의 확인", "assignee": self.WENDY["login"]}, dict(self.BOB))
        self.assertEqual(pin.record["doc"], "rr")
        self.assertEqual(self._notices(), [("mention", "rr"), ("assigned", "rr")])

    def test_later_notices_about_a_pin_name_its_document(self):
        """Edit, reply, close and reopen notices about a pin in the second document carry that document's key: they
        are made from the stored record, which has its doc."""
        ps._EVENTS_CACHE.clear()
        ps.record_person(dict(self.WENDY))
        pid = add_pin({"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr", "note": "정의 확인"},
                         dict(self.BOB)).record["id"]
        n = len(ps._read_events()[0])
        edit = {"base_rev": 0, "note": "@Wendy Kim 정의 확인", "assignee": self.WENDY["login"]}
        self.assertEqual(edit_pin(pid, edit, dict(self.BOB)).record["doc"], "rr")
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/reply" % pid, {"text": "봤어요"})))[0], 200)
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/close" % pid, {"reply": "고침"})))[0], 200)
        self.assertEqual(split_resp(self.talk(jreq("POST", "/api/pins/%d/reopen" % pid, {"reason": "아직"})))[0], 200)
        self.assertEqual(self._notices(n), [("mention", "rr"), ("assigned", "rr"), ("replied", "rr"),
                                            ("review_requested", "rr"), ("reopened", "rr")])

    def test_view_only_pick_returns_region_without_synctex(self):
        self.fake_pages(self.rv)
        with mock.patch.object(locate, "region_text", return_value="Reviewer   one\n comment"), \
                mock.patch.object(locate, "by_synctex", side_effect=AssertionError("SyncTeX must not be called")):
            code, _, body = split_resp(self.talk(jreq("POST", "/api/pick", {"doc": "rv", "page": 1, "x0": 10, "y0": 20,
                                                                            "x1": 110, "y1": 60})))
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual((d["kind"], d["view_only"], d["page"], d["quote"], d["pdf"]),
                         ("region", True, 1, "Reviewer one comment", "review.pdf"))
        self.assertNotIn("lo", d)
        self.assertEqual(len(d["frac"]), 4)                                     # even without frac in the request, it's built from coordinates

    def test_view_only_pin_save_validation_and_pins_md(self):
        self.fake_pages(self.rv, n=3)
        ok = {"doc": "rv", "page": 2, "frac": [0.1, 0.2, 0.5, 0.1], "note": "R1 코멘트 답변", "quote": "Reviewer one"}
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", ok)))
        self.assertEqual(code, 200, body)
        pid = json.loads(body)["id"]
        rec = self.pin(pid)
        self.assertEqual((rec["doc"], rec["kind"], rec["page"], rec["pdf"]),
                         ("rv", "region", 2, str(self.pdf.resolve())))
        self.assertNotIn("file", rec)
        self.assertNotIn("lo", rec)
        self.assertTrue(ps.valid_rec(rec))
        for bad in ({"lo": 3, "hi": 4}, {"file": "main.tex"}, {"frac": [0.9, 0.2, 0.5, 0.1]}, {"frac": [0.1, 0.2, 0, 0.1]},
                    {"frac": None}, {"page": 9}):
            code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", dict(ok, **bad))))
            self.assertEqual(code, 400, bad)
        # validation for LaTeX documents is unchanged — a pin without lo/hi is 400
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", {"doc": "rr", "file": "rr/rr.tex", "page": 1})))
        self.assertEqual(code, 400)
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "doc": "ms"}, dict(LOCAL_ACTOR)).record["id"]
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertIn("## 본문 · `ms` · `main.tex`", md)
        self.assertIn("## 리뷰어 코멘트 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", md)
        self.assertIn("| %d | 2 | 쪽 2, 영역 가로 10–60%% 세로 20–30%% | 영역 | «Reviewer one» R1 코멘트 답변 |" % pid, md)
        self.assertIn("문서: 본문(`ms`) 1건 · 답변서(`rr`) 0건 · 리뷰어 코멘트(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("## 답변서", md)                                        # a document with no open pins gets no subsection
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)
        for line in md.splitlines():
            if line.startswith("| ") and not line.startswith("|---"):
                self.assertEqual(line.count(" | ") + 2, 6, line)               # still a 5-column table

    def test_view_only_pin_edit_note_and_region_only(self):
        """A view-only document's pin takes a note and a region only; lines are refused (no_source_lines)."""
        self.fake_pages(self.rv)
        pid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "a"}, dict(LOCAL_ACTOR), doc=self.rv).record["id"]
        rev = self.pin(pid)["rev"]
        self.assertEqual(edit_pin(pid, {"lo": 2, "hi": 3, "base_rev": rev}, dict(LOCAL_ACTOR)),
                         InputRejected(parse.REGION_EDIT_REFUSAL, "no_source_lines"))
        p = record_of(edit_pin(pid, {"note": "b", "base_rev": rev}, dict(LOCAL_ACTOR)))   # even without doc in the request, it resolves via the pin's own document
        self.assertEqual(p["note"], "b")
        p = record_of(edit_pin(pid, {"loc": {"page": 1, "frac": [0.3, 0.3, 0.2, 0.2], "quote": "new"},
                                        "base_rev": p["rev"]}, dict(LOCAL_ACTOR)))
        self.assertEqual((p["frac"][0], p["quote"], p["pdf_build"]), (0.3, "new", "pages-20260101000000"))
        self.assertTrue(ps.valid_rec(self.pin(pid)))
        ps.set_done(pid, True, dict(LOCAL_ACTOR))                            # close/drop are resolved by id, independent of document
        self.assertTrue(self.pin(pid)["done"])

    def test_region_record_validation_is_by_shape(self):
        base = {"id": 1, "pdf": str(self.pdf), "page": 1, "frac": [0, 0, 0.5, 0.5], "kind": "region", "doc": "gone"}
        self.assertTrue(ps.valid_rec(base))                                     # even a document removed from config isn't a broken row
        self.assertFalse(ps.valid_rec(dict(base, lo=1, hi=2)))
        self.assertFalse(ps.valid_rec(dict(base, frac=None)))
        self.assertFalse(ps.valid_rec(dict(base, pdf="review.pdf")))            # relative path
        self.assertFalse(ps.valid_rec(dict(base, doc="Bad Key")))
        # a pin for a document not in config surfaces separately in pins.md (it's not hidden)
        ps.C.pins_jsonl.write_text(json.dumps(base) + "\n")
        md = ps.pins_md_text(ps.read_pins()[0])
        self.assertIn("## 설정에 없는 문서 · `gone`", md)

    def test_sync_and_overlaps_skip_region_pins(self):
        self.fake_pages(self.rv)
        rid = add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}, dict(LOCAL_ACTOR), doc=self.rv).record["id"]
        tid = self.add(4, 5)
        self.main.write_text("\n" + TEX, encoding="utf-8")                     # lines shift down
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
            self.assertTrue(ps.build_async(self.ms).get("busy"))                  # the same document allows only one build at a time
            self.assertTrue(ps.build_all(self.ms).get("busy"))
            self.assertEqual(ps.build_async(self.rrd), {"state": "running"})       # different documents run concurrently
            self.assertTrue(self.ms.lock.locked() and self.rrd.lock.locked())
            self.assertFalse(ps.BUILD_LOCK.locked())                           # the single-document global lock is left untouched
            gate.set()
            for _ in range(100):
                if not (self.ms.lock.locked() or self.rrd.lock.locked()):
                    break
                time.sleep(0.05)
        self.assertFalse(self.ms.lock.locked() or self.rrd.lock.locked())
        self.assertEqual(limn_build.state_snapshot(self.ms)["state"], "fail")
        self.assertEqual(limn_build.state_snapshot(self.rv)["state"], "idle")      # build state is per-document too

    def test_git_pull_is_shared_across_docs(self):
        """With several documents one pull serves the builds within the share window (shared=True); a single document
        pulls on every build."""
        calls = []

        def fake_pull(m, main_only, git):
            """Count the pull; it finds nothing new."""
            calls.append(m)
            return UpToDate(None)
        with mock.patch.object(gitsync, "pull", side_effect=fake_pull), \
             mock.patch.object(ps, "PULL_SHARE", gitsync.PullShare()):
            a = ps.repo_pull()
            b = ps.repo_pull()
        self.assertEqual(len(calls), 1)                                         # once per repository
        self.assertNotIn("shared", a)
        self.assertTrue(b["shared"])
        ps.set_docs(None)
        with mock.patch.object(gitsync, "pull", side_effect=fake_pull):
            ps.repo_pull(), ps.repo_pull()
        self.assertEqual(len(calls), 3)                                         # single document: once per build (unchanged from before)

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm not available")
    def test_view_only_pdf_renders_and_rerenders_on_change(self):
        rv = self.rv
        self.assertTrue(limn_build.pdf_changed(rv))                           # not rendered yet
        res = ps._build_tracked(rv)
        self.assertEqual(res["state"], "ok", res.get("log"))
        first = limn_build.cur_pages(rv).name
        self.assertTrue((limn_build.cur_pages(rv) / "review.pdf").is_file())
        self.assertFalse(limn_build.pdf_changed(rv))
        self.assertFalse(limn_build.refresh_pdf_doc(rv, ps.build_async))   # unchanged, so it doesn't redraw
        self.pdf.write_bytes(MINI_PDF.replace(b"Reviewer one", b"Reviewer two"))
        os.utime(self.pdf, (time.time() + 3, time.time() + 3))
        self.assertTrue(limn_build.pdf_changed(rv))
        time.sleep(1.1)                                                    # page directory names are second-granularity
        res = ps._build_tracked(rv)
        self.assertEqual(res["state"], "ok")
        self.assertNotEqual(limn_build.cur_pages(rv).name, first)
        self.assertEqual(limn_build.state_snapshot(rv)["seq"], 2)
        b = limn_build.load_builds(rv)["by"]
        self.assertNotEqual(b[first]["src_hash"], b[limn_build.cur_pages(rv).name]["src_hash"])   # the source of location estimation


# ---------------------------------------------------------------- estimated time to finish (eta_min) — server/pins.md/viewer display
# '⏳ 처리 중 · ~04:02' read like an expected completion time, but it was actually the claim's
# auto-release time (another session claimed 23 items at once with a 480-minute ttl, 2026-09-23). Now
# the agent supplies an estimate (eta_min), and the screen shows it rounded up to the nearest 5 minutes,
# as '약 15분 · 20:40쯤'. The claim lock remains only a safety net, capped at 120 minutes.
class ClaimEta(Base):
    A = {"login": "alice@x.com", "name": "Wendy"}
    B = {"login": "bob@x.com", "name": "Bob"}

    def test_body_validation_and_derived_ttl(self):
        self.assertEqual(parse.parse_claim_body({}), (parse.CLAIM_TTL_DEFAULT, None))
        for eta, ttl in ((1, 30), (5, 30), (15, 30), (20, 40), (45, 90), (60, 120), (90, 120), (240, 120)):
            self.assertEqual(parse.parse_claim_body({"eta_min": eta}), (ttl, eta), eta)
        self.assertEqual(parse.parse_claim_body({"eta_min": 15, "ttl_min": 10}), (10, 15))     # supplying ttl passes it through unchanged
        for bad in (0, "15", 1.5, True, None, -5):              # refused: answered 400 by the handler
            self.assertIsInstance(parse.parse_claim_body({"eta_min": bad}), InputRejected, bad)
        self.assertIsInstance(parse.parse_claim_body({"eta_min": 15, "ttl_min": 0}), InputRejected)
        # exceeding the cap clamps instead of 400ing — so an agent that claimed via the old procedure (ttl_min 480) doesn't break when extending
        self.assertEqual(parse.parse_claim_body({"eta_min": 241}), (120, 240))
        self.assertEqual(parse.parse_claim_body({"eta_min": 15, "ttl_min": 480}), (120, 15))
        self.assertEqual(parse.parse_claim_body({"ttl_min": 480}), (120, None))

    def test_claim_stores_eta_and_start(self):
        pid = self.add()
        t0 = time.time()
        p = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 15})))
        self.assertAlmostEqual(p["eta_ts"], t0 + 15 * 60, delta=5)
        self.assertAlmostEqual(p["claim_ts"], t0, delta=5)
        self.assertAlmostEqual(p["claim_until"], t0 + 30 * 60, delta=5)
        self.assertIsInstance(p["claimed_at"], str)
        rows, _ = ps.read_pins()                                        # it's a stored value (not a computed field)
        self.assertIn("eta_ts", find_pin(rows, pid))

    def test_same_identity_reclaim_extends_and_updates_estimate(self):
        pid = self.add()
        first = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 5})))
        with ps.PIN_LOCK:                                              # move it back to having been claimed 10 minutes ago
            rows, _ = ps.read_pins()
            r = find_pin(rows, pid)
            for k in ("claim_ts", "eta_ts", "claim_until"):
                r[k] -= 600
            ps.write_pins(rows)
        second = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 20})))
        self.assertAlmostEqual(second["claim_ts"], first["claim_ts"] - 600, delta=1)      # the start time stays put
        self.assertEqual(second["claimed_at"], first["claimed_at"])
        self.assertAlmostEqual(second["eta_ts"], time.time() + 20 * 60, delta=5)          # the new estimate starts from now
        self.assertAlmostEqual(second["claim_until"], time.time() + 40 * 60, delta=5)
        third = record_of(ps.claim_pin(pid, self.A, *parse.parse_claim_body({})))                    # extending with no new estimate keeps the previous one
        self.assertEqual(third["eta_ts"], second["eta_ts"])
        self.assertEqual(third["rev"], second["rev"] + 1)

    def test_other_identity_conflict_reports_eta_and_new_claim_drops_old_eta(self):
        pid = self.add()
        ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 15}))
        refused = ps.claim_pin(pid, self.B, *parse.parse_claim_body({"eta_min": 5}))          # answered 409 "claimed"
        self.assertIsInstance(refused, ClaimedByOther)
        self.assertIsNotNone(refused.eta_ts)
        with ps.PIN_LOCK:                                              # A's claim has expired
            rows, _ = ps.read_pins()
            find_pin(rows, pid)["claim_until"] = time.time() - 1
            ps.write_pins(rows)
        p = record_of(ps.claim_pin(pid, self.B, *parse.parse_claim_body({})))
        self.assertEqual(p["claimed_by"]["login"], "bob@x.com")
        self.assertNotIn("eta_ts", p)                                   # doesn't inherit someone else's old estimate

    def test_close_drop_unclaim_clear_all_claim_fields(self):
        for how in ("close", "drop", "unclaim"):
            pid = self.add()
            ps.claim_pin(pid, self.A, *parse.parse_claim_body({"eta_min": 10}))
            if how == "close":
                rec = record_of(ps.set_done(pid, True, self.A))
            elif how == "unclaim":
                rec = record_of(ps.unclaim_pin(pid, self.A))
            else:
                ps.drop_pin(pid, self.A)
                rec = ps.read_jsonl(ps.C.dropped)[0][-1]
            for k in CLAIM_FIELDS:
                self.assertNotIn(k, rec, (how, k))

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
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, json.dumps({"ttl_min": 480, "eta_min": 300}).encode(), hj))
        code, _, body = split_resp(out)
        self.assertEqual(code, 200)                                     # extending under the same identity (no header = local/agent)
        got = json.loads(body)
        self.assertEqual((got["ttl_min_applied"], got["eta_min_applied"]), (120, 240))
        self.assertAlmostEqual(got["pin"]["eta_ts"], time.time() + 240 * 60, delta=5)

    def test_pins_payload_fills_start_for_legacy_claims(self):
        pid = self.add()
        with ps.PIN_LOCK:                                              # a claim shape written by a pre-eta server
            rows, _ = ps.read_pins()
            r = find_pin(rows, pid)
            r.update(claimed_by=dict(self.A), claimed_at="2026-09-23 20:02:00", claim_until=time.time() + 3600)
            ps.write_pins(rows)
        rec = [x for x in ps.pins_payload(ps.snapshot_pins(), False) if x["id"] == pid][0]
        self.assertAlmostEqual(rec["claim_ts"], position.epoch("2026-09-23 20:02:00"), delta=0.01)
        self.assertNotIn("claim_ts", find_pin(ps.read_pins()[0], pid))   # a computed field — not stored

    def test_pins_md_claim_text(self):
        now = 1_790_000_000.0
        r = {"claimed_by": {"name": "Kim"}}
        self.assertEqual(md_render.claim_md(dict(r), now), "처리 중(Kim)")
        for left_s, want in ((14 * 60 + 10, "약 15분"), (3 * 60, "약 5분"), (15 * 60, "약 15분"), (16 * 60, "약 20분"),
                             (-60, "예상 초과")):
            self.assertEqual(md_render.claim_md(dict(r, eta_ts=now + left_s), now), "처리 중(Kim, %s)" % want)
        self.assertEqual([md_render.ceil5(m) for m in (0, 0.2, 5, 5.01, 14.9, 23)], [5, 5, 5, 10, 15, 25])
        pid = self.add()
        ps.claim_pin(pid, {"login": "k", "name": "에이전트 A"}, *parse.parse_claim_body({"eta_min": 15}))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(에이전트 A, 약 15분)", md)


class ClaimEtaDocs(unittest.TestCase):
    """Whether SKILL.md's pin-handling procedure teaches "claim only that pin right before fixing it, estimate via eta_min"."""

    def test_skill_claim_step_teaches_single_pin_and_estimate(self):
        en, ko = SKILL_MD.read_text(encoding="utf-8"), SKILL_KO.read_text(encoding="utf-8")
        self.assertIn("claim only that pin, right before you edit it", en)
        self.assertIn("고치기 직전에 그 핀만 claim", ko)
        for skill, rows in ((en, ("| Typo or single word | 5 |", "| One sentence | 5–10 |", "| Rewrite a paragraph | 10–20 |",
                                  "| Restructure / several places | 20–40 |")),
                            (ko, ("| 오타·단어 | 5 |", "| 문장 하나 | 5–10 |", "| 문단 다시 쓰기 | 10–20 |", "| 구조 변경·여러 곳 | 20–40 |"))):
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


# ---------------------------------------------------------------- badge wording: self-explanatory phrases (overlap/location match rate) · pins.md display
# '#20 안', '일치 100%', '⊂#N' were unreadable without context (author feedback 2026-09-23). Overlaps now
# read '#20 범위 안' / '#20과 같은 범위' / '#20과 일부 겹침'; the location match rate is hidden at 90%+ and
# shows '위치 불확실' only when low. The pins.md number column joins the same phrases with ' · '.
class BadgeWording(Base):
    NUMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 19, 20, 100, 1000, 21, 32]

    def test_josa_follows_korean_reading(self):
        got = [md_render.josa(n, "과", "와") for n in self.NUMS]
        self.assertEqual(got, ["과", "와", "과", "와", "와", "과", "과", "과", "와", "과", "과", "와", "와", "와", "과", "과", "과",
                               "과", "와"])
        if shutil.which("node"):
            js = extract_js_fn("josa") + "\nconsole.log(JSON.stringify(%s.map(n=>josa(n,'과','와'))));" % json.dumps(self.NUMS)
            self.assertEqual(json.loads(run_node(js)), got)

    def test_rel_badge_prefers_same_range_then_inside_then_partial(self):
        by_id = {1: {"lo": 4, "hi": 9}, 2: {"lo": 4, "hi": 9}, 3: {"lo": 5, "hi": 6}, 20: {"lo": 8, "hi": 12}}
        self.assertEqual(md_render.rel_badge([{"id": 1, "rel": "contains"}], by_id, {"id": 2, "lo": 4, "hi": 9}), "#1과 같은 범위")
        self.assertEqual(md_render.rel_badge([{"id": 2, "rel": "inside"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "#2와 같은 범위")
        self.assertEqual(md_render.rel_badge([{"id": 1, "rel": "inside"}, {"id": 2, "rel": "inside"}], by_id,
                                      {"id": 3, "lo": 5, "hi": 6}), "#1 범위 안")
        self.assertEqual(md_render.rel_badge([{"id": 20, "rel": "partial"}], by_id, {"id": 3, "lo": 5, "hi": 9}), "#20과 일부 겹침")
        self.assertEqual(md_render.rel_badge([{"id": 2, "rel": "partial"}], by_id, {"id": 9, "lo": 8, "hi": 12}), "#2와 일부 겹침")
        self.assertEqual(md_render.rel_badge([{"id": 3, "rel": "contains"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "")

    def test_js_rel_badge_matches_server(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        js = "\n".join([extract_js_fn("josa"), extract_js_fn("relBadge"), r"""
            const PINS=[{id:1,lo:4,hi:9},{id:2,lo:4,hi:9},{id:3,lo:5,hi:6},{id:20,lo:8,hi:12}];
            console.log(JSON.stringify([relBadge([{id:1,rel:'contains'}],{id:2,lo:4,hi:9}).label,
              relBadge([{id:1,rel:'inside'},{id:2,rel:'inside'}],{id:3,lo:5,hi:6}).label,
              relBadge([{id:20,rel:'partial'}],{id:3,lo:5,hi:9}).label, relBadge([{id:3,rel:'contains'}],{id:1,lo:4,hi:9})]));
            """])
        self.assertEqual(json.loads(run_node(js)), ["#1과 같은 범위", "#1 범위 안", "#20과 일부 겹침", None])
        self.assertIn("const rb=closedCard?null:relBadge(p.rel,p);", extract_js_fn("card"))

    def test_overlap_banner_verbs(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        cases = r"""
            console.log(JSON.stringify([['equal',4],['inside',20],['contains',4],['contains',20],['partial',2]].map(a=>overlapText(a[0],a[1]))));
            """
        js = "\n".join([extract_js_fn("josa"), extract_js_fn("overlapText"), cases])
        self.assertEqual(json.loads(run_node(js)),
                         ["열린 핀 #4와 같은 범위입니다", "열린 핀 #20 범위 안입니다", "열린 핀 #4를 감쌉니다", "열린 핀 #20을 감쌉니다",
                          "열린 핀 #2와 일부 겹칩니다"])
        self.assertEqual(json.loads(run_node(js_i18n("en") + "\n" + js)),
                         ["Same range as open pin #4", "Inside open pin #20's range", "Encloses open pin #4", "Encloses open pin #20",
                          "Partially overlaps open pin #2"])

    def test_pins_md_number_column_uses_words(self):
        a = self.add(4, 9)
        b = self.add(4, 9)
        c = self.add(5, 6)
        edit_pin(c, {"note": "고침", "base_rev": self.pin(c)["rev"]}, dict(LOCAL_ACTOR))
        ps.claim_pin(c, {"login": "k", "name": "Kim"}, *parse.parse_claim_body({"eta_min": 10}))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("| %d · #%d와 같은 범위 |" % (a, b), md)
        self.assertIn("| %d · #%d과 같은 범위 |" % (b, a), md)
        self.assertIn("| %d · #%d 범위 안 · 처리 중(Kim, 약 10분) · 수정됨 |" % (c, a), md)
        for sym in ("⊂", "∩", "⏳", "✎", "⚠"):
            self.assertNotIn(sym, md)
        self.assertIn("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다", md)

    def test_skill_symbol_table_uses_words(self):
        # pins.md markers are a language-stable contract: both procedures quote them verbatim.
        for path, head, end in ((SKILL_MD, "### Markers in the number column", "### Rules"),
                                (SKILL_KO, "### 번호 칸의 표시", "### 규칙")):
            skill = path.read_text(encoding="utf-8")
            table = skill[skill.index(head):skill.index(end)]
            for row in ("| `#N 범위 안` |", "| `#N과 같은 범위` |", "| `#N과 일부 겹침` |", "| `처리 중(<이름>, 약 N분)` |",
                        "| `수정됨` |", "| `위치 잃음` |"):
                self.assertIn(row, table)
            self.assertNotRegex(table, r"^\| `[⊂∩⏳✎⚠]", )


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

    def test_kind_req_stored_only_when_given_and_validated(self):
        """kind_req is stored only when given, and an unknown value is refused (bad_kind_req)."""
        q = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
                       dict(self.S)).record["id"]
        f = self.add()
        self.assertEqual(self.pin(q)["kind_req"], "question")
        self.assertNotIn("kind_req", self.pin(f))                 # an old-style call (agent curl) has no field = fix request
        self.assertEqual(add_pin({"file": str(self.main), "lo": 4, "hi": 5, "kind_req": "ask"}, dict(self.S)),
                         InputRejected("kind_req 는 fix|question 중 하나입니다.", "bad_kind_req"))

    def test_edit_switches_kind_even_on_closed_pin(self):
        pid = self.add()
        p = record_of(edit_pin(pid, {"kind_req": "question", "base_rev": 0}, dict(self.S)))
        self.assertEqual(p["kind_req"], "question")
        ps.set_done(pid, True, dict(self.S))
        p = record_of(edit_pin(pid, {"kind_req": "fix", "base_rev": self.pin(pid)["rev"]}, dict(self.S)))
        self.assertEqual(p["kind_req"], "fix")

    def test_reply_endpoint_appends_message_with_header_identity(self):
        pid = self.add()
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "  0 은 전 구간 평균입니다\r\n두 번째 줄 "},
                            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]})
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(d["msg"]["id"], 1)
        self.assertEqual(d["msg"]["text"], "0 은 전 구간 평균입니다\n두 번째 줄")   # CRLF -> LF, leading/trailing whitespace stripped
        self.assertEqual(d["msg"]["by"], {"login": self.S["login"], "name": self.S["name"]})
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "에이전트 답"})
        self.assertEqual(d["msg"]["id"], 2)
        self.assertEqual(d["msg"]["by"]["login"], "local")
        p = self.pin(pid)
        self.assertEqual([m["id"] for m in p["thread"]], [1, 2])
        self.assertFalse(p.get("done"))                          # a reply doesn't change the status
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
        self.assertEqual((code, d["ok"], d["pin"]), (200, False, None))   # a nonexistent id follows the same convention as other routes

    def test_control_characters_are_stripped_but_newlines_kept(self):
        self.assertEqual(parse.parse_thread_text("a\x00b\x1b[31m\tc\nd"), "ab[31m\tc\nd")

    def test_thread_is_capped(self):
        pid = self.add()
        with mock.patch.object(ps, "THREAD_MAX", 2):
            ps.reply_pin(pid, "1", dict(self.S))
            ps.reply_pin(pid, "2", dict(self.S))
            self.assertEqual(ps.reply_pin(pid, "3", dict(self.S)), ThreadFull(2))   # answered 409 "full" over HTTP
            ps.set_done(pid, True, dict(self.S), "닫음")          # a status-transition record is exempt from the cap
        self.assertEqual([m.get("ev") for m in self.pin(pid)["thread"]], [None, None, "close"])

    def test_close_reply_is_appended_to_thread_once(self):
        pid = self.add()
        ps.reply_pin(pid, "질문이 있어요", dict(self.S))
        ps.set_done(pid, True, dict(self.S), "제목을 고침", "PR #227")
        ps.set_done(pid, True, dict(self.S), "두 번째 닫기")      # already closed — nothing gets appended
        th = self.pin(pid)["thread"]
        self.assertEqual([(m["id"], m.get("ev"), m["text"], m.get("ref")) for m in th],
                         [(1, None, "질문이 있어요", None), (2, "close", "제목을 고침", "PR #227")])
        self.assertEqual(self.pin(pid)["close_reply"], "제목을 고침")   # the old field is left in place too (compat with old viewers/agents)

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
        self.assertNotIn("state", ps.read_pins()[0][0])           # a computed field — not stored

    def test_malformed_thread_is_a_broken_line(self):
        for th in ("x", [{"id": "1", "text": "a", "at": "t", "by": {}}], [{"id": 1, "text": 3, "at": "t", "by": {}}],
                   [{"id": 1, "text": "a", "at": "t", "by": {"name": 3}}], [{"id": 1, "text": "a", "at": "t", "by": {}, "ev": "boom"}]):
            r = {"id": 1, "file": str(self.main), "lo": 1, "hi": 1, "thread": th}
            self.assertFalse(ps.valid_rec(r), th)
        ok = {"id": 1, "file": str(self.main), "lo": 1, "hi": 1, "kind_req": "question",
              "thread": [{"id": 1, "text": "a", "at": "2026-09-24 10:00:00", "by": {"login": "x", "name": "X"}, "ev": "close", "ref": "PR #1"}]}
        self.assertTrue(ps.valid_rec(ok))
        self.assertFalse(ps.valid_rec(dict(ok, kind_req="Q")))

    def test_legacy_records_are_not_rewritten_by_reads(self):
        legacy = {"id": 7, "file": str(self.main), "name": "main.tex", "lo": 4, "hi": 5, "page": 1, "note": "옛 핀",
                  "at": "2026-09-21 20:00:00", "done": True, "done_at": "2026-09-21 21:00:00",
                  "close_reply": "고침", "anchor": mapping.anchor_of(files.tex_lines(self.main), 4, 5),
                  "synced_at": self.main.stat().st_mtime + 10}
        ps.C.pins_jsonl.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")
        before = ps.C.pins_jsonl.read_bytes()
        mtime = ps.C.pins_jsonl.stat().st_mtime_ns
        rows = ps.pins_payload(ps.snapshot_pins(), True)
        self.talk(req("GET", "/api/pins?all=1"))
        self.talk(req("GET", "/pins.md"))
        self.assertEqual(ps.C.pins_jsonl.read_bytes(), before)
        self.assertEqual(ps.C.pins_jsonl.stat().st_mtime_ns, mtime)
        self.assertEqual(rows[0]["state"], "done")
        self.assertNotIn("thread", rows[0])

    def test_pins_md_marks_questions_and_shows_current_round_of_thread(self):
        q = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
                       dict(self.S)).record["id"]
        for i in range(5):
            ps.reply_pin(q, "답글 %d\n둘째 줄 | 파이프" % i, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % q))
        self.assertIn("| %d · 질문 |" % q, row)
        self.assertIn("[스레드 5건, 앞 2건은 GET /api/pins/%d]" % q, row)
        self.assertIn("Bob Park: 답글 4 둘째 줄 \\| 파이프", row)   # a newline collapses, | gets escaped
        self.assertNotIn("답글 1", row)
        self.assertEqual(row.count("|") - row.count("\\|"), 6)          # still a 5-column table
        self.assertIn("/api/pins/N/reply", md)
        self.assertIn("'질문' = 고칠 곳이 아니라 물음이다", md)
        ps.set_done(q, True, dict(self.S), "답했다")
        ps.set_done(q, False, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % q))
        self.assertNotIn("[스레드", row)                                  # messages from before the close aren't shown


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
        self.assertEqual(d["state"], "review")                      # a remote agent closing via a tailnet address
        code, d = self.post("/api/pins/%d/close" % b, {"review": False})
        self.assertEqual(d["state"], "done")
        code, d = self.post("/api/pins/%d/close" % self.add(), {"review": "yes"})
        self.assertEqual(code, 400)

    def test_review_pins_are_not_open_for_agents(self):
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        _, _, raw = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(json.loads(raw), [])                         # not in the open-pin list (legacy contract)
        self.assertIsInstance(ps.claim_pin(pid, dict(LOCAL_ACTOR), 30), ClaimClosedPin)   # 409 "done"
        m = ps.meta(ps.DOCS[0], dict(LOCAL_ACTOR))
        self.assertEqual((m["n_open"], m["n_review"], m["n_done"]), (0, 1, 0))

    def test_confirm_and_idempotence(self):
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        W = {"Tailscale-User-Login": self.W["login"], "Tailscale-User-Name": self.W["name"]}
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["state"]), (200, "done"))
        p = self.pin(pid)
        self.assertEqual(p["confirmed_by"], self.W)                   # confirmation doesn't require being the author
        self.assertTrue(p["confirmed_at"])
        self.assertEqual(p["thread"][-1]["ev"], "confirm")
        rev = p["rev"]
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["ok"], self.pin(pid)["rev"]), (200, True, rev))   # already done — unchanged
        code, d = self.post("/api/pins/%d/confirm" % self.add(), None, W)
        self.assertEqual((code, d["error"]), (409, "open"))
        code, d = self.post("/api/pins/999/confirm", None, W)
        self.assertEqual((code, d["ok"]), (200, False))

    def test_agent_cannot_confirm(self):
        # observed bug: a request without an identity header (agent/local curl) could succeed at /confirm —
        # awaiting review is a record that "a human saw this," so an agent confirming its own work defeats the purpose.
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        code, d = self.post("/api/pins/%d/confirm" % pid)             # no header = agent
        self.assertEqual(code, 403)
        self.assertIn("확인은 사람이 합니다", d.get("error", ""))
        self.assertEqual(pin_state(self.pin(pid)), "review")       # the status doesn't change
        self.assertEqual(ps.confirm_pin(pid, dict(LOCAL_ACTOR)), AgentCannotConfirm())   # a value, answered 403 above

    def test_reopen_with_reason_appends_to_thread_and_clears_review(self):
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "식 번호가 아직 틀림"},
                            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]})
        self.assertEqual(d["state"], "open")
        p = self.pin(pid)
        self.assertNotIn("review", p)
        self.assertEqual([(m.get("ev"), m["text"]) for m in p["thread"]], [("close", "고침"), ("reopen", "식 번호가 아직 틀림")])
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀림", row)
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "x" * (parse.THREAD_TEXT_MAX + 1)})
        self.assertEqual(code, 400)
        code, d = self.post("/api/pins/%d/reopen" % pid)              # a body-less legacy reopen still works too (already open — thread unchanged)
        self.assertEqual(code, 200)
        self.assertEqual(len(self.pin(pid)["thread"]), 2)

    def test_reopen_after_confirm_drops_confirmation(self):
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR))
        ps.confirm_pin(pid, dict(self.S))
        ps.set_done(pid, False, dict(self.S), reason="다시")
        p = self.pin(pid)
        self.assertNotIn("confirmed_by", p)
        self.assertEqual(pin_state(p), "open")

    def test_legacy_done_is_done_not_review(self):
        self.assertEqual(pin_state({"done": True}), "done")
        self.assertEqual(pin_state({"done": True, "review": False}), "done")
        self.assertEqual(pin_state({"done": True, "review": True}), "review")
        self.assertEqual(pin_state({"review": True}), "open")    # a review flag left on an open pin is meaningless
        self.assertFalse(ps.valid_rec({"id": 1, "file": str(self.main), "lo": 1, "hi": 1, "review": "y"}))

    def test_pins_md_review_section_and_header(self):
        a = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "q", "kind_req": "question"}, dict(self.S)).record["id"]
        b = self.add(8, 9)
        ps.set_done(a, True, dict(LOCAL_ACTOR), "구간은 0 을 포함 | 유의하지 않음", "PR #12")
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("열린 핀 1건  ·  검토 대기 1건(맨 아래, 처리하지 않는다)  ·  닫힌 핀 0건", md)
        sec = md[md.index("## 검토 대기 1건"):]
        self.assertIn("| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |", sec)
        self.assertIn("| %d · 질문 | `main.tex L4-L5` | Bob Park | 구간은 0 을 포함 \\| 유의하지 않음 (PR #12) |" % a, sec)
        opn = md[:md.index("## 검토 대기")]
        starts = [ln.split("|")[1].strip() for ln in opn.splitlines() if ln.startswith("| ") and not ln.startswith("| #")]
        self.assertEqual(starts, [str(b)])                             # only open pins appear in the open table
        self.assertIn("`\"review\":true`", md)
        self.assertIn("검토 대기 핀은 다시 처리하지 않는다", md)
        ps.confirm_pin(a, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("## 검토 대기", md)
        self.assertIn("열린 핀 1건  ·  닫힌 핀 1건", md)                # with nothing awaiting review, the header line reverts to the old look


# ---------------------------------------------------------------- @-mentions · people.json · events.jsonl (docs/handbook/api.md §@태그·사람·이벤트)
class MentionsPeopleEvents(Base):
    S = {"login": "bob@example.com", "name": "Bob Park"}
    W = {"login": "wendy@example.com", "name": "Wendy Kim"}
    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
    HW = {"Tailscale-User-Login": "wendy@example.com", "Tailscale-User-Name": "Wendy Kim"}

    def setUp(self):
        super().setUp()
        ps._PEOPLE_SEEN.clear()
        ps._EVENTS_CACHE.clear()

    def events(self):
        return ps._read_events()[0]

    def post(self, path, body=None, headers=None):
        h = {"Content-Type": "application/json"} if body is not None else {}
        h.update(headers or {})
        code, _, raw = split_resp(self.talk(req("POST", path, json.dumps(body).encode() if body is not None else b"", h)))
        return code, json.loads(raw)

    def people(self, extra=()):
        d = {p["login"]: dict(p) for p in (self.S, self.W) + tuple(extra)}
        return d

    def test_resolve_mentions_rules(self):
        ppl = self.people(({"login": "wlee@x.com", "name": "Wendy Lee"}, {"login": "sy@x.com", "name": "박서준"}))
        R = mentions.resolve_mentions
        self.assertEqual(R("@Bob Park 확인 부탁", ppl), [self.S["login"]])
        self.assertEqual(R("@bob park님 이거요", ppl), [self.S["login"]])            # case-insensitive, Korean particle attached
        self.assertEqual(R("@Bob 봐 주세요", ppl), [self.S["login"]])               # first word of the name (only one match)
        self.assertEqual(R("@Wendy 어때요", ppl), [])                                   # two candidates share the first word — ambiguous, don't resolve
        self.assertEqual(R("@Wendy 어때요", ppl, [self.W["login"]]), [self.W["login"]])  # resolved via the viewer's chosen hint
        self.assertEqual(R("메일 bob@example.com 로", ppl), [])                     # an email address is not a mention
        self.assertEqual(R("@Bobx", ppl), [])                                         # letters right after an English name = a different word
        self.assertEqual(R("@박서준님 @Wendy Kim @박서준", ppl), ["sy@x.com", self.W["login"]])
        self.assertEqual(R("@nobody", ppl), [])

    def test_people_json_records_humans_only_and_throttles(self):
        self.assertFalse(ps.record_person(dict(LOCAL_ACTOR)))
        self.assertFalse(ps.C.people_file.exists())
        self.assertTrue(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1000))
        self.assertFalse(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1100))   # same value within 10 minutes — not written
        self.assertTrue(ps.record_person(dict(self.S, name="Bob P."), now=1101))        # written when the name changes
        self.assertTrue(ps.record_person(dict(self.W), now=2000))
        d = json.loads(ps.C.people_file.read_text(encoding="utf-8"))
        self.assertEqual(d["version"], 1)
        self.assertEqual([p["login"] for p in d["people"]], [self.S["login"], self.W["login"]])
        s = d["people"][0]
        self.assertEqual((s["name"], s["pic"]), ("Bob P.", "https://p/s.png"))
        self.assertTrue(s["first_seen"] <= s["last_seen"])

    def test_people_json_write_is_atomic(self):
        ps.record_person(dict(self.S), now=1000)
        before = ps.C.people_file.read_bytes()
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(ps.record_person(dict(self.W), now=2000))
        self.assertEqual(ps.C.people_file.read_bytes(), before)         # the old file is unchanged (no half-written file)
        with mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            ps.emit_events([{"type": "mention", "pin": 1, "to": ["x"]}])
        self.assertFalse(ps.C.events_file.exists())

    def test_viewer_open_records_person_and_people_api_merges_pin_actors(self):
        self.talk(req("GET", "/", headers=self.HW))
        self.talk(req("GET", "/api/meta?light=1", headers=self.HS))     # polling doesn't count
        self.assertEqual([p["login"] for p in ps.load_people()], [self.W["login"]])
        add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "x"}, dict(self.S)).record["id"]
        code, _, raw = split_resp(self.talk(req("GET", "/api/people", headers=self.HW)))
        d = json.loads(raw)
        self.assertEqual(sorted(p["login"] for p in d["people"]), sorted([self.S["login"], self.W["login"]]))
        self.assertEqual(d["me"]["login"], self.W["login"])
        self.assertNotIn("local", [p["login"] for p in d["people"]])

    def test_mentions_stored_on_pin_and_message_with_events(self):
        ps.record_person(dict(self.W))
        code, d = self.post("/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "kind_req": "question",
                                        "note": "@Wendy Kim 구간의 정의는?"}, self.HS)
        pid = d["id"]
        p = self.pin(pid)
        self.assertEqual(p["mentions"], [self.W["login"]])
        self.assertEqual(p["note"], "@Wendy Kim 구간의 정의는?")       # the text is unchanged
        ev = self.events()
        self.assertEqual([(e["type"], e["pin"], e["to"], e["by"]["login"]) for e in ev],
                         [("mention", pid, [self.W["login"]], self.S["login"])])
        self.assertEqual(ev[0]["kind_req"], "question")
        self.assertEqual(ev[0]["seq"], 1)
        self.assertIn("구간의 정의는?", ev[0]["excerpt"])
        # agent reply -> replied goes to the author and the mentioned person
        self.post("/api/pins/%d/reply" % pid, {"text": "구간은 95% 신뢰구간입니다"})
        e = self.events()[-1]
        self.assertEqual((e["type"], sorted(e["to"]), e["msg"]), ("replied", sorted([self.S["login"], self.W["login"]]), 1))
        # when the mentioned person replies, they're excluded from the recipients themselves
        self.post("/api/pins/%d/reply" % pid, {"text": "@Bob Park 맞아요"}, self.HW)
        types = [(x["type"], x["to"]) for x in self.events()[2:]]
        self.assertEqual(types, [("mention", [self.S["login"]])])       # the author, mentioned by this message, gets only one mention (doesn't overlap with replied)
        self.assertEqual(self.pin(pid)["thread"][-1]["mentions"], [self.S["login"]])
        # when an agent closes it, review_requested goes to the author; when the author reopens with a reason, reopened is skipped since it's themself
        self.post("/api/pins/%d/close" % pid, {"reply": "답함"})
        self.assertEqual(self.events()[-1]["type"], "review_requested")
        self.assertEqual(self.events()[-1]["to"], [self.S["login"]])
        n = len(self.events())
        self.post("/api/pins/%d/reopen" % pid, {"reason": "@Wendy Kim 한 번 더 봐 주세요"}, self.HS)
        tail = self.events()[n:]
        # v0.2.1: every @-tag in a reopen reason notifies, even someone tagged before; the author reopened it themself
        self.assertEqual([(x["type"], x["to"]) for x in tail], [("mention", [self.W["login"]])])
        self.post("/api/pins/%d/close" % pid, {"reply": "다시 답함"})
        self.post("/api/pins/%d/reopen" % pid, {"reason": "아직"}, self.HW)
        self.assertEqual((self.events()[-1]["type"], self.events()[-1]["to"]), ("reopened", [self.S["login"]]))
        seqs = [x["seq"] for x in self.events()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_edit_adds_mention_event_only_for_new_names(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 봐 주세요"}, dict(LOCAL_ACTOR)).record["id"]
        edit_pin(pid, {"note": "@Wendy Kim @Bob Park 봐 주세요", "base_rev": 0}, dict(LOCAL_ACTOR))
        self.assertEqual([(e["type"], e["to"]) for e in self.events()],
                         [("mention", [self.W["login"]]), ("mention", [self.S["login"]])])
        edit_pin(pid, {"note": "그냥 메모", "base_rev": 1}, dict(LOCAL_ACTOR))
        self.assertNotIn("mentions", self.pin(pid))

    def test_pins_md_marks_human_addressed_pins_and_tells_agents_to_skip(self):
        ps.record_person(dict(self.W))
        a = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 이 구간 맞나요?", "kind_req": "question"},
                       dict(self.S)).record["id"]
        self.add(8, 9)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % a))
        self.assertIn("| %d · → @Wendy Kim · 질문 |" % a, row)   # priority: reopened > -> @ > question
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("명시적으로 시키지 않으면 건너뛴다", md)
        rows = ps.pins_payload(ps.snapshot_pins(), True)
        self.assertEqual(next(r for r in rows if r["id"] == a)["addressed"], [self.W["login"]])

    # ---- assignee — docs/handbook/api.md §담당. Guessing the skip rule from free text was ambiguous (A-DEMO #43).
    def test_assignee_person_is_addressed_agent_is_fyi_and_legacy_falls_back(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
        note = "이거 콜링 제대로 작동하나 @Bob Park 확인 부탁합니다"
        legacy = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": note}, dict(self.W)).record["id"]
        person = add_pin({"file": str(self.main), "lo": 8, "hi": 9, "note": note, "assignee": self.S["login"]}, dict(self.W)).record["id"]
        agent = add_pin({"file": str(self.main), "lo": 2, "hi": 3, "note": "@Bob Park 질문 참고", "kind_req": "question",
                            "assignee": "agent"}, dict(self.W)).record["id"]
        rows = {r["id"]: r for r in ps.pins_payload(ps.snapshot_pins(), True)}
        self.assertNotIn("assignee", rows[legacy])                        # legacy pin: no field -> inferred per #87 (fix request = fyi)
        self.assertEqual((rows[legacy]["addressed"], rows[legacy]["fyi"]), ([], [self.S["login"]]))
        self.assertEqual((rows[person]["addressed"], rows[person]["fyi"]), ([self.S["login"]], []))
        self.assertEqual((rows[agent]["addressed"], rows[agent]["fyi"]), ([], [self.S["login"]]))   # even a question is fyi if the assignee is an agent
        md = ps.C.pins_md.read_text(encoding="utf-8")
        def line(pid):
            """The pins.md table row for pin pid."""
            return next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("| %d · 참고 @Bob Park |" % legacy, line(legacy))
        self.assertIn("| %d · → @Bob Park |" % person, line(person))
        self.assertIn("| %d · 참고 @Bob Park · 질문 |" % agent, line(agent))
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("'→ @이름' = 담당이 사람인 핀", md)

    def test_assignee_validation_and_events(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
        base = {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "@Bob Park 봐 주세요"}
        for bad in ("nobody@x.com", "local", 3, ""):
            code, d = self.post("/api/pin", dict(base, assignee=bad), self.HW)
            self.assertEqual(code, 400, bad)
            self.assertTrue("assignee" in d["error"] or "담당" in d["error"], d)
        code, d = self.post("/api/pin", dict(base, assignee=self.S["login"]), self.HW)
        self.assertEqual(code, 200)
        pid = d["id"]
        self.assertEqual(self.pin(pid)["assignee"], self.S["login"])
        self.assertEqual(sorted((e["type"], tuple(e["to"])) for e in self.events()),
                         [("assigned", (self.S["login"],)), ("mention", (self.S["login"],))])   # the mentioned person also gets a notification
        self.assertNotIn("thread", self.pin(pid))                        # the assignee set at creation isn't a thread record
        # switching the assignee to an agent leaves an ev=assign entry with no event. Switching back to a person emits assigned.
        n = len(self.events())
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": "agent", "base_rev": 0}, self.HW)
        self.assertEqual(code, 200)
        p = self.pin(pid)
        self.assertEqual((p["assignee"], p["thread"][-1]["ev"], p["thread"][-1]["text"]), ("agent", "assign", "담당: 에이전트"))
        self.assertEqual(self.events()[n:], [])
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": self.S["login"], "base_rev": 1}, self.HW)
        self.assertEqual(self.pin(pid)["thread"][-1]["text"], "담당: @Bob Park")
        self.assertEqual([(e["type"], e["to"]) for e in self.events()[n:]], [("assigned", [self.S["login"]])])
        code, d = self.post("/api/pins/%d/edit" % pid, {"assignee": "ghost", "base_rev": 2}, self.HW)
        self.assertEqual(code, 400)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("담당 바꿈(Wendy Kim): 담당: @Bob Park", md)
        self.assertIn("assigned", NOTIFY_TYPES)

    def test_legacy_pins_read_without_rewrite(self):
        ps.record_person(dict(self.S))
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 확인 부탁"}, dict(self.W)).record["id"]
        f = ps.C.pins_jsonl
        before = f.read_bytes()
        for _ in range(2):
            ps.pins_payload(ps.snapshot_pins(), True)
            self.talk(req("GET", "/api/pins?all=1"))
            self.talk(req("GET", "/pins.md"))
        self.assertEqual(f.read_bytes(), before)
        self.assertNotIn("assignee", self.pin(pid))

    def test_addressed_counts_current_round_only_and_needs_question_kind(self):
        r = {"kind_req": "question", "mentions": [],
             "thread": [{"id": 1, "mentions": ["a"], "text": "", "at": "", "by": {}},
                        {"id": 2, "ev": "close", "text": "", "at": "", "by": {}},
                        {"id": 3, "ev": "reopen", "mentions": ["b"], "text": "", "at": "", "by": {}}]}
        self.assertEqual(mentions.addressed_to(r), ["b"])
        self.assertEqual(mentions.pin_mentions_all(r), ["a", "b"])
        self.assertEqual(mentions.fyi_mentions_to(r), [])       # a question pin isn't fyi — it's captured only as addressed
        fix = dict(r, kind_req="fix")
        self.assertEqual(mentions.addressed_to(fix), [])         # a fix-request pin isn't skipped even with an @-mention
        self.assertEqual(mentions.fyi_mentions_to(fix), ["b"])   # it's captured only as fyi instead

    def test_reopen_after_confirm_marks_reopened_symbol_not_just_first_round_msg(self):
        # observed bug: reopening after a confirm made the round start with [confirm, reopen, ...], so the
        # "reopened" marker was missing (the old check only looked at "is the round's first message a
        # reopen?"). pin_reopened_in_round() now skips over confirm.
        pid = self.add()
        ps.set_done(pid, True, dict(LOCAL_ACTOR), "고침")
        ps.confirm_pin(pid, dict(self.S))
        ps.set_done(pid, False, dict(self.S), reason="다시 봐 주세요")
        self.assertTrue(ps.pin_reopened_in_round(self.pin(pid)))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(ln for ln in md.splitlines() if ln.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)

    def test_self_mention_never_becomes_addressed(self):
        ps.record_person(dict(self.W))
        ps.record_person(dict(self.S))
        pid = add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Wendy Kim 셀프 태그",
                          "kind_req": "question"}, dict(self.W)).record["id"]
        p = self.pin(pid)
        self.assertNotIn("mentions", p)                    # a self-@mention isn't stored
        self.assertEqual(mentions.addressed_to(p), [])
        msg = ps.reply_pin(pid, "@Bob Park 님 확인 부탁드립니다 @Wendy Kim", dict(self.W)).record["thread"][-1]
        self.assertEqual(msg["mentions"], [self.S["login"]])  # the reply's own author (W) is excluded

    def test_mention_hints_validated(self):
        self.assertIsInstance(parse.parse_mention_hints("x"), InputRejected)
        self.assertIsInstance(parse.parse_mention_hints(["a"] * (parse.MENTION_MAX + 1)), InputRejected)
        self.assertEqual(parse.parse_mention_hints(None), [])

    def test_events_are_capped_but_seq_keeps_rising(self):
        with mock.patch.object(ps, "EVENTS_KEEP", 3):
            for i in range(5):
                ps.emit_events([{"type": "mention", "pin": i, "to": ["x"]}])
        self.assertEqual([e["seq"] for e in self.events()], [3, 4, 5])


class NotifyServer(Base):
    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
    HW = {"Tailscale-User-Login": "wendy@example.com", "Tailscale-User-Name": "Wendy Kim"}

    def setUp(self):
        super().setUp()
        ps._EVENTS_CACHE.clear()

    def get(self, path, headers=None):
        code, h, raw = split_resp(self.talk(req("GET", path, headers=headers)))
        return code, h, raw

    def test_service_worker_route(self):
        code, h, raw = self.get("/sw.js")
        self.assertEqual(code, 200)
        self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")
        self.assertEqual(h["cache-control"], "no-cache")
        js = raw.decode()
        self.assertIn("showNotification" if False else "notificationclick", js)
        self.assertIn("clients.openWindow", js)
        self.assertIn("postMessage({type:e.action==='restore'?'restore-pin':'open-pin'", js)   # v0.2.2: [되살리기] on a 'dropped' notification
        self.assertNotIn("'fetch'", js)                                   # doesn't cache app data
        code, _, _ = self.get("/sw.js", {"Host": "evil.example"})
        self.assertEqual(code, 403)
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_event_cursor_in_light_meta(self):
        ps.emit_events([{"type": "mention", "pin": 1, "doc": "main", "to": ["wendy@example.com"], "by": {"login": "bob@example.com"}},
                        {"type": "replied", "pin": 1, "doc": "main", "to": ["bob@example.com"], "by": {"login": "local"}},
                        {"type": "mention", "pin": 2, "doc": "main", "to": ["wendy@example.com"], "by": {"login": "wendy@example.com"}}])
        _, _, raw = self.get("/api/meta?light=1", self.HW)
        d = json.loads(raw)
        self.assertEqual(d["ev_seq"], 3)
        self.assertNotIn("events", d)                                     # not included without a cursor
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual([(e["seq"], e["type"], e["doc_name"]) for e in json.loads(raw)["events"]], [(1, "mention", "본문")])
        _, _, raw = self.get("/api/meta?light=1&ev=1", self.HW)
        self.assertEqual(json.loads(raw)["events"], [])                   # something you did yourself (seq 3) doesn't come back
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HS)
        self.assertEqual([e["seq"] for e in json.loads(raw)["events"]], [2])
        _, _, raw = self.get("/api/meta?light=1&ev=0")
        self.assertEqual(json.loads(raw)["events"], [])                   # not included for local/agent
        code, _, _ = self.get("/api/meta?light=1&ev=x", self.HW)
        self.assertEqual(code, 400)
        before = sorted(p.name for p in ps.C.state.iterdir())
        self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual(sorted(p.name for p in ps.C.state.iterdir()), before)   # polling doesn't count


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
