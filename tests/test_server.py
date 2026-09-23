"""pin_server 회귀 테스트 — 포트를 열지 않는다(socketpair 로 핸들러를 직접 돌린다).

실행: python3 -m unittest discover -s skills/manuscript-pin-picker/tests
"""
import importlib.util
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

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pin_server", HERE.parent / "scripts" / "pin_server.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)


def extract_js_fn(name: str) -> str:
    """ps.HTML 에서 'function NAME(...){ ... }' 정의 하나를 중괄호 균형을 맞춰 그대로 뽑는다.

    문자열 리터럴에 중괄호가 없는(=이 파일의 순수 로직 함수들 — 그 안에 DOM/CSS 텍스트가 없는)
    함수에만 안전하다. 이렇게 뽑은 실제 서버 소스를 node 로 그대로 돌려, 프런트엔드 로직을
    회귀 테스트가 문자열로 베껴 둔 사본이 아니라 진짜 소스로 검증한다.

    'async function NAME(' 도 뽑는다 — 'function NAME(' 만 찾으면 앞의 'async '가 잘려 나가
    (await 가 있는 함수를) node 가 'await is only valid in async functions'로 거부한다."""
    src = ps.HTML
    key = "function %s(" % name
    i = src.index(key)
    if i >= 6 and src[i - 6:i] == "async ":
        i -= 6
    j = src.index("{", i)
    depth = 0
    k = j
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1]


def run_node(js: str, tz: str = None):
    """js 를 node 로 실행하고 stdout 을 돌려준다. node 가 없으면 스킵한다(테스트 쪽에서 처리).

    tz 를 주면 그 시간대로 실행한다 — isEstimated 가 더 이상 벽시계를 안 쓰는지(frac_build 경로)
    직접 확인하는 용도."""
    node = shutil.which("node")
    if not node:
        return None
    env = dict(os.environ)
    if tz is not None:
        env["TZ"] = tz
    r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=15, env=env)
    if r.returncode != 0:
        raise AssertionError("node 실행 실패:\n%s" % r.stderr)
    return r.stdout

TEX = """\\documentclass{article}
\\begin{document}
\\section{Intro}
First paragraph line one about rarewordalpha.
First paragraph line two.

% TODO 주석
Body line seven betaunique.
Body line eight gammaunique.
% 꼬리 주석

\\begin{table}
\\begin{tabular}{l}
cell deltaunique \\\\
\\end{tabular}
\\end{table}
After table epsilonunique.
\\subsection{Next}
Tail paragraph zetaunique.
\\end{document}
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "ms"
        self.src.mkdir()
        self.main = self.src / "main.tex"
        self.main.write_text(TEX, encoding="utf-8")
        C = ps.C
        C.src, C.main = self.src, self.main
        C.state = root / "state"
        C.state.mkdir()
        C.build = C.state / "build"
        C.port, C.dpi, C.timeout = 18999, 150, 60
        C.envs = tuple(ps.DEFAULT_ENVS.split(","))
        C.allow = frozenset()
        C.origin_check = True
        C.git_pull = False
        C.pdfjs_dir = None
        C.label, C.accent, C.repo = "원고", ps.ACCENT_PALETTE[0], None
        ps.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None, seq=0,
                              finished_at=None, last=None, errors=[], log_tail="", head=None, pull=None)
        ps.init_seq()

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, lo=4, hi=5, note="n", actor=None):
        return ps.add_pin({"file": str(self.main), "lo": lo, "hi": hi, "page": 1, "note": note},
                          actor or dict(ps.LOCAL_ACTOR))

    def pin(self, pid):
        return ps.find_pin(ps.snapshot_pins(), pid)

    def talk(self, raw: bytes, shut=True) -> bytes:
        """raw 를 한 연결로 보내고 서버가 닫을 때까지 응답 바이트를 모은다."""
        a, b = socket.socketpair()
        def serve():
            try:
                ps.Handler(b, ("127.0.0.1", 0), None)
            finally:
                b.close()                         # socketserver 의 shutdown_request 몫
        t = threading.Thread(target=serve, daemon=True)
        t.start()
        a.sendall(raw)
        if shut:
            a.shutdown(socket.SHUT_WR)
        a.settimeout(10)
        out = b""
        try:
            while True:
                chunk = a.recv(65536)
                if not chunk:
                    break
                out += chunk
        finally:
            a.close()
        t.join(10)
        return out


def split_resp(out: bytes):
    """응답 바이트 한 건을 (상태 코드, 소문자 헤더 dict, 본문) 으로 나눈다."""
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    code = int(lines[0].split()[1])
    hdrs = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        hdrs[k.strip().lower()] = v.strip()
    return code, hdrs, body


def req(method, path, body=b"", headers=None):
    h = {"Host": "127.0.0.1:18999"}
    h.update(headers or {})
    if body:
        h["Content-Length"] = str(len(body))
    head = "%s %s HTTP/1.1\r\n" % (method, path) + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n"
    return head.encode() + body


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
        body = req("POST", "/api/pins/%d/close" % pid)   # TE 를 무시하는 서버는 이것을 다음 요청으로 읽는다
        raw = (b"POST /api/pins/%d/reopen HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nTransfer-Encoding: chunked\r\n\r\n"
               % pid + body)
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        self.assertEqual(out.count(b"HTTP/1.1 "), 1, out)
        self.assertFalse(self.pin(pid).get("done"))

    def test_short_body_does_nothing(self):
        self.add()
        raw = b"POST /api/clear HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: 5\r\n\r\n"   # 본문 없이 끊김
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
        out = self.talk(req("POST", "/api/pins/%d/close" % pid))           # curl 모양: 본문·Origin 없음
        self.assertIn(b" 200 ", out)
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net",
                                                         "Origin": "https://box.tail1234.ts.net",
                                                         "Tailscale-User-Login": "bob@x.com"}))
        self.assertIn(b" 200 ", out)

    def test_rebinding_with_forged_tailscale_header_rejected(self):
        # rebinding 페이지는 같은 출처 GET 에 Tailscale-User-Login 을 preflight 없이 실을 수 있다.
        pid = self.add(note="secret-note")
        h = {"Host": "evil.example:18999", "Tailscale-User-Login": "x@y"}
        for path in ("/api/pins", "/api/meta", "/api/snippet?file=main.tex&lo=4&hi=4"):
            out = self.talk(req("GET", path, headers=h))
            self.assertIn(b" 403 ", out, path)
            self.assertNotIn(b"secret-note", out)
            self.assertNotIn(b"rarewordalpha", out)
        out = self.talk(req("POST", "/api/pins/%d/drop" % pid, headers=h))   # Origin 없는 POST
        self.assertIn(b" 403 ", out)
        self.assertIsNotNone(self.pin(pid))

    def test_host_ok_ignores_loopback_port_ssh_forward(self):
        # 결함: host_ok 가 루프백 이름이어도 포트가 C.port 와 같아야 했다 — SSH -L 로 다른 로컬
        # 포트에 포워딩하면(Host: localhost:9000, 서버는 18999) 403 이 됐다.
        self.assertTrue(ps.host_ok("localhost:9000"))
        self.assertTrue(ps.host_ok("127.0.0.1:1"))
        self.assertTrue(ps.host_ok("[::1]:9000"))
        self.assertTrue(ps.host_ok("localhost"))              # 포트 없음도 여전히 허용

    def test_host_ok_still_rejects_non_loopback_non_tailnet(self):
        self.assertFalse(ps.host_ok("evil.example"))
        self.assertFalse(ps.host_ok("evil.example:18999"))    # 서버 포트를 흉내내도 이름이 아니면 거부

    def test_host_ok_tailnet_unaffected(self):
        self.assertTrue(ps.host_ok("box.tail1234.ts.net"))
        self.assertTrue(ps.host_ok("box.tail1234.ts.net:443"))

    def test_origin_ok_loopback_host_accepts_any_loopback_port(self):
        # 설계(P0b 수선 2): Host 가 루프백이면 Origin 도 루프백이기만 하면 된다(포트 무관 — SSH -L 은 Host·Origin
        # 포트가 서버 바인딩 포트와 다르다. 실측: 18110→18106 포워딩 뒤 POST 가 전부 403 이었다).
        self.assertTrue(ps.origin_ok("http://127.0.0.1:9000", "localhost:9000"))
        self.assertTrue(ps.origin_ok("http://localhost:18999", "127.0.0.1:18999"))
        self.assertTrue(ps.origin_ok("http://127.0.0.1:18110", "localhost:18106"))
        self.assertTrue(ps.origin_ok("http://[::1]:9000", "[::1]:9000"))
        self.assertTrue(ps.origin_ok("http://127.0.0.1:18999", None))
        self.assertFalse(ps.origin_ok("http://evil.example:18999", "localhost:18999"))
        self.assertFalse(ps.origin_ok("null", "localhost:18999"))

    def test_origin_ok_loopback_host_rejects_tailnet_origin(self):
        # 결함(should → 설계 3): 루프백 Host 에 *.ts.net Origin 을 받아, 다른 tailnet 의 Funnel 공개 페이지가
        # 로컬 사용자 브라우저로 본문 없는 POST(close·clear)를 preflight 없이 보냈다(실측 200).
        self.assertFalse(ps.origin_ok("https://evil-funnel.tailabcd.ts.net", "127.0.0.1:18999"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net", "localhost:18999"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net", None))

    def test_origin_ok_tailnet_host_requires_same_host_and_port(self):
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net"))
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:443", "box.tail1234.ts.net"))   # 기본 포트 정규화
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net", "box.tail1234.ts.net:443"))
        self.assertTrue(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net:8443"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:8443", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://evil.tailabcd.ts.net", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("http://127.0.0.1:18999", "box.tail1234.ts.net"))
        self.assertFalse(ps.origin_ok("https://box.tail1234.ts.net:99999", "box.tail1234.ts.net"))   # 틀린 포트

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
        # SSH -L 9000:127.0.0.1:18999 뒤에서 브라우저가 보내는 모양: Host 는 포워딩 포트, Origin 은 없다(직접
        # 주소창 접근) 또는 있어도 실제 서버 포트를 가리킨다(브라우저가 연결한 포트가 Origin 의 포트다 — 이
        # 테스트는 curl 모양의 Origin 없는 요청으로 가장 흔한 경우를 확인한다).
        out = self.talk(req("GET", "/api/meta", headers={"Host": "localhost:9000"}))
        self.assertIn(b" 200 ", out)

    def test_ssh_forwarded_port_post_with_matching_origin_allowed(self):
        # 실제 브라우저가 포워딩 뒤에서 보내는 모양(Host 와 Origin 이 둘 다 포워딩 포트) — 고치기 전에는
        # GET 만 통과하고 첫 드래그(POST /api/pick 류)는 항상 403 이라 뷰어가 읽기 전용이 됐다.
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Host": "localhost:9000",
                                                         "Origin": "http://localhost:9000",
                                                         "Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        self.assertEqual(len(ps.snapshot_pins()), 1)

    def test_ssh_forwarded_non_loopback_origin_still_rejected(self):
        # 포워딩 뒤에서도 루프백이 아닌 출처는 막는다(포트만 보지 않을 뿐 이름은 본다).
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Host": "localhost:9000",
                                                         "Origin": "http://evil.example:9000",
                                                         "Content-Type": "application/json"}))
        self.assertIn(b" 403 ", out)
        self.assertEqual(ps.snapshot_pins(), [])

    def test_forged_host_plus_identity_header_still_403(self):
        # Host 완화가 rebinding 방어를 깨지 않는지 — 루프백이 아닌 이름은 여전히 거부된다.
        pid = self.add(note="secret-note-2")
        out = self.talk(req("GET", "/api/pins", headers={"Host": "evil.example",
                                                          "Tailscale-User-Login": "x@y"}))
        self.assertIn(b" 403 ", out)
        self.assertNotIn(b"secret-note-2", out)
        self.assertIsNotNone(self.pin(pid))

    def test_no_origin_check_switch(self):
        ps.C.origin_check = False
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.example.com"}))
        self.assertIn(b" 200 ", out)

    def test_allow_rejects_headerless_tailnet_request(self):
        ps.C.allow = frozenset({"ok@x.com"})
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net"}))   # 태그 장치 모양
        self.assertIn(b" 403 ", out)
        out = self.talk(req("GET", "/api/meta"))                                          # 루프백 curl
        self.assertIn(b" 200 ", out)
        out = self.talk(req("GET", "/api/meta", headers={"Host": "box.tail1234.ts.net",
                                                         "Tailscale-User-Login": "ok@x.com"}))
        self.assertIn(b" 200 ", out)

    def test_non_ascii_content_length_is_400(self):
        raw = b"POST /api/pin HTTP/1.1\r\nHost: 127.0.0.1:18999\r\nContent-Length: \xb2\r\n\r\n"
        out = self.talk(raw)
        self.assertIn(b" 400 ", out)
        out = self.talk(b"GET /api/meta HTTP/1.1\r\nHost: 127.0.0.1:\xb2\r\n\r\n")   # Host 포트도 같은 함정
        self.assertIn(b" 403 ", out)

    def test_deep_json_is_400(self):
        body = b"[" * 100000 + b"]" * 100000
        out = self.talk(req("POST", "/api/pin", body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)


VENDOR = HERE.parent / "vendor" / "pdfjs"


class VendorPdfjs(Base):
    """GET /vendor/pdfjs/<파일> — 벡터 렌더링용 PDF.js 정적 서빙(MIME·캐시·경로 탈출·Host 검사)."""

    def get(self, path, headers=None):
        return split_resp(self.talk(req("GET", path, headers=headers)))

    def test_serves_both_modules_as_javascript(self):
        for name in ("pdf.min.mjs", "pdf.worker.min.mjs"):
            code, h, body = self.get("/vendor/pdfjs/%s?v=%s" % (name, ps.PDFJS_VERSION))
            self.assertEqual(code, 200, name)
            self.assertEqual(h["content-type"], "text/javascript; charset=utf-8")   # 모듈 스크립트는 JS MIME 이어야 실행된다
            self.assertEqual(h["x-content-type-options"], "nosniff")
            self.assertEqual(h["cache-control"], "public, max-age=86400")
            self.assertEqual(body, (VENDOR / name).read_bytes())

    def test_traversal_and_non_module_names_are_404(self):
        for path in ("/vendor/pdfjs/../scripts/pin_server.py", "/vendor/pdfjs/..%2f..%2fscripts%2fpin_server.py",
                     "/vendor/pdfjs/%2e%2e/%2e%2e/scripts/pin_server.py", "/vendor/pdfjs/sub/pdf.min.mjs",
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
        self.assertEqual(code, 404)                        # 뷰어는 이것을 보고 PNG 로 돌아간다

    def test_host_and_origin_checked_like_other_gets(self):
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.get("/vendor/pdfjs/pdf.min.mjs", {"Host": "box.tail1234.ts.net",
                                                                "Origin": "https://box.tail1234.ts.net",
                                                                "Tailscale-User-Login": "a@b"})[0], 200)

    def test_version_pinned_in_vendor_html_and_readme(self):
        head = (VENDOR / "pdf.min.mjs").read_bytes()[:2000].decode("utf-8")
        self.assertIn("pdfjsVersion = %s" % ps.PDFJS_VERSION, head)
        whead = (VENDOR / "pdf.worker.min.mjs").read_bytes()[:2000].decode("utf-8")
        self.assertIn("pdfjsVersion = %s" % ps.PDFJS_VERSION, whead)
        readme = (VENDOR / "README.md").read_text(encoding="utf-8")
        self.assertIn("pdfjs-dist@%s" % ps.PDFJS_VERSION, readme)
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
    """GET /pdf?build=<pages_build> — 쪽 이미지와 같은 빌드의 PDF 만 준다."""

    def setUp(self):
        super().setUp()
        self.old, self.new = "pages-20250101000000", "pages-20260101000000"
        for name, body in ((self.old, b"%PDF-old"), (self.new, b"%PDF-new")):
            d = ps.C.state / name
            d.mkdir()
            (d / "main.pdf").write_bytes(body)
        ps.atomic_write(ps.C.pages_ptr, self.new)
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
            self.assertEqual(got, body)                   # 직전 빌드를 물으면 직전 빌드 — 지금 것으로 바꾸지 않는다

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
        (ps.C.state / self.new / "main.pdf").unlink()   # 쪽 디렉토리에 짝 PDF 가 없으면 build/ 로 물러서지 않는다
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
        m = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertEqual(m["pages_build"], self.new)
        self.assertEqual(self.get("/pdf?build=%s" % m["pages_build"])[2], b"%PDF-new")


class Store(Base):
    def test_concurrent_adds_all_kept(self):
        ids, errs = [], []

        def go(i):
            try:
                ids.append(self.add(note="c%d" % i))
            except Exception as e:  # noqa: BLE001
                errs.append(e)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(len(set(ids)), 30)
        self.assertEqual(len(ps.snapshot_pins()), 30)

    def test_bad_record_is_quarantined_not_500(self):
        self.add()
        with open(ps.C.pins_jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 900, "file": str(self.main), "lo": "5", "hi": None}) + "\n")
            fh.write(json.dumps({"id": 950, "lo": 3, "hi": 3}) + "\n")
        rows = ps.snapshot_pins()
        self.assertEqual([r["id"] for r in rows], [1])
        nid = self.add()
        self.assertEqual(nid, 2)
        self.assertEqual(len(list(ps.C.state.glob("pins.jsonl.corrupt-*.bak"))), 1)

    def test_mistyped_fields_are_quarantined(self):
        self.add()
        good = {"file": str(self.main), "lo": 4, "hi": 4}
        bad = [dict(good, id=960, file="main.tex"),               # 상대 경로
               dict(good, id=961, author="str"),
               dict(good, id=962, frac="bad"),
               dict(good, id=963, edited_by=5),
               dict(good, id=964, rev="x"),
               dict(good, id=965, synced_at="x"),
               dict(good, id=966, edited_at=5),
               dict(good, id=967, done="yes"),
               dict(good, id=968, frac=[0, 0, 1]),
               dict(good, id=969, author={"name": 3})]
        with open(ps.C.pins_jsonl, "a", encoding="utf-8") as fh:
            for r in bad:
                fh.write(json.dumps(r) + "\n")
        os.utime(self.main, (time.time() + 5, time.time() + 5))   # sync_all 이 synced_at 을 비교하게
        self.assertEqual([r["id"] for r in ps.snapshot_pins()], [1])
        self.assertEqual(len(list(ps.C.state.glob("pins.jsonl.corrupt-*.bak"))), 1)

    def test_out_of_tree_file_is_not_read(self):
        outside = Path(self.tmp.name) / "outside.tex"
        outside.write_text("line one outsidesecret\nline two\n", encoding="utf-8")
        with open(ps.C.pins_jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 970, "file": str(outside), "lo": 1, "hi": 1, "anchor": {}}) + "\n")
        with self.assertRaises(ps.HTTPError) as cm:
            ps.edit_pin(970, {"lo": 1, "hi": 2, "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(cm.exception.code, 400)
        self.assertNotIn("outsidesecret", json.dumps(ps.snapshot_pins()))

    def test_lines_edit_drops_via_score(self):
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "via": "synctex", "score": 0.74},
                         dict(ps.LOCAL_ACTOR))
        p = ps.edit_pin(pid, {"lo": 4, "hi": 6, "scope": "lines", "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertNotIn("via", p)
        self.assertNotIn("score", p)

    def test_stale_term_in_pins_md(self):
        pid = self.add(8, 9)
        self.main.write_text(TEX.replace("Body line seven betaunique.", "rewritten").replace(
            "Body line eight gammaunique.", "rewritten2"), encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        self.assertTrue(self.pin(pid).get("stale"))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("%d ⚠" % pid, md)          # v2: 위치 잃음은 번호 칸의 ⚠ 기호로 표시된다
        self.assertIn("위치를 잃음", md)          # 기호 범례 줄
        self.assertNotIn("원문에서 사라짐", md)

    def test_render_failure_does_not_commit(self):
        self.add()
        before = ps.C.pins_jsonl.read_text()
        with mock.patch.object(ps, "pins_md_text", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.add(note="x")
        self.assertEqual(ps.C.pins_jsonl.read_text(), before)

    def test_two_clears_same_second_keep_both(self):
        self.add(note="FIRST")
        ps.clear_pins()
        self.add(note="SECOND")
        ps.clear_pins()
        baks = list(ps.C.state.glob("pins_*.jsonl.bak"))
        self.assertEqual(len(baks), 2)
        blob = "".join(p.read_text() for p in baks)
        self.assertIn("FIRST", blob)
        self.assertIn("SECOND", blob)

    def test_restore_survives_failed_pins_write(self):
        pid = self.add()
        ps.drop_pin(pid, dict(ps.LOCAL_ACTOR))
        with mock.patch.object(ps, "write_pins", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ps.restore_pin(pid, dict(ps.LOCAL_ACTOR))
        dropped, _ = ps.read_jsonl(ps.C.dropped)
        self.assertIn(pid, [r["id"] for r in dropped])
        self.assertEqual(ps.restore_pin(pid, dict(ps.LOCAL_ACTOR))["id"], pid)
        self.assertEqual(ps.read_jsonl(ps.C.dropped)[0], [])

    def test_edit_loc_keeps_page_frac_and_defaults_kind(self):
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 3, "frac": [0.1, 0.2, 0.3, 0.4]},
                         dict(ps.LOCAL_ACTOR))
        p = ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 8, "hi": 9}, "base_rev": 0},
                        dict(ps.LOCAL_ACTOR))
        self.assertEqual((p["lo"], p["hi"], p["page"], p["kind"]), (8, 9, 3, "lines"))
        self.assertEqual(p["frac"], [0.1, 0.2, 0.3, 0.4])

    def test_add_pin_stamps_pdf_build(self):
        # 설계 1: frac 이 가리키는 좌표계를 벽시계가 아니라 '어느 빌드였는지'(pdf_build)로 못박는다.
        pid = self.add()
        self.assertEqual(self.pin(pid)["pdf_build"], ps.cur_pages().name)

    def test_add_pin_keeps_client_pdf_build(self):
        # 뷰어는 pick 응답의 pdf_build(드래그할 때 화면의 빌드)를 그대로 보낸다 — 재빌드 직후 화면을 바꾸기 전의
        # 드래그는 옛 빌드로 남아야 한다.
        (ps.C.state / "pages-20260101000000").mkdir()
        ps.C.pages_ptr.write_text("pages-20260101000000")
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "pdf_build": "pages"},
                         dict(ps.LOCAL_ACTOR))
        self.assertEqual(self.pin(pid)["pdf_build"], "pages")
        with self.assertRaises(ps.HTTPError):
            ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "pdf_build": "../pins"}, dict(ps.LOCAL_ACTOR))

    def _new_build(self, name="pages-20260101000000"):
        (ps.C.state / name).mkdir(exist_ok=True)
        ps.C.pages_ptr.write_text(name)
        return name

    def test_edit_loc_with_new_frac_restamps_pdf_build(self):
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "frac": [0, 0, 1, 1]},
                         dict(ps.LOCAL_ACTOR))
        old_build = self.pin(pid)["pdf_build"]
        nb = self._new_build()
        p = ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 4, "hi": 5,
                                       "frac": [0.1, 0.1, 0.2, 0.2]}, "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertNotEqual(p["pdf_build"], old_build)
        self.assertEqual(p["pdf_build"], nb)

    def test_edit_loc_without_frac_keeps_pdf_build_even_if_sent(self):
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        nb = self._new_build()
        p = ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 8, "hi": 9, "pdf_build": nb}, "base_rev": 0},
                        dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["pdf_build"], old_build)

    def test_edit_loc_replaces_legacy_frac_build_field(self):
        pid = self.add()
        rows, _ = ps.read_pins()
        rows[0].pop("pdf_build")
        rows[0]["frac_build"] = "pages"
        ps.write_pins(rows)
        nb = self._new_build()
        p = ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0, 0, 1, 1]},
                              "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["pdf_build"], nb)
        self.assertNotIn("frac_build", p)

    def test_edit_note_only_does_not_touch_pdf_build(self):
        # 결함(must-2 갈래 a): 메모만 고쳐도 edited_at 이 지금으로 튀어(옛 로직) '추정' 표시가 꺼졌다.
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = ps.edit_pin(pid, {"note": "고친 메모", "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["pdf_build"], old_build)

    def test_note_append_does_not_touch_pdf_build(self):
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = ps.edit_pin(pid, {"note_append": "덧붙임"}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["pdf_build"], old_build)

    def test_lo_hi_only_edit_does_not_touch_pdf_build(self):
        # frac 없이 lo/hi 만 손으로 옮기면 frac 좌표 자체를 다시 찍은 게 아니므로 pdf_build 도 그대로다.
        pid = self.add()
        old_build = self.pin(pid)["pdf_build"]
        self._new_build()
        p = ps.edit_pin(pid, {"lo": 4, "hi": 6, "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["pdf_build"], old_build)

    def test_meta_exposes_pages_build(self):
        d = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertEqual(d["pages_build"], ps.cur_pages().name)


class Legacy(Base):
    def test_migrate_copies_pdf_next_to_pages(self):
        (ps.C.state / "pages").mkdir()
        (ps.C.state / "pages" / "page-01.png").write_bytes(b"png")
        ps.C.build.mkdir()
        (ps.C.build / "main.pdf").write_bytes(b"%PDF-old")
        (ps.C.build / "main.synctex.gz").write_bytes(b"syn-old")
        ps.migrate_pages()
        self.assertEqual(ps.cur_pdf(), ps.C.state / "pages" / "main.pdf")
        (ps.C.build / "main.pdf").write_bytes(b"%PDF-new")       # 재빌드가 build/ 를 덮어써도
        self.assertEqual(ps.cur_pdf().read_bytes(), b"%PDF-old")  # pick 은 화면과 짝인 PDF 를 읽는다
        self.assertEqual((ps.C.state / "pages" / "main.synctex.gz").read_bytes(), b"syn-old")
        ps.migrate_pages()                                        # 두 번 불러도 덮지 않는다
        self.assertEqual(ps.cur_pdf().read_bytes(), b"%PDF-old")


class Anchor(Base):
    def _shift(self, n):
        lines = TEX.splitlines()
        lines[3:3] = ["inserted %d" % i for i in range(n)]      # L4 앞에 n 줄
        time.sleep(0.01)
        self.main.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))

    def test_trailing_comment_kept(self):
        pid = self.add(8, 10)                     # 본문 두 줄 + 꼬리 주석
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (11, 13, "moved +3"))

    def test_leading_comment_kept(self):
        pid = self.add(7, 10)                     # 앞 주석 + 본문 + 꼬리 주석
        self._shift(3)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"], p["sync"]), (10, 13, "moved +3"))

    def test_old_anchor_without_offsets(self):
        pid = self.add(8, 9)
        rows = ps.snapshot_pins()
        for r in rows:
            r["anchor"].pop("head_off")
            r["anchor"].pop("tail_off")
        ps.write_pins(rows)
        self._shift(2)
        p = self.pin(pid)
        self.assertEqual((p["lo"], p["hi"]), (10, 11))


class Ladder(Base):
    def test_para_stays_inside_env(self):
        lines = TEX.splitlines()
        lad = ps.compute_levels(lines, 14, 14)    # 표 안의 셀
        para = ps.find_level(lad["levels"], "para")
        self.assertGreaterEqual(para["lo"], 13)
        self.assertLessEqual(para["hi"], 15)

    def test_para_stops_at_subsection(self):
        lines = TEX.splitlines()
        lad = ps.compute_levels(lines, 17, 17)    # 표 뒤 줄 — 다음 줄이 \subsection
        para = ps.find_level(lad["levels"], "para")
        self.assertEqual(para["hi"], 17)


# ---------------------------------------------------------------- P0b-01 비동기 빌드

class AsyncBuild(Base):
    def tearDown(self):
        if ps.BUILD_LOCK.locked():
            ps.BUILD_LOCK.release()
        ps.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None)
        super().tearDown()

    def test_async_returns_running_then_409_while_busy(self):
        ev = threading.Event()

        def fake_build():
            ev.wait(5)
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.01, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            r1 = ps.build_async()
            self.assertEqual(r1, {"state": "running"})
            self.assertEqual(ps.build_state_snapshot()["state"], "running")
            r2 = ps.build_async()
            self.assertEqual(r2, {"state": "running", "busy": True})
            ev.set()
            for _ in range(200):
                if not ps.BUILD_LOCK.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.BUILD_LOCK.locked())
        self.assertEqual(ps.build_state_snapshot()["state"], "ok")

    def test_phase_copy_observed_before_build_runs(self):
        seen = []

        def fake_build():
            seen.append(ps.build_state_snapshot()["phase"])
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.0, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all()
        self.assertEqual(seen, ["copy"])
        self.assertEqual(ps.build_state_snapshot()["phase"], None)   # 끝나면 phase 를 비운다

    def test_ok_errors_state_surfaces_in_build_state(self):
        def fake_build():
            return {"ok": True, "state": "ok_errors", "errors": [{"line": 412, "msg": "Undefined control sequence"}],
                    "log": "boom", "elapsed_s": 1.2, "pages": 3}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all()
        st = ps.build_state_snapshot()
        self.assertEqual(st["state"], "ok_errors")
        self.assertEqual(st["errors"][0]["line"], 412)

    def test_ok_errors_commits_built_src_mtime(self):
        def fake_build():
            return {"ok": True, "state": "ok_errors", "errors": [{"line": 1, "msg": "x"}],
                    "log": "", "elapsed_s": 0.0, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all()
        self.assertIsNotNone(ps.read_built_src_mtime())

    def test_failed_build_does_not_commit_built_src_mtime(self):
        # 결함: built_src_mtime 을 빌드 '시작 때' 썼고 실패해도 남았다 — 화면은 옛 PDF인데
        # '원고 수정됨' 배지가 꺼졌다. ok|ok_errors 일 때만 확정해야 한다.
        self.assertIsNone(ps.read_built_src_mtime())

        def fake_build_fail():
            return {"ok": False, "state": "fail", "errors": [], "log": "boom", "elapsed_s": 0.1, "pages": 0}
        with mock.patch.object(ps, "_build", side_effect=fake_build_fail):
            ps.build_all()
        self.assertIsNone(ps.read_built_src_mtime())          # 실패했으니 여전히 없다
        self.assertEqual(ps.build_state_snapshot()["state"], "fail")

        def fake_build_ok():
            return {"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.1, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build_ok):
            ps.build_all()
        first_ok = ps.read_built_src_mtime()
        self.assertIsNotNone(first_ok)                        # 성공하고 나서야 확정된다

        with mock.patch.object(ps, "_build", side_effect=fake_build_fail):
            ps.build_all()
        self.assertEqual(ps.read_built_src_mtime(), first_ok)  # 그 다음 실패는 확정값을 건드리지 않는다

    def test_async_worker_exception_ends_in_fail_not_stuck_running(self):
        # 결함: 비동기 빌드 워커에서 예외가 나면 BUILD_STATE 가 running 에 영원히 멈췄다.
        with mock.patch.object(ps, "_build", side_effect=RuntimeError("boom")):
            r = ps.build_async()
            self.assertEqual(r, {"state": "running"})
            for _ in range(200):
                if not ps.BUILD_LOCK.locked():
                    break
                time.sleep(0.02)
        self.assertFalse(ps.BUILD_LOCK.locked())
        st = ps.build_state_snapshot()
        self.assertEqual(st["state"], "fail")
        self.assertIn("boom", st.get("log_tail") or "")

    def test_rebuild_async_endpoint_202_then_409(self):
        ps.BUILD_LOCK.acquire()
        try:
            out = self.talk(req("POST", "/api/rebuild?async=1"))
            self.assertIn(b" 409 ", out)
        finally:
            ps.BUILD_LOCK.release()

    def test_get_api_build_reports_known_state(self):
        out = self.talk(req("GET", "/api/build"))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn(data["state"], ("idle", "running", "ok", "ok_errors", "fail"))
        self.assertIn("phase", data)
        self.assertIn("log_tail", data)

    def test_real_build_progresses_through_all_phases(self):
        """실제 latexmk·pdftoppm 으로 한 번 돌려 copy→latex→render 순서를 관측한다(도구가 있을 때만)."""
        import shutil as _sh
        if not (_sh.which("latexmk") and _sh.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        seen = []
        stop = threading.Event()

        def poll():
            while not stop.is_set():
                ph = ps.build_state_snapshot()["phase"]
                if ph and (not seen or seen[-1] != ph):
                    seen.append(ph)
                time.sleep(0.01)
        t = threading.Thread(target=poll, daemon=True)
        t.start()
        res = ps.build_all()
        stop.set()
        t.join(2)
        self.assertEqual(res["state"], "ok")
        self.assertIn("latex", seen)
        self.assertIn("render", seen)
        self.assertTrue(ps.cur_pdf().exists())


# ---------------------------------------------------------------- 위치 추정(.est) — 서버 판정

class Estimate(Base):
    """설계 1: est = (pin.pdf_build ≠ 지금 빌드) 그리고 (두 빌드의 원고 지문이 다름), 또는 sync moved/lost.
    판정은 서버가 하고 GET /api/pins 의 est 로 싣는다 — 벽시계(브라우저 시간대·edited_at)는 쓰지 않는다."""

    def _fake_build(self, name, src_hash, src_mtime=None):
        (ps.C.state / name).mkdir(exist_ok=True)
        ps.C.pages_ptr.write_text(name)
        ps.finish_build({"ok": True, "state": "ok", "errors": [], "log": "", "elapsed_s": 0.1, "pages": 1,
                         "build": name, "src_hash": src_hash}, src_mtime if src_mtime is not None else time.time())
        return name

    def est_of(self, pid):
        out = self.talk(req("GET", "/api/pins?all=1"))
        rows = json.loads(out.split(b"\r\n\r\n", 1)[1])
        return {r["id"]: r["est"] for r in rows}[pid]

    def test_same_build_is_not_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self.assertIs(self.est_of(pid), False)

    def test_rebuild_with_same_source_is_not_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h1")
        self.assertIs(self.est_of(pid), False)

    def test_rebuild_with_changed_source_is_estimated_and_survives_note_edit(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h2")
        self.assertIs(self.est_of(pid), True)
        ps.edit_pin(pid, {"note": "메모만", "base_rev": 0}, dict(ps.LOCAL_ACTOR))        # must-2(a)
        self.assertIs(self.est_of(pid), True)
        ps.edit_pin(pid, {"note_append": "덧붙임"}, dict(ps.LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)

    def test_relocating_on_current_build_clears_estimate(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()
        self._fake_build("pages-20260101000100", "h2")
        p = self.pin(pid)
        ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 4, "hi": 5, "frac": [0, 0, 0.5, 0.5]},
                          "base_rev": p["rev"]}, dict(ps.LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), False)

    def test_pin_on_stale_pdf_is_estimated_after_rebuild(self):
        # must-2(b): 원고를 고친 뒤 옛 PDF 위에서 찍은 핀. 찍은 시각이 다음 빌드보다 늦어도 빌드 신원으로 잡힌다.
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add()                                  # 화면은 h1 빌드(원고는 이미 바뀜)
        self._fake_build("pages-20260101000100", "h2")
        self.assertIs(self.est_of(pid), True)

    def test_unknown_pin_build_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "pdf_build": "pages"},
                         dict(ps.LOCAL_ACTOR))            # 이력에 없는 빌드 — 모르면 추정(보수적)
        self.assertIs(self.est_of(pid), True)

    def test_sync_moved_or_lost_is_estimated(self):
        self._fake_build("pages-20260101000000", "h1")
        pid = self.add(8, 8)
        self.assertIs(self.est_of(pid), False)
        time.sleep(0.02)
        self.main.write_text("new first line\n" + TEX, encoding="utf-8")
        os.utime(self.main, (time.time() + 5, time.time() + 5))
        self.assertIs(self.est_of(pid), True)             # moved +1
        self.assertEqual(self.pin(pid)["sync"], "moved +1")

    def test_same_source_falls_back_to_src_mtime_without_hash(self):
        a = {"src_hash": None, "src_mtime": 100.0}
        self.assertTrue(ps.same_source(a, {"src_hash": None, "src_mtime": 100.0}))
        self.assertFalse(ps.same_source(a, {"src_hash": None, "src_mtime": 101.0}))
        self.assertFalse(ps.same_source(a, None))
        self.assertFalse(ps.same_source({"src_hash": "x"}, {"src_hash": "y", "src_mtime": 1}))

    def test_legacy_pin_uses_epoch_heuristic_on_server(self):
        # pdf_build 가 없는 옛 핀: at(서버 현지 시각 문자열)을 서버가 epoch 로 풀어 built_at·빌드 시작 src_mtime 과 비교.
        (ps.C.state / "built_at.txt").write_text("2026-09-22T10:00:00+09:00")
        ps.write_built_src_mtime(ps._epoch("2026-09-22T09:30:00+09:00"))
        ctx = ps.est_context()
        old = {"at": "2026-09-22T09:00:00+09:00", "sync": "ok"}
        self.assertTrue(ps.pin_est(old, ctx))
        # 메모만 고쳐 edited_at 이 빌드보다 늦어져도 추정 유지(must-2 a) — 기준은 at 뿐
        self.assertTrue(ps.pin_est(dict(old, edited_at="2026-09-22T11:00:00+09:00"), ctx))
        self.assertFalse(ps.pin_est({"at": "2026-09-22T09:45:00+09:00"}, ctx))   # 원고가 그 뒤로 안 바뀜
        self.assertFalse(ps.pin_est({"at": "2026-09-22T10:30:00+09:00"}, ctx))   # 빌드 뒤에 찍음
        self.assertTrue(ps.pin_est({"frac_build": "pages-x", "at": "2026-09-22T10:30:00+09:00"}, ctx))  # 옛 필드명도 신원 경로

    def test_legacy_epoch_ignores_process_timezone_for_offset_strings(self):
        with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
            time.tzset()
            try:
                ny = ps._epoch("2026-09-22T09:00:00+09:00")
            finally:
                pass
        with mock.patch.dict(os.environ, {"TZ": "Asia/Seoul"}):
            time.tzset()
            seoul = ps._epoch("2026-09-22T09:00:00+09:00")
        time.tzset()
        self.assertEqual(ny, seoul)

    def test_fingerprint_ignores_diff_dirs_and_tracks_content(self):
        h0 = ps.source_fingerprint(self.src)
        for d in ("diff", "diff_temporary"):
            (self.src / d).mkdir()
            (self.src / d / "x.tex").write_text("latexdiff", encoding="utf-8")
            (self.src / d / "y.pdf").write_bytes(b"%PDF")
        self.assertEqual(ps.source_fingerprint(self.src), h0)
        os.utime(self.main, (time.time() + 10, time.time() + 10))                 # 시각만 바뀜
        self.assertEqual(ps.source_fingerprint(self.src), h0)
        self.main.write_text(TEX + "% x\n", encoding="utf-8")
        self.assertNotEqual(ps.source_fingerprint(self.src), h0)

    def test_build_history_and_seq_in_meta(self):
        m0 = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertEqual(m0["build_seq"], 0)
        self._fake_build("pages-20260101000000", "h1")
        ps.finish_build({"ok": False, "state": "fail", "errors": [{"line": 3, "msg": "x"}], "log": "boom",
                         "elapsed_s": 0.1}, None)
        m = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertEqual(m["build_seq"], 2)
        self.assertEqual(m["last_build"]["state"], "fail")
        self.assertEqual(m["last_build"]["errors"], [{"line": 3, "msg": "x"}])
        self.assertTrue(m["last_build"]["finished_at"])
        h = ps.load_builds()
        self.assertEqual(h["seq"], 2)
        self.assertEqual([b["build"] for b in h["builds"]], ["pages-20260101000000"])   # 실패는 이력에 빌드를 안 남긴다
        self.assertEqual(h["by"]["pages-20260101000000"]["src_hash"], "h1")

    def test_seed_builds_restores_last_state_and_seq_after_restart(self):
        self._fake_build("pages-20260101000000", "h1")
        ps.finish_build({"ok": False, "state": "ok_errors", "errors": [{"line": 1, "msg": "m"}], "log": "L",
                         "elapsed_s": 0.1}, None)
        ps.BUILD_STATE.update(state="idle", seq=0, last=None, errors=[], log_tail="")   # 재기동 흉내
        ps.seed_builds()
        st = ps.build_state_snapshot()
        self.assertEqual((st["state"], st["seq"]), ("ok_errors", 2))
        self.assertEqual(st["errors"], [{"line": 1, "msg": "m"}])
        self.assertEqual(st["log_tail"], "L")

    def test_seed_builds_fingerprints_current_build_when_source_unchanged(self):
        d = ps.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        ps.write_built_src_mtime(ps.src_mtime(force=True) + 1)
        ps.seed_builds()
        ent = ps.load_builds()["by"]["pages"]
        self.assertEqual(ent["src_hash"], ps.source_fingerprint(self.src))
        pid = self.add()                                   # 기동 뒤 첫 핀 → 원고를 안 바꾼 재빌드에서 오탐 없음
        self._fake_build("pages-20260101000100", ps.source_fingerprint(self.src))
        self.assertIs(self.est_of(pid), False)

    def test_seed_builds_leaves_hash_empty_when_source_is_newer(self):
        d = ps.C.state / "pages"
        d.mkdir()
        (d / "page-1.png").write_bytes(b"x")
        ps.write_built_src_mtime(ps.src_mtime(force=True) - 100)
        ps.seed_builds()
        self.assertIsNone(ps.load_builds()["by"]["pages"]["src_hash"])

    def test_light_meta_does_not_write_builds_file(self):
        self._fake_build("pages-20260101000000", "h1")
        st = ps.C.builds_file.stat()
        for _ in range(3):
            self.talk(req("GET", "/api/meta?light=1"))
        st2 = ps.C.builds_file.stat()
        self.assertEqual((st.st_mtime_ns, st.st_size), (st2.st_mtime_ns, st2.st_size))

    def test_real_build_est_end_to_end(self):
        """실제 latexmk 로: 무변경 재빌드 → est 없음, 원고 수정 뒤 재빌드 → est, 메모 수정 뒤에도 유지."""
        import shutil as _sh
        if not (_sh.which("latexmk") and _sh.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        self.assertEqual(ps.build_all()["state"], "ok")
        b1 = ps.cur_pages().name
        pid = self.add()
        self.assertEqual(self.pin(pid)["pdf_build"], b1)
        time.sleep(1.1)                                      # 빌드 디렉토리 이름이 초 단위
        self.assertEqual(ps.build_all()["state"], "ok")
        self.assertNotEqual(ps.cur_pages().name, b1)
        self.assertIs(self.est_of(pid), False)
        self.main.write_text(TEX.replace("After table epsilonunique.", "After table epsilonunique longer."),
                             encoding="utf-8")
        time.sleep(1.1)
        self.assertEqual(ps.build_all()["state"], "ok")
        self.assertIs(self.est_of(pid), True)
        ps.edit_pin(pid, {"note": "메모만", "base_rev": self.pin(pid)["rev"]}, dict(ps.LOCAL_ACTOR))
        self.assertIs(self.est_of(pid), True)


# ---------------------------------------------------------------- P0b-02 light meta 폴링

class LightMeta(Base):
    def test_light_meta_has_no_write_side_effect(self):
        self.add()
        before = ps.C.pins_jsonl.stat().st_mtime_ns
        for _ in range(5):
            d = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        after = ps.C.pins_jsonl.stat().st_mtime_ns
        self.assertEqual(before, after)
        self.assertNotIn("n_open", d)
        for k in ("src_mtime", "build_src_mtime", "pins_rev", "build", "pages_build"):
            self.assertIn(k, d)

    def test_pins_rev_changes_only_when_file_changes(self):
        rev0 = ps.pins_rev()
        self.add()
        rev1 = ps.pins_rev()
        self.assertNotEqual(rev0, rev1)
        rev2 = ps.pins_rev()
        self.assertEqual(rev1, rev2)      # 변화 없으면 그대로

    def test_src_mtime_ignores_main_pdf_and_build_dir(self):
        m0 = ps.src_mtime()
        (ps.C.src / "main.pdf").write_bytes(b"%PDF-fake")
        (ps.C.src / "build").mkdir()
        (ps.C.src / "build" / "leftover.tex").write_text("x", encoding="utf-8")
        self.assertEqual(ps.src_mtime(), m0)          # 캐시 밖이어도(2초 지난 뒤에도) 변하면 안 된다
        ps._SRC_MTIME_CACHE[2] = 0.0                  # 캐시를 강제로 만료시켜 재계산을 확인
        self.assertEqual(ps.src_mtime(), m0)

    def test_src_mtime_ignores_diff_dir(self):
        # 결함(should, P0b 수선): 빌드 rsync 는 diff/(latexdiff 산출물)를 빼는데(exclude "diff/") src_mtime
        # 은 안 빼서, latexdiff 를 한 번만 돌려도 '원고 수정됨' 배지가 뜨고 다음 재빌드 뒤 모든 핀이
        # 레이아웃이 그대로인데도 '추정'으로 바뀌는 오탐이 났다.
        m0 = ps.src_mtime()
        (ps.C.src / "diff").mkdir()
        (ps.C.src / "diff" / "latexdiff-out.tex").write_text("x", encoding="utf-8")
        self.assertEqual(ps.src_mtime(), m0)
        ps._SRC_MTIME_CACHE[2] = 0.0                  # 캐시를 강제로 만료시켜 재계산을 확인
        self.assertEqual(ps.src_mtime(), m0)

    def test_src_mtime_reacts_to_tex_change(self):
        ps._SRC_MTIME_CACHE[2] = 0.0
        m0 = ps.src_mtime()
        time.sleep(0.05)
        os.utime(self.main, (time.time() + 10, time.time() + 10))
        ps._SRC_MTIME_CACHE[2] = 0.0
        self.assertGreater(ps.src_mtime(), m0)

    def test_built_src_mtime_file_missing_is_fine(self):
        self.assertIsNone(ps.read_built_src_mtime())
        d = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertIsNone(d["build_src_mtime"])

    def test_src_mtime_force_bypasses_cache(self):
        # 결함: write_built_src_mtime() 이 2초 캐시 값을 그대로 썼다 — 캐시가 채워진 지 2초 안에
        # 원고를 고치고 바로 재빌드하면 '수정 전' mtime 이 빌드 시작 시각으로 잘못 기록됐다.
        m0 = ps.src_mtime(force=True)      # 캐시를 채운다
        time.sleep(0.05)
        os.utime(self.main, (time.time() + 10, time.time() + 10))
        cached = ps.src_mtime()            # 캐시 안(2초 이내) — 옛 값
        self.assertEqual(cached, m0)
        forced = ps.src_mtime(force=True)  # 캐시를 건너뛰고 실측 — 새 값
        self.assertGreater(forced, m0)

    def test_write_built_src_mtime_uses_fresh_value(self):
        os.utime(self.main, (time.time() + 20, time.time() + 20))
        ps.write_built_src_mtime()
        self.assertAlmostEqual(ps.read_built_src_mtime(), ps.src_mtime(force=True), delta=1.0)

    def test_light_query_param_via_handler(self):
        out = self.talk(req("GET", "/api/meta?light=1"))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("n_open", data)
        self.assertIn("pins_rev", data)


# ---------------------------------------------------------------- P0b-03 겹침·덧붙이기

class Overlaps(Base):
    def test_inside_and_contains_pair(self):
        p1 = self.add(4, 9, note="outer")     # 앞 두 문단(빈 줄 없음 아님, 넉넉히 겹치게 lo/hi 조정)
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
        # 설계 2: 같은 범위는 따로 'equal' 로 낸다 — 뷰어가 '같은 범위입니다'로 밝히고 배너를 띄운다.
        pid = self.add(4, 9, note="first")
        ov = ps.overlaps_for_range(str(self.main), 4, 9)
        self.assertEqual(ov, [{"id": pid, "lo": 4, "hi": 9, "rel": "equal"}])

    def test_selection_rel_all_four_relations(self):
        self.assertEqual(ps.selection_rel(4, 9, 4, 9), "equal")
        self.assertEqual(ps.selection_rel(5, 6, 4, 9), "inside")
        self.assertEqual(ps.selection_rel(3, 10, 4, 9), "contains")
        self.assertEqual(ps.selection_rel(8, 12, 4, 9), "partial")
        self.assertIsNone(ps.selection_rel(10, 12, 4, 9))

    def test_pick_end_to_end_includes_quote_and_overlaps(self):
        import shutil as _sh
        if not (_sh.which("latexmk") and _sh.which("pdftoppm") and _sh.which("pdftotext")):
            self.skipTest("latex 도구 없음")
        res = ps.build_all()
        self.assertEqual(res["state"], "ok")
        pages = ps.page_list()
        self.assertTrue(pages)
        p = pages[0]
        d = ps.pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4})
        self.assertNotIn("error", d)
        self.assertIn("quote", d)
        self.assertIn("overlaps", d)
        self.assertEqual(d["pdf_build"], ps.cur_pages().name)
        # 화면이 옛 빌드면 그 빌드로 되짚고 그 이름을 돌려준다(재빌드 직후 화면을 바꾸기 전의 드래그).
        b1 = ps.cur_pages().name
        time.sleep(1.1)
        self.assertEqual(ps.build_all()["state"], "ok")
        self.assertNotEqual(ps.cur_pages().name, b1)
        d2 = ps.pick({"page": 1, "x0": 0, "y0": 0, "x1": p["pt_w"], "y1": p["pt_h"] * 0.4, "pdf_build": b1})
        self.assertEqual(d2["pdf_build"], b1)
        gone = ps.pick({"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "pdf_build": "pages-19990101000000"})
        self.assertTrue(gone.get("pdf_build_gone"))
        with self.assertRaises(ps.HTTPError):
            ps.pick({"page": 1, "x0": 0, "y0": 0, "x1": 10, "y1": 10, "pdf_build": "../x"})

    def test_note_append_then_undo(self):
        pid = self.add(note="원본")
        p0 = self.pin(pid)
        p1 = ps.edit_pin(pid, {"note_append": "추가 텍스트"}, dict(ps.LOCAL_ACTOR))
        self.assertIn("추가 텍스트", p1["note"])
        self.assertIn("(추가 ", p1["note"])
        self.assertEqual(len(ps.C.pins_jsonl.read_text().splitlines()), 1)   # 줄 수 불변
        undone = ps.edit_pin(pid, {"note": p0["note"], "base_rev": p1["rev"]}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(undone["note"], p0["note"])

    def test_note_append_does_not_need_base_rev(self):
        pid = self.add()
        p = ps.edit_pin(pid, {"note_append": "x"}, dict(ps.LOCAL_ACTOR))
        self.assertIn("x", p["note"])

    def test_note_append_empty_string_rejected(self):
        pid = self.add(note="원본")
        with self.assertRaises(ps.HTTPError) as cm:
            ps.edit_pin(pid, {"note_append": ""}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(ps.HTTPError):                 # 공백만 있어도 거부한다
            ps.edit_pin(pid, {"note_append": "   "}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(self.pin(pid)["note"], "원본")        # 거부됐으니 안 바뀐다

    def test_note_append_over_note_max_combined_is_rejected(self):
        pid = self.add(note="x" * (ps.NOTE_MAX - 20))          # 여유가 20자뿐
        with self.assertRaises(ps.HTTPError) as cm:
            ps.edit_pin(pid, {"note_append": "y" * 100}, dict(ps.LOCAL_ACTOR))   # 개별 상한(2000)은 넘지 않지만 합치면 넘는다
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(len(self.pin(pid)["note"]), ps.NOTE_MAX - 20)          # 거부됐으니 원래 길이 그대로
        self.assertEqual(self.pin(pid)["rev"], 0)                                # rev 도 안 오른다

    def test_get_pins_includes_rel_field(self):
        p1 = self.add(4, 9)
        p2 = self.add(4, 5)
        out = self.talk(req("GET", "/api/pins?all=1"))
        rows = json.loads(out.split(b"\r\n\r\n", 1)[1])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[p2]["rel"], [{"id": p1, "rel": "inside"}])

    def test_overlaps_endpoint_recomputes_for_arbitrary_range(self):
        # must-1(P0b 수선): 단계 전환(useLevel)·▲▼(nudge)로 CUR.lo/hi 가 바뀌면 /api/pick(좌표 필요)을
        # 다시 부를 수 없다 — 범위만으로 가볍게 다시 묻는 엔드포인트가 있어야 배너가 따라간다.
        pid = self.add(4, 9, note="outer")
        out = self.talk(req("GET", "/api/overlaps?file=%s&lo=4&hi=5" % str(self.main)))
        self.assertIn(b" 200 ", out)
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(data["overlaps"], [{"id": pid, "lo": 4, "hi": 9, "rel": "inside"}])

    def test_overlaps_endpoint_range_out_of_file_is_400(self):
        out = self.talk(req("GET", "/api/overlaps?file=%s&lo=1&hi=99999" % str(self.main)))
        self.assertIn(b" 400 ", out)


# ---------------------------------------------------------------- P0b-04 pins.md v2 · quote

class PinsMdV2(Base):
    def test_relative_path_for_included_file(self):
        sub = self.src / "sections"
        sub.mkdir()
        f = sub / "intro.tex"
        f.write_text("line one\nline two\n", encoding="utf-8")
        pid = ps.add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n"}, dict(ps.LOCAL_ACTOR))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("`sections/intro.tex L1-L1`", md)
        self.assertEqual(self.pin(pid)["lo"], 1)

    def test_root_file_location_matches_basename(self):
        self.add(4, 5)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("`main.tex L4-L5`", md)

    def test_closed_pins_do_not_grow_pins_md(self):
        self.add(4, 5)
        before = len(ps.C.pins_md.read_text(encoding="utf-8").splitlines())
        for i in range(20):
            pid = self.add(4, 5, note="c%d" % i)
            ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        after = len(ps.C.pins_md.read_text(encoding="utf-8").splitlines())
        self.assertEqual(before, after)
        self.assertIn("닫힌 핀 20건", ps.C.pins_md.read_text(encoding="utf-8"))

    def test_newline_in_note_becomes_line_separator(self):
        self.add(4, 5, note="첫줄\n둘째줄")
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("첫줄 ⏎ 둘째줄", md)
        self.assertNotIn("첫줄\n둘째줄", md)
        for line in md.splitlines():
            if line.startswith("| ") and "⏎" in line:
                self.assertEqual(line.count("|"), 6)   # 5열 표: 파이프 6개

    def test_overlap_symbol_in_number_column(self):
        p1 = self.add(4, 9)
        self.add(4, 5)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("⊂#%d" % p1, md)

    def test_close_guidance_shows_reply_ref_body(self):
        # 결함: pins.md 의 닫기 안내가 본문 없는 curl 만 보여줘, 이 파일 하나만 읽는 에이전트는
        # reply·ref 를 남기는 방법을 몰랐다(§닫을 때 사유 남기기, SKILL.md 와 동일한 형태여야 한다).
        self.add(4, 5)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("curl -X POST -H 'Content-Type: application/json'", md)
        self.assertIn('-d \'{"reply":"무엇을 고쳤는지(≤500자)","ref":"커밋/PR(≤80자)"}\'', md)
        self.assertIn("http://127.0.0.1:%d/api/pins/N/close" % ps.C.port, md)
        self.assertIn("본문 생략", md)   # 본문을 생략해도 되는 옛 방식이 여전히 된다는 안내

    def test_quote_shown_only_for_single_long_raw_line(self):
        long_line = "x" * 650
        f = self.src / "long.tex"
        f.write_text(long_line + "\n", encoding="utf-8")
        pid = ps.add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n", "scope": "raw",
                          "quote": "짧은 인용"}, dict(ps.LOCAL_ACTOR))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("«짧은 인용»", md)
        # 짧은 줄(600자 이하)에는 quote 가 있어도 붙지 않는다
        rows = ps.snapshot_pins()
        for r in rows:
            if r["id"] == pid:
                r["lo"] = r["hi"] = 4
                r["quote"] = "안 보여야 함"
                r["file"] = str(self.main)
        ps.write_pins(rows)
        md2 = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("«안 보여야 함»", md2)

    def test_truncate_quote_appends_ellipsis_only_when_cut(self):
        self.assertEqual(ps.truncate_quote("짧음", 60), "짧음")
        self.assertNotIn("…", ps.truncate_quote("짧음", 60))
        long = "x" * 90
        cut = ps.truncate_quote(long, 60)
        self.assertEqual(cut, "x" * 59 + "…")
        self.assertEqual(len(cut), 60)   # 결함: 61자(60자+…)가 됐었다 — 설계는 ≤60자
        self.assertEqual(ps.truncate_quote("x" * 60, 60), "x" * 60)   # 정확히 경계면 안 붙는다

    def test_quote_truncated_with_ellipsis_in_pins_md(self):
        # 결함: 인용문이 60자 넘게 잘려도 말줄임표가 없어서 완전한 문장처럼 보였다.
        long_line = "y" * 650
        f = self.src / "long2.tex"
        f.write_text(long_line + "\n", encoding="utf-8")
        pid = ps.add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n", "scope": "raw",
                          "quote": "가" * 90}, dict(ps.LOCAL_ACTOR))
        stored = self.pin(pid)["quote"]
        self.assertEqual(stored, "가" * 59 + "…")
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("«" + stored + "»", md)   # render_quote 가 이미 …가 붙은 값을 다시 자르지 않는다

    def test_location_col_escapes_pipe_in_filename(self):
        # 결함: 위치 칸의 파일명에 파이프가 있으면 표 열 구조가 깨질 수 있었다(메모·인용문은 이미 이스케이프했다).
        sub = self.src / "a|b"
        sub.mkdir()
        f = sub / "c.tex"
        f.write_text("line one\n", encoding="utf-8")
        ps.add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n"}, dict(ps.LOCAL_ACTOR))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("a\\|b/c.tex L1-L1", md)
        for line in md.splitlines():
            if "a\\|b" in line:
                # 5열 표 구분자 6개 + 파일명 안의 이스케이프된 파이프 1개("\|"도 문자로는 '|'다) = 7.
                self.assertEqual(line.count("|"), 7)
                self.assertNotIn("a|b/c.tex", line)     # 이스케이프 안 된 원본 조각은 없어야 한다

    def test_range_col_escapes_pipe_in_env_kind(self):
        # 결함(should, P0b 수선): 위치 칸(loc_label)·인용문(render_quote)은 파이프를 이스케이프했지만
        # 범위 칸(range_label)은 env 이름을 그대로 돌려줘서, kind='env:x|y' 를 저장하면 pins.md 표 행이
        # 6칸이 아니라 6칸을 넘겨 표가 깨졌다.
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "n",
                          "scope": "env", "kind": "env:x|y"}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(ps.range_label(self.pin(pid)), "env:x\\|y")
        md = ps.C.pins_md.read_text(encoding="utf-8")
        for line in md.splitlines():
            if "env:x" in line:
                self.assertIn("env:x\\|y", line)
                # 5열 표 구분자 6개 + 범위 칸 안의 이스케이프된 파이프 1개 = 7(파일명 칸 테스트와 같은 셈).
                self.assertEqual(line.count("|"), 7)

    def test_every_cell_escapes_pipe_and_newline(self):
        # 설계 5: 모든 칸 전수 — kind(범위 칸, env·비env 두 분기), 파일명, 메모, 인용문. 어느 칸이든 '|' 나 줄바꿈이
        # 그대로 들어가면 행이 깨진다.
        ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "a|b\nc",
                    "scope": "env", "kind": "env:x|y\nz"}, dict(ps.LOCAL_ACTOR))
        ps.add_pin({"file": str(self.main), "lo": 8, "hi": 8, "page": 1, "note": "n", "kind": "k|1\r\nk2"},
                   dict(ps.LOCAL_ACTOR))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        rows = [ln for ln in md.splitlines() if ln.startswith("| ") and "main.tex" in ln]
        self.assertEqual(len(rows), 2)
        for ln in rows:
            unescaped = re.sub(r"\\\|", "", ln)
            self.assertEqual(unescaped.count("|"), 6, ln)
        self.assertIn("env:x\\|y z", rows[0])
        self.assertIn("a\\|b ⏎ c", rows[0])
        self.assertIn("k\\|1 k2", rows[1])
        self.assertEqual(ps.md_cell("a|b\r\nc"), "a\\|b c")

    def test_legend_absent_when_no_symbols(self):
        self.add(4, 5)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기호:", md)

    def test_open_pins_table_has_five_columns(self):
        self.add(4, 5)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        for line in md.splitlines():
            if line.startswith("| ") and "쪽" not in line and "#" not in line[:4]:
                self.assertEqual(line.count("|"), 6)


# ---------------------------------------------------------------- P0b-보완: 삭제/완료 구분·되살리기·닫기 사유·재닫기 무변경

class CloseReplyRef(Base):
    """§C: /close 가 선택 {"reply","ref"} 를 받아 close_reply/close_ref 로 저장한다."""

    def test_close_with_reply_and_ref_is_stored(self):
        pid = self.add()
        p = ps.set_done(pid, True, dict(ps.LOCAL_ACTOR),
                        *ps.clean_close_body({"reply": "제목을 고침", "ref": "PR #227"}))
        self.assertEqual(p["close_reply"], "제목을 고침")
        self.assertEqual(p["close_ref"], "PR #227")
        self.assertTrue(p["done"])

    def test_close_without_body_behaves_as_before(self):
        pid = self.add()
        p = ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        self.assertNotIn("close_reply", p)
        self.assertNotIn("close_ref", p)

    def test_clean_close_body_empty_or_whitespace_is_none(self):
        self.assertEqual(ps.clean_close_body({}), (None, None))
        self.assertEqual(ps.clean_close_body({"reply": "", "ref": "  "}), (None, None))
        self.assertEqual(ps.clean_close_body({"reply": None, "ref": None}), (None, None))

    def test_clean_close_body_rejects_wrong_type(self):
        with self.assertRaises(ps.HTTPError):
            ps.clean_close_body({"reply": 123})
        with self.assertRaises(ps.HTTPError):
            ps.clean_close_body({"ref": ["PR #227"]})

    def test_clean_close_body_enforces_length_caps(self):
        with self.assertRaises(ps.HTTPError):
            ps.clean_close_body({"reply": "x" * (ps.CLOSE_REPLY_MAX + 1)})
        with self.assertRaises(ps.HTTPError):
            ps.clean_close_body({"ref": "x" * (ps.CLOSE_REF_MAX + 1)})
        # 상한 그 자체는 통과한다.
        reply, ref = ps.clean_close_body({"reply": "x" * ps.CLOSE_REPLY_MAX, "ref": "x" * ps.CLOSE_REF_MAX})
        self.assertEqual(len(reply), ps.CLOSE_REPLY_MAX)
        self.assertEqual(len(ref), ps.CLOSE_REF_MAX)

    def test_close_endpoint_http_stores_reply_and_escapes_in_card(self):
        pid = self.add()
        body = json.dumps({"reply": "제목을 <b>고침</b>", "ref": "PR #227"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 200 ", out)
        p = self.pin(pid)
        self.assertEqual(p["close_reply"], "제목을 <b>고침</b>")
        self.assertEqual(p["close_ref"], "PR #227")

    def test_close_endpoint_http_rejects_oversized_reply(self):
        pid = self.add()
        body = json.dumps({"reply": "x" * (ps.CLOSE_REPLY_MAX + 1)}).encode()
        out = self.talk(req("POST", "/api/pins/%d/close" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)
        self.assertFalse(self.pin(pid).get("done"))


class CloseIdempotent(Base):
    """§D: 이미 닫힌 핀을 다시 닫으면 아무것도 바뀌지 않는다(rev 도 그대로)."""

    def test_second_close_does_not_overwrite_closed_by_or_rev(self):
        pid = self.add()
        first = ps.set_done(pid, True, {"login": "alice", "name": "Alice"})
        self.assertEqual(first["rev"], 1)
        second = ps.set_done(pid, True, {"login": "bob", "name": "Bob"})
        self.assertEqual(second["closed_by"]["login"], "alice")
        self.assertEqual(second["rev"], first["rev"])
        self.assertEqual(second["done_at"], first["done_at"])

    def test_second_close_with_reply_does_not_apply(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), *ps.clean_close_body({"reply": "first"}))
        again = ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), *ps.clean_close_body({"reply": "second"}))
        self.assertEqual(again["close_reply"], "first")

    def test_reopen_then_close_allows_new_reply(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), *ps.clean_close_body({"reply": "first", "ref": "PR #1"}))
        ps.set_done(pid, False, dict(ps.LOCAL_ACTOR))
        reopened = self.pin(pid)
        self.assertNotIn("close_reply", reopened)
        self.assertNotIn("close_ref", reopened)
        closed_again = ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), *ps.clean_close_body({"reply": "second"}))
        self.assertEqual(closed_again["close_reply"], "second")
        self.assertNotIn("close_ref", closed_again)

    def test_close_http_endpoint_second_call_returns_ok_unchanged(self):
        pid = self.add()
        out1 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out1)
        rev_after_first = self.pin(pid)["rev"]
        out2 = self.talk(req("POST", "/api/pins/%d/close" % pid))
        self.assertIn(b" 200 ", out2)
        self.assertTrue(json.loads(out2.split(b"\r\n\r\n", 1)[1])["ok"])
        self.assertEqual(self.pin(pid)["rev"], rev_after_first)


class DroppedList(Base):
    """§B: GET /api/pins/dropped — 삭제한 핀을 dropped_at·dropped_by 와 함께 읽기 전용으로 낸다."""

    def test_dropped_payload_includes_dropped_at_and_by(self):
        pid = self.add(note="oops")
        ps.drop_pin(pid, {"login": "alice", "name": "Alice"})
        out = ps.dropped_payload()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], pid)
        self.assertEqual(out[0]["dropped_by"]["login"], "alice")
        self.assertIn("dropped_at", out[0])

    def test_dropped_payload_empty_when_nothing_dropped(self):
        self.add()
        self.assertEqual(ps.dropped_payload(), [])

    def test_dropped_payload_excludes_restored_pins(self):
        pid = self.add()
        ps.drop_pin(pid, dict(ps.LOCAL_ACTOR))
        ps.restore_pin(pid, dict(ps.LOCAL_ACTOR))
        self.assertEqual(ps.dropped_payload(), [])

    def test_get_pins_dropped_endpoint_http(self):
        pid = self.add(note="secret-drop-note")
        ps.drop_pin(pid, {"login": "alice", "name": "Alice"})
        out = self.talk(req("GET", "/api/pins/dropped"))
        self.assertIn(b" 200 ", out)
        payload = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(payload["dropped"]), 1)
        self.assertEqual(payload["dropped"][0]["id"], pid)
        self.assertEqual(payload["dropped"][0]["note"], "secret-drop-note")

    def test_get_pins_dropped_respects_origin_check(self):
        pid = self.add()
        ps.drop_pin(pid, dict(ps.LOCAL_ACTOR))
        out = self.talk(req("GET", "/api/pins/dropped", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)


# ---------------------------------------------------------------- 프런트엔드 순수 로직(node 로 실제 소스 실행)
#
# 서버는 표준 라이브러리·127.0.0.1 만 쓰지만, 이 테스트들은 회귀 검증을 위해 node 로 클라이언트 JS 를
# 그대로 돌린다(서버 자체를 바꾸지 않는다). node 가 없는 환경에서는 스킵한다.

class FrontendLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_is_estimated_draws_server_est_only_regardless_of_timezone(self):
        # 설계 1: 뷰어는 서버가 준 est 를 그대로 그린다 — 시간대·edited_at·sync 로 다시 판정하지 않는다.
        js = "\n".join([
            extract_js_fn("isEstimated"),
            r"""
            const out=[isEstimated({est:true}), isEstimated({est:false,sync:'moved +3',at:'2026-01-01 00:00:00'}),
                       isEstimated({}), isEstimated({est:'true'})];
            console.log(JSON.stringify(out));
            """,
        ])
        seoul = json.loads(run_node(js, tz="Asia/Seoul"))
        ny = json.loads(run_node(js, tz="America/New_York"))
        self.assertEqual(seoul, [True, False, False, False])
        self.assertEqual(seoul, ny)

    def test_sel_rel_matches_python_selection_rel(self):
        # 설계 2: 뷰어는 범위가 바뀔 때마다 서버 왕복 없이 겹침을 다시 센다 — 규칙이 서버와 같아야 한다.
        cases = [(lo, hi, 4, 7) for lo in range(1, 10) for hi in range(lo, 11)]
        js = "\n".join([extract_js_fn("selRel"),
                        "console.log(JSON.stringify(%s.map(c=>selRel(c[0],c[1],c[2],c[3]))));" % json.dumps(cases)])
        got = json.loads(run_node(js))
        self.assertEqual(got, [ps.selection_rel(*c) for c in cases])

    def test_overlaps_for_filters_by_file_and_skips_done(self):
        js = "\n".join([extract_js_fn("selRel"), extract_js_fn("overlapsFor"), r"""
            const PINS=[{id:1,file:'/a.tex',lo:4,hi:9},{id:2,file:'/b.tex',lo:4,hi:9},{id:3,file:'/a.tex',lo:4,hi:9,done:true},
                        {id:4,file:'/a.tex',lo:5,hi:5},{id:5,file:'/a.tex',lo:20,hi:30}];
            console.log(JSON.stringify(overlapsFor({file:'/a.tex',lo:4,hi:9},PINS)));
            """])
        self.assertEqual(json.loads(run_node(js)),
                         [{"id": 1, "lo": 4, "hi": 9, "rel": "equal"}, {"id": 4, "lo": 5, "hi": 5, "rel": "contains"}])

    def test_pick_overlap_priority_equal_inside_contains_partial(self):
        js = "\n".join([
            extract_js_fn("pickOverlap"),
            r"""
            const out=[];
            out.push(pickOverlap([{id:6,lo:241,hi:243,rel:'contains'}]));
            out.push(pickOverlap([{id:1,lo:1,hi:100,rel:'contains'},{id:2,lo:10,hi:20,rel:'inside'}]));
            out.push(pickOverlap([{id:1,lo:1,hi:5,rel:'contains'},{id:2,lo:1,hi:9,rel:'contains'}]));
            out.push(pickOverlap([{id:3,lo:1,hi:9,rel:'inside'},{id:7,lo:4,hi:5,rel:'equal'}]));
            out.push(pickOverlap([{id:9,lo:1,hi:9,rel:'partial'},{id:8,lo:4,hi:12,rel:'partial'}]));
            console.log(JSON.stringify(out.map(o=>o&&o.id)));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)), [6, 2, 2, 7, 8])

    def test_overlap_banner_follows_level_change_and_dismiss_resets(self):
        # must-1 라이브 경로: 드래그(기본 단계 = 환경, 핀을 감쌈) → [문단] 단계로 바꿔 기존 핀과 같은 범위 → 배너가
        # '같은 범위'로 바뀐다. [별도 핀으로 저장]은 그 관계만 끄고, 새 드래그(pick 의 리셋)에서 다시 뜬다.
        js = "\n".join([
            r"""
            const box={hidden:true,dataset:{},innerHTML:''};
            const $=s=>box;
            let CUR=null, PINS=[{id:5,file:'/m.tex',lo:405,hi:406}];
            """,
            extract_js_fn("selRel"), extract_js_fn("overlapsFor"), extract_js_fn("pickOverlap"),
            extract_js_fn("overlapVerb"), "let OVERLAP_DISMISSED=null;", extract_js_fn("recomputeOverlap"),
            extract_js_fn("renderOverlapBanner"), extract_js_fn("lvOf"), extract_js_fn("useLevel"),
            r"""
            const out=[];
            CUR={file:'/m.tex',lo:401,hi:413,levels:[{level:'para',lo:405,hi:406},{level:'env',lo:401,hi:413}]};
            recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            useLevel(CUR,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel, /같은 범위/.test(box.innerHTML)]);
            OVERLAP_DISMISSED='5:equal'; renderOverlapBanner(); out.push([box.hidden]);
            useLevel(CUR,'env'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);   // 관계가 바뀌면 다시 알림
            OVERLAP_DISMISSED=null;                        // pick() 의 리셋(새 선택)
            useLevel(CUR,'para'); recomputeOverlap(); renderOverlapBanner(); out.push([box.hidden, box.dataset.rel]);
            console.log(JSON.stringify(out));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [False, "contains"])
        self.assertEqual(out[1], [False, "equal", True])
        self.assertEqual(out[2], [True])
        self.assertEqual(out[3], [False, "contains"])
        self.assertEqual(out[4], [False, "equal"])

    def test_poll_build_single_flight_and_once_per_seq(self):
        # 설계 4: pollBuild 는 단일 비행 — 동시에 몇 번 불려도 /api/build 는 한 번, 완료(seq 하나) 처리도 한 번.
        # 새로 연 탭은 이미 실패해 있는 빌드를 토스트 없이 패널로만 보인다.
        js = "\n".join([
            r"""
            const document={hidden:false};
            const el=()=>({hidden:true,textContent:'',disabled:false});
            const els={}; const $=s=>(els[s]=els[s]||el());
            let calls=0, resolveApi=null, nextState=null;
            function api(url){calls++; return new Promise(r=>{resolveApi=()=>r({data:nextState});});}
            const toasts=[], panels=[]; let refreshes=0;
            function toast(m,k){toasts.push(k);} function showBuildErr(b){panels.push(b.state);} function hideBuildErr(){}
            async function refreshDoc(){refreshes++;}
            const META={pages:[1,2]};
            let timers=0; function setInterval(){timers++; return 1;} function clearInterval(){}
            let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=3,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
            """,
            extract_js_fn("buildChipText"), extract_js_fn("pullSuffix"), extract_js_fn("pollBuild"),
            extract_js_fn("pollBuildOnce"),
            r"""
            (async()=>{
              const out={};
              // 부팅: 이미 ok_errors 로 끝난 빌드(seq 그대로) → 패널만, 토스트 없음
              nextState={state:'ok_errors',seq:3,errors:[]};
              const p=pollBuild(); resolveApi(); await p;
              out.boot={calls, toasts:toasts.slice(), panels:panels.slice(), refreshes};
              // 동시 세 번 → 요청 한 번, 완료 처리 한 번
              calls=0; toasts.length=0; panels.length=0;
              nextState={state:'ok',seq:4,elapsed_s:3};
              const a=pollBuild(), b=pollBuild(), c=pollBuild();
              out.same=(a===b&&b===c);
              resolveApi(); await Promise.all([a,b,c]);
              out.burst={calls, toasts:toasts.slice(), refreshes};
              // 같은 seq 를 다시 봐도 아무 일 없음
              const d=pollBuild(); resolveApi(); await d;
              out.again={calls, toasts:toasts.slice(), refreshes};
              // 숨은 탭은 요청하지 않는다
              document.hidden=true; await pollBuild(); out.hidden=calls; document.hidden=false;
              // 5초 틈새에 두 빌드가 지나감(seq 4→6, 마지막 fail) → 한 번만, fail 토스트
              nextState={state:'fail',seq:6,errors:[]};
              const e=pollBuild(); resolveApi(); await e;
              out.skip={toasts:toasts.slice(), panels:panels.slice()};
              console.log(JSON.stringify(out));
            })();
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["boot"], {"calls": 1, "toasts": [], "panels": ["ok_errors"], "refreshes": 0})
        self.assertTrue(out["same"])
        self.assertEqual(out["burst"], {"calls": 1, "toasts": ["ok"], "refreshes": 1})
        self.assertEqual(out["again"], {"calls": 2, "toasts": ["ok"], "refreshes": 1})
        self.assertEqual(out["hidden"], 2)
        self.assertEqual(out["skip"], {"toasts": ["ok", "err"], "panels": ["fail"]})

    def test_rel_badge_matches_python_smallest_inside_rule(self):
        # 결함: relBadge(JS, 카드 태그)가 insides[0](서버가 보낸 순서, 임의)을 골랐는데 서버의
        # rel_badge()(pins.md)는 범위가 가장 작은 바깥 핀을 골랐다 — 카드와 pins.md 표기가 어긋났다.
        js = "\n".join([
            extract_js_fn("relBadge"),
            r"""
            const PINS=[{id:1,lo:1,hi:100},{id:2,lo:10,hi:20},{id:3,lo:5,hi:50}];
            // rel 배열은 실제 서버 순서를 흉내내 일부러 '가장 작은 것'을 뒤에 둔다.
            const rel=[{id:1,rel:'inside'},{id:3,rel:'inside'},{id:2,rel:'inside'}];
            console.log(JSON.stringify(relBadge(rel)));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["id"], 2)     # id=2(범위 10-20, 길이 11)가 가장 작은 바깥 핀

        # Python 쪽(rel_badge, pins.md)과 같은 by_id 로 같은 규칙을 비교한다.
        by_id = {1: {"lo": 1, "hi": 100}, 2: {"lo": 10, "hi": 20}, 3: {"lo": 5, "hi": 50}}
        rel = [{"id": 1, "rel": "inside"}, {"id": 3, "rel": "inside"}, {"id": 2, "rel": "inside"}]
        self.assertEqual(ps.rel_badge(rel, by_id), "⊂#2")

    def test_jump_to_card_sets_cur_and_clears_highlight_after_timeout(self):
        # 결함: 배지 클릭이 .flash 만 붙였고(.cur 없음), 정적 box-shadow 라 강조가 풀리지 않았다.
        js = "\n".join([
            r"""
            // jumpToCard 가 쓰는 만큼만 최소 DOM 을 흉내낸다.
            function makeEl(){
              const classes=new Set();
              return {
                classList:{add:(...c)=>c.forEach(x=>classes.add(x)),
                           remove:(...c)=>c.forEach(x=>classes.delete(x)),
                           contains:c=>classes.has(c)},
                scrollIntoView(){}, get offsetWidth(){return 0;},
              };
            }
            const el=makeEl();
            const document={querySelector:()=>el, querySelectorAll:()=>[]};
            const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
            const SMOOTH='auto';
            """,
            extract_js_fn("jumpToCard"),
            r"""
            jumpToCard(1);
            const mid=[el.classList.contains('cur'), el.classList.contains('flash')];
            // setTimeout 콜백을 동기로 즉시 실행할 수 있게 node 의 실제 타이머를 아주 짧게 기다린다.
            setTimeout(()=>{
              const after=[el.classList.contains('cur'), el.classList.contains('flash')];
              console.log(JSON.stringify({mid, after}));
            }, 1300);
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["mid"], [True, True])     # 클릭 직후: .cur 와 .flash 둘 다 있다
        self.assertEqual(out["after"], [False, False])  # 1.2초 뒤: 강조가 풀린다(정적 box-shadow 버그 수정)

    def test_diff_toast_distinguishes_dropped_from_closed(self):
        # §A: 옛 구현은 열린 목록에서 사라진 핀을 전부 '완료'로 알렸다 — 공저자가 지운 핀도 작성자
        # 화면에 '#N 이 완료되었습니다'로 떴다(실측). id 2 는 d(열림+닫힘)에 아예 없으므로 삭제,
        # id 3 은 d 에 done:true 로 있으므로 완료다.
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; const RESTORED=[];
            function toast(msg,kind,action){TOASTS.push({msg,kind,hasAction:!!action});}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            const prev=[{id:1},{id:2},{id:3}];
            const d=[{id:1,done:false},{id:3,done:true}];
            const dropped=[{id:2,dropped_by:{name:'Bob'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(len(out), 2)
        closed = [t for t in out if "완료" in t["msg"]]
        dropped = [t for t in out if "삭제함" in t["msg"]]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["msg"], "#3 이 완료되었습니다")
        self.assertEqual(closed[0]["kind"], "ok")
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["msg"], "#2 을 Bob 가 삭제함")
        self.assertEqual(dropped[0]["kind"], "warn")
        self.assertTrue(dropped[0]["hasAction"])          # [되살리기] 액션이 붙는다

    def test_diff_toast_dropped_action_calls_restore_pin(self):
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            let CAPTURED=null; const RESTORED=[];
            function toast(msg,kind,action){if(action)CAPTURED=action;}
            function restorePin(id){RESTORED.push(id);}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            diffToast([{id:9}],[],[{id:9,dropped_by:{login:'x'}}]);
            CAPTURED.fn();
            console.log(JSON.stringify(RESTORED));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)), [9])

    def test_diff_toast_unknown_dropper_falls_back_to_generic_label(self):
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            diffToast([{id:5}],[],[]);   // dropped 목록에도 없음(폴링 경합) — 그래도 삭제로는 알린다
            console.log(JSON.stringify(TOASTS));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(len(out), 1)
        self.assertIn("#5 을", out[0])
        self.assertIn("삭제함", out[0])

    def test_diff_toast_suppresses_own_recent_action_but_not_others(self):
        # 결함: 자기 탭이 방금 닫거나 지운 핀도 markMine 없이 diffToast 를 그대로 타 로컬 토스트와
        # 겹쳐 두 번 떴다. markMine(id) 로 표시해 둔 id 는 한 번만 삼키고, 표시 안 된(=다른 탭이 한)
        # id 는 그대로 알려야 한다.
        js = "\n".join([
            r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(msg,kind,action){TOASTS.push(msg);}
            function restorePin(id){}
            const MY_ACTIONS=new Map();
            """,
            extract_js_fn("markMine"),
            extract_js_fn("consumeMine"),
            extract_js_fn("diffToast"),
            r"""
            markMine(1); markMine(2);   // 이 탭이 방금 #1 을 완료, #2 를 삭제했다
            const prev=[{id:1},{id:2},{id:3},{id:4}];
            const d=[{id:1,done:true},{id:3,done:true}];   // #2,#4 는 d 에 없음=삭제
            const dropped=[{id:2,dropped_by:{login:'me'}},{id:4,dropped_by:{name:'Coauthor'}}];
            diffToast(prev,d,dropped);
            console.log(JSON.stringify(TOASTS));
            """,
        ])
        out = json.loads(run_node(js))
        joined = " | ".join(out)
        self.assertNotIn("#1", joined)                 # 자기 동작 — 억제됨
        self.assertNotIn("#2", joined)                  # 자기 동작 — 억제됨
        self.assertIn("#3 이 완료되었습니다", joined)     # 다른 탭이 완료 — 그대로 뜸
        self.assertTrue(any("#4" in t and "삭제함" in t and "Coauthor" in t for t in out))  # 다른 탭이 삭제 — 그대로 뜸


# ---------------------------------------------------------------- 프런트엔드 구조(소스 문자열 검사)
#
# 타이머·fetch·visibility 를 아우르는 폴링 루프와 패널 자동 표시는 node 로 통째로 실행하려면 fetch·
# document.hidden·setInterval 을 모두 흉내내야 해서(이 스킬의 하드 제약은 표준 라이브러리뿐이라 그런
# 셔레이더를 서버에 추가할 수 없다) 여기서는 실제로 배포되는 ps.HTML 소스 문자열에 고친 패턴이 있고
# 고치기 전 패턴이 없는지를 검사한다 — 실행 검증은 아니지만 회귀(원래 버그 패턴으로 되돌아감)는 잡는다.

class FrontendStructure(unittest.TestCase):
    def test_build_polling_is_conditional_not_permanent(self):
        # 결함: startBuildPolling() 이 무조건 setInterval(pollBuild,1000) 을 걸어 탭이 숨거나 할 일이
        # 없어도 매초 /api/build 를 불렀다.
        m = re.search(r"function startBuildPolling\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        self.assertNotIn("setInterval(pollBuild", m.group(1))
        self.assertIn("pollBuild()", m.group(1))
        m1 = re.search(r"\nfunction pollBuild\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("if(document.hidden)returnPromise.resolve()", m1.group(1).replace(" ", ""))
        self.assertIn("if(BUILD_INFLIGHT)returnBUILD_INFLIGHT", m1.group(1).replace(" ", ""))
        m2 = re.search(r"async function pollBuildOnce\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m2.group(1)
        self.assertIn("if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000)", body.replace(" ", ""))
        self.assertIn("clearInterval(BUILD_TIMER)", body)

    def test_light_poll_kicks_off_build_polling_when_running_or_seq_changed(self):
        m = re.search(r"async function pollLightOnce\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1).replace(" ", "")
        self.assertIn("d.build&&d.build.state==='running'", body)
        self.assertIn("d.build_seq!==LAST_BUILD_SEQ", body)
        self.assertIn("pollBuild()", body)

    def test_light_poll_is_single_flight(self):
        # 결함: visibilitychange 와 focus 가 겹치면 pollLight() 가 매번 새로 /api/meta·loadPins 를
        # 불러 loadPins 가 최대 3 회 나갔다. pollBuild 와 같은 단일 비행 패턴이어야 한다.
        m = re.search(r"\nfunction pollLight\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1).replace(" ", "")
        self.assertIn("if(document.hidden)returnPromise.resolve()", body)
        self.assertIn("if(LIGHT_INFLIGHT)returnLIGHT_INFLIGHT", body)
        self.assertIn("LIGHT_INFLIGHT=pollLightOnce()", body)

    def test_build_err_reopen_affordance_exists(self):
        self.assertIn('id="build-err-chip"', ps.HTML)
        self.assertIn('data-act="build-err-reopen"', ps.HTML)
        self.assertIn("case 'build-err-reopen'", ps.HTML)
        self.assertIn("function hideBuildErr()", ps.HTML)
        self.assertIn("case 'err-close':hideBuildErr()", ps.HTML)

    def test_pick_resets_overlap_dismissed_and_recounts(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1)
        cur_idx = body.index("CUR=d;")
        self.assertGreater(body.index("OVERLAP_DISMISSED=null"), cur_idx)
        self.assertGreater(body.index("CUR.overlaps=overlapsFor(CUR,PINS)"), cur_idx)

    def test_level_and_nudge_recount_overlap_only_for_composer(self):
        for act in ("level", "nudge"):
            m = re.search(r"case '%s':\{(.*?)\}\s*\n" % act, ps.HTML)
            self.assertIsNotNone(m)
            self.assertIn("if(!inEdit)recomputeOverlap()", m.group(1).replace(" ", ""))

    def test_pdf_build_travels_drag_to_pick_to_save_and_repick(self):
        self.assertIn("pdf_build:META.pages_build", ps.HTML)                  # 드래그 → /api/pick
        self.assertIn("quote:d.quote,pdf_build:d.pdf_build", ps.HTML)         # pick 응답 → /api/pin
        self.assertIn("frac:c.frac,pdf_build:c.pdf_build", ps.HTML)           # 위치 다시 잡기 → loc

    def test_no_wall_clock_estimate_left_in_viewer(self):
        self.assertNotIn("pinAtEpoch", ps.HTML)
        self.assertNotIn("frac_build", ps.HTML)
        self.assertNotIn("LAST_SEEN_BUILD", ps.HTML)

    def test_dropped_list_ui_exists(self):
        # §B: '닫힌 핀' 아래 접힌 '삭제한 핀 N ▸' 목록과 되살리기 버튼.
        self.assertIn('id="dropped-toggle"', ps.HTML)
        self.assertIn('id="dropped-list"', ps.HTML)
        self.assertIn("case'dropped-toggle':SHOW_DROPPED=!SHOW_DROPPED;drawPins()", ps.HTML.replace(" ", ""))
        self.assertIn("function droppedCard(", ps.HTML)
        self.assertIn("data-act=\"restore\"", ps.HTML)
        self.assertIn("case 'restore':restorePin(id)", ps.HTML)

    def test_load_pins_fetches_dropped_list_for_diff_and_panel(self):
        m = re.search(r"async function loadPins\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("/api/pins/dropped", body)
        self.assertIn("DROPPED=dropped", body)
        self.assertIn("diffToast(prevOpen,d,dropped)", body)

    def test_draw_pins_renders_dropped_toggle_and_list(self):
        m = re.search(r"function drawPins\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("DROPPED.length", body)
        self.assertIn("droppedCard", body)

    def test_done_card_shows_close_reply_and_ref(self):
        # §C: 닫힌 카드에 닫을 때 남긴 reply·ref 를 보여 준다(둘 다 esc 를 거친다).
        m = re.search(r"function doneCard\(p\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("p.close_ref", body)
        self.assertIn("p.close_reply", body)
        self.assertIn("esc(p.close_reply)", body)
        self.assertIn("esc(p.close_ref)", body)

    def test_close_curl_example_in_skill_md_documents_reply_and_ref(self):
        # SKILL.md 의 '핀 소비 절차' 닫기 예시가 reply·ref 를 남기도록 바뀌었는지(§C).
        skill = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('"reply"', skill)
        self.assertIn('"ref"', skill)
        self.assertIn("/close", skill)


# ---------------------------------------------------------------- §P0c-B: GET /pins.md — 원격 에이전트 진입점

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
        out = self.talk(req("GET", "/pins.md", headers={"Host": "x.tail1234.ts.net:18004"}))
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
        # GET /api/pins 와 같은 sync 경로를 타야 한다 — 원고를 고쳐 줄이 밀렸으면 반영돼야 한다.
        pid = self.add(lo=7, hi=7, note="n")
        self.main.write_text("\n" + TEX, encoding="utf-8")   # 앞에 빈 줄 하나 — 전부 한 줄씩 밀린다
        out = self.talk(req("GET", "/pins.md"))
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("L8-L8", body)
        self.assertEqual(self.pin(pid)["lo"], 8)

    def test_pins_md_endpoint_respects_origin_check(self):
        out = self.talk(req("GET", "/pins.md", headers={"Host": "evil.example"}))
        self.assertIn(b" 403 ", out)


# ---------------------------------------------------------------- §P0c-C: 처리 중 표시(claim)

class Claim(Base):
    def test_claim_sets_fields_and_bumps_rev(self):
        pid = self.add()
        p = ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        self.assertEqual(p["claimed_by"], {"login": "alice@x.com", "name": "Alice"})
        self.assertEqual(p["rev"], 1)
        self.assertTrue(ps.claim_active(self.pin(pid)))

    def test_default_ttl_used_when_body_omits_it(self):
        pid = self.add()
        before = time.time()
        p = ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), ps.clean_claim_ttl({}))
        self.assertAlmostEqual(p["claim_until"], before + ps.CLAIM_TTL_DEFAULT * 60, delta=5)

    def test_claim_conflict_from_other_identity_is_409(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        with self.assertRaises(ps.HTTPError) as cm:
            ps.claim_pin(pid, {"login": "bob@x.com", "name": "Bob"}, 120)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(cm.exception.body["claimed_by"]["login"], "alice@x.com")
        self.assertIn("claim_until", cm.exception.body)

    def test_claim_same_identity_extends(self):
        pid = self.add()
        first = ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 5)
        second = ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 200)
        self.assertGreater(second["claim_until"], first["claim_until"])
        self.assertEqual(second["rev"], first["rev"] + 1)

    def test_claim_on_closed_pin_is_409_done(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        with self.assertRaises(ps.HTTPError) as cm:
            ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        self.assertEqual(cm.exception.code, 409)
        self.assertEqual(cm.exception.body["error"], "done")

    def test_claim_missing_pin_id_returns_none(self):
        self.assertIsNone(ps.claim_pin(999, dict(ps.LOCAL_ACTOR), 120))

    def test_ttl_out_of_range_or_wrong_type_rejected(self):
        for bad in (0, 481, "120", 12.5, True, None):
            with self.assertRaises(ps.HTTPError):
                ps.clean_claim_ttl({"ttl_min": bad})
        self.assertEqual(ps.clean_claim_ttl({}), ps.CLAIM_TTL_DEFAULT)
        self.assertEqual(ps.clean_claim_ttl({"ttl_min": 1}), 1)
        self.assertEqual(ps.clean_claim_ttl({"ttl_min": 480}), 480)

    def test_expired_claim_is_inactive_and_can_be_reclaimed_by_another_identity(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        rows = ps.snapshot_pins()
        for r in rows:
            if r["id"] == pid:
                r["claim_until"] = time.time() - 10
        ps.write_pins(rows)
        self.assertFalse(ps.claim_active(self.pin(pid)))
        p = ps.claim_pin(pid, {"login": "bob@x.com", "name": "Bob"}, 120)
        self.assertEqual(p["claimed_by"]["login"], "bob@x.com")

    def test_unclaim_clears_fields_regardless_of_requester(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        p = ps.unclaim_pin(pid, {"login": "bob@x.com", "name": "Bob"})
        self.assertNotIn("claimed_by", p)
        self.assertNotIn("claimed_at", p)
        self.assertNotIn("claim_until", p)

    def test_unclaim_missing_pin_returns_none(self):
        self.assertIsNone(ps.unclaim_pin(999, dict(ps.LOCAL_ACTOR)))

    def test_close_clears_claim(self):
        pid = self.add()
        ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), 120)
        p = ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        self.assertNotIn("claimed_by", p)

    def test_drop_clears_claim_even_in_dropped_record(self):
        pid = self.add()
        ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), 120)
        ps.drop_pin(pid, dict(ps.LOCAL_ACTOR))
        dropped = ps.dropped_payload()
        self.assertEqual(len(dropped), 1)
        self.assertNotIn("claimed_by", dropped[0])

    def test_pins_md_shows_hourglass_with_claimer_name_and_legend(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "kim@example.com", "name": "Coauthor Kim"}, 120)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("⏳Coauthor Kim", md)
        self.assertIn("처리 중(다른 에이전트가 잡음)", md)

    def test_pins_md_hourglass_uses_local_label_for_curl_claims(self):
        pid = self.add()
        ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), 120)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("⏳로컬/에이전트", md)

    def test_claim_fields_survive_jsonl_roundtrip(self):
        pid = self.add()
        ps.claim_pin(pid, {"login": "alice@x.com", "name": "Alice"}, 120)
        rows, bad = ps.read_jsonl(ps.C.pins_jsonl)
        self.assertEqual(bad, [])
        self.assertIn("claimed_by", ps.find_pin(rows, pid))

    def test_http_claim_then_conflict_then_unclaim(self):
        pid = self.add()
        h1 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "alice@x.com", "Tailscale-User-Name": "Alice"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h1))
        self.assertIn(b" 200 ", out)
        h2 = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": "bob@x.com", "Tailscale-User-Name": "Bob"}
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, headers=h2))
        self.assertIn(b" 409 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["claimed_by"]["login"], "alice@x.com")
        out = self.talk(req("POST", "/api/pins/%d/unclaim" % pid))
        self.assertIn(b" 200 ", out)
        self.assertFalse(ps.claim_active(self.pin(pid)))

    def test_http_claim_bad_ttl_type_is_400(self):
        pid = self.add()
        body = json.dumps({"ttl_min": "soon"}).encode()
        out = self.talk(req("POST", "/api/pins/%d/claim" % pid, body, {"Content-Type": "application/json"}))
        self.assertIn(b" 400 ", out)

    def test_http_claim_missing_pin_returns_ok_false(self):
        out = self.talk(req("POST", "/api/pins/999/claim"))
        self.assertIn(b" 200 ", out)
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertFalse(body["ok"])


# ---------------------------------------------------------------- §P0c-D: 기준 커밋·빌드를 pins.md 머리에

class BuildHeadInPinsMd(Base):
    def test_head_line_present_when_head_and_built_at_known(self):
        (ps.C.state / "head.txt").write_text("abc1234", encoding="utf-8")
        (ps.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("기준: abc1234 · 빌드 2026-09-22 10:00:00", md)
        self.assertIn("다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인", md)

    def test_head_line_omitted_when_files_missing(self):
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기준:", md)
        self.assertNotIn("다른 체크아웃에서", md)

    def test_head_line_omitted_for_dash_placeholder(self):
        # _build() 는 git 저장소가 아니면 head.txt 에 '-' 를 쓴다 — 그때는 '기준' 을 보여줄 게 없다.
        (ps.C.state / "head.txt").write_text("-", encoding="utf-8")
        (ps.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("기준:", md)

    def test_head_block_adds_at_most_two_lines(self):
        without = ps.pins_md_text([]).splitlines()
        (ps.C.state / "head.txt").write_text("abc1234", encoding="utf-8")
        (ps.C.state / "built_at.txt").write_text("2026-09-22 10:00:00", encoding="utf-8")
        withit = ps.pins_md_text([]).splitlines()
        self.assertLessEqual(len(withit) - len(without), 2)


# ---------------------------------------------------------------- §P0c-E: --git-pull

class GitPull(unittest.TestCase):
    """git_pull_phase() 를 임시 bare 저장소 + 클론으로 검증한다 — 실제 원고 저장소는 쓰지 않는다."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git 없음")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bare = self.root / "upstream.git"
        self._run(["git", "init", "--quiet", "--bare", str(self.bare)], self.root)
        seed = self.root / "_seed"
        self._run(["git", "clone", "--quiet", str(self.bare), str(seed)], self.root)
        self._configure(seed)
        self._run(["git", "checkout", "--quiet", "-b", "main"], seed)
        (seed / "f.txt").write_text("seed\n", encoding="utf-8")
        self._run(["git", "add", "-A"], seed)
        self._run(["git", "commit", "--quiet", "-m", "seed"], seed)
        self._run(["git", "push", "--quiet", "-u", "origin", "main"], seed)
        self._run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], self.bare)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, args, cwd):
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise AssertionError("%s 실패:\n%s%s" % (args, r.stdout, r.stderr))
        return r.stdout

    def _configure(self, d):
        self._run(["git", "config", "user.email", "t@example.com"], d)
        self._run(["git", "config", "user.name", "T"], d)

    def _clone(self, name):
        d = self.root / name
        self._run(["git", "clone", "--quiet", str(self.bare), str(d)], self.root)
        self._configure(d)
        return d

    def test_state_not_git(self):
        plain = self.root / "plain"
        plain.mkdir()
        r = ps.git_pull_phase(plain)
        self.assertEqual(r, {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None})

    def test_state_ok_when_upstream_advanced(self):
        d = self._clone("c1")
        other = self._clone("c2")
        (other / "f.txt").write_text("new\n", encoding="utf-8")
        self._run(["git", "add", "-A"], other)
        self._run(["git", "commit", "--quiet", "-m", "more"], other)
        self._run(["git", "push", "--quiet"], other)
        r = ps.git_pull_phase(d)
        self.assertEqual(r["state"], "ok")
        self.assertIsNotNone(r["head_before"])
        self.assertIsNotNone(r["head_after"])
        self.assertNotEqual(r["head_before"], r["head_after"])

    def test_state_up_to_date_when_no_new_commits(self):
        d = self._clone("c3")
        r = ps.git_pull_phase(d)
        self.assertEqual(r["state"], "up_to_date")
        self.assertEqual(r["head_before"], r["head_after"])
        self.assertIsNotNone(r["head_before"])

    def test_state_skipped_dirty(self):
        d = self._clone("c4")
        (d / "f.txt").write_text("locally modified\n", encoding="utf-8")
        r = ps.git_pull_phase(d)
        self.assertEqual(r["state"], "skipped")
        self.assertEqual(r["reason"], "dirty")

    def test_state_skipped_diverged(self):
        d = self._clone("c5")
        (d / "f.txt").write_text("local change\n", encoding="utf-8")
        self._run(["git", "add", "-A"], d)
        self._run(["git", "commit", "--quiet", "-m", "local-only"], d)
        other = self._clone("c6")
        (other / "g.txt").write_text("remote change\n", encoding="utf-8")
        self._run(["git", "add", "-A"], other)
        self._run(["git", "commit", "--quiet", "-m", "remote-only"], other)
        self._run(["git", "push", "--quiet"], other)
        r = ps.git_pull_phase(d)
        self.assertEqual(r["state"], "skipped")
        self.assertEqual(r["reason"], "diverged")

    def test_state_skipped_no_upstream(self):
        d = self._clone("c7")
        self._run(["git", "checkout", "--quiet", "-b", "untracked"], d)
        r = ps.git_pull_phase(d)
        self.assertEqual(r["state"], "skipped")
        self.assertEqual(r["reason"], "no_upstream")

    def test_repo_root_found_from_subdirectory(self):
        d = self._clone("c8")
        sub = d / "manuscript" / "1st"
        sub.mkdir(parents=True)
        r = ps.git_pull_phase(sub)
        self.assertEqual(r["state"], "up_to_date")

    def test_no_shell_no_user_input_in_argv(self):
        # 보안: subprocess.run 이 리스트 인자로 돈다(쉘 없음) — _git() 의 시그니처 자체가 그 계약이다.
        import inspect
        src = inspect.getsource(ps._git)
        self.assertIn("subprocess.run([\"git\"]", src)
        self.assertNotIn("shell=True", src)


class GitPullBuildIntegration(Base):
    def test_pull_result_surfaces_in_build_response_and_state(self):
        if not (shutil.which("latexmk") and shutil.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        ps.C.git_pull = True
        res = ps.build_all()
        self.assertEqual(res["state"], "ok")
        # Base.setUp() 의 임시 원고는 git 저장소가 아니다 — not_git 이 실제로 타는지 확인한다.
        self.assertEqual(res["pull"], {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None})
        self.assertEqual(res.get("head"), ps.C.state.joinpath("head.txt").read_text().strip())
        snap = ps.build_state_snapshot()
        self.assertEqual(snap.get("pull"), res["pull"])
        self.assertEqual(snap.get("head"), res["head"])

    def test_pull_absent_when_flag_off(self):
        if not (shutil.which("latexmk") and shutil.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        ps.C.git_pull = False
        res = ps.build_all()
        self.assertNotIn("pull", res)


# ---------------------------------------------------------------- §P0c-F: 에이전트 응답 다이어트

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
        def fake_build():
            return {"ok": True, "state": "ok", "errors": [], "log": "font path\n" * 200,
                    "elapsed_s": 0.01, "pages": 1, "head": "abc1234"}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log", body)
        self.assertEqual(body["state"], "ok")
        self.assertEqual(body["head"], "abc1234")

    def test_sync_rebuild_ok_errors_trims_log_to_40_lines(self):
        def fake_build():
            return {"ok": True, "state": "ok_errors", "errors": [{"line": 1, "msg": "x"}],
                    "log": "\n".join("l%d" % i for i in range(200)), "elapsed_s": 0.01, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(len(body["log"].splitlines()), 40)

    def test_sync_rebuild_log1_query_bypasses_diet(self):
        def fake_build():
            return {"ok": True, "state": "ok", "errors": [], "log": "keep-full", "elapsed_s": 0.01, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            out = self.talk(req("POST", "/api/rebuild?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["log"], "keep-full")

    def test_get_api_build_applies_same_diet_and_log1_bypasses(self):
        def fake_build():
            return {"ok": True, "state": "ok", "errors": [], "log": "font path\n" * 200,
                    "elapsed_s": 0.01, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build):
            ps.build_all()
        out = self.talk(req("GET", "/api/build"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertNotIn("log_tail", body)
        out = self.talk(req("GET", "/api/build?log=1"))
        body = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertIn("log_tail", body)

    def test_rebuild_response_shrinks_on_success(self):
        # 라이브 실측과 같은 축(§검증) — mock 으로 같은 결론을 빠르게 확인한다.
        big_log = "font path\n" * 300

        def fake_build_before():
            return {"ok": True, "state": "ok", "errors": [], "log": big_log, "elapsed_s": 0.01, "pages": 1}
        with mock.patch.object(ps, "_build", side_effect=fake_build_before):
            before = self.talk(req("POST", "/api/rebuild?log=1"))
            after = self.talk(req("POST", "/api/rebuild"))
        self.assertGreater(len(before), len(after))


# ---------------------------------------------------------------- §P0c-G: 작성자 표시(필요할 때만)

class AuthorPrefixInPinsMd(Base):
    def test_single_author_has_no_prefix(self):
        self.add(note="n", actor={"login": "alice@x.com", "name": "Alice"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("@Alice:", md)

    def test_multiple_authors_get_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        self.add(8, 8, note="n2", actor={"login": "bob@x.com", "name": "Bob"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("@Alice: n1", md)
        self.assertIn("@Bob: n2", md)

    def test_same_author_twice_does_not_trigger_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        self.add(8, 8, note="n2", actor={"login": "alice@x.com", "name": "Alice"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("@Alice:", md)

    def test_legacy_pin_without_author_counts_as_one_group(self):
        pid1 = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "legacy"},
                          dict(ps.LOCAL_ACTOR))
        rows = ps.snapshot_pins()
        for r in rows:
            if r["id"] == pid1:
                r.pop("author", None)
        ps.write_pins(rows)
        self.add(8, 8, note="n2", actor={"login": "bob@x.com", "name": "Bob"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("@Bob: n2", md)
        self.assertNotIn("@None", md)
        self.assertIn("legacy", md)

    def test_closed_pins_excluded_from_author_count(self):
        # 닫힌 핀의 작성자는 열린 표에 안 보이니 카운트에서도 빠져야 한다(열린 핀 기준 판정).
        pid = self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        self.add(8, 8, note="n2", actor={"login": "bob@x.com", "name": "Bob"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("@Bob:", md)


# ---------------------------------------------------------------- 뷰어 구조 — claim UI·log=1

class FrontendClaimUI(unittest.TestCase):
    def test_claim_badge_and_unclaim_button_wired(self):
        self.assertIn("function claimActive(", ps.HTML)
        self.assertIn("function claimLabel(", ps.HTML)
        self.assertIn('data-act="unclaim"', ps.HTML)
        self.assertIn("case 'unclaim':unclaimPin(id)", ps.HTML)
        self.assertIn("function unclaimPin(", ps.HTML)
        self.assertIn("/api/pins/'+id+'/unclaim'", ps.HTML)

    def test_no_claim_button_offered_to_viewer(self):
        # 뷰어는 claim 을 걸지 않는다(에이전트 전용) — 'claim' 액션 버튼이 없어야 한다.
        self.assertNotIn('data-act="claim"', ps.HTML)

    def test_build_status_fetch_requests_full_log(self):
        self.assertIn("/api/build?log=1", ps.HTML)

    def test_pull_chip_and_toast_wiring(self):
        self.assertIn("원격 main 당겨오는 중", ps.HTML)
        self.assertIn("function pullSuffix(", ps.HTML)
        self.assertIn("pullSuffix(b)", ps.HTML)


# 모바일(갤럭시 Z 폴드 7 등) — references/design.md §모바일 레이아웃. 실측은 Playwright 로 했고, 여기서는
# 배포되는 HTML 에 필요한 요소·문구·CSS·이벤트 경로가 있는지와 순수 로직 함수를 node 로 검사한다.
class FrontendMobileStructure(unittest.TestCase):
    def test_viewport_meta_allows_zoom_and_handles_keyboard_and_notch(self):
        m = re.search(r'<meta name="viewport" content="([^"]*)"', ps.HTML)
        self.assertIsNotNone(m)
        v = m.group(1)
        for part in ("width=device-width", "initial-scale=1", "viewport-fit=cover", "interactive-widget=resizes-content"):
            self.assertIn(part, v)
        # 핀치 확대를 막지 않는다 — 원고를 읽으려면 확대가 필요하다
        self.assertNotIn("user-scalable=no", v)
        self.assertNotIn("maximum-scale", v)

    def test_rebuild_label_is_short_everywhere(self):
        self.assertIn('data-act="rebuild"', ps.HTML)
        self.assertRegex(ps.HTML, r'id="btn-rebuild"[^>]*>PDF 재빌드</button>')
        self.assertNotIn("다시 만들기", ps.HTML)
        self.assertNotIn("다시 만들기", Path(ps.__file__).read_text(encoding="utf-8"))
        skill = HERE.parent
        for doc in [skill / "SKILL.md"] + sorted((skill / "references").glob("*.md")):
            self.assertFalse("PDF 다시 만들기" in doc.read_text(encoding="utf-8"), doc.name)

    def test_compact_toolbar_elements_and_more_menu(self):
        for el in ('id="btn-side"', 'id="side-n"', 'id="btn-select"', 'id="btn-more"', '<dialog id="more"',
                   'id="coach"', 'id="more-info"', 'id="m-theme"', 'id="m-done"', 'id="m-dropped"', 'id="m-jump"'):
            self.assertIn(el, ps.HTML)
        self.assertIn('aria-pressed="false"', re.search(r'<button id="btn-select"[^>]*>', ps.HTML).group(0))
        # 덜 중요한 버튼은 compact 에서 숨고(.sec) [⋯] 안에 같은 data-act 로 있다
        for bid, act in (("btn-reload", "reload"), ("btn-zoom-out", "zoom-out"), ("btn-zoom-in", "zoom-in"),
                         ("btn-fit", "fit"), ("btn-theme", "theme"), ("btn-help", "help")):
            tag = re.search(r'<button id="%s"[^>]*>' % bid, ps.HTML).group(0)
            self.assertIn('class="sec"', tag)
            more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index('<dialog id="help"')]
            self.assertIn('data-act="%s"' % act, more)
        self.assertRegex(ps.HTML, r'<input class="n sec" id="jump"')
        self.assertIn("body.compact .sec{display:none}", ps.HTML)
        for act in ("side", "selmode", "more", "more-close", "m-jump", "coach-close", "card-toggle"):
            self.assertIn("case '%s':" % act, ps.HTML)

    def test_touch_css_targets_inputs_safe_area_and_selection_touch_action(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}")]
        self.assertIn("min-height:44px", coarse)
        self.assertIn("input,textarea,select{font-size:16px}", coarse)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("var(--kb,0px)", css)
        # touch-action: PDF 영역(#left)은 스크롤만 넘기고 브라우저 핀치를 막는다(두 손가락은 앱 확대, §PDF 영역 전용
        # 확대). 선택 모드의 쪽은 none(한 손가락 끌기 = 선택). 그 밖에는 폭·높이 손잡이 둘뿐이다(끄는 동안 스크롤과
        # 다투지 않게 none). 사이드바·시트는 건드리지 않는다.
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual([x.strip() for x in re.findall(r"([^{}]*)\{[^{}]*touch-action", css_nc)],
                         ["#left", "#grip", "body.selmode .pg", "body.lay-narrow #sheet-grip"])
        self.assertRegex(css_nc, r"\n#left\{[^}]*touch-action:pan-x pan-y\}")
        self.assertIn("body.selmode .pg{touch-action:none", css)
        self.assertNotIn("touch-action:pinch-zoom", css)
        # 알림은 시트·패널 도구 줄과 겹치지 않는 자리로 옮긴다
        self.assertIn("body.lay-narrow #toasts{", css)
        self.assertIn("body.lay-mid #toasts{", css)

    def test_selection_uses_pointer_events_one_path(self):
        self.assertIn("$('#doc').addEventListener('pointerdown'", ps.HTML)
        for ev in ("pointermove", "pointerup", "pointercancel"):
            self.assertIn("window.addEventListener('%s'" % ev, ps.HTML)
        self.assertIn("if(mouse||SELMODE)", ps.HTML)            # 마우스는 모드와 무관하게 예전처럼 끈다
        self.assertIn("if(!e.isPrimary){cancelDrag()", ps.HTML)  # 두 번째 손가락(핀치)은 선택을 버린다
        self.assertNotIn("window.addEventListener('mouseup',e=>{if(!DRAG)", ps.HTML)   # 옛 마우스 전용 경로가 없다
        self.assertIn("function quickPick(", ps.HTML)
        self.assertIn("LONGPRESS_MS", ps.HTML)

    def test_touch_does_not_autofocus_note_or_pop_hover_tips(self):
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("if(LAST_PTR==='mouse')$('#note').focus(", m.group(1))
        self.assertIn("if(touchRecent())return; armTip(", ps.HTML)
        self.assertIn("document.addEventListener('contextmenu'", ps.HTML)

    def test_keyboard_and_resize_hooks(self):
        self.assertIn("visualViewport.addEventListener('resize',onViewport)", ps.HTML)
        self.assertIn("new ResizeObserver(", ps.HTML)
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", ps.HTML, re.S)
        self.assertIn("topAnchor()", m.group(1))
        self.assertIn("restoreAnchor(a)", m.group(1))

    def test_page_images_lazy(self):
        self.assertIn('<img loading="lazy"', ps.HTML)


# 벡터 렌더링(references/design.md §벡터 렌더링) — 배포 HTML 에 PDF.js 경로·폴백·가시 영역 렌더·픽셀 상한이 있는지.
class FrontendVector(unittest.TestCase):
    def fn(self, name):
        m = re.search(r"\n(?:async )?function %s\([^)]*\)\{(.*?)\n\}" % name, ps.HTML, re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_loads_vendored_pdfjs_same_origin_with_version(self):
        self.assertNotIn("__PDFJS_VERSION__", ps.HTML)
        self.assertIn("const PDFJS_V='%s'" % ps.PDFJS_VERSION, ps.HTML)
        self.assertIn("import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V)", ps.HTML)
        self.assertIn("workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V", ps.HTML)
        for cdn in ("cdn.jsdelivr", "unpkg.com", "cdnjs", "mozilla.github.io/pdf.js/build"):
            self.assertNotIn(cdn, ps.HTML)                   # 테일넷 안에서만 돈다 — 외부 CDN 금지
        self.assertIn("isEvalSupported:false", ps.HTML)
        self.assertIn("useWasm:false", ps.HTML)              # wasm 은 vendor 에 없다(vendor/pdfjs/README.md)

    def test_pdf_is_the_screen_build(self):
        body = self.fn("vecOpen")
        self.assertIn("'/pdf?build='+encodeURIComponent(build)", body)
        self.assertIn("build=META.pages_build", body)
        self.assertIn("doc.numPages!==n", body)                 # 쪽 수가 다르면 쓰지 않는다
        # 재빌드 뒤 옛 문서를 닫는다. PDFDocumentProxy 에는 destroy 가 없다(실측: 'old.destroy is not a function').
        self.assertIn("vecClose(old)", body)
        self.assertIn("doc.loadingTask.destroy()", self.fn("vecClose"))
        self.assertNotRegex(ps.HTML, r"\b(doc|old|VEC\.doc)\.destroy\(")

    def test_fallback_to_png_on_any_failure(self):
        boot = self.fn("vecBoot")
        self.assertIn("catch(e){VEC.lib=null; vecFail(", boot)
        self.assertIn("vecFail('PDF 를 벡터로 열지 못했습니다'", self.fn("vecOpen"))
        run = self.fn("vecRun")
        self.assertIn("RenderingCancelledException", run)       # 취소는 실패가 아니다
        self.assertIn("vecFail('쪽을 그리지 못했습니다'", run)
        fail = self.fn("vecFail")
        self.assertIn("vecReleaseAll()", fail)                  # 캔버스를 걷으면 밑의 PNG 가 보인다
        self.assertIn("$('#vec-chip')", fail)
        self.assertIn('id="vec-chip" class="tag t" hidden', ps.HTML)
        self.assertIn('<img loading="lazy"', ps.HTML)          # PNG 는 첫 화면·폴백으로 남는다
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pg.drawn>img{visibility:hidden}", css)
        self.assertIn(".pg>canvas{position:absolute;display:block;pointer-events:none}", css)   # 드래그는 .pg 가 받는다

    def test_visible_pages_only_and_release(self):
        obs = self.fn("vecObserve")
        self.assertIn("new IntersectionObserver(", obs)
        self.assertIn("root:$('#left'),rootMargin:VEC_KEEP", obs)
        self.assertIn("vecRelease(n)", obs)
        self.assertIn("cv.width=0; cv.height=0", self.fn("vecDrop"))
        self.assertIn("vecObserve()", self.fn("buildDoc"))
        ref = self.fn("refreshDoc")
        self.assertIn("vecReleaseAll()", ref)                   # 옛 PDF 로 그린 캔버스는 걷는다
        self.assertIn("vecOpen()", ref)                         # 새 빌드의 PDF 를 다시 연다
        self.assertIn("vecInvalidate()", self.fn("setW"))       # 확대가 바뀌면 다시 그린다

    def test_no_text_layer(self):
        for s in ("getTextContent", "TextLayer", "textLayer"):
            self.assertNotIn(s, ps.HTML)


class FrontendVectorLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_backing_size_is_css_times_k_until_the_pixel_cap(self):
        js = "\n".join([
            extract_js_fn("vecTarget"),
            "const cap=16777216; const out=[];",
            "for(const [cw,ch,k] of [[898,1270,2],[370,523,2.6],[1796,2540,2],[3592,5080,2],[4490,6350,2]]){",
            "  const t=vecTarget(cw,ch,k,cap); out.push([t.bw,t.bh,t.capped,t.bw*t.bh<=cap,+(t.bw/(cw*k)).toFixed(3)]);}",
            "console.log(JSON.stringify(out));",
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[0][:3], [1796, 2540, False])
        self.assertEqual(out[1][:3], [962, 1360, False])
        for row in out[:2]:
            self.assertGreaterEqual(row[4], 1.0)               # 상한 안에서는 CSS × DPR 이상
        for row in out[2:]:                                    # 1796×2540 CSS × DPR 2 = 18.2M 픽셀 > 16.8M
            self.assertTrue(row[2])                            # 상한을 넘으면 낮춘다(상세 캔버스가 보이는 부분을 채운다)
            self.assertTrue(row[3])

    def test_detail_region_cover_check(self):
        js = "\n".join([
            extract_js_fn("vecCovers"),
            "const reg={x:0.1,y:0.2,w:0.5,h:0.3}; const out=[];",
            "out.push(vecCovers(reg,{x:100,y:200,w:500,h:300,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:150,y:250,w:100,h:100,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:50,y:250,w:100,h:100,cw:1000,ch:1000}));",
            "out.push(vecCovers(reg,{x:150,y:250,w:100,h:300,cw:1000,ch:1000}));",
            "out.push(vecCovers(null,{x:0,y:0,w:1,h:1,cw:10,ch:10}));",
            "console.log(JSON.stringify(out));",
        ])
        self.assertEqual(json.loads(run_node(js)), [True, True, False, False, False])


# PDF 영역 전용 확대(references/design.md §PDF 영역 전용 확대) — 브라우저 확대 입력을 가로채 쪽 폭만 바꾸는지.
class FrontendZoom(unittest.TestCase):
    def test_ctrl_wheel_on_pdf_area_is_intercepted_non_passive(self):
        self.assertIn("L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();", ps.HTML)
        i = ps.HTML.index("L.addEventListener('wheel'")
        self.assertIn("{passive:false}", ps.HTML[i:i + 300])
        self.assertIn("const L=$('#left')", ps.HTML[i - 200:i])     # PDF 영역에만 — 사이드바의 휠은 그대로
        self.assertIn("zoomTo(W*f,pt[0],pt[1])", ps.HTML)            # 포인터 기준

    def test_safari_gesture_and_touch_pinch(self):
        for ev in ("gesturestart", "gesturechange", "gestureend", "touchstart", "touchmove", "touchend", "touchcancel"):
            self.assertIn("L.addEventListener('%s'" % ev, ps.HTML)
        i = ps.HTML.index("L.addEventListener('touchstart'")
        blk = ps.HTML[i:i + 400]
        self.assertIn("e.touches.length!==2", blk)
        self.assertIn("cancelDrag(); cancelLP();", blk)            # 핀치는 그리던 선택·길게 누르기를 버린다
        self.assertIn("{passive:false}", blk)

    def test_keyboard_zoom_skips_inputs(self):
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", ps.HTML, re.S)
        body = m.group(1)
        self.assertIn("if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);", body)
        self.assertIn("e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1)", body)
        self.assertLess(body.index("inField="), body.index("zoomKey(e)"))

    def test_zoom_bounds_and_anchor(self):
        self.assertIn("const ZOOM_MIN=0.5,ZOOM_MAX=5", ps.HTML)
        setw = re.search(r"\nfunction setW\(w,save\)\{(.*?)\}\n", ps.HTML, re.S).group(1)
        self.assertIn("wBounds(fitWidth())", setw)
        self.assertNotIn("2200", setw)
        zt = re.search(r"\nfunction zoomTo\(w,cx,cy\)\{(.*?)\}\n", ps.HTML, re.S).group(1)
        self.assertLess(zt.index("zoomAnchor(cx,cy)"), zt.index("setW(w)"))
        self.assertLess(zt.index("setW(w)"), zt.index("zoomRestore(a)"))


class FrontendZoomLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_zoom_key_map(self):
        js = "\n".join([
            extract_js_fn("zoomKey"),
            "const ks=[['=','Equal'],['+','Equal'],['-','Minus'],['_','Minus'],['0','Digit0'],['+','NumpadAdd'],",
            " ['Process','Equal'],['Process','Minus'],['Process','Digit0'],['1','Digit1'],['Enter','Enter'],['a','KeyA']];",
            "console.log(JSON.stringify(ks.map(([key,code])=>zoomKey({key,code}))));",
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["in", "in", "out", "out", "fit", "in", "in", "out", "fit", None, None, None])

    def test_wheel_factor_mouse_notch_vs_trackpad_pinch(self):
        js = "\n".join([
            "const ZOOM_STEP=1.2;", extract_js_fn("wheelFactor"),
            "console.log(JSON.stringify([wheelFactor(-100,0),wheelFactor(100,0),wheelFactor(-3,1),wheelFactor(0,0),",
            " wheelFactor(-10,0),wheelFactor(10,0),wheelFactor(-49,0)].map(v=>+v.toFixed(4))));",
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[:4], [1.2, 0.8333, 1.2, 1])
        self.assertAlmostEqual(out[4], 1.1052, places=3)          # 핀치 dy=-10 → 조금 확대
        self.assertAlmostEqual(out[4] * out[5], 1.0, places=3)     # 벌렸다 오므리면 제자리
        self.assertLess(out[6], 1.2)                               # 잘게 나뉜 dy 는 한 이벤트에 한 칸을 넘지 않는다

    def test_width_bounds_are_half_to_five_times_fit(self):
        js = "\n".join([
            "const ZOOM_MIN=0.5,ZOOM_MAX=5;", extract_js_fn("wBounds"),
            "console.log(JSON.stringify([wBounds(956),wBounds(370),wBounds(100)]));",
        ])
        self.assertEqual(json.loads(run_node(js)), [[478, 4780], [185, 1850], [160, 800]])


class FrontendMobileLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_layout_for_breakpoints(self):
        cases = [(412, True), (700, True), (701, True), (880, True), (1099, True), (1100, True), (1440, True),
                 (412, False), (880, False), (1440, False)]
        js = "\n".join([
            "let innerWidth=0; const MQ_COARSE={matches:false};",
            extract_js_fn("layoutFor"),
            "console.log(JSON.stringify(%s.map(c=>{innerWidth=c[0];MQ_COARSE.matches=c[1];return layoutFor();})));" % json.dumps(cases),
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["narrow", "narrow", "mid", "mid", "mid", "wide", "wide", "narrow", "wide", "wide"])

    def test_quick_pick_box_is_small_and_clamped(self):
        js = "\n".join([
            r"""
            const c01=v=>Math.min(1,Math.max(0,v)); const QUICK_W=0.07,QUICK_H=0.006; const out=[];
            const pg={getBoundingClientRect:()=>({left:100,top:50,width:400,height:600})};
            function newBox(){return {};} function finishRect(pg,box,x0,y0,x1,y1){out.push([x0,y0,x1,y1].map(v=>+v.toFixed(4)));}
            """,
            extract_js_fn("fracAt"), extract_js_fn("quickPick"),
            "quickPick(pg,300,350); quickPick(pg,90,40); quickPick(pg,510,660); console.log(JSON.stringify(out));",
        ])
        self.assertEqual(json.loads(run_node(js)),
                         [[0.43, 0.494, 0.57, 0.506], [0, 0, 0.07, 0.006], [0.93, 0.994, 1, 1]])

    def test_keyboard_inset_ignores_pinch_zoom_and_desktop(self):
        # 키보드(visualViewport 가 줄어듦)만 --kb 로 친다. 핀치 확대(scale>1)·작은 차이·마우스 기기는 0.
        js = "\n".join([
            r"""
            const props={}; let active=null;
            const document={documentElement:{clientHeight:915,style:{setProperty:(k,v)=>{props[k]=v;},getPropertyValue:k=>props[k]||''}},
                            get activeElement(){return active;}};
            const MQ_COARSE={matches:true}; const window={visualViewport:null};
            const $=()=>({contains:()=>false}); function requestAnimationFrame(f){f();}
            """,
            extract_js_fn("onViewport"),
            r"""
            const out=[];
            for(const [h,s,coarse] of [[400,1,true],[457.5,2,true],[875,1,true],[400,1,false],[915,1,true]]){
              window.visualViewport={height:h,scale:s}; MQ_COARSE.matches=coarse; onViewport(); out.push([props['--kb'],props['--vvh']]);}
            console.log(JSON.stringify(out));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)),
                         [["515px", "400px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"], ["0px", "915px"]])

    def test_card_accordion_summary_is_first_note_line(self):
        js = "\n".join([
            r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d'}; let EDIT=null, PINS=[];
            const OPEN_CARDS=new Set([2]);
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function claimLabel(){return '';} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            function avatar(){return '';}
            """,
            extract_js_fn("rng"), extract_js_fn("card"),
            r"""
            const a=card({id:1,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:'첫 줄 <b>\n둘째 줄'});
            const b=card({id:2,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,note:''});
            const sum=s=>(/<span class="sum" data-act="card-toggle">([^<]*)<\/span>/.exec(s)||[])[1];
            console.log(JSON.stringify([sum(a), / open"/.test(a), sum(b), / open"/.test(b), /class="tags"/.test(a),
              /data-act="card-toggle" aria-expanded="false"/.test(a), /aria-expanded="true"/.test(b)]));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)),
                         ["첫 줄 &lt;b&gt;", False, "(메모 없음)", True, True, True, True])


# 패널 정리·폭 조절(references/design.md §패널 정리와 폭 조절). 실측은 Playwright(펼친 화면 880×790·접은 화면 412×915·
# 데스크톱 1440×900)로 했고, 여기서는 한계·단계·라벨 같은 순수 로직을 node 로, 배치·배선을 HTML 문자열로 본다.
class FrontendPanelWidthLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_side_bounds_per_layout(self):
        js = "\n".join([extract_js_fn("sideBounds"), r"""
            console.log(JSON.stringify([sideBounds('mid',880),sideBounds('mid',760),sideBounds('mid',701),
                                        sideBounds('wide',1440),sideBounds('wide',1100),sideBounds('wide',700)]));"""])
        got = json.loads(run_node(js))
        # 펼친 화면: 최소 300(도구 줄이 한 줄), 최대 60%(본문 320px 이상), 기본은 예전 clamp(300,38vw,360) 그대로
        self.assertEqual(got[0], {"min": 300, "max": 528, "def": 334, "presets": [300, 334, 440]})
        self.assertEqual(got[1]["max"], 440)
        self.assertEqual(got[2], {"min": 300, "max": 381, "def": 300, "presets": [300, 300, 351]})
        # 데스크톱: 기본 430 과 최소 280 은 예전 그대로, 최대는 본문 480px + 손잡이를 남긴다
        self.assertEqual(got[3], {"min": 280, "max": 954, "def": 430, "presets": [320, 430, 605]})
        self.assertEqual(got[4]["max"], 614)
        self.assertEqual(got[5], {"min": 280, "max": 280, "def": 280, "presets": [280, 280, 280]})
        for b in got:
            self.assertTrue(all(b["min"] <= w <= b["max"] for w in b["presets"] + [b["def"]]), b)

    def test_clamp_and_preset_cycle(self):
        js = "\n".join([extract_js_fn("clampSide"), extract_js_fn("nextPreset"), extract_js_fn("presetIndex"), r"""
            const b={min:300,max:528},P=[300,334,440];
            console.log(JSON.stringify([[100,300.4,420,999].map(w=>clampSide(w,b)),
              [300,334,420,440,500,302].map(w=>nextPreset(P,w)), [300,331,338,420,440].map(w=>presetIndex(P,w))]));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [[300, 300, 420, 528], [334, 440, 440, 300, 300, 334], [0, 1, 1, -1, 2]])

    def test_level_name_is_short_and_disambiguates_nested_same_env(self):
        js = "\n".join([extract_js_fn("levelName"), extract_js_fn("rng"), r"""
            const A=[{level:'para',label:'문단'},{level:'env',label:'환경 abstract',env:'abstract'},
                     {level:'env2',label:'환경 frontmatter (바깥)',env:'frontmatter'}];
            const B=[{level:'env',label:'환경 itemize',env:'itemize'},{level:'env2',label:'환경 itemize (바깥)',env:'itemize'}];
            console.log(JSON.stringify([A.map(l=>levelName(l,A)),B.map(l=>levelName(l,B)),rng(159,159),rng(155,173)]));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [["문단", "abstract", "frontmatter"], ["itemize", "itemize (바깥)"], "L159", "L155-L173"])

    def test_via_tag_is_short_and_flags_low_score(self):
        js = "\n".join(["const T={synctex:'S',text:'X'};", extract_js_fn("viaTag"), r"""
            console.log(JSON.stringify([viaTag({via:'synctex',score:0.934}),viaTag({via:'text',score:0.2}),viaTag({})]));"""])
        got = json.loads(run_node(js))
        self.assertEqual(got[0], {"t": "일치 93%", "tip": "좌표로 찾음 · S", "low": False})
        self.assertEqual(got[1], {"t": "글자 일치 20%", "tip": "글자로 찾음 · X", "low": True})
        self.assertIsNone(got[2])


class FrontendPanelTidyStructure(unittest.TestCase):
    def test_grip_is_one_pointer_events_separator(self):
        tag = re.search(r'<div id="grip"[^>]*>', ps.HTML).group(0)
        for part in ('role="separator"', 'aria-orientation="vertical"', 'tabindex="0"', 'aria-controls="right"'):
            self.assertIn(part, tag)
        self.assertIn("$('#grip'); let D=null;", ps.HTML)
        self.assertIn("g.setPointerCapture(e.pointerId)", ps.HTML)
        self.assertNotIn("$('#grip').addEventListener('mousedown'", ps.HTML)   # 옛 마우스 전용 경로가 없다
        self.assertNotIn("body.compact #grip{display:none}", ps.HTML)          # mid 에서도 보인다
        self.assertIn("body.lay-narrow #grip,body.lay-mid:not(.side-open) #grip{display:none}", ps.HTML)

    def test_width_is_remembered_per_layout_and_relayout_keeps_anchor(self):
        self.assertIn("function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}", ps.HTML)
        m = re.search(r"\nfunction setSideWidth\(w\)\{(.*?)\}\n", ps.HTML, re.S)
        self.assertIsNotNone(m)
        self.assertIn("savePrefs({[sideKey()]:w})", m.group(1))
        self.assertIn("relayout()", m.group(1))
        m = re.search(r"\nfunction relayout\(\)\{(.*?)\}\n", ps.HTML, re.S)
        body = m.group(1)
        self.assertLess(body.index("applySideWidth()"), body.index("autoW()"))   # 패널 폭을 먼저 정해야 쪽 폭이 맞는다
        # 끄는 동안에는 ResizeObserver 가 매 프레임 다시 맞추지 않는다
        self.assertIn("!document.body.classList.contains('resizing'))scheduleRelayout()", ps.HTML)
        self.assertIn("body.lay-mid.side-open #right{width:var(--side-w,", ps.HTML)

    def test_sheet_grip_and_size_presets_in_more(self):
        tag = re.search(r'<div id="sheet-grip"[^>]*>', ps.HTML).group(0)
        self.assertIn('role="separator"', tag)
        self.assertIn('aria-orientation="horizontal"', tag)
        self.assertIn(":not(#sheet-grip){display:none}", ps.HTML)   # 접힌 시트에서도 손잡이가 남는다
        self.assertIn("var(--sheet-f,.64)", ps.HTML)
        more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index('<dialog id="help"')]
        self.assertIn('id="m-size"', more)
        self.assertIn("case 'size-preset':sizePreset(+a.dataset.i)", ps.HTML)
        self.assertIn("renderSizeSeg(); d.showModal()", ps.HTML)

    def test_actions_row_is_fixed_at_panel_bottom_outside_composer(self):
        right = ps.HTML[ps.HTML.index('<div id="right">'):ps.HTML.index('<div id="tip"')]
        comp = right[right.index('<div id="composer"'):right.index('<div id="list">')]
        self.assertNotIn('id="btn-save"', comp)
        acts = right.index('<div id="c-actions">')
        self.assertGreater(acts, right.index('<div id="list">'))
        # 취소가 먼저, 주요 동작(핀 저장)이 오른쪽에 넓게
        self.assertLess(right.index('id="btn-cancel"', acts), right.index('id="btn-save"', acts))
        self.assertRegex(right, r'<button class="p" id="btn-save"')
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#composer[hidden]~#c-actions{display:none}", css)
        self.assertIn("grid-template-columns:1fr 2fr", css)
        self.assertIn("body.compact #c-actions{position:sticky;bottom:0", css)
        self.assertIn("#composer:not([hidden])~#list #empty{display:none}", css)   # 고르는 중에는 도움말 문단을 숨긴다

    def test_composer_is_one_loc_line_segmented_ladder_and_folded_snippet(self):
        self.assertNotIn('id="c-meta"', ps.HTML)            # 위치 정보 세 번 반복 → 한 줄
        self.assertNotIn("드래그한 줄 L'+d.raw_lo", ps.HTML)
        row = ps.HTML[ps.HTML.index('<div class="c-loc-row">'):ps.HTML.index('<div id="c-warn"')]
        for el in ('id="c-loc"', 'id="c-page"', 'id="c-tag"', 'id="c-copy"'):
            self.assertIn(el, row)
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        seg = re.search(r"\n\.seg\{([^}]*)\}", css).group(1)
        self.assertIn("flex-wrap:nowrap", seg)
        self.assertIn("overflow-x:auto", seg)
        self.assertIn('<div class="step" role="group"', ps.HTML)
        self.assertIn("#c-snip:not(.open){max-height:calc(6em + 18px);overflow:hidden}", css)
        m = re.search(r"\nfunction renderComposer\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIn("pre.scrollHeight>pre.clientHeight", m.group(1))
        # narrow 시트에서는 메모 칸이 원문보다 위(동작 줄 밑에 숨지 않게)
        self.assertIn("body.lay-narrow #note{order:1", css)

    def test_card_head_tags_row_and_action_grid(self):
        m = re.search(r"\nfunction card\(p\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1)
        self.assertNotIn('<span class="tags">', body)                        # 배지는 머리 줄 안이 아니라
        self.assertGreater(body.index('<div class="tags">'), body.index("b-fold"))   # 머리(접기 버튼) 뒤 한 줄
        self.assertLess(body.index('b-drop'), body.index('b-close'))         # 완료(주요)는 맨 오른쪽
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pin .acts{display:grid;grid-auto-flow:column;grid-auto-columns:1fr", css)
        self.assertIn("button.b-close{background:var(--acc-soft)", css)
        self.assertIn("button.b-drop{color:var(--danger)}", css)

    def test_compact_toolbar_is_one_even_row(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact #bar1 .sp{display:none}", css)
        self.assertIn("body.compact #bar1 #btn-more{flex:0 0 44px", css)


if __name__ == "__main__":
    unittest.main()


class PinNumberJump(unittest.TestCase):
    """카드 머리의 #번호를 누르면 PDF 에서 그 핀 자리로 간다([보기]·N쪽과 같은 data-act="view")."""

    def test_number_is_a_button_that_jumps(self):
        src = ps.HTML
        self.assertIn('<span class="n go" role="button" tabindex="0" data-act="view"', src)
        self.assertIn("누르면 PDF에서 이 핀 자리로 갑니다", src)

    def test_number_is_keyboard_and_touch_reachable(self):
        src = ps.HTML
        self.assertIn("t.getAttribute('role')==='button'&&t.dataset&&t.dataset.act", src)
        self.assertIn(".loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;min-height:44px}", src)

    def test_view_action_still_routes_to_jumppin(self):
        self.assertIn("case 'view':jumpPin(id);break;", ps.HTML)


# ---------------------------------------------------------------- 인스턴스 이름표(§동시 인스턴스)

class RepoNameFromUrl(unittest.TestCase):
    def test_https_url(self):
        self.assertEqual(ps.repo_name_from_url("https://github.com/example-lab/paper-a.git"),
                         "paper-a")

    def test_ssh_url_with_path(self):
        self.assertEqual(ps.repo_name_from_url("git@github.com:example-lab/paper-a.git"),
                         "paper-a")

    def test_scp_style_without_slash(self):
        self.assertEqual(ps.repo_name_from_url("git@host:reponame.git"), "reponame")

    def test_no_git_suffix(self):
        self.assertEqual(ps.repo_name_from_url("https://github.com/org/name"), "name")

    def test_trailing_slash(self):
        self.assertEqual(ps.repo_name_from_url("https://github.com/org/name/"), "name")


class DefaultLabel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_uses_repo_name_when_remote_given(self):
        src = self.root / "some-checkout-dir"
        src.mkdir()
        self.assertEqual(ps.default_label(src, "git@github.com:example-lab/paper-a.git"),
                         "paper-a")

    def test_falls_back_to_folder_name_without_remote(self):
        src = self.root / "my-manuscript"
        src.mkdir()
        self.assertEqual(ps.default_label(src, None), "my-manuscript")

    def test_git_remote_url_none_when_not_a_repo(self):
        if not shutil.which("git"):
            self.skipTest("git 없음")
        src = self.root / "plain-dir"
        src.mkdir()
        self.assertIsNone(ps.git_remote_url(src))

    def test_git_remote_url_reads_origin(self):
        if not shutil.which("git"):
            self.skipTest("git 없음")
        src = self.root / "repo"
        src.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=src, check=True)
        subprocess.run(["git", "remote", "add", "origin", "git@example.com:org/paper-x.git"],
                       cwd=src, check=True)
        self.assertEqual(ps.git_remote_url(src), "git@example.com:org/paper-x.git")
        self.assertEqual(ps.default_label(src, ps.git_remote_url(src)), "paper-x")


class LabelValidation(unittest.TestCase):
    def test_strips_and_collapses_whitespace(self):
        self.assertEqual(ps.clean_label("  A-DEMO  "), "A-DEMO")
        self.assertEqual(ps.clean_label("A\nPPTL"), "A DEMO")

    def test_empty_becomes_default_placeholder(self):
        self.assertEqual(ps.clean_label(""), "원고")
        self.assertEqual(ps.clean_label(None), "원고")

    def test_over_length_exits(self):
        with self.assertRaises(SystemExit):
            ps.clean_label("x" * (ps.LABEL_MAX + 1))

    def test_exactly_max_length_ok(self):
        v = "x" * ps.LABEL_MAX
        self.assertEqual(ps.clean_label(v), v)


class AccentValidation(unittest.TestCase):
    def test_valid_format(self):
        self.assertTrue(ps.valid_accent("#1d4ed8"))
        self.assertTrue(ps.valid_accent("#AABBCC"))

    def test_invalid_formats_rejected(self):
        for bad in ("1d4ed8", "#1d4ed", "#1d4ed8ff", "#gggggg", "red", "", None):
            self.assertFalse(ps.valid_accent(bad))

    def test_pick_accent_is_deterministic_for_same_label(self):
        a = ps.pick_accent("A-DEMO")
        b = ps.pick_accent("A-DEMO")
        self.assertEqual(a, b)
        self.assertIn(a, ps.ACCENT_PALETTE)

    def test_pick_accent_differs_for_different_labels_usually(self):
        # 팔레트가 8색이라 100% 보장은 못 하지만, 서로 다른 이름표 몇 개가 전부 같은 색으로
        # 뭉치면 해시 분산이 깨진 것이다.
        colors = {ps.pick_accent(lbl) for lbl in ("A-DEMO", "paper-b", "grant-2026", "thesis")}
        self.assertGreater(len(colors), 1)


class BuildHtmlSubstitution(unittest.TestCase):
    def test_label_and_accent_appear_in_output(self):
        out = ps.build_html("A-DEMO", "#1d4ed8")
        self.assertIn("<title>A-DEMO · 원고 핀</title>", out)
        self.assertIn('id="brand-chip" class="chip" style="background:#1d4ed8"', out)
        self.assertIn(">A-DEMO</span>", out)
        self.assertIn('id="brand-stripe" style="background:#1d4ed8"', out)
        self.assertNotIn("__LABEL__", out)
        self.assertNotIn("__ACCENT__", out)
        self.assertNotIn("__FAVICON_HREF__", out)

    def test_label_is_html_escaped(self):
        out = ps.build_html("<script>alert(1)</script>", "#1d4ed8")
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_favicon_is_data_svg_with_first_letter(self):
        out = ps.favicon_href("paper-a", "#1d4ed8")
        self.assertTrue(out.startswith("data:image/svg+xml,"))
        self.assertIn("circle", out)
        # 대문자로 바꾼 첫 글자가 (url-인코딩된) svg 안에 있어야 한다
        from urllib.parse import unquote
        self.assertIn(">A<", unquote(out))

    def test_favicon_escapes_label_first_char(self):
        # 첫 글자가 '<' 처럼 XML 을 깨는 문자라도 안전해야 한다
        out = ps.favicon_href("<x", "#1d4ed8")
        from urllib.parse import unquote
        self.assertIn("&lt;", unquote(out))


class HtmlTemplateStructure(unittest.TestCase):
    """모듈 로드 시점(main() 실행 전)의 ps.HTML 에 이름표 자리·마크업이 있는지 — 구조 검증은 실제
    치환값과 무관하게 항상 참이어야 한다."""

    def test_title_has_label_placeholder(self):
        self.assertIn("<title>__LABEL__ · 원고 핀</title>", ps.HTML)

    def test_favicon_placeholder(self):
        self.assertIn('<link rel="icon" href="__FAVICON_HREF__">', ps.HTML)

    def test_brand_stripe_present(self):
        self.assertIn('id="brand-stripe"', ps.HTML)
        self.assertIn("#brand-stripe{position:fixed;top:0;left:0;right:0;height:4px", ps.HTML)

    def test_brand_chip_is_first_child_of_bar1(self):
        m = re.search(r'<div class="bar" id="bar1"[^>]*>\s*(<span id="brand-chip"[^>]*>[^<]*</span>)',
                      ps.HTML)
        self.assertIsNotNone(m, "brand-chip 이 #bar1 의 첫 자식이어야 한다")

    def test_chip_narrow_screen_css_keeps_it_visible(self):
        self.assertIn("@media (max-width:480px){.chip{", ps.HTML)
        self.assertNotIn("display:none", re.search(r"\.chip\{[^}]*\}", ps.HTML).group(0))

    def test_document_title_prefixes_label(self):
        self.assertIn(
            "if(META)document.title=(META.label?META.label+' · ':'')+'원고 핀 · '+META.main+' · 열린 '+PINS.length;",
            ps.HTML)


class InstanceMeta(Base):
    def test_meta_exposes_label_accent_repo(self):
        ps.C.label, ps.C.accent, ps.C.repo = "A-DEMO", "#1d4ed8", "git@example.com:org/a-demo.git"
        d = ps.meta(dict(ps.LOCAL_ACTOR))
        self.assertEqual(d["label"], "A-DEMO")
        self.assertEqual(d["accent"], "#1d4ed8")
        self.assertEqual(d["repo"], "git@example.com:org/a-demo.git")

    def test_meta_repo_is_none_without_remote(self):
        ps.C.repo = None
        d = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertIsNone(d["repo"])

    def test_meta_endpoint_serves_new_fields(self):
        ps.C.label, ps.C.accent = "A-DEMO", "#1d4ed8"
        out = self.talk(req("GET", "/api/meta"))
        data = json.loads(out.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(data["label"], "A-DEMO")
        self.assertEqual(data["accent"], "#1d4ed8")
        self.assertIn("repo", data)


class InstanceIdInPinsMd(Base):
    def test_disk_header_has_paper_and_repo_line(self):
        ps.C.label, ps.C.repo = "A-DEMO", "git@github.com:example-lab/paper-a.git"
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        lines = md.splitlines()
        src_idx = next(i for i, l in enumerate(lines) if l.startswith("원고: `"))
        self.assertEqual(lines[src_idx + 1],
                         "논문: A-DEMO · 저장소: git@github.com:example-lab/paper-a.git")

    def test_header_shows_placeholder_without_repo(self):
        ps.C.label, ps.C.repo = "paper-a", None
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("논문: paper-a · 저장소: (없음)", md)

    def test_guidance_mentions_remote_check_only_when_repo_known(self):
        ps.C.label, ps.C.repo = "A-DEMO", "git@github.com:example-lab/paper-a.git"
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("git remote get-url origin", md)
        self.assertIn("다르면 다른 논문의 핀이니 멈춘다", md)

    def test_guidance_omits_remote_check_without_repo(self):
        ps.C.label, ps.C.repo = "paper-a", None
        self.add()
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("git remote get-url origin", md)

    def test_get_pins_md_endpoint_also_has_id_line(self):
        ps.C.label, ps.C.repo = "A-DEMO", "git@github.com:example-lab/paper-a.git"
        self.add()
        out = self.talk(req("GET", "/pins.md"))
        body = out.split(b"\r\n\r\n", 1)[1].decode("utf-8")
        self.assertIn("논문: A-DEMO · 저장소: git@github.com:example-lab/paper-a.git", body)
