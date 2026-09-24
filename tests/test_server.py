"""pin_server 회귀 테스트 — 포트를 열지 않는다(socketpair 로 핸들러를 직접 돌린다).

실행: python3 -m unittest discover -s skills/manuscript-pin-picker/tests
"""
import importlib.util
import errno
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
ROOT = HERE.parents[1]
SKILL = ROOT / "skills" / "manuscript-pin-picker"
spec = importlib.util.spec_from_file_location("pin_server", SKILL / "scripts" / "pin_server.py")
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


def js_icons() -> str:
    """뷰어의 Lucide 아이콘 표(ICONS)와 ic() — card()·archiveRow() 처럼 아이콘을 그리는 함수를 node 로 돌릴 때 함께 싣는다."""
    m = re.search(r"const ICONS=\{.*?\};", ps.HTML)
    return m.group(0) + "\n" + extract_js_fn("ic")


def js_thread() -> str:
    """스레드를 그리는 함수들(card()·doneCard() 가 부른다). 호출부는 who·avatar·esc·arcTime·ic·THREAD_OPEN·REPLY 를 준비한다."""
    ev = re.search(r"^const EV_LABEL=.*;$", ps.HTML, re.M).group(0)
    st = re.search(r"^const ST_NAME=.*;$", ps.HTML, re.M).group(0)
    mo = re.search(r"^const MSG_OPEN=.*;$", ps.HTML, re.M).group(0)
    return "\n".join([ev, st, mo, "let PEOPLE=[];", extract_js_fn("hasRef")] + [extract_js_fn(n) for n in (
        "relTime", "relSpan", "msgBody", "isAgent", "isQuestion", "assigneeOf", "assignChip", "stDot", "reopenedTurn", "threadOf", "allMentions", "replyCount", "msgText", "msgHtml", "threadHtml", "pinState", "isMe", "reviewerLabel",
        "peopleName", "mentionToks", "reEsc", "meLogin", "pinRefExists", "fmtText", "mentionsMe", "addressedTag", "fyiTag")])


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
        with ps._SYNC_LOCK:
            ps._SYNC_STATE.clear()
            ps._SYNC_STATE.update(state="checking", reason=None, checked_at=None,
                                  head_before=None, head_after=None)
        C.pdfjs_dir = None
        C.label, C.accent, C.repo = "원고", ps.ACCENT_PALETTE[0], None
        ps.BUILD_STATE.update(state="idle", phase=None, started_at=None, start_ts=None, seq=0,
                              finished_at=None, last=None, errors=[], log_tail="", head=None, pull=None)
        ps.set_docs(None)                          # 단일 문서(--doc 없음)로 시작 — 여러 문서 테스트가 남긴 목록을 지운다
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
            try:
                a.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno not in (errno.ENOTCONN, errno.EPIPE, errno.ECONNRESET):
                    raise
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


VENDOR = SKILL / "vendor" / "pdfjs"


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
        self.assertIn("%d · 위치 잃음" % pid, md)   # 위치 잃음은 번호 칸에 말로 쓴다(예전 ⚠)
        self.assertIn("'위치 잃음' = 위치를 되찾지 못함", md)          # 표시 범례 줄
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
        aux = ps.cur_pages() / "main.aux"
        self.assertTrue(aux.is_file(), "successful build must publish its matching .aux with PDF pages")
        labels = ps.outline_labels(ps.cur_doc())
        self.assertEqual(labels["build"], res["build"])
        self.assertEqual([(row["number"], row["title"]) for row in labels["labels"][:2]],
                         [("1", "Intro"), ("1.1", "Next")])


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
            ps.set_done(pid, True, {"login": "a@x.com", "name": "A"})   # 사람이 닫음 = 완료(에이전트가 닫으면 검토 대기로 표에 남는다)
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
        self.assertIn("#%d 범위 안" % p1, md)
        self.assertNotIn("⊂", md)

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
            extract_js_fn("josa"), extract_js_fn("overlapVerb"), "let OVERLAP_DISMISSED=null;", extract_js_fn("recomputeOverlap"),
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
            // 여러 문서(§여러 문서) 전역 — 단일 문서 뷰어와 같은 값
            const DOC='main', DOC_SEQ=new Map(), BUILD_ERR_BY=new Map(); function dq(u){return u;}
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
            extract_js_fn("josa"), extract_js_fn("relBadge"),
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
        self.assertEqual(ps.rel_badge(rel, by_id), "#2 범위 안")

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

    def test_doc_menu_closes_even_when_switch_doc_is_synchronous_and_cached(self):
        # 회귀: switchDoc() 이 캐시된 문서에서 동기로 drawDocTabs→drawDocsMenu 까지 돌면 열린 #docs-menu 를
        # 다시 그려 클릭된 <a> 를 DOM 에서 떼어낸다. switchDoc() 호출 뒤에 a.closest() 를 부르면 null 이
        # 나와 메뉴가 열린 채 남는다 — inMenu 는 반드시 switchDoc() 호출 '전'에 정해야 한다.
        m = re.search(r"case 'doc':\{(.*?)\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        js = ("""
            (async()=>{
              const out={};
              const docsMenu={closed:false,close(){this.closed=true;}};
              function $(sel){return sel==='#docs-menu'?docsMenu:{};}
              let detached=false;
              function switchDoc(k){detached=true;}   // 캐시된 문서: 동기로 끝나며 a 를 떼어낸 것을 흉내
              const a={dataset:{doc:'ms'},closest(sel){return (!detached&&sel==='#docs-menu')?{}:null;}};
              switch('doc'){case 'doc':{%s}}
              out.closed=docsMenu.closed;
              console.log(JSON.stringify(out));
            })();
            """ % body)
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        data = json.loads(out)
        self.assertTrue(data["closed"], "캐시된 문서를 골라도 #docs-menu 가 닫혀야 한다")

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
        self.assertRegex(body, r"(DROPPED|LDROP)\.length")   # LDROP = listDropped()(지금 문서 또는 모든 문서)
        self.assertIn("droppedCard", body)

    def test_done_card_shows_close_reply_and_ref(self):
        # §C: 닫힌 카드에 닫을 때 남긴 reply·ref 를 보여 준다(둘 다 esc 를 거친다).
        m = re.search(r"function doneCard\(p\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("p.close_ref", body)
        self.assertIn("p.close_reply", body)
        self.assertIn("arcLine('r:'+p.id,p.close_reply", body)        # 답 한 줄은 arcLine 이 esc 를 거쳐 그린다
        self.assertIn("fmtText(text,logins)", extract_js_fn("arcLine"))   # fmtText 가 먼저 esc 를 거친다
        self.assertIn("esc(p.close_ref)", body)

    def test_close_curl_example_in_skill_md_documents_reply_and_ref(self):
        # SKILL.md 의 '핀 소비 절차' 닫기 예시가 reply·ref 를 남기도록 바뀌었는지(§C).
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
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
        for bad in (0, -1, "120", 12.5, True, None):                  # 형이 틀리거나 1 보다 작으면 400
            with self.assertRaises(ps.HTTPError):
                ps.clean_claim_ttl({"ttl_min": bad})
        self.assertEqual(ps.clean_claim_ttl({}), ps.CLAIM_TTL_DEFAULT)
        self.assertEqual(ps.clean_claim_ttl({"ttl_min": 1}), 1)
        self.assertEqual(ps.clean_claim_ttl({"ttl_min": 120}), 120)
        self.assertEqual(ps.CLAIM_TTL_MAX, 120)
        for over in (121, 480, 10_000):                                # 상한(120, 예전 480)을 넘으면 깎아서 받는다(하위 호환)
            self.assertEqual(ps.clean_claim_ttl({"ttl_min": over}), 120)

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
        self.assertIn("처리 중(Coauthor Kim)", md)                     # 예상 없이 잡으면 이름만
        self.assertNotIn("⏳", md)
        self.assertIn("'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다", md)

    def test_pins_md_hourglass_uses_local_label_for_curl_claims(self):
        pid = self.add()
        ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), 120)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(로컬/에이전트)", md)

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

    def test_main_only_rejects_feature_branch(self):
        d = self._clone("feature")
        self._run(["git", "checkout", "--quiet", "-b", "feature"], d)
        self._run(["git", "push", "--quiet", "-u", "origin", "feature"], d)
        r = ps.git_pull_phase(d, main_only=True)
        self.assertEqual((r["state"], r["reason"]), ("skipped", "not_main"))

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

    def test_pull_bumped_mtime_does_not_falsely_mark_stale(self):
        # 결함: _build_tracked() 가 pull 전(src_mtime_at_start)을 built_src_mtime 으로 확정해서,
        # pull 이 .tex mtime 을 앞으로 밀면(실제 fast-forward merge 가 그렇다) 빌드가 방금 그 새
        # 원고로 끝났는데도 '원고 수정됨' 배지가 계속 떴다. 측정은 pull 뒤(복사 전)여야 한다.
        if not (shutil.which("latexmk") and shutil.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        ps.C.git_pull = True

        def fake_pull():
            # git fast-forward 흉내 — 실제 merge 처럼 .tex mtime 을 앞으로 민다.
            os.utime(self.main, (time.time() + 50, time.time() + 50))
            return {"state": "ok", "head_before": "aaa1111", "head_after": "bbb2222"}

        with mock.patch.object(ps, "repo_pull", side_effect=fake_pull):
            res = ps.build_all()
        self.assertEqual(res["state"], "ok")
        ps._SRC_MTIME_CACHE[2] = 0.0
        m = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertIs(m["stale_build"], False)
        self.assertAlmostEqual(ps.read_built_src_mtime(), ps.src_mtime(force=True), delta=1.0)

    def test_edit_after_copy_phase_still_marks_stale(self):
        # pull 뒤(또는 pull 없을 때 복사 시작 시각)의 mtime 을 쓰더라도, 복사 뒤(latex 컴파일 중) 원본을
        # 고치면 그 편집은 이번 빌드에 안 들어갔으므로 여전히 '원고 수정됨' 배지가 떠야 한다.
        if not (shutil.which("latexmk") and shutil.which("pdftoppm")):
            self.skipTest("latexmk/pdftoppm 없음")
        ps.C.git_pull = True
        original_run_logged = ps.run_logged

        def bump_then_run(cmd, cwd, timeout):
            os.utime(self.main, (time.time() + 50, time.time() + 50))   # 복사 끝난 뒤(latex 단계에서) 원본 편집
            return original_run_logged(cmd, cwd, timeout)

        def fake_pull():
            return {"state": "up_to_date", "head_before": "aaa1111", "head_after": "aaa1111"}

        with mock.patch.object(ps, "repo_pull", side_effect=fake_pull), \
             mock.patch.object(ps, "run_logged", side_effect=bump_then_run):
            res = ps.build_all()
        self.assertEqual(res["state"], "ok")
        ps._SRC_MTIME_CACHE[2] = 0.0
        m = ps.meta(dict(ps.LOCAL_ACTOR), light=True)
        self.assertIs(m["stale_build"], True)


class AutomaticMainSync(Base):
    def test_new_head_schedules_each_tex_document_once(self):
        docs = [ps.Doc("ms", "본문", src=self.src, main=self.main),
                ps.Doc("hl", "하이라이트", src=self.src, main=self.main),
                ps.Doc("pdf", "참고", kind="pdf", src=self.src, main=self.src / "ref.pdf")]
        ps.set_docs(docs)
        ps.C.git_pull = True
        pull = {"state": "ok", "reason": None, "head_before": "a" * 40, "head_after": "b" * 40}
        with mock.patch.object(ps, "git_pull_phase", return_value=pull) as git_pull, \
             mock.patch.object(ps, "build_async", return_value={"state": "running"}) as build:
            out = ps.sync_main_once()
        git_pull.assert_called_once_with(self.src, main_only=True)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(out["state"], "updating")

    def test_current_head_still_rebuilds_old_pdf_on_startup(self):
        ps.C.git_pull = True
        (ps.C.state / "head.txt").write_text("aaaaaaa", encoding="utf-8")
        pull = {"state": "up_to_date", "reason": None, "head_before": "b" * 40, "head_after": "b" * 40}
        with mock.patch.object(ps, "git_pull_phase", return_value=pull), \
             mock.patch.object(ps, "build_async", return_value={"state": "running"}) as build:
            out = ps.sync_main_once()
        build.assert_called_once()
        self.assertEqual(out["state"], "updating")

    def test_dirty_checkout_is_visible_and_never_rebuilt(self):
        ps.C.git_pull = True
        pull = {"state": "skipped", "reason": "dirty", "head_before": "a" * 40, "head_after": "a" * 40}
        with mock.patch.object(ps, "git_pull_phase", return_value=pull), \
             mock.patch.object(ps, "build_async") as build:
            out = ps.sync_main_once()
        build.assert_not_called()
        self.assertEqual(out["state"], "blocked")
        self.assertEqual(ps.meta(dict(ps.LOCAL_ACTOR), light=True)["sync"]["reason"], "dirty")

    def test_updating_clears_when_pdf_reaches_synced_head(self):
        ps.C.git_pull = True
        with ps._SYNC_LOCK:
            ps._SYNC_STATE.update(state="updating", reason=None, head_after="b" * 40)
        (ps.C.state / "head.txt").write_text("bbbbbbb", encoding="utf-8")
        self.assertEqual(ps.sync_status()["state"], "current")

    def test_failed_pdf_build_reports_error(self):
        ps.C.git_pull = True
        with ps._SYNC_LOCK:
            ps._SYNC_STATE.update(state="updating", reason=None, head_after="b" * 40)
        (ps.C.state / "head.txt").write_text("aaaaaaa", encoding="utf-8")
        with ps.cur_doc().bstate_lock:
            ps.cur_doc().bstate["state"] = "fail"
        status = ps.sync_status()
        self.assertEqual((status["state"], status["reason"]), ("error", "build_failed"))


class ManuscriptRevisions(Base):
    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git 없음")
        self.repo = self.src.parent
        self.secret = self.repo / "other" / "private.tex"
        self.secret.parent.mkdir()
        self.secret.write_text("private text\n", encoding="utf-8")
        for cmd in (["git", "init", "--quiet"], ["git", "config", "user.email", "t@example.com"],
                    ["git", "config", "user.name", "T"], ["git", "add", "ms/main.tex", "other/private.tex"],
                    ["git", "commit", "--quiet", "-m", "first"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        self.main.write_text(TEX + "New manuscript sentence.\n", encoding="utf-8")
        self.secret.write_text("hidden change\n", encoding="utf-8")
        for cmd in (["git", "add", "ms/main.tex", "other/private.tex"],
                    ["git", "commit", "--quiet", "-m", "manuscript update"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        self.latest = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

    def test_latest_revision_diff_is_real_and_scoped(self):
        history = ps.revision_history(ps.cur_doc())
        self.assertTrue(history["available"])
        self.assertEqual(history["revisions"][0]["id"], self.latest)
        d = ps.revision_diff(ps.cur_doc(), self.latest)
        self.assertIn("New manuscript sentence.", d["diff"])
        self.assertNotIn("hidden change", d["diff"])
        self.assertNotIn("other/private.tex", d["diff"])
        self.assertFalse(d["truncated"])

    def test_http_revision_endpoints(self):
        code, _, raw = split_resp(self.talk(req("GET", "/api/revisions")))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["revisions"][0]["id"], self.latest)
        code, _, raw = split_resp(self.talk(req("GET", "/api/revision-diff?commit=" + self.latest)))
        self.assertEqual(code, 200)
        self.assertIn("New manuscript sentence.", json.loads(raw)["diff"])
        code, _, _ = split_resp(self.talk(req("GET", "/api/revision-diff?commit=HEAD")))
        self.assertEqual(code, 400)

    def test_rejects_arbitrary_commit_and_bad_id(self):
        for commit in ("HEAD", "a" * 40, "--help"):
            with self.assertRaises(ps.HTTPError):
                ps.revision_diff(ps.cur_doc(), commit)

    def test_shared_build_root_keeps_document_histories_separate(self):
        heads = {"ms": self.main}
        for key in ("hl", "cl"):
            path = self.repo / key / (key + ".tex")
            path.parent.mkdir()
            path.write_text("\\documentclass{article}\n" + key + "\n", encoding="utf-8")
            subprocess.run(["git", "add", str(path.relative_to(self.repo))], cwd=self.repo,
                           check=True, capture_output=True)
            subprocess.run(["git", "commit", "--quiet", "-m", key + " update"], cwd=self.repo,
                           check=True, capture_output=True)
            heads[key] = path
        docs = [ps.Doc(k, k, src=self.repo, main=path) for k, path in heads.items()]
        for d in docs:
            history = ps.revision_history(d)
            self.assertTrue(history["available"])
            self.assertEqual(history["revisions"][0]["subject"],
                             "manuscript update" if d.key == "ms" else d.key + " update")
        hl_head = ps.revision_history(docs[1])["revisions"][0]["id"]
        with self.assertRaises(ps.HTTPError):
            ps.revision_diff(docs[0], hl_head)

    def test_main_path_outside_document_source_is_unavailable(self):
        bad = ps.Doc("bad", "bad", src=self.src, main=self.secret)
        self.assertFalse(ps.revision_history(bad)["available"])
        link = self.src / "linked.tex"
        link.symlink_to(self.secret)
        linked = ps.Doc("linked", "linked", src=self.src, main=link)
        self.assertFalse(ps.revision_history(linked)["available"])

    def test_caps_large_diff(self):
        old = ps.REVISION_DIFF_MAX
        ps.REVISION_DIFF_MAX = 50
        try:
            d = ps.revision_diff(ps.cur_doc(), self.latest)
        finally:
            ps.REVISION_DIFF_MAX = old
        self.assertTrue(d["truncated"])
        self.assertLessEqual(len(d["diff"].encode("utf-8")), 53)  # UTF-8 replacement at the byte boundary

    def test_revision_spec_uses_first_parent_and_rejects_root(self):
        spec = ps.revision_spec(ps.cur_doc(), self.latest)
        self.assertEqual((spec.base, spec.head), (self.first, self.latest))
        with self.assertRaises(ps.HTTPError):
            ps.revision_spec(ps.cur_doc(), self.first)

    def test_revision_snapshot_uses_git_and_rejects_symlinks(self):
        self.main.write_text("uncommitted secret")
        dest = self.repo / "snapshot"
        spec = ps.revision_spec(ps.cur_doc(), self.latest)
        ps.revision_snapshot(spec, spec.head, dest)
        self.assertIn("New manuscript sentence.", (dest / "main.tex").read_text())
        self.assertFalse((dest / "other").exists())
        (self.src / "escape.tex").symlink_to(self.secret)
        for cmd in (["git", "add", "ms/escape.tex"], ["git", "commit", "-qm", "link"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        with self.assertRaises(ps.HTTPError):
            ps.revision_snapshot(ps.revision_spec(ps.cur_doc(), head), head, self.repo / "bad-snapshot")

    def test_outline_uses_only_current_pdf_aux_and_balanced_tex_groups(self):
        current = ps.C.state / "pages-20260924010000"
        current.mkdir()
        (ps.C.state / "pages.cur").write_text(current.name)
        (current / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {2}A \textbf{nested {title}} \& B}{iv}{section.2}}" + "\n" +
            r"\@writefile{toc}{\contentsline {subsection}{\numberline {2.1}Use \texorpdfstring{$x^2$}{x squared}}{8}{subsection.2.1}}" + "\n")
        ps.C.build.mkdir()
        (ps.C.build / "main.aux").write_text("wrong next build")
        data = ps.outline_labels(ps.cur_doc())
        self.assertEqual(data["build"], current.name)
        self.assertEqual(data["labels"], [
            {"number": "2", "title": "A nested title & B", "page": "iv", "level": "section", "anchor": "section.2"},
            {"number": "2.1", "title": "Use x squared", "page": "8", "level": "subsection", "anchor": "subsection.2.1"},
        ])

    def test_outline_missing_snapshot_does_not_read_mutable_build(self):
        ps.C.build.mkdir()
        (ps.C.build / "main.aux").write_text(r"\@writefile{toc}{\contentsline {section}{\numberline {9}Stale}{1}{section.9}}")
        self.assertEqual(ps.outline_labels(ps.cur_doc())["labels"], [])

    def _wait_revision(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = ps.revision_status(ps.cur_doc(), self.latest)
            if status["state"] != "running":
                return status
            time.sleep(.01)
        self.fail("revision worker did not finish")

    def test_async_revision_http_deduplicates_caches_and_preserves_current_build(self):
        entered, release = threading.Event(), threading.Event()
        original = self.main.read_bytes()
        marker = ps.C.state / "pages.cur"
        marker.write_text("pages-20260924000000")
        before = dict(ps.BUILD_STATE)
        calls = []
        def compile(spec, jobdir, timeout):
            calls.append(spec)
            entered.set()
            release.wait(3)
            (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4\nrevision")
            return {"state": "ready", "warnings": ["test warning"], "error": None, "reason": None}
        body = json.dumps({"commit": self.latest}).encode()
        request = req("POST", "/api/revision-build", body, {"Content-Type": "application/json"})
        with mock.patch.object(ps, "revision_compile", side_effect=compile):
            try:
                code, _, raw = split_resp(self.talk(request))
                self.assertEqual(code, 202)
                self.assertEqual(json.loads(raw)["base"], self.first)
                self.assertTrue(entered.wait(2))
                self.assertEqual(split_resp(self.talk(request))[0], 202)
                self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))[0], 404)
            finally:
                release.set()
                status = self._wait_revision()
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["warnings"], ["test warning"])
            self.assertEqual(split_resp(self.talk(request))[0], 200)
            self.assertEqual(len(calls), 1)
        code, headers, pdf = split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))
        self.assertEqual((code, headers["content-type"], pdf), (200, "application/pdf", b"%PDF-1.4\nrevision"))
        self.assertEqual(self.main.read_bytes(), original)
        self.assertEqual(marker.read_text(), "pages-20260924000000")
        self.assertEqual(ps.BUILD_STATE, before)
        with mock.patch.object(ps, "revision_history", return_value={"available": True, "revisions": []}):
            self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-pdf?commit=" + self.latest)))[0], 404)
            with self.assertRaises(ps.HTTPError):
                ps.revision_status(ps.cur_doc(), self.latest)

    def test_revision_failure_has_no_pdf_and_can_retry(self):
        failure = ps.HTTPError(503, "test timeout", reason="timeout")
        with mock.patch.object(ps, "revision_compile", side_effect=failure) as run:
            ps.revision_start(ps.cur_doc(), self.latest)
            status = self._wait_revision()
            self.assertEqual((status["state"], status["reason"]), ("error", "timeout"))
            with self.assertRaises(ps.HTTPError):
                ps.revision_pdf(ps.cur_doc(), self.latest)
            ps.revision_start(ps.cur_doc(), self.latest)
            self._wait_revision()
            self.assertEqual(run.call_count, 2)

    def test_revision_requests_enforce_origin_allowlist_and_field_validation(self):
        body = json.dumps({"commit": self.latest}).encode()
        ps.C.allow = frozenset({"allowed@example.com"})
        code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", body,
            {"Content-Type": "application/json", "Tailscale-User-Login": "stranger@example.com"})))
        self.assertEqual(code, 403)
        ps.C.allow = frozenset()
        code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", body,
            {"Content-Type": "application/json", "Origin": "https://evil.example"})))
        self.assertEqual(code, 403)
        for bad in ({"commit": []}, {"commit": "HEAD"}, {"commit": self.latest, "command": "evil"}):
            code, _, _ = split_resp(self.talk(req("POST", "/api/revision-build", json.dumps(bad).encode(),
                {"Content-Type": "application/json"})))
            self.assertEqual(code, 400)
        self.assertEqual(split_resp(self.talk(req("GET", "/api/revision-build?commit=HEAD")))[0], 400)

    def test_revision_source_limits_and_gitlinks_are_rejected(self):
        spec = ps.revision_spec(ps.cur_doc(), self.latest)
        with mock.patch.object(ps, "REVISION_FILE_MAX", 1):
            with self.assertRaises(ps.HTTPError) as raised:
                ps.revision_snapshot(spec, self.latest, self.repo / "large")
            self.assertEqual(raised.exception.body["reason"], "size_limit")
        for cmd in (["git", "update-index", "--add", "--cacheinfo", "160000," + self.first + ",ms/sub"],
                    ["git", "commit", "-qm", "add submodule"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        with self.assertRaises(ps.HTTPError) as raised:
            ps.revision_snapshot(spec, head, self.repo / "submodule-snapshot")
        self.assertEqual(raised.exception.body["reason"], "unsafe_snapshot")

    def test_revision_jobs_are_bounded_and_cache_expires(self):
        with mock.patch.object(ps, "REVISION_SLOTS", threading.BoundedSemaphore(0)):
            with self.assertRaises(ps.HTTPError) as raised:
                ps.revision_start(ps.cur_doc(), self.latest)
            self.assertEqual(raised.exception.code, 409)
        spec = ps.revision_spec(ps.cur_doc(), self.latest)
        root = ps._revision_cache_root(ps.cur_doc())
        jobdir = root / spec.key
        jobdir.mkdir()
        (jobdir / "revision.pdf").write_bytes(b"%PDF-1.4")
        status = jobdir / "status.json"
        status.write_text(json.dumps({"state": "ready"}))
        self.assertEqual(ps.revision_status(ps.cur_doc(), self.latest)["state"], "ready")
        os.utime(status, (1, 1))
        self.assertEqual(ps.revision_status(ps.cur_doc(), self.latest)["state"], "idle")
        for i in range(8):
            (root / ("%064x" % i)).mkdir()
        ps._revision_prune(root, spec.key)
        self.assertLessEqual(sum(p.is_dir() for p in root.iterdir()), ps.REVISION_CACHE_KEEP)

    def test_corrupt_revision_cache_is_a_miss(self):
        spec = ps.revision_spec(ps.cur_doc(), self.latest)
        root = ps._revision_cache_root(ps.cur_doc())
        jobdir = root / spec.key
        jobdir.mkdir()
        for content in ("[]", "null", "1", "bad JSON", '{"state":"running"}', '{"state":"ready"}'):
            (jobdir / "status.json").write_text(content)
            self.assertEqual(ps.revision_status(ps.cur_doc(), self.latest)["state"], "idle")

    def test_sandbox_is_required_and_has_no_unsandboxed_fallback(self):
        with mock.patch.object(ps.shutil, "which", return_value=None):
            with self.assertRaises(ps.HTTPError) as raised:
                ps.revision_sandbox(self.repo, Path("."), "latexmk", [])
        self.assertEqual(raised.exception.body["reason"], "tool_unavailable")
        with self.assertRaises(ValueError):
            ps.revision_sandbox(self.repo, Path("."), "sh", [])

    def test_revision_exec_bounds_output_and_time(self):
        with self.assertRaises(ps.HTTPError) as raised:
            ps.revision_exec(["python3", "-c", "print('x' * 10000)"], self.repo, 2, 100)
        self.assertEqual(raised.exception.body["reason"], "size_limit")
        with self.assertRaises(ps.HTTPError) as raised:
            ps.revision_exec(["python3", "-c", "import time; time.sleep(20)"], self.repo, .1)
        self.assertEqual(raised.exception.body["reason"], "timeout")

    def test_outline_complex_titles_keep_alignment_and_http_build_identity(self):
        pages = ps.C.state / "pages"
        pages.mkdir()
        (pages / "main.aux").write_text(
            r"\@writefile{toc}{\contentsline {section}{\numberline {1}Bad \unknown{macro}}{1}{section.1}}" + "\n" +
            r"\@writefile{toc}{\contentsline {section}{\protect\numberline {2}A \{literal\} title}{2}{section.2}}" + "\n" +
            r"\@writefile{toc}{\contentsline {section}{Unnumbered}{3}{section*.3}}" + "\n" +
            r"\@writefile{lof}{\contentsline {figure}{\numberline {1}Not a section}{4}{figure.1}}")
        code, _, raw = split_resp(self.talk(req("GET", "/api/outline-labels")))
        self.assertEqual(code, 200)
        data = json.loads(raw)
        self.assertEqual(data["build"], "pages")
        self.assertEqual([r["number"] for r in data["labels"]], ["", "2", ""])
        self.assertEqual(data["labels"][1]["title"], "A {literal} title")
        self.assertEqual(data["labels"][0]["title"], "")

    def test_page_snapshot_keeps_aux_with_its_pdf(self):
        ps.C.build.mkdir()
        pdf, aux = ps.C.build / "main.pdf", ps.C.build / "main.aux"
        pdf.write_bytes(b"%PDF-1.4")
        aux.write_text(r"\@writefile{toc}{\contentsline {section}{\numberline {1}Before}{1}{section.1}}")
        def render(cmd, **kwargs):
            Path(str(cmd[-1]) + "-1.png").write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0)
        with mock.patch.object(ps.subprocess, "run", side_effect=render):
            pages, error = ps._render_pages(pdf, [aux])
        self.assertIsNone(error)
        (ps.C.state / "pages.cur").write_text(pages.name)
        aux.write_text("changed by a failed next build")
        self.assertEqual(ps.outline_labels(ps.cur_doc())["labels"][0]["title"], "Before")

    @unittest.skipUnless(all(shutil.which(t) for t in ("bwrap", "latexdiff", "latexmk", "pdftotext")), "TeX sandbox tools unavailable")
    def test_actual_sandbox_build_tracks_changed_input_and_preserves_sources(self):
        self.main.write_text("\\documentclass{article}\n\\begin{document}\n\\input{section}\n\\end{document}\n")
        section = self.src / "section.tex"
        section.write_text("Old sentence.\n")
        for cmd in (["git", "add", "ms"], ["git", "commit", "-qm", "split document"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        section.write_text("New sentence.\n")
        for cmd in (["git", "add", "ms"], ["git", "commit", "-qm", "change included section"]):
            subprocess.run(cmd, cwd=self.repo, check=True, capture_output=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        before = {p.name: p.read_bytes() for p in self.src.iterdir()}
        dest = self.repo / "actual-job"
        dest.mkdir()
        status = ps.revision_compile(ps.revision_spec(ps.cur_doc(), head), dest, 30)
        self.assertEqual(status["state"], "ready")
        text = subprocess.check_output(["pdftotext", str(dest / "revision.pdf"), "-"], text=True)
        self.assertIn("Old", text)
        self.assertIn("New", text)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.src.iterdir()})
        self.assertFalse(list(dest.glob("work-*")))



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
    # 작성자 접두는 '[이름] ' 형식이다(§api.md 메모 앞 [작성자]) — '@이름: '이던 예전 모양은 @태그로 잘못
    # 읽혔다(실측: pins.md 의 '@Alice Kim: …'가 멘션처럼 보임).
    def test_single_author_has_no_prefix(self):
        self.add(note="n", actor={"login": "alice@x.com", "name": "Alice"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Alice]", md)

    def test_multiple_authors_get_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        self.add(8, 8, note="n2", actor={"login": "bob@x.com", "name": "Bob"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("[Alice] n1", md)
        self.assertIn("[Bob] n2", md)

    def test_same_author_twice_does_not_trigger_prefix(self):
        self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        self.add(8, 8, note="n2", actor={"login": "alice@x.com", "name": "Alice"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Alice]", md)

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
        self.assertIn("[Bob] n2", md)
        self.assertNotIn("[None]", md)
        self.assertIn("legacy", md)

    def test_closed_pins_excluded_from_author_count(self):
        # 닫힌 핀의 작성자는 열린 표에 안 보이니 카운트에서도 빠져야 한다(열린 핀 기준 판정).
        pid = self.add(4, 5, note="n1", actor={"login": "alice@x.com", "name": "Alice"})
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        self.add(8, 8, note="n2", actor={"login": "bob@x.com", "name": "Bob"})
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("[Bob]", md)


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
        skill = SKILL
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
            self.assertRegex(tag, r'class="sec( btn-[a-z]+)*"')
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
        self.assertIn("input,textarea,select{font-size:var(--text-xl)}", coarse)   # iOS 확대 방지 — 16px 이상
        self.assertIn("--text-xl:16px", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("var(--kb,0px)", css)
        # touch-action: PDF 영역(#left)은 스크롤만 넘기고 브라우저 핀치를 막는다(두 손가락은 앱 확대, §PDF 영역 전용
        # 확대). 선택 모드의 쪽은 none(한 손가락 끌기 = 선택). 그 밖에는 폭·높이 손잡이 둘뿐이다(끄는 동안 스크롤과
        # 다투지 않게 none). 사이드바·시트는 건드리지 않는다.
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertEqual([x.strip() for x in re.findall(r"([^{}]*)\{[^{}]*touch-action", css_nc)],
                     ["#left", "#outline-grip", "#grip", "body.selmode .pg", "body.lay-narrow #sheet-grip"])
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

    def test_stale_doc_detached_before_awaiting_new_pdf(self):
        # 다른 문서/재빌드로 캐시 미스가 나면, fetch 가 끝날 때까지 VEC.doc 를 비워 둔다 —
        # 그 사이 IntersectionObserver 가 큐에 넣는 vecRun 이 옛 PDFDocumentProxy 를 잘못된
        # 쪽 번호로 건드리지 않게 한다(다른 문서 오염·'Invalid page request' 로 PNG 에 고착).
        body = self.fn("vecOpen")
        i_if = body.index("if(!doc){")
        i_null = body.index("VEC.doc=null")
        i_fetch = body.index("await fetch(")
        self.assertLess(i_if, i_null)
        self.assertLess(i_null, i_fetch)
        self.assertIn("if(prev&&!vecCached(prev))vecClose(prev)", body)
        # old 는 이미 null 일 수 있다(위에서 비웠으므로) — null 가드 없이 vecClose(null) 을 부르면 안 된다
        self.assertIn("if(old&&old!==doc&&!vecCached(old))vecClose(old)", body)

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
        self.assertIn('id="vec-chip" class="badge badge-warning" hidden', ps.HTML)
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

    def test_vecopen_stale_doc_not_touched_while_new_pdf_is_fetching(self):
        # 실측 재현: VEC.doc 가 옛 문서(1쪽)를 가리킨 채 27쪽짜리 새 문서를 vecOpen 하면,
        # fetch 가 끝나기 전에는 VEC.doc 가 null 이어야 하고(=vecNextJob 이 아무 일도 못 뽑는다),
        # 그 사이 걸린 vecRun 도 옛 doc.getPage 를 부르면 안 된다(불렀다면 여기서 던진다).
        js = "\n".join([
            "const VEC_CACHE_MAX=3;",
            extract_js_fn("vecCacheKey"),
            extract_js_fn("vecCachePut"),
            extract_js_fn("vecCached"),
            extract_js_fn("vecForget"),
            extract_js_fn("vecClose"),
            extract_js_fn("vecCancel"),
            extract_js_fn("vecNextJob"),
            extract_js_fn("vecOpen"),
            r"""
            function $(sel){return {hidden:false};}
            function dq(u){return u;}
            function vecSchedule(){}
            function loadOutline(){}
            function vecFail(msg){throw new Error('vecFail: '+msg);}
            global.document={getElementById:(id)=>({})};

            let oldClosed=false;
            const oldDoc={numPages:1, loadingTask:{destroy(){oldClosed=true;}},
              getPage(){throw new Error('옛(다른 문서/옛 빌드) doc.getPage 가 불렸다');}};
            const VEC={lib:null, doc:oldDoc, build:'old', gen:0, failed:null, tDoc:0,
              st:new Map(), cur:null, cache:new Map(), near:new Set([2])};
            const DOC='doc1';
            const META={pages_build:'new', pages:new Array(27).fill(0), built_at:'v2'};

            let resolveFetch, resolveGetDoc;
            global.fetch=function(){return new Promise(res=>{resolveFetch=res;});};
            VEC.lib={getDocument(){return {promise:new Promise(res=>{resolveGetDoc=res;})};}};

            const p=vecOpen();
            const results={};
            results.docNulledBeforeFetch=(VEC.doc===null);
            results.oldClosedImmediately=oldClosed;
            results.noJobWhileDocNull=(vecNextJob()===null);

            resolveFetch({ok:true, arrayBuffer:()=>Promise.resolve(new ArrayBuffer(8))});
            setTimeout(()=>{
              resolveGetDoc({numPages:27, loadingTask:{destroy(){}}});
              p.then(()=>{
                results.newDocInstalled=(VEC.doc&&VEC.doc.numPages===27);
                console.log(JSON.stringify(results));
              }).catch(e=>{results.error=String(e); console.log(JSON.stringify(results));});
            },10);
            """,
        ])
        out = json.loads(run_node(js))
        self.assertNotIn("error", out, out)
        self.assertTrue(out["docNulledBeforeFetch"])
        self.assertTrue(out["oldClosedImmediately"])
        self.assertTrue(out["noJobWhileDocNull"])
        self.assertTrue(out["newDocInstalled"])

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
                         ["narrow", "narrow", "mid", "mid", "mid", "wide", "wide", "narrow", "mid", "wide"])

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
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main'; function docInfo(){return null;}
            let LAYOUT='mid', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """,
            extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locText"), extract_js_fn("locCopy"), extract_js_fn("docChip"), js_thread(), extract_js_fn("card"), js_icons(),
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
        # 900px 이하는 오버레이, 그 이상은 본문 480px + 손잡이 8px을 남긴다.
        self.assertEqual(got[0], {"min": 300, "max": 440, "def": 330, "presets": [300, 330, 440]})
        self.assertEqual(got[1]["max"], 440)
        self.assertEqual(got[2], {"min": 300, "max": 440, "def": 330, "presets": [300, 330, 351]})
        # 데스크톱: 기본 348, 최소 280, 최대는 본문 480px + 손잡이를 남긴다
        self.assertEqual(got[3], {"min": 280, "max": 954, "def": 348, "presets": [300, 348, 605]})
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

    def test_via_tag_hides_confident_matches_and_flags_uncertain(self):
        # 90% 이상은 배지를 숨기고, 낮으면 '위치 불확실'(30% 미만은 경고 색). 방법·일치율·할 일은 설명에 둔다.
        js = "\n".join(["const T={synctex:'S',text:'X'};", extract_js_fn("viaTag"), r"""
            const V="const VIA_HIDE=90,VIA_WARN=30;";
            console.log(JSON.stringify([viaTag({via:'synctex',score:0.934}),viaTag({via:'synctex',score:0.884}),
              viaTag({via:'text',score:0.2}),viaTag({via:'synctex',score:1}),viaTag({})]));"""])
        js = js.replace("function viaTag(", "const VIA_HIDE=90,VIA_WARN=30;\nfunction viaTag(", 1)
        got = json.loads(run_node(js))
        self.assertIsNone(got[0])
        self.assertEqual(got[1], {"t": "위치 불확실", "tip": "좌표로 찾음 · 일치 88% — S", "low": False})
        self.assertEqual(got[2], {"t": "위치 불확실", "tip": "글자로 찾음 · 일치 20% — X 많이 어긋났을 수 있습니다.", "low": True})
        self.assertIsNone(got[3])
        self.assertIsNone(got[4])
        self.assertIn("const VIA_HIDE=90,VIA_WARN=30;", ps.HTML)


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
        self.assertRegex(right, r'<button class="btn-default" id="btn-save"')   # 주요 동작 = default 변형
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
        self.assertIn('class="btn-sm btn-soft b-close"', body)               # 완료 = soft(옅은 파랑, 저자 지정 09-23), 삭제 = destructive
        self.assertNotIn('btn-secondary b-close', body)
        self.assertIn("button.btn-soft{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary)", css)
        self.assertIn('class="btn-sm btn-destructive b-drop"', body)

    def test_compact_toolbar_is_one_even_row(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact #bar1 .sp{display:none}", css)
        self.assertIn("body.compact #bar1 #btn-more{flex:0 0 44px", css)

    def test_mid_layout_pins_nav_top_and_action_bar_bottom(self):
        # 펼친 폴드·태블릿(mid): 동작 줄은 패널을 따라다니지 않고 화면 아래 전체 폭에, 탐색 줄은 위 전체 폭에 고정한다
        # (references/design.md §펼친 화면 레이아웃). 브라우저 실측은 FrontendResponsiveBrowser 에 있다.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        css_nc = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        self.assertIn("body.lay-mid #bar1{position:fixed;left:0;right:0;top:auto;bottom:var(--kb,0px);", css)
        self.assertIn("body.lay-mid #doc-nav{position:fixed;top:0;left:0;right:0;", css)
        self.assertIn("padding-top:var(--mid-top);padding-bottom:var(--mbar-h)}", css)     # 본문·패널은 둘 사이에만
        self.assertIn("@media (pointer:coarse){body.lay-mid{--mbar-tb:var(--control-h-touch)}}", css)
        # 엄지 순서: [선택] 왼쪽 끝, [핀 N] 오른쪽 끝. DOM 은 narrow 시트와 공유하므로 order 로만 바꾼다.
        self.assertIn("body.lay-mid #btn-select{order:1}", css)
        self.assertIn("body.lay-mid #bar1 #btn-side{order:5;", css)
        # 도구 줄은 #right 의 fixed 자식이다 — #right 에 기준 상자를 만드는 속성을 주면 동작 줄이 패널과 함께 움직인다
        for sel, body in re.findall(r"([^{}]*#right[^{}]*)\{([^{}]*)\}", css_nc):
            if "lay-mid" in sel:
                self.assertIsNone(re.search(r"(?:^|;)(?:transform|translate|filter|opacity|contain|will-change|perspective)\s*:", body), sel)
        self.assertRegex(css_nc, r"@keyframes mid-panel-in\{from\{right:")      # 여는 움직임은 right 로만
        # 첫 안내는 탐색 줄을 가리지 않고 동작 줄 위([선택] 위)에 뜬다. 알림은 동작 줄 바로 위 패널 쪽(FrontendToasts).
        self.assertIn("body.lay-mid #coach{top:auto;bottom:calc(var(--mbar-h)", css)
        self.assertIn("body.lay-mid #toasts{", css)
        # 문서 링크가 넘치면 흐린 끝으로 알린다(스크롤바 대신)
        self.assertIn("body.lay-mid #doc-links.fade-r{mask-image:", css)
        self.assertIn("function docLinksFade(){", ps.HTML)
        self.assertIn("$('#doc-links').addEventListener('scroll',docLinksFade,{passive:true});", ps.HTML)



# ---------------------------------------------------------------- 디자인 토큰 가드(references/design.md §디자인 토큰)
# 색·radius·글자 크기가 규칙마다 제각각이던 것(색 리터럴 54가지, radius 14가지, 글자 12가지)을 토큰 층으로 모았다.
# 앞으로 규칙에 리터럴을 다시 박으면 여기서 막는다. 예외는 아래 허용 목록 하나이고, 늘리면 design.md 의 표도 함께 고친다.
TOKEN_SELECTORS = (":root", ":root[data-theme=light]")            # 색 리터럴이 살 수 있는 유일한 곳
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(|"
                      r"\b(?:white|black|red|green|blue|gray|grey|yellow|orange|purple|pink|silver)\b", re.I)
RADIUS_OK = re.compile(r"^(?:var\(--radius(?:-sm|-lg)?\)|0|50%)$")
INLINE_STYLE_OK = {"background:__ACCENT__"}                         # 인스턴스 이름표 색 — 서버가 --accent 값으로 채운다


def css_rules():
    """<style> 안의 (선택자, [(속성, 값)]) 목록. 주석을 빼고 @media 안 규칙도 평평하게 편다."""
    css = ps.HTML[ps.HTML.index("<style>") + len("<style>"):ps.HTML.index("</style>")]
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]*)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        decls = []
        for d in m.group(2).split(";"):
            if ":" in d:
                k, v = d.split(":", 1)
                decls.append((k.strip(), v.strip()))
        out.append((sel, decls))
    return out


class FrontendDesignTokens(unittest.TestCase):
    def test_colour_literals_only_in_token_blocks(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if sel in TOKEN_SELECTORS and k.startswith("--"):
                    continue                                          # 토큰 정의
                if COLOR_RE.search(v):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])

    def test_both_themes_define_every_colour_token(self):
        blocks = {sel: dict(decls) for sel, decls in css_rules() if sel in TOKEN_SELECTORS and any(k == "color-scheme" for k, _ in decls)}
        dark, light = blocks[":root"], blocks[":root[data-theme=light]"]
        lit = lambda b: {k for k, v in b.items() if k.startswith("--") and COLOR_RE.search(v)}
        self.assertEqual(lit(dark) - set(light), set())               # 다크 색이 라이트로 새어 들지 않는다
        self.assertEqual(set(light) - set(dark), set())               # 라이트는 다크에 있는 토큰만 덮는다
        for k in ("--background", "--foreground", "--card", "--card-foreground", "--muted", "--muted-foreground",
                  "--border", "--input", "--ring", "--primary", "--primary-foreground", "--secondary",
                  "--secondary-foreground", "--destructive", "--destructive-foreground", "--status-open",
                  "--status-claimed", "--status-closed", "--status-dropped", "--status-warning"):
            self.assertIn(k, dark)

    def test_radius_uses_scale_only(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if re.fullmatch(r"border(?:-[a-z]+)*-radius", k) and not all(RADIUS_OK.match(t) for t in v.split()):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])
        defs = {k: v for sel, decls in css_rules() if sel == ":root" for k, v in decls}
        self.assertEqual([defs["--radius-sm"], defs["--radius"], defs["--radius-lg"]], ["4px", "6px", "10px"])

    def test_font_size_uses_text_scale_only(self):
        bad = []
        for sel, decls in css_rules():
            for k, v in decls:
                if k == "font-size" and not re.fullmatch(r"var\(--text-(?:xs|sm|base|lg|xl)\)|inherit", v):
                    bad.append("%s { %s:%s }" % (sel, k, v))
                if k == "font" and v != "inherit" and not v.startswith("var(--text-"):
                    bad.append("%s { %s:%s }" % (sel, k, v))
        self.assertEqual(bad, [])
        defs = {k: v for sel, decls in css_rules() if sel == ":root" for k, v in decls}
        self.assertEqual([defs["--text-" + n] for n in ("xs", "sm", "base", "lg", "xl")], ["11px", "12px", "13px", "14px", "16px"])

    def test_inline_styles_and_scripts_carry_no_design_literals(self):
        body = ps.HTML[ps.HTML.index("</style>"):]
        for st in re.findall(r'style="([^"]*)"', body):
            self.assertTrue(st in INLINE_STYLE_OK or not (COLOR_RE.search(st) or re.search(r"font-size|radius", st)), st)
        # JS 가 요소 스타일에 색·글자 크기를 직접 쓰지 않는다(값은 폭·높이·좌표·토큰 변수뿐)
        self.assertEqual(re.findall(r"\.style\.(?:color|background\w*|fontSize|borderRadius|borderColor)\s*=", body), [])
        self.assertIsNone(re.search(r"['\"]#[0-9a-fA-F]{3,8}['\"]", body))

    def test_every_var_is_defined(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        runtime = set(re.findall(r"setProperty\('(--[a-z0-9-]+)'", ps.HTML))    # JS 가 재서 넣는 값(--kb·--side-w 등)
        used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
        self.assertEqual(used - defined - runtime, set())             # 이름을 바꾸다 남은 옛 토큰(--acc, --dim …)이 없다

    def test_component_variants_exist(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        for cls in ("button.btn-default{", "button.btn-secondary{", "button.btn-soft{", "button.btn-ghost{", "button.btn-destructive{",
                    "button.btn-sm{", "button.btn-icon{", ".badge{", ".badge-default{", ".badge-secondary{",
                    ".badge-destructive{", ".badge-claimed{", ".badge-warning{", ".card{"):
            self.assertIn(cls, css)
        for old in ("button.p{", "button.x{", "button.ghost{", "button.ib{", "button.ico{", ".tag{", ".tag.t{"):
            self.assertNotIn(old, css)                                # 옛 표시 전용 클래스는 없앴다



# ---------------------------------------------------------------- 알림(토스트) — references/design.md §알림
# 저자 지적(2026-09-24): 핀을 저장하면 '되돌리기' 알림이 오른쪽 패널에서 너무 먼 왼쪽 아래(1,100px+)에 떴고, 왼쪽 색 띠가
# 촌스러웠다. 이제 방금 누른 자리(패널 열의 오른쪽 아래, 동작 줄 바로 위 · narrow 는 시트 위)에 sonner 모양으로 뜬다.
class FrontendToasts(unittest.TestCase):
    css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]

    def rules(self, pat):
        return [(sel, dict(d)) for sel, d in css_rules() if re.search(pat, sel)]

    def test_toast_has_no_left_stripe_and_is_a_single_floating_surface(self):
        for sel, d in self.rules(r"\.toast"):
            self.assertFalse([k for k in d if k.startswith("border-left")], sel)
        base = dict(self.rules(r"^\.toast$")[0][1])
        self.assertEqual(base["border"], "1px solid var(--border)")
        self.assertEqual(base["border-radius"], "var(--radius-lg)")
        self.assertEqual(base["background"], "var(--popover)")
        self.assertIn("box-shadow", base)
        # 상태는 앞머리 아이콘 색으로 — 띠가 아니다
        for kind, icon in (("ok", "circle-check"), ("warn", "triangle-alert"), ("err", "circle-x")):
            self.assertIn("%s:()=>ic('%s')" % (kind, icon), ps.HTML)
        self.assertIn(".toast.warn>.ic{color:var(--warning)}", self.css)
        self.assertIn(".toast.err>.ic{color:var(--destructive)}", self.css)

    def test_toast_anchored_per_layout_near_the_action(self):
        box = dict(self.rules(r"^#toasts$")[0][1])
        self.assertEqual(box["right"], "var(--toast-r,var(--space-3))")
        self.assertEqual(box["bottom"], "var(--toast-b,var(--space-3))")
        self.assertNotIn("left", box)                                  # 예전: 왼쪽 아래 고정
        self.assertIn("body.lay-narrow #toasts{", self.css)
        self.assertIn("body.lay-mid #toasts{", self.css)
        self.assertNotRegex(self.css, r"body\.lay-mid #toasts\{[^}]*top:")   # 예전: 본문 왼쪽 위
        body = extract_js_fn("placeToasts")
        self.assertIn("'#c-actions'", body)                           # 저장·취소 버튼을 가리지 않는다
        self.assertIn("LAYOUT==='mid'?['#bar1']", body)               # 아래 도구 줄을 가리지 않는다
        self.assertIn("right.getBoundingClientRect().top", body)      # narrow: 시트 위
        self.assertIn("innerWidth-rr.right+12", body)                 # 패널 열 안 오른쪽
        for v in ("--toast-b", "--toast-r", "--toast-w"):
            self.assertIn("setProperty('%s'" % v, body)

    def test_toast_stacks_newest_on_top_and_collapses_after_three(self):
        body = extract_js_fn("toast")
        self.assertIn("box.insertBefore(t,box.firstChild)", body)
        self.assertIn("setTimeout(kill,6000)", body)
        self.assertIn("#toasts:not(:hover):not(:focus-within) .toast:nth-child(n+4){display:none}", self.css)
        self.assertIn("@keyframes toast-in", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce){*{animation:none!important", self.css)

    def test_toast_title_and_description_split(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")
        js = extract_js_fn("toastSplit") + "\nconsole.log(JSON.stringify(['핀 #3 저장됨 · pins.md 갱신','빌드 실패 — 화면은 이전 PDF입니다','복사함','핀 #10 · 본문 — 서준님이 불렀습니다: 봐 주세요'].map(toastSplit)));"
        self.assertEqual(json.loads(run_node(js)), [["핀 #3 저장됨", "pins.md 갱신"], ["빌드 실패", "화면은 이전 PDF입니다"], ["복사함", ""],
                                                          ["핀 #10 · 본문", "서준님이 불렀습니다: 봐 주세요"]])


# ---------------------------------------------------------------- 외곽선 안의 외곽선 없음(references/design.md §한 겹 담기)
# 저자 지적(2026-09-24): 테두리 상자 안에 또 테두리 상자를 그리는 방식이 촌스럽다. 담는 층은 하나 — 카드(가는 테두리 하나)
# 또는 떠 있는 면(대화상자·알림·@목록). 그 안의 배지·버튼·분절 컨트롤·스테퍼·원문·겹침 안내·스레드는 채움·간격·구분선으로만 가른다.
class FrontendNoNestedOutlines(unittest.TestCase):
    INNER = re.compile(r"^(?:\.badge|\.seg|\.step|pre\b|#c-overlap|\.thread|\.edit\b|\.arc-thread|\.arc-orig|\.arc-row|\.msg|\.reply-box)")
    SEPARATORS = {".thread": "border-top", ".arc-row+.arc-row": "border-top"}

    def test_inner_components_draw_no_outline_box(self):
        bad = []
        for sel, decls in css_rules():
            for part in [x.strip() for x in sel.split(",")]:
                if not self.INNER.match(part) or part.startswith(".dchip"):
                    continue
                for k, v in decls:
                    if k == "border" and v not in ("0", "none", "1px solid transparent"):
                        bad.append("%s { %s:%s }" % (part, k, v))
                    if re.fullmatch(r"border-(?:top|right|bottom|left)", k) and self.SEPARATORS.get(part) != k and v not in ("0", "none"):
                        bad.append("%s { %s:%s }" % (part, k, v))
                    if k == "border-color" and v != "transparent" and not part.startswith("button.badge"):
                        bad.append("%s { %s:%s }" % (part, k, v))
        self.assertEqual(bad, [])

    def test_card_buttons_are_filled_and_destructive_is_quiet(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn(".pin :is(.acts,.e-acts,.r-acts) button:not(.btn-soft):not(.btn-destructive):not(.btn-default){background:var(--secondary);"
                      "color:var(--secondary-foreground);border-color:transparent}", css)
        self.assertIn(".pin .acts button.btn-destructive{background:transparent}", css)
        self.assertIn(".seg button.on{background:var(--popover);border-color:transparent;", css)
        more = ps.HTML[ps.HTML.index('<div class="more-grid">'):]
        more = more[:more.index("</dialog>")]
        for tag in re.findall(r"<button[^>]*>", more):
            self.assertIn("btn-secondary", tag)                      # 대화상자 안 버튼도 테두리 없이 채운다

    def test_floating_surfaces_are_the_only_shadows_with_hairlines(self):
        for sel in ("dialog", "#mention-pop"):
            d = dict(dict(css_rules())[sel])
            self.assertEqual(d["border"], "1px solid var(--border)", sel)
            self.assertEqual(d["box-shadow"], "var(--shadow-lg)", sel)


# ---------------------------------------------------------------- 뜻·기능 점검(references/design.md §뜻과 모양) + UX QA(2026-09-24)
class FrontendSemanticAudit(unittest.TestCase):
    css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]

    def test_relative_time_with_absolute_on_hover(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")
        js = "\n".join(["const esc=t=>String(t==null?'':t);", extract_js_fn("relTime"), extract_js_fn("relSpan"), r"""
            const now=new Date(2026,8,24,15,0).getTime();
            console.log(JSON.stringify(['2026-09-24 15:00:10','2026-09-24 14:57:00','2026-09-24 11:00:00','2026-09-21 10:00:00','2026-09-01 10:00:00','x']
              .map(s=>relTime(s,now)).concat([relSpan('2026-09-01 10:00','arc-t','닫은 시각')])));"""])
        out = json.loads(run_node(js))
        self.assertEqual(out[:6], ["방금", "3분 전", "4시간 전", "3일 전", "9-1", "x"])
        self.assertIn('data-tip="닫은 시각 2026-09-01 10:00"', out[6])
        self.assertIn("setInterval(tickRel,60000);", ps.HTML)
        self.assertIn(".arc-t{flex:none;font-size:var(--text-xs);white-space:nowrap}", self.css)   # 예전: '09-24 1…'

    def test_one_toast_per_event_notify_wins(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")
        js = "\n".join(["const TOAST_KEYS=[];", extract_js_fn("toastDup"), r"""
            const el=()=>({isConnected:true,removed:false,remove(){this.removed=true;this.isConnected=false;}});
            const a=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:1,el:a,t:Date.now()});
            const r1=toastDup({keys:['review_requested:37'],rank:2});           // 알림 경로가 이긴다 — 옛 것을 걷고 띄운다
            const b=el(); TOAST_KEYS.push({keys:['review_requested:37'],rank:2,el:b,t:Date.now()});
            const r2=toastDup({keys:['review_requested:37'],rank:1});           // 뒤늦은 목록 비교 알림은 띄우지 않는다
            const r3=toastDup({keys:['reopened:37'],rank:1}), r4=toastDup(null);
            const r5=toastDup({keys:['review_requested:37'],rank:2});           // 같은 경로의 다음 사건(두 번째 검토 대기)은 막지 않는다
            console.log(JSON.stringify([r1,a.removed,r2,r3,r4,r5]));"""])
        self.assertEqual(json.loads(run_node(js)), [False, True, True, False, False, False])
        self.assertIn("{keys:[e.type+':'+e.pin],rank:2}", extract_js_fn("notifyShow"))
        self.assertIn("{keys:reviewed.map(i=>'review_requested:'+i)}", extract_js_fn("diffToast"))
        self.assertIn("{keys:['reopened:'+p.id]}", extract_js_fn("reviewToast"))

    def test_closed_cards_drop_position_badges_and_thread_count_opens_reply(self):
        body = extract_js_fn("card")
        self.assertIn("const rb=closedCard?null:relBadge(p.rel,p);", body)
        self.assertIn("const v=closedCard?null:viaTag(p);", body)
        self.assertIn('class="th-n" role="button" tabindex="0" data-act="reply-open"', body)

    def test_long_messages_clamp_and_identity_marks(self):
        self.assertIn(".msg-t.clamp{display:-webkit-box;-webkit-line-clamp:6;", self.css)
        self.assertIn("data-act=\"msg-more\"", extract_js_fn("msgBody"))
        self.assertIn("if(isAgent(a))return '<span class=\"av i agent\" aria-hidden=\"true\">'+ic('bot')+'</span>';", extract_js_fn("avatar"))
        self.assertIn("(나)", extract_js_fn("msgHtml"))
        self.assertIn("(나)", extract_js_fn("card"))

    def test_touch_targets_in_archive_rows(self):
        coarse = self.css[self.css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}")]
        self.assertIn("button.arc-orig-t{min-height:44px;min-width:44px;", coarse)
        self.assertIn(".arc-reply{min-height:44px;", coarse)
        self.assertIn(".th-n{min-height:44px;min-width:44px;", coarse)

    def test_review_count_labels_scope_and_filter_is_compact(self):
        self.assertIn("' (이 문서 '+here+')'", extract_js_fn("updateReviewCount"))
        body = extract_js_fn("drawPins")
        self.assertIn("mf.innerHTML=ic('at-sign')+MINE.length; mf.setAttribute('aria-label','나를 부른 핀 '+MINE.length);", body)

    def test_revision_note_wraps_and_returns_to_previous_doc(self):
        self.assertIn("#revision-pin button{flex:none;margin-left:auto}", self.css)
        self.assertIn("data-act=\"rev-back\"", extract_js_fn("revTargetNote"))
        self.assertIn("REV_BACK=DOC", extract_js_fn("showChange"))
        self.assertIn("case 'rev-back':", ps.HTML)

    def test_source_diff_wrap_toggle_defaults_on_touch(self):
        self.assertIn('id="revision-wrap" class="tg btn-sm" data-act="diff-wrap"', ps.HTML)
        self.assertIn("setDiffWrap(typeof v==='boolean'?v:MQ_COARSE.matches)", extract_js_fn("initDiffWrap"))
        self.assertIn("#revision-diff.wrap .rd-code{flex:1;min-width:0;white-space:pre-wrap", self.css)

    def test_navigation_text_is_dotted_and_pending_looks_pending(self):
        self.assertIn(".pin .n.go{text-decoration:underline dotted;", self.css)
        self.assertIn(".pin-ref{color:inherit;font-weight:600;cursor:pointer;text-decoration:underline dotted;", self.css)
        self.assertIn("button[data-pending]{cursor:progress;", self.css)


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
        self.assertIn("/^(button|link)$/.test(t.getAttribute('role')||'')&&t.dataset&&t.dataset.act", src)
        self.assertIn(".loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;min-height:44px}", src)
        # 회귀: #N 은 글자 폭만큼(26~35px)만 그려져 터치 44px 최소 히트 영역에 못 미쳤다(실측). 시각 크기는
        # 그대로 두고 고정 44×44 ::before 히트 영역을 가운데 얹는다 — inset 방식(부모 폭에 비례)이 아니라
        # 고정 width/height 라야 짧은 번호(예: 한 자리)에서도 44 를 보장한다. position:relative 는 .n.go 에만
        # 준다 — .loc·.pg-link 까지 주면 DOM 순서상 뒤에 오는 .loc 가 포지션드 스태킹에서 ::before 위로 올라와
        # 오른쪽 절반의 히트 테스트를 가로챘다(브라우저 실측으로 발견해 되돌린 회귀).
        css = src[src.index("<style>"):src.index("</style>")]
        self.assertIn(".pin .n.go{position:relative}", css)
        self.assertIn(".pin .n.go::before{content:'';position:absolute;left:50%;top:50%;"
                      "width:var(--control-h-touch);height:var(--control-h-touch);transform:translate(-50%,-50%)}", css)

    def test_view_action_still_routes_to_jumppin(self):
        self.assertIn("case 'view':jumpPin(id);break;", ps.HTML)

    def test_touch_media_query_wins_over_btn_icon_btn_sm_specificity(self):
        # 회귀: button.btn-icon.btn-sm{width:var(--control-h-sm)}(기본 규칙, 0-0-2-1) 이 터치 규칙
        # button.btn-icon{width:var(--control-h-touch)}(0-0-1-1) 보다 구체적이라 카드 접기(.b-fold)·토스트
        # 닫기 버튼이 터치에서도 24px 로 남았다(실측). 같은 specificity(.btn-icon.btn-sm) 로 @media(pointer:coarse)
        # 안에 다시 못박아야 이긴다.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        coarse = css[css.index("@media (pointer:coarse){"):]
        coarse = coarse[:coarse.index("\n}\n") + 3]
        self.assertIn("button.btn-icon.btn-sm{width:var(--control-h-touch);min-width:var(--control-h-touch);"
                      "height:var(--control-h-touch)}", coarse)
        # 실제 사용처: 카드 접기 버튼과 토스트 닫기 버튼 둘 다 .btn-icon.btn-sm 조합을 쓴다.
        self.assertIn('btn-icon btn-sm btn-ghost cmp b-fold', ps.HTML)
        self.assertIn("c.className='btn-icon btn-sm btn-ghost'", ps.HTML)

    def test_compact_bar1_buttons_keep_touch_min_width_despite_shrink_to_fit(self):
        # 회귀: body.compact #bar1 button{min-width:0}(id 포함이라 구체적) 이 터치 규칙 button{min-width:44px}
        # 보다 이겨서, lay-mid 처럼 좁은 화면에서 [선택] 버튼이 40px 까지 줄었다(실측). 같은 selector 를
        # @media(pointer:coarse) 안에서 다시 못박아 44px 바닥을 지킨다.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact #bar1 button{flex:1 1 auto;min-width:0;", css)
        self.assertIn("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}", css)
        # 이 오버라이드는 위 min-width:0 규칙보다 소스상 뒤에 있어야 동률 specificity 에서 이긴다.
        self.assertGreater(css.index("@media (pointer:coarse){body.compact #bar1 button{min-width:44px}}"),
                            css.index("body.compact #bar1 button{flex:1 1 auto;min-width:0;"))


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
        self.assertIn('id="paper-identity-mark" aria-hidden="true">A</span><span>A-DEMO</span>', out)
        self.assertNotIn('id="brand-chip"', out)
        self.assertIn('id="brand-stripe" style="background:#1d4ed8"', out)
        self.assertNotIn("__LABEL__", out)
        self.assertNotIn("__LABEL_INITIAL__", out)
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

    def test_identity_crumb_precedes_desktop_doc_links_and_not_right_toolbar(self):
        self.assertLess(ps.HTML.index('id="paper-identity"'), ps.HTML.index('id="doc-links"'))
        self.assertLess(ps.HTML.index('id="paper-identity"'), ps.HTML.index('id="right"'))
        self.assertNotIn('id="brand-chip"', ps.HTML)

    def test_identity_crumb_does_not_take_mobile_space(self):
        self.assertIn('body.lay-narrow #paper-identity{display:none}', ps.HTML)
        self.assertIn('body:not(.lay-narrow) #doc-nav{display:flex}', ps.HTML)

    def test_document_title_prefixes_label(self):
        # 여러 문서면 메인 파일 이름 대신 문서 이름(META.doc_name)을 쓴다 — 이름표 접두는 그대로다.
        self.assertIn(
            "if(META)document.title=(META.label?META.label+' · ':'')+'원고 핀 · '+(multiDoc()?META.doc_name||META.main:META.main)"
            "+' · 열린 '+PINS.length;",
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


# ---------------------------------------------------------------- §여러 문서(--doc) — 한 뷰어 안에서 문서 전환

# pdftoppm·pdftotext 가 읽는 가장 작은 PDF(한 쪽, 글자 한 줄). xref 는 poppler 가 스스로 다시 세운다.
MINI_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R"
            b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
            b"4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 150 Td (Reviewer one) Tj ET\nendstream endobj\n"
            b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def jreq(method, path, obj=None, headers=None):
    body = json.dumps(obj).encode() if obj is not None else b""
    h = {"Content-Type": "application/json"} if obj is not None else {}
    h.update(headers or {})
    return req(method, path, body, h)


class DocArgs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ms = Path(self.tmp.name) / "repo"
        (self.ms / "manuscript" / "2nd").mkdir(parents=True)
        (self.ms / "manuscript" / "2nd" / "m.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "sub" / "rr").mkdir(parents=True)
        (self.ms / "sub" / "rr" / "rr.tex").write_text(TEX, encoding="utf-8")
        (self.ms / "sub" / "review.pdf").write_bytes(MINI_PDF)
        (self.ms / "notes.txt").write_text("x")
        (Path(self.tmp.name) / "outside.tex").write_text(TEX)

    def tearDown(self):
        self.tmp.cleanup()

    def test_simple_tex_uses_its_folder_as_build_root(self):
        d = ps.parse_doc_arg("rr=답변서:sub/rr/rr.tex", self.ms)
        self.assertEqual((d["key"], d["name"], d["kind"]), ("rr", "답변서", "tex"))
        self.assertEqual(d["src"], (self.ms / "sub" / "rr").resolve())
        self.assertEqual(d["main"], (self.ms / "sub" / "rr" / "rr.tex").resolve())

    def test_extended_form_sets_build_root_separately(self):
        d = ps.parse_doc_arg("ms=본문:manuscript::2nd/m.tex", self.ms)
        self.assertEqual(d["src"], (self.ms / "manuscript").resolve())
        self.assertEqual(d["main"], (self.ms / "manuscript" / "2nd" / "m.tex").resolve())
        doc = ps.make_docs(["ms=본문:manuscript::2nd/m.tex"], self.ms)[0]
        self.assertEqual(doc.main_rel, Path("2nd/m.tex"))
        ps.C.state = Path(self.tmp.name) / "st"
        self.assertEqual(doc.out, ps.C.state / "docs" / "ms" / "build" / "2nd")   # latexmk 는 메인이 있는 폴더에서

    def test_pdf_is_view_only(self):
        d = ps.parse_doc_arg("rv=리뷰어 코멘트:sub/review.pdf", self.ms)
        self.assertEqual(d["kind"], "pdf")
        self.assertEqual(d["name"], "리뷰어 코멘트")                  # 이름 안의 공백은 그대로

    def test_absolute_path_inside_manuscript_is_accepted(self):
        d = ps.parse_doc_arg("rr=답변서:%s" % (self.ms / "sub" / "rr" / "rr.tex"), self.ms)
        self.assertEqual(d["kind"], "tex")

    def test_rejects_bad_specs(self):
        bad = ["rr답변서:sub/rr/rr.tex",               # '=' 없음
               "RR=답변서:sub/rr/rr.tex",              # 대문자 키
               "a" * 25 + "=x:sub/rr/rr.tex",          # 키 25자
               "rr=답변서",                            # ':' 없음
               "rr=:sub/rr/rr.tex",                    # 이름 빔
               "rr=" + "가" * 41 + ":sub/rr/rr.tex",   # 이름 41자
               "rr=답변서:",                           # 경로 빔
               "rr=답변서:../outside.tex",             # --manuscript 밖
               "rr=답변서:sub/rr/none.tex",            # 없는 파일
               "rr=답변서:notes.txt",                  # 확장자
               "rv=코멘트:sub::review.pdf",            # '::' 는 LaTeX 전용
               "ms=본문:manuscript::../outside.tex",   # 메인이 빌드 루트 밖
               "ms=본문:manuscript::2nd/m.tex::x",     # '::' 두 번
               "ms=본문:nope::2nd/m.tex"]              # 빌드 루트 없음
        for spec in bad:
            with self.assertRaises(ValueError, msg=spec):
                ps.parse_doc_arg(spec, self.ms)

    def test_make_docs_rejects_duplicate_keys_and_marks_main_root(self):
        with self.assertRaises(ValueError):
            ps.make_docs(["rr=a:sub/rr/rr.tex", "rr=b:sub/rr/rr.tex"], self.ms)
        docs = ps.make_docs(["main=본문:manuscript/2nd/m.tex", "rr=답변서:sub/rr/rr.tex", "rv=코멘트:sub/review.pdf"], self.ms)
        self.assertEqual([d.root for d in docs], [True, False, False])    # 키 main 인 LaTeX 문서만 상태 폴더 루트 배치
        self.assertEqual([d.kind for d in docs], ["tex", "tex", "pdf"])
        with self.assertRaises(ValueError):
            ps.make_docs(["d%d=x:sub/rr/rr.tex" % i for i in range(ps.DOCS_MAX + 1)], self.ms)


class MultiDoc(Base):
    """ms(본문, 키 main 아님)·rr(답변서, 다른 폴더)·rv(보기 전용 PDF) 세 문서."""

    def setUp(self):
        super().setUp()
        (self.src / "rr").mkdir()
        self.rr = self.src / "rr" / "rr.tex"
        self.rr.write_text(TEX, encoding="utf-8")
        self.pdf = self.src / "review.pdf"
        self.pdf.write_bytes(MINI_PDF)
        self.docs = ps.make_docs(["ms=본문:main.tex", "rr=답변서:rr/rr.tex", "rv=리뷰어 코멘트:review.pdf"], self.src)
        ps.set_docs(self.docs)
        self.ms, self.rrd, self.rv = self.docs

    def tearDown(self):
        ps.set_docs(None)
        super().tearDown()

    def fake_pages(self, D, name="pages-20260101000000", n=1):
        """빌드 없이 쪽 디렉토리 하나를 그 문서에 둔다(1x1 PNG 헤더 + PDF 사본)."""
        d = D.dir / name
        d.mkdir(parents=True, exist_ok=True)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (417).to_bytes(4, "big") + (417).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
        for i in range(1, n + 1):
            (d / ("page-%d.png" % i)).write_bytes(png)
        (d / D.pdf_name).write_bytes(MINI_PDF)
        ps.atomic_write(D.dir / "pages.cur", name)
        return d

    def test_state_layout_per_doc(self):
        self.assertEqual(self.ms.dir, ps.C.state / "docs" / "ms")
        self.assertEqual(self.rv.dir, ps.C.state / "docs" / "rv")
        with ps.using_doc(self.rrd):
            self.assertEqual(ps.cur_pages(), ps.C.state / "docs" / "rr" / "pages")
        self.assertEqual(ps.C.pins_jsonl, ps.C.state / "pins.jsonl")          # 핀 저장소는 하나

    def test_single_doc_mode_keeps_legacy_paths(self):
        ps.set_docs(None)
        self.assertFalse(ps.multi_doc())
        self.assertIs(ps.cur_doc(), ps.LEGACY_DOC)
        self.assertEqual(ps.cur_pages(), ps.C.state / "pages")
        self.assertEqual(ps.LEGACY_DOC.build, ps.C.build)
        self.assertIs(ps.LEGACY_DOC.lock, ps.BUILD_LOCK)                        # 옛 전역 잠금·상태가 곧 이 문서의 것
        self.assertIs(ps.LEGACY_DOC.bstate, ps.BUILD_STATE)
        pid = self.add()
        self.assertEqual(self.pin(pid)["doc"], "main")
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertNotIn("## ", md)                                             # 소절 없이 예전 모양
        self.assertIn("| # | 쪽 | 위치 | 범위 | 메모 |", md)

    def test_old_pin_without_doc_reads_as_first_doc_without_rewrite(self):
        rec = {"id": 1, "file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "옛 핀", "at": "2026-09-01 10:00:00"}
        ps.C.pins_jsonl.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = ps.pins_payload(ps.read_pins()[0], True)
        self.assertEqual(rows[0]["doc"], "ms")                                  # 첫 문서
        self.assertNotIn('"doc"', ps.C.pins_jsonl.read_text(encoding="utf-8"))  # 이관 쓰기 없음
        self.assertEqual(ps.docs_payload()["docs"][0]["n_open"], 1)

    def test_api_docs_lists_kind_and_counts(self):
        ps.add_pin({"file": str(self.rr), "lo": 4, "hi": 5, "page": 1, "doc": "rr"}, dict(ps.LOCAL_ACTOR))
        with ps.using_doc(self.rrd):
            ps.add_pin({"file": str(self.rr), "lo": 8, "hi": 8, "page": 1}, dict(ps.LOCAL_ACTOR))
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
        code, _, _ = split_resp(self.talk(req("GET", "/pages/page-2.png?doc=ms")))   # ms 에는 쪽이 없다
        self.assertEqual(code, 404)
        code, hdrs, _ = split_resp(self.talk(req("GET", "/pdf?doc=rr")))
        self.assertEqual((code, hdrs["content-type"]), (200, "application/pdf"))
        code, _, body = split_resp(self.talk(req("GET", "/api/meta?doc=nope")))
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["docs"], ["ms", "rr", "rv"])

    def test_pin_doc_is_inferred_from_file_and_body_query_must_agree(self):
        code, _, body = split_resp(self.talk(jreq("POST", "/api/pin", {"file": "rr/rr.tex", "lo": 4, "hi": 5})))
        self.assertEqual(code, 200)
        self.assertEqual(self.pin(json.loads(body)["id"])["doc"], "rr")     # 에이전트 curl — file 로 짐작
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin?doc=ms", {"file": "main.tex", "lo": 4, "hi": 5, "doc": "rr"})))
        self.assertEqual(code, 400)
        code, _, body = split_resp(self.talk(jreq("GET", "/api/pins?doc=rr")))
        self.assertEqual([p["doc"] for p in json.loads(body)], ["rr"])

    def test_view_only_pick_returns_region_without_synctex(self):
        self.fake_pages(self.rv)
        with mock.patch.object(ps, "region_text", return_value="Reviewer   one\n comment"), \
                mock.patch.object(ps, "by_synctex", side_effect=AssertionError("SyncTeX 를 부르면 안 된다")):
            code, _, body = split_resp(self.talk(jreq("POST", "/api/pick", {"doc": "rv", "page": 1, "x0": 10, "y0": 20,
                                                                            "x1": 110, "y1": 60})))
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual((d["kind"], d["view_only"], d["page"], d["quote"], d["pdf"]),
                         ("region", True, 1, "Reviewer one comment", "review.pdf"))
        self.assertNotIn("lo", d)
        self.assertEqual(len(d["frac"]), 4)                                     # frac 없이 와도 좌표로 만든다

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
        # LaTeX 문서의 검증은 그대로 — lo/hi 없는 핀은 400
        code, _, _ = split_resp(self.talk(jreq("POST", "/api/pin", {"doc": "rr", "file": "rr/rr.tex", "page": 1})))
        self.assertEqual(code, 400)
        ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "doc": "ms"}, dict(ps.LOCAL_ACTOR))
        md = ps.pins_md_text(ps.snapshot_pins())
        self.assertIn("## 본문 · `ms` · `main.tex`", md)
        self.assertIn("## 리뷰어 코멘트 · `rv` · `review.pdf` — 보기 전용 PDF(줄 번호 없음)", md)
        self.assertIn("| %d | 2 | 쪽 2, 영역 가로 10–60%% 세로 20–30%% | 영역 | «Reviewer one» R1 코멘트 답변 |" % pid, md)
        self.assertIn("문서: 본문(`ms`) 1건 · 답변서(`rr`) 0건 · 리뷰어 코멘트(`rv`, 보기 전용) 1건", md)
        self.assertNotIn("## 답변서", md)                                        # 열린 핀 없는 문서는 소절을 안 만든다
        self.assertIn("보기 전용 PDF 의 핀은 줄 번호가 없다", md)
        for line in md.splitlines():
            if line.startswith("| ") and not line.startswith("|---"):
                self.assertEqual(line.count(" | ") + 2, 6, line)               # 5열 그대로

    def test_view_only_pin_edit_note_and_region_only(self):
        self.fake_pages(self.rv)
        with ps.using_doc(self.rv):
            pid = ps.add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2], "note": "a"}, dict(ps.LOCAL_ACTOR))
        rev = self.pin(pid)["rev"]
        with self.assertRaises(ps.HTTPError) as cm:
            ps.edit_pin(pid, {"lo": 2, "hi": 3, "base_rev": rev}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(cm.exception.code, 400)
        p = ps.edit_pin(pid, {"note": "b", "base_rev": rev}, dict(ps.LOCAL_ACTOR))   # 요청에 doc 이 없어도 핀의 문서로
        self.assertEqual(p["note"], "b")
        p = ps.edit_pin(pid, {"loc": {"page": 1, "frac": [0.3, 0.3, 0.2, 0.2], "quote": "new"}, "base_rev": p["rev"]},
                        dict(ps.LOCAL_ACTOR))
        self.assertEqual((p["frac"][0], p["quote"], p["pdf_build"]), (0.3, "new", "pages-20260101000000"))
        self.assertTrue(ps.valid_rec(self.pin(pid)))
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))                            # 닫기·drop 은 문서와 무관하게 id 로
        self.assertTrue(self.pin(pid)["done"])

    def test_region_record_validation_is_by_shape(self):
        base = {"id": 1, "pdf": str(self.pdf), "page": 1, "frac": [0, 0, 0.5, 0.5], "kind": "region", "doc": "gone"}
        self.assertTrue(ps.valid_rec(base))                                     # 설정에서 뺀 문서여도 깨진 줄이 아니다
        self.assertFalse(ps.valid_rec(dict(base, lo=1, hi=2)))
        self.assertFalse(ps.valid_rec(dict(base, frac=None)))
        self.assertFalse(ps.valid_rec(dict(base, pdf="review.pdf")))            # 상대 경로
        self.assertFalse(ps.valid_rec(dict(base, doc="Bad Key")))
        # 설정에 없는 문서의 핀은 pins.md 에 따로 드러난다(숨지 않는다)
        ps.C.pins_jsonl.write_text(json.dumps(base) + "\n")
        md = ps.pins_md_text(ps.read_pins()[0])
        self.assertIn("## 설정에 없는 문서 · `gone`", md)

    def test_sync_and_overlaps_skip_region_pins(self):
        self.fake_pages(self.rv)
        with ps.using_doc(self.rv):
            rid = ps.add_pin({"page": 1, "frac": [0.1, 0.1, 0.2, 0.2]}, dict(ps.LOCAL_ACTOR))
        tid = self.add(4, 5)
        self.main.write_text("\n" + TEX, encoding="utf-8")                     # 줄이 밀린다
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

        def slow_build():
            gate.wait(5)
            return {"ok": False, "state": "fail", "errors": [], "log": "x", "elapsed_s": 0.0}
        with mock.patch.object(ps, "_build", side_effect=slow_build):
            with ps.using_doc(self.ms):
                self.assertEqual(ps.build_async(), {"state": "running"})
                self.assertTrue(ps.build_async().get("busy"))                  # 같은 문서는 한 번에 하나
                self.assertTrue(ps.build_all().get("busy"))
            with ps.using_doc(self.rrd):
                self.assertEqual(ps.build_async(), {"state": "running"})       # 다른 문서는 동시에
            self.assertTrue(self.ms.lock.locked() and self.rrd.lock.locked())
            self.assertFalse(ps.BUILD_LOCK.locked())                           # 단일 문서의 전역 잠금은 안 건드린다
            gate.set()
            for _ in range(100):
                if not (self.ms.lock.locked() or self.rrd.lock.locked()):
                    break
                time.sleep(0.05)
        self.assertFalse(self.ms.lock.locked() or self.rrd.lock.locked())
        with ps.using_doc(self.ms):
            self.assertEqual(ps.build_state_snapshot()["state"], "fail")
        with ps.using_doc(self.rv):
            self.assertEqual(ps.build_state_snapshot()["state"], "idle")      # 빌드 상태도 문서마다

    def test_git_pull_is_shared_across_docs(self):
        calls = []
        with mock.patch.object(ps, "git_pull_phase", side_effect=lambda m: calls.append(m) or {"state": "up_to_date"}):
            ps._PULL_LAST.update(at=0.0, res=None)
            a = ps.repo_pull()
            b = ps.repo_pull()
        self.assertEqual(len(calls), 1)                                         # 저장소 단위로 한 번
        self.assertNotIn("shared", a)
        self.assertTrue(b["shared"])
        ps.set_docs(None)
        with mock.patch.object(ps, "git_pull_phase", side_effect=lambda m: calls.append(m) or {"state": "ok"}):
            ps.repo_pull(), ps.repo_pull()
        self.assertEqual(len(calls), 3)                                         # 단일 문서는 빌드마다(예전 그대로)

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm 이 없다")
    def test_view_only_pdf_renders_and_rerenders_on_change(self):
        with ps.using_doc(self.rv):
            self.assertTrue(ps.pdf_changed(self.rv))                           # 아직 안 그렸다
            res = ps._build_tracked()
            self.assertEqual(res["state"], "ok", res.get("log"))
            first = ps.cur_pages().name
            self.assertTrue((ps.cur_pages() / "review.pdf").is_file())
            self.assertFalse(ps.pdf_changed(self.rv))
            self.assertFalse(ps.refresh_pdf_doc(self.rv))                      # 그대로면 다시 그리지 않는다
            self.pdf.write_bytes(MINI_PDF.replace(b"Reviewer one", b"Reviewer two"))
            os.utime(self.pdf, (time.time() + 3, time.time() + 3))
            self.assertTrue(ps.pdf_changed(self.rv))
            time.sleep(1.1)                                                    # 쪽 디렉토리 이름은 초 단위
            res = ps._build_tracked()
            self.assertEqual(res["state"], "ok")
            self.assertNotEqual(ps.cur_pages().name, first)
            self.assertEqual(ps.build_state_snapshot()["seq"], 2)
            b = ps.load_builds()["by"]
            self.assertNotEqual(b[first]["src_hash"], b[ps.cur_pages().name]["src_hash"])   # 위치 추정의 원천


class FrontendDocs(unittest.TestCase):
    """데스크톱 문서 선택과 모바일 문서 메뉴를 구분한다."""

    def test_document_selector_and_mobile_button(self):
        css = ps.HTML
        self.assertIn("#doc-select-wrap{display:none;", css)
        self.assertIn("#doc-links{display:none;", css)
        self.assertIn("body.docs-multi:not(.lay-narrow) #doc-links{display:flex}", css)
        self.assertIn("body:not(.lay-narrow) #doc-nav{display:flex}", css)
        self.assertIn("#btn-doc{display:none;", css)
        self.assertIn("body.lay-narrow.docs-multi #btn-doc{display:inline-flex}", css)
        self.assertIn("body.view-only #btn-rebuild{display:none}", css)
        self.assertIn('id="all-docs"', css)
        self.assertIn("$('#all-docs').hidden=!multiDoc()", ps.HTML)
        self.assertIn("document.body.classList.toggle('docs-multi',multiDoc())", ps.HTML)

    def test_selector_views_and_outline_are_in_pdf_area(self):
        self.assertIn('<select id="doc-select" aria-label="문서 선택">', ps.HTML)
        self.assertIn('<div id="doc-links" role="group" aria-label="문서 선택">', ps.HTML)
        self.assertIn('id="view-manuscript" data-act="view-mode"', ps.HTML)
        self.assertIn('id="view-revisions" data-act="view-mode"', ps.HTML)
        self.assertIn('<nav id="outline" aria-label="원고 목차">', ps.HTML)
        self.assertIn('body.outline-collapsed #outline{display:none}', ps.HTML)
        self.assertIn('id="nav-toc-toggle" data-act="outline"', ps.HTML)
        self.assertLess(ps.HTML.index('id="doc-nav"'), ps.HTML.index('id="right"'))
        body = extract_js_fn("drawDocTabs")
        self.assertIn("box.value=DOC", body)
        self.assertIn("DOCS.map", body)
        self.assertIn('aria-current="', body)

    def test_default_theme_is_light(self):
        self.assertIn('<html lang="ko" data-theme="light">', ps.HTML)
        self.assertIn("p={theme:'light'}", ps.HTML)
        self.assertIn("prefs().theme||'light'", ps.HTML)

    def test_outline_labels_only_attach_to_matching_pdf_entries(self):
        js = "\n".join([extract_js_fn("mergeOutlineLabels"), r"""
            const entries=[
              {title:'Experimental design',page:9,depth:0},
              {title:'Questions and comparisons',page:10,depth:1},
              {title:'Repeated',page:11,depth:1},
              {title:'Repeated',page:12,depth:1}];
            const labels=[
              {number:'4',title:'Experimental design',page:'9'},
              {number:'4.2',title:'Questions and comparisons',page:'11'},
              {number:'4.3',title:'Repeated',page:'11'},
              {number:'4.4',title:'Repeated',page:'13'}];
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>[x.number,x.pageLabel])));"""])
        self.assertEqual(json.loads(run_node(js)),
                         [["4", "9"], ["", ""], ["4.3", "11"], ["", ""]])

    def test_outline_labels_require_matching_section_depth_when_supported(self):
        js = "\n".join([extract_js_fn("mergeOutlineLabels"), r"""
            const entries=[{title:'Overview',page:1,depth:0},{title:'Overview',page:1,depth:1}];
            const labels=[{number:'0.9',title:'Overview',page:'1',level:'subsection'},
                          {number:'1',title:'Overview',page:'1',level:'section'},
                          {number:'1.1',title:'Overview',page:'1',level:'subsection'}];
            console.log(JSON.stringify(mergeOutlineLabels(entries,labels).map(x=>x.number)));"""])
        self.assertEqual(json.loads(run_node(js)), ["1", "1.1"])

    def test_revision_async_result_is_ignored_after_doc_commit_or_view_change(self):
        js = "\n".join(["let REVISION_SEQ=8,DOC='ms',REVISION_COMMIT='abc';",
                        "const document={body:{classList:{contains:x=>x==='revision-open'}}};",
                        extract_js_fn("revisionCurrent"), r"""
            console.log(JSON.stringify([
              revisionCurrent(8,'ms','abc'),revisionCurrent(7,'ms','abc'),
              revisionCurrent(8,'hl','abc'),revisionCurrent(8,'ms','def')]));"""])
        self.assertEqual(json.loads(run_node(js)), [True, False, False, False])

    def test_pin_actions_restore_pdf_from_revision_view(self):
        self.assertIn("setViewMode('manuscript')", extract_js_fn("jumpPin"))
        self.assertIn("jumpPin(id)", extract_js_fn("openEdit"))

    def test_revision_diff_rows_have_line_semantics_and_escape_source(self):
        patch = ("diff --git a/ms/main.tex b/ms/main.tex\n"
                 "index 123..456 100644\n--- a/ms/main.tex\n+++ b/ms/main.tex\n"
                 "@@ -3,2 +3,2 @@ heading\n-old <script>alert(1)</script>\n"
                 "+new <img src=x onerror=alert(1)>\n context\n")
        esc = re.search(r"^const esc=.*;$", ps.HTML, re.M).group(0)
        js = "\n".join([esc, extract_js_fn("renderRevisionDiff"),
                        "console.log(JSON.stringify(renderRevisionDiff(%s)));" % json.dumps(patch)])
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        rendered = json.loads(out)
        self.assertRegex(rendered, r'rd-hunk[^>]*>.*?@@ -3,2 \+3,2 @@')
        self.assertRegex(rendered, r'rd-del[^>]*>.*?rd-no[^>]*>3</span>')
        self.assertRegex(rendered, r'rd-add[^>]*>.*?rd-no[^>]*>3</span>')
        self.assertRegex(rendered, r'rd-context[^>]*>.*?rd-no[^>]*>4</span>')
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img ', rendered)
        self.assertIn('rd-meta', rendered)

    def test_revision_file_selection_renders_only_selected_patch(self):
        esc = re.search(r"^const esc=.*;$", ps.HTML, re.M).group(0)
        js = "\n".join([esc, extract_js_fn("renderRevisionDiff"), extract_js_fn("renderRevisionFile"), r"""
            let REVISION_WHOLE='+from first\n+from second', REVISION_FILES=[
              {text:'+from first'}, {text:'+from second'}];
            const nodes={'#revision-file':{value:'1'},'#revision-diff':{innerHTML:''}};
            function $(selector){return nodes[selector];}
            renderRevisionFile(); console.log(JSON.stringify(nodes['#revision-diff'].innerHTML));"""])
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        rendered = json.loads(out)
        self.assertIn('from second', rendered)
        self.assertNotIn('from first', rendered)
        self.assertIn('rd-add', rendered)

    def test_hash_dq_and_initial_doc(self):
        js = "\n".join([r"""
            const DOCS=[{key:'ms'},{key:'rr'},{key:'rv'}]; let DOC='ms'; let _prefs={}; function prefs(){return _prefs;}
            const location={hash:''};
            """, extract_js_fn("docInfo"), extract_js_fn("dq"), extract_js_fn("hashDoc"), extract_js_fn("initialDoc"), r"""
            const out=[];
            out.push(dq('/api/meta'), dq('/api/meta?light=1'), dq('/pdf?build=x','rr'));
            location.hash='#doc=rr'; out.push(initialDoc());
            location.hash='#doc=Nope'; _prefs={lastDoc:'rv'}; out.push(initialDoc());       // 해시가 틀리면 마지막 문서
            location.hash='#doc=zz'; _prefs={lastDoc:'gone'}; out.push(initialDoc());      // 둘 다 없으면 첫 문서
            location.hash='#x=1&doc=rv'; _prefs={}; out.push(hashDoc());
            console.log(JSON.stringify(out));
            """])
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        self.assertEqual(json.loads(out), ["/api/meta?doc=ms", "/api/meta?light=1&doc=ms", "/pdf?build=x&doc=rr",
                                           "rr", "rv", "ms", "rv"])

    def test_switch_shortcuts_skip_input_fields(self):
        m = re.search(r"document\.addEventListener\('keydown',e=>\{(.*?)\n\}\);", ps.HTML, re.S)
        body = m.group(1)
        i = body.index("if(multiDoc()&&!inField){")
        self.assertIn("e.key==='PageUp'||e.key==='PageDown'", body[i:])
        self.assertIn("/^Digit[1-9]$/.test(e.code||'')", body[i:])
        self.assertLess(body.index("const t=e.target,inField="), i)

    def test_view_memory_and_pdfjs_cache_are_bounded(self):
        self.assertIn("const VEC_CACHE_MAX=3;", ps.HTML)
        put = extract_js_fn("vecCachePut")
        self.assertIn("while(c.size>VEC_CACHE_MAX)", put)
        self.assertIn("vecClose(d)", put)
        sw = extract_js_fn("switchDoc")
        self.assertIn("saveView();", sw)
        self.assertIn("setHash(k)", sw)
        self.assertIn("savePrefs({lastDoc:k})", sw)
        show = extract_js_fn("showDoc")
        self.assertIn("restoreView(v)", show)
        self.assertIn("vecOpen()", show)

    def test_cross_doc_card_actions_switch_first(self):
        self.assertIn("function jumpPin(id){if(viaDoc(id,jumpPin))return;", ps.HTML)
        self.assertIn("function openEdit(id){if(viaDoc(id,openEdit))return;", ps.HTML)
        js = "\n".join([r"""
            const OPEN_ALL=[{id:1,doc:'ms'},{id:2,doc:'rr'},{id:3}]; let DOC='ms'; const DEFAULT_DOC='ms';
            const DOCS=[{key:'ms'},{key:'rr'}]; const seen=[];
            function switchDoc(k){seen.push('switch:'+k); DOC=k; return Promise.resolve();}
            """, extract_js_fn("docInfo"), extract_js_fn("pdoc"), extract_js_fn("viaDoc"), r"""
            (async()=>{const out=[viaDoc(1,()=>{}), viaDoc(3,()=>{}), viaDoc(2,id=>seen.push('then:'+id))];
              await Promise.resolve(); await Promise.resolve(); out.push(seen); console.log(JSON.stringify(out));})();
            """])
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        self.assertEqual(json.loads(out), [False, False, True, ["switch:rr", "then:2"]])

    def test_region_selection_saves_page_and_frac_only(self):
        body = extract_js_fn("savePin")
        self.assertIn("if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};", body)
        self.assertIn("body.doc=d.doc||DOC||undefined;", body)
        self.assertIn("if(!o||!o.file)return out;", extract_js_fn("overlapsFor"))
        self.assertIn("#composer.region #c-levels", ps.HTML)


# ---------------------------------------------------------------- 아이콘: Lucide 만, 이모지·기호 글자 없음
# 이모지·기본 문자 아이콘(⏳ ▾ ☾ ✎ 등)은 기기·글꼴마다 모양이 달라 보기 흉했다(저자 지적 2026-09-23). 아이콘은
# Lucide(vendor/lucide/README.md)의 SVG 요소만 인라인으로 쓴다. 산문 속 화살표(→)와 키 이름(⌘)은 글자로 남긴다.
ICON_GLYPHS = re.compile("[⏳⌛▲-◃◐-◓☀☼☾✓✔✎✏⚠"
                         "⧉⋯＋×↵⊂∩★☆●○"
                         "\U0001F000-\U0001FFFF✀-➿️]")


def html_without_comments(h: str) -> str:
    h = re.sub(r"/\*.*?\*/", "", h, flags=re.S)
    return "\n".join(l for l in h.split("\n") if not l.strip().startswith("//"))


class FrontendIcons(unittest.TestCase):
    VENDOR = SKILL / "vendor" / "lucide"

    def test_vendor_license_and_readme_record_version_and_icons(self):
        lic = (self.VENDOR / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("ISC License", lic)
        self.assertIn("Lucide Icons and Contributors", lic)
        readme = (self.VENDOR / "README.md").read_text(encoding="utf-8")
        self.assertIn("lucide-static@%s" % ps.LUCIDE_VERSION, readme)
        table = readme[readme.index("## 쓰는 아이콘"):readme.index("## 갱신")]
        names = set()
        for row in re.findall(r"^\| (`[^|]+) \|", table, flags=re.M):
            names |= set(re.findall(r"`([a-z0-9-]+)`", row))
        self.assertEqual(names, set(ps.LUCIDE))

    def test_icon_markup_is_plain_svg_elements(self):
        for name, body in ps.LUCIDE.items():
            els = re.findall(r"<[^>]+>", body)
            self.assertTrue(els, name)
            for el in els:
                self.assertRegex(el, r'^<(path|circle|rect|line|polyline|polygon|ellipse)( [a-z-]+="[^"<>]*")+/>$', name)
        svg = ps.icon_svg("check")
        for attr in ('viewBox="0 0 24 24"', 'fill="none"', 'stroke="currentColor"', 'stroke-width="2"', 'aria-hidden="true"'):
            self.assertIn(attr, svg)

    def test_every_used_icon_exists_and_every_icon_is_used(self):
        h = ps.HTML
        self.assertNotIn("{{ic:", h)
        self.assertNotIn("__LUCIDE_JSON__", h)
        used = set(re.findall(r"ic\('([a-z0-9-]+)'\)", h)) | set(re.findall(r'class="ic ic-([a-z0-9-]+)"', h))
        used |= set(re.findall(r"'(chevron-(?:up|down|left|right))'", h))
        used |= set(re.findall(r"THEME_ICON=\{system:'([a-z-]+)',light:'([a-z-]+)',dark:'([a-z-]+)'\}", h)[0])
        self.assertEqual(used - set(ps.LUCIDE), set())
        self.assertEqual(set(ps.LUCIDE) - used, set())

    def test_no_emoji_or_symbol_glyph_icons_in_viewer(self):
        found = sorted(set(ICON_GLYPHS.findall(html_without_comments(ps.HTML))))
        self.assertEqual(found, [])

    def test_js_ic_matches_server_icon_svg(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")
        js = js_icons() + "\nconsole.log(JSON.stringify(['check','clock','x'].map(ic).concat([ic('nope')])));"
        self.assertEqual(json.loads(run_node(js)), [ps.icon_svg("check"), ps.icon_svg("clock"), ps.icon_svg("x"), ""])

    def test_toolbar_icon_buttons_keep_accessible_names(self):
        for bid, label in (("btn-zoom-out", "축소"), ("btn-zoom-in", "확대"), ("btn-help", "도움말"), ("btn-more", "더보기"),
                           ("c-copy", "위치 복사")):
            tag = re.search(r'<button[^>]*id="%s"[^>]*>' % bid, ps.HTML).group(0)
            self.assertIn('aria-label="%s"' % label, tag)
        self.assertIn("b.innerHTML=ic(THEME_ICON[t]);", ps.HTML)


# ---------------------------------------------------------------- 상태 띠·보관함(닫힌·삭제한 핀)
# 닫힌·삭제한 핀을 펼치면 열린 카드와 모양이 같아 경계가 모호했다(저자 지적 2026-09-23). 열린 목록 뒤에 폭 전체를 쓰는
# sticky 구획 머리('완료 N ─── 펼치기')를 두고, 그 아래는 카드가 아니라 흐린 납작한 행이다. 상태는 카드 왼쪽 띠 색으로 가른다.
class FrontendArchive(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def run_rows(self, script: str):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={loc:'l',reopen:'r',restore:'s',n:'n'}; let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main';
            function docInfo(){return null;} function authorTip(){return 'tip';} function who(a){return a?a.name:'';}
            """, js_icons(), extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locCopy"), extract_js_fn("docChip"),
            "const ARC_OPEN=new Set(); let LAYOUT='wide', REPLY=null, META=null; const THREAD_OPEN=new Set(); function avatar(){return '';}",
            extract_js_fn("arcTime"), extract_js_fn("arcLoc"), extract_js_fn("arcLine"), js_thread(),
            extract_js_fn("arcHead"), extract_js_fn("doneCard"), extract_js_fn("droppedCard"), script])
        return json.loads(run_node(js))

    def test_done_row_is_flat_with_reply_line_and_hidden_original_request(self):
        out = self.run_rows(r"""
            const p={id:7,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'제목을 <b>바꿈</b>',close_ref:'PR #227',note:'원래 <메모>'};
            const a=doneCard(p); ARC_OPEN.add('o:7'); ARC_OPEN.add('r:7'); const b=doneCard(p);
            console.log(JSON.stringify([/class="arc-row done"/.test(a), !/class="pin/.test(a), /ic-check/.test(a),
              /data-act="rv-reopen"[^>]*>다시 열기</.test(a), /PR #227/.test(a), /class="rt arc-t" data-at="2026-09-23 20:40:11" data-tip="닫은 사람 에이전트 · 닫은 시각 2026-09-23 20:40:11">[^<]+</.test(a),
              /<span class="arc-reply" [^>]*>제목을 &lt;b&gt;바꿈&lt;\/b&gt;<\/span>/.test(a), /arc-orig"/.test(a), /원래 요청<\/button>/.test(a),
              /arc-reply open/.test(b), /class="arc-orig"><b>원래 요청<\/b>원래 &lt;메모&gt;/.test(b)]));
            """)
        self.assertEqual(out, [True, True, True, True, True, True, True, False, True, True, True])

    def test_done_row_reopen_reuses_reason_ui_not_bare_reopen(self):
        # 결함 실측: 완료 행의 [다시 열기]가 이유를 묻지 않고 곧장 /reopen 을 불렀다. 이제 review 카드와
        # 같은 openReply(id,'reopen') 경로(data-act="rv-reopen")를 쓰고, 입력 칸을 스레드 안 .reply-slot 에 낀다.
        out = self.run_rows(r"""
            const p={id:9,file:'/m.tex',name:'m.tex',lo:3,hi:5,page:2,done:true,done_at:'2026-09-23 20:40:11',
              closed_by:{name:'에이전트'},close_reply:'고침',thread:[{id:1,by:{name:'에이전트'},at:'2026-09-23 20:40:11',text:'고침',ev:'close'}]};
            const idle=doneCard(p);
            REPLY={id:9,mode:'reopen',el:null};
            const reopening=doneCard(p);
            console.log(JSON.stringify([!/data-act="reopen"/.test(idle), /data-act="rv-reopen"/.test(idle),
              /class="reply-slot"/.test(idle), /class="reply-slot"/.test(reopening), /class="arc-thread"/.test(reopening)]));
            """)
        self.assertEqual(out, [True, True, False, True, True])

    def test_placeholder_ref_dash_is_hidden(self):
        # 결함 실측: QA 스크립트·옛 호출이 ref 자리에 '-'를 넣으면 '닫음 · -' 처럼 의미 없는 참조가 떴다.
        out = self.run_rows(r"""
            const dash=doneCard({id:1,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'-'});
            const real=doneCard({id:2,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00',close_ref:'PR #9'});
            const evDash=msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'-'});
            const evReal=msgHtml({id:1,by:{name:'에이전트'},at:'2026-09-23 08:05:00',text:'답',ev:'close',ref:'abc1234'});
            console.log(JSON.stringify([/arc-ref/.test(dash), /arc-ref/.test(real), /PR #9/.test(real),
              / · -</.test(evDash), evDash.includes(' · -'), evReal.includes(' · abc1234')]));
            """)
        self.assertEqual(out, [False, True, True, False, False, True])

    def test_done_row_without_reply_says_so_and_dropped_row_restores(self):
        out = self.run_rows(r"""
            const a=doneCard({id:3,file:'/m.tex',name:'m.tex',lo:1,hi:1,page:1,done:true,done_at:'2026-09-23 08:05:00'});
            const d=droppedCard({id:4,file:'/m.tex',name:'m.tex',lo:2,hi:9,page:1,note:'잘못 찍음',dropped_at:'2026-09-23 09:00:00',dropped_by:{name:'김'}});
            console.log(JSON.stringify([/설명 없이 닫힘/.test(a), /원래 요청/.test(a), /class="arc-row dropped"/.test(d), /ic-trash-2/.test(d),
              /data-act="restore"[^>]*>되살리기</.test(d), />잘못 찍음</.test(d), /L2-L9/.test(d), /data-act="reopen"/.test(d)]));
            """)
        self.assertEqual(out, [True, False, True, True, True, True, True, False])

    def test_section_head_reads_label_count_and_fold_state(self):
        out = self.run_rows(r"""
            const strip=s=>s.replace(/<svg.*?<\/svg>/g,'').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
            console.log(JSON.stringify([strip(arcHead('완료',18,false)), strip(arcHead('삭제',2,true)),
              /ic-chevron-right/.test(arcHead('완료',1,false)), /ic-chevron-down/.test(arcHead('완료',1,true))]));
            """)
        self.assertEqual(out, ["완료 18 펼치기", "삭제 2 접기", True, True])

    def test_sections_are_sticky_and_wired(self):
        h = ps.HTML
        for sid in ("sec-open", "sec-done", "sec-dropped"):
            self.assertIn('id="%s"' % sid, h)
        css = h[h.index("<style>"):h.index("</style>")]
        self.assertRegex(css, r"\.list-head\{position:sticky;top:var\(--stick-top,0px\)")
        self.assertRegex(css, r"button\.arc-head\{position:sticky;top:var\(--stick-top,0px\)")
        # 회귀: revealList() 의 scrollIntoView({block:'start'}) 는 이 헤더의 '스티키 미보정' 정적 위치를 뷰포트
        # 맨 위(0)로 맞춘다. scroll-margin-top 이 없으면 그 정적 위치가 실제 스티키 고정 위치(stick-top)보다
        # 위라서, 헤더 바로 다음 행(되살리기 버튼)이 #bar1 뒤로 가려졌다(터치 QA 실측). scroll-margin-top 을
        # 같은 --stick-top 변수로 둬 둘을 맞춘다.
        self.assertRegex(css, r"button\.arc-head\{[^}]*scroll-margin-top:var\(--stick-top,0px\)")
        self.assertIn("function stickTop()", h)
        self.assertIn("case 'arc-toggle':", h)
        body = extract_js_fn("drawPins")
        self.assertIn("arcHead('완료',LDONE.length,SHOW_DONE)", body)
        self.assertIn("arcHead('삭제',LDROP.length,SHOW_DROPPED)", body)
        self.assertIn("LDONE.slice().reverse().map(doneCard)", body)
        # 문서 전환·모든 문서 토글에도 같은 목록 함수(listDone/listDropped)를 쓴다
        self.assertIn("const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();", body)

    def test_status_without_stripes_dot_badge_and_icons(self):
        # 저자 지적(2026-09-24): 왼쪽 색 띠는 촌스럽다. 상태는 카드 머리의 점 + 같은 뜻의 배지, 보관함은 앞머리 아이콘.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        for sel, decls in css_rules():
            if re.search(r"\.pin\b|\.arc-row|\.toast|#revision-pin|\.dm-item", sel):
                keys = [k for k, _ in decls]
                self.assertFalse([k for k in keys if k.startswith("border-left")], sel)
                self.assertNotIn("::before", sel.replace(".pin .n.go::before", ""))   # 겹쳐 그린 띠도 없다
                for k, v in decls:
                    self.assertNotRegex(v, r"inset \d+px 0 0", sel)          # box-shadow 로 그린 띠도 없다
        self.assertNotIn(".strip{", css)
        for st in ("claimed", "review", "lost", "done", "dropped"):
            self.assertIn(".st-dot.%s{background:var(--status-" % st, css)
        self.assertEqual(css.count("--status-claimed:"), 2)             # 다크·라이트 둘 다
        body = extract_js_fn("card")
        self.assertIn("(claimed?' claimed':'')", body)
        self.assertIn("stDot(rv?'review':p.stale?'lost':claimed?'claimed':'open')", body)
        self.assertIn("aria-label=\"상태: '+ST_NAME[st]+'\"", extract_js_fn("stDot"))   # 색만으로 가르지 않는다
        self.assertIn("ic('rotate-ccw')+'다시 열림", body)
        self.assertIn(".arc-row+.arc-row{border-top:1px solid var(--border)}", css)


# ---------------------------------------------------------------- 처리 예상 시간(eta_min) — 서버·pins.md·뷰어 표시
# '⏳ 처리 중 · ~04:02' 가 예상 완료처럼 읽혔는데 실제로는 잠금 자동 해제 시각이었다(다른 세션이 23건을 ttl 480 분으로 한꺼번에
# 잡음, 2026-09-23). 에이전트가 견적(eta_min)을 넣고, 화면은 5분 단위로 올린 '약 15분 · 20:40쯤'을 보인다. 잠금은 안전장치로만
# 남고 상한은 120 분이다.
class ClaimEta(Base):
    A = {"login": "alice@x.com", "name": "Alice"}
    B = {"login": "bob@x.com", "name": "Bob"}

    def test_body_validation_and_derived_ttl(self):
        self.assertEqual(ps.clean_claim_body({}), (ps.CLAIM_TTL_DEFAULT, None))
        for eta, ttl in ((1, 30), (5, 30), (15, 30), (20, 40), (45, 90), (60, 120), (90, 120), (240, 120)):
            self.assertEqual(ps.clean_claim_body({"eta_min": eta}), (ttl, eta), eta)
        self.assertEqual(ps.clean_claim_body({"eta_min": 15, "ttl_min": 10}), (10, 15))     # ttl 을 주면 그대로
        for bad in (0, "15", 1.5, True, None, -5):
            with self.assertRaises(ps.HTTPError) as cm:
                ps.clean_claim_body({"eta_min": bad})
            self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(ps.HTTPError):
            ps.clean_claim_body({"eta_min": 15, "ttl_min": 0})
        # 상한을 넘으면 400 이 아니라 깎는다 — 옛 절차(ttl_min 480)로 잡아 둔 에이전트가 연장하다 깨지지 않게
        self.assertEqual(ps.clean_claim_body({"eta_min": 241}), (120, 240))
        self.assertEqual(ps.clean_claim_body({"eta_min": 15, "ttl_min": 480}), (120, 15))
        self.assertEqual(ps.clean_claim_body({"ttl_min": 480}), (120, None))

    def test_claim_stores_eta_and_start(self):
        pid = self.add()
        t0 = time.time()
        p = ps.claim_pin(pid, self.A, *ps.clean_claim_body({"eta_min": 15}))
        self.assertAlmostEqual(p["eta_ts"], t0 + 15 * 60, delta=5)
        self.assertAlmostEqual(p["claim_ts"], t0, delta=5)
        self.assertAlmostEqual(p["claim_until"], t0 + 30 * 60, delta=5)
        self.assertIsInstance(p["claimed_at"], str)
        rows, _ = ps.read_pins()                                        # 저장값이다(계산 필드가 아님)
        self.assertIn("eta_ts", ps.find_pin(rows, pid))

    def test_same_identity_reclaim_extends_and_updates_estimate(self):
        pid = self.add()
        first = ps.claim_pin(pid, self.A, *ps.clean_claim_body({"eta_min": 5}))
        with ps.PIN_LOCK:                                              # 10분 전에 잡은 것으로 옮긴다
            rows, _ = ps.read_pins()
            r = ps.find_pin(rows, pid)
            for k in ("claim_ts", "eta_ts", "claim_until"):
                r[k] -= 600
            ps.write_pins(rows)
        second = ps.claim_pin(pid, self.A, *ps.clean_claim_body({"eta_min": 20}))
        self.assertAlmostEqual(second["claim_ts"], first["claim_ts"] - 600, delta=1)      # 시작 시각은 그대로
        self.assertEqual(second["claimed_at"], first["claimed_at"])
        self.assertAlmostEqual(second["eta_ts"], time.time() + 20 * 60, delta=5)          # 새 예상은 지금부터
        self.assertAlmostEqual(second["claim_until"], time.time() + 40 * 60, delta=5)
        third = ps.claim_pin(pid, self.A, *ps.clean_claim_body({}))                      # 예상 없이 연장하면 앞 예상을 둔다
        self.assertEqual(third["eta_ts"], second["eta_ts"])
        self.assertEqual(third["rev"], second["rev"] + 1)

    def test_other_identity_conflict_reports_eta_and_new_claim_drops_old_eta(self):
        pid = self.add()
        ps.claim_pin(pid, self.A, *ps.clean_claim_body({"eta_min": 15}))
        with self.assertRaises(ps.HTTPError) as cm:
            ps.claim_pin(pid, self.B, *ps.clean_claim_body({"eta_min": 5}))
        self.assertEqual(cm.exception.code, 409)
        self.assertIn("eta_ts", cm.exception.body)
        with ps.PIN_LOCK:                                              # A 의 잠금이 풀렸다
            rows, _ = ps.read_pins()
            ps.find_pin(rows, pid)["claim_until"] = time.time() - 1
            ps.write_pins(rows)
        p = ps.claim_pin(pid, self.B, *ps.clean_claim_body({}))
        self.assertEqual(p["claimed_by"]["login"], "bob@x.com")
        self.assertNotIn("eta_ts", p)                                   # 남의 옛 예상을 물려받지 않는다

    def test_close_drop_unclaim_clear_all_claim_fields(self):
        for how in ("close", "drop", "unclaim"):
            pid = self.add()
            ps.claim_pin(pid, self.A, *ps.clean_claim_body({"eta_min": 10}))
            if how == "close":
                rec = ps.set_done(pid, True, self.A)
            elif how == "unclaim":
                rec = ps.unclaim_pin(pid, self.A)
            else:
                ps.drop_pin(pid, self.A)
                rec = ps.read_jsonl(ps.C.dropped)[0][-1]
            for k in ps.CLAIM_FIELDS:
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
        # 옛 스킬 절차대로 ttl_min=480 으로 잡아 둔 에이전트가 같은 값으로 연장해도 깨지지 않는다(200, 120 으로 적용).
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
        self.assertEqual(code, 200)                                     # 같은 신원(헤더 없음 = 로컬/에이전트)의 연장
        got = json.loads(body)
        self.assertEqual((got["ttl_min_applied"], got["eta_min_applied"]), (120, 240))
        self.assertAlmostEqual(got["pin"]["eta_ts"], time.time() + 240 * 60, delta=5)

    def test_pins_payload_fills_start_for_legacy_claims(self):
        pid = self.add()
        with ps.PIN_LOCK:                                              # eta 이전 서버가 쓴 claim 모양
            rows, _ = ps.read_pins()
            r = ps.find_pin(rows, pid)
            r.update(claimed_by=dict(self.A), claimed_at="2026-09-23 20:02:00", claim_until=time.time() + 3600)
            ps.write_pins(rows)
        rec = [x for x in ps.pins_payload(ps.snapshot_pins(), False) if x["id"] == pid][0]
        self.assertAlmostEqual(rec["claim_ts"], ps._epoch("2026-09-23 20:02:00"), delta=0.01)
        self.assertNotIn("claim_ts", ps.find_pin(ps.read_pins()[0], pid))   # 계산 필드 — 저장하지 않는다

    def test_pins_md_claim_text(self):
        now = 1_790_000_000.0
        r = {"claimed_by": {"name": "Kim"}}
        self.assertEqual(ps.claim_md(dict(r), now), "처리 중(Kim)")
        for left_s, want in ((14 * 60 + 10, "약 15분"), (3 * 60, "약 5분"), (15 * 60, "약 15분"), (16 * 60, "약 20분"),
                             (-60, "예상 초과")):
            self.assertEqual(ps.claim_md(dict(r, eta_ts=now + left_s), now), "처리 중(Kim, %s)" % want)
        self.assertEqual([ps.ceil5(m) for m in (0, 0.2, 5, 5.01, 14.9, 23)], [5, 5, 5, 10, 15, 25])
        pid = self.add()
        ps.claim_pin(pid, {"login": "k", "name": "에이전트 A"}, *ps.clean_claim_body({"eta_min": 15}))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("처리 중(에이전트 A, 약 15분)", md)


class FrontendClaimEta(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def run_info(self, script: str, tz="Asia/Seoul"):
        js = "\n".join(["function who(a){return a?a.name:'';}", extract_js_fn("ceil5"), extract_js_fn("hhmm"),
                        extract_js_fn("claimInfo"), extract_js_fn("claimLabel"), script])
        return json.loads(run_node(js, tz=tz))

    def test_estimate_rounds_up_to_five_minutes_and_clock(self):
        # 20:23:00 KST 에 보고, 예상 완료는 20:37:12 → 남은 14.2분은 '약 15분', 시각은 20:40쯤.
        out = self.run_info(r"""
            const now=Date.parse('2026-09-23T20:23:00+09:00'), eta=Date.parse('2026-09-23T20:37:12+09:00')/1000;
            const p={claimed_by:{name:'A'},claim_ts:Date.parse('2026-09-23T20:20:00+09:00')/1000,eta_ts:eta,
                     claim_until:Date.parse('2026-09-23T22:20:00+09:00')/1000};
            const a=claimInfo(p,now), b=claimInfo(Object.assign({},p,{eta_ts:(now/1000)+3*60}),now);
            console.log(JSON.stringify([a.t,a.late,b.t,/잠금 자동 해제 22:20/.test(a.tip),/22:20/.test(a.t),/예상 완료 20:37/.test(a.tip)]));
            """)
        self.assertEqual(out, ["처리 중 · 약 15분 · 20:40쯤", False, "처리 중 · 약 5분 · 20:30쯤", True, False, True])

    def test_overrun_reports_late_by_five_minute_steps(self):
        out = self.run_info(r"""
            const now=Date.parse('2026-09-23T20:45:00+09:00')/1000;
            const p=o=>Object.assign({claimed_by:{name:'A'},claim_until:now+3600},o);
            console.log(JSON.stringify([claimInfo(p({eta_ts:now-30}),now*1000).t, claimInfo(p({eta_ts:now-7*60}),now*1000).t,
              claimInfo(p({eta_ts:now-30}),now*1000).late, claimLabel(p({eta_ts:now-10*60}),now*1000)]));
            """)
        self.assertEqual(out, ["예상보다 늦어짐 (+5분)", "예상보다 늦어짐 (+10분)", True, "예상보다 늦어짐 (+10분)"])

    def test_legacy_claim_without_eta_shows_start_and_elapsed(self):
        out = self.run_info(r"""
            const st=Date.parse('2026-09-23T20:02:00+09:00')/1000, now=(st+22*60+30)*1000;
            const a=claimInfo({claimed_by:{name:'A'},claim_ts:st,claim_until:st+480*60},now);
            const b=claimInfo({claimed_by:{name:'A'},claim_until:st+480*60},now);
            console.log(JSON.stringify([a.t, b.t, /04:02/.test(a.t), /잠금 자동 해제 04:02/.test(a.tip)]));
            """)
        self.assertEqual(out, ["처리 중 · 20:02부터 (23분째)", "처리 중", False, True])

    def test_clock_uses_viewer_local_time(self):
        js = r"""
            const now=Date.parse('2026-09-23T11:23:00Z'), eta=Date.parse('2026-09-23T11:37:12Z')/1000;
            console.log(JSON.stringify(claimInfo({claimed_by:{name:'A'},eta_ts:eta,claim_until:eta+600},now).t));
            """
        self.assertEqual(self.run_info(js, tz="Asia/Seoul"), "처리 중 · 약 15분 · 20:40쯤")
        self.assertEqual(self.run_info(js, tz="America/New_York"), "처리 중 · 약 15분 · 07:40쯤")

    def test_js_ceil5_matches_server(self):
        out = self.run_info("console.log(JSON.stringify([0,0.2,5,5.01,14.9,23].map(ceil5)));")
        self.assertEqual(out, [ps.ceil5(m) for m in (0, 0.2, 5, 5.01, 14.9, 23)])

    def test_card_uses_claim_tag_and_ticker(self):
        self.assertIn("if(claimed)tags.push(claimTag(p));", extract_js_fn("card"))
        self.assertIn('data-claim="', extract_js_fn("claimTag"))
        self.assertIn("setInterval(tickClaims,30000);", ps.HTML)
        self.assertNotIn("toLocaleTimeString", extract_js_fn("claimInfo"))


class ClaimEtaDocs(unittest.TestCase):
    """SKILL.md 핀 처리 절차가 '고치기 직전에 그 핀만 claim, eta_min 에 견적'을 가르치는지."""

    def test_skill_claim_step_teaches_single_pin_and_estimate(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("고치기 직전에 그 핀만 claim", skill)
        self.assertIn('"eta_min"', skill)
        for row in ("| 오타·단어 | 5 |", "| 문장 하나 | 5–10 |", "| 문단 다시 쓰기 | 10–20 |", "| 구조 변경·여러 곳 | 20–40 |"):
            self.assertIn(row, skill)
        self.assertNotIn("⏳", skill)
        api = (SKILL / "references" / "api.md").read_text(encoding="utf-8")
        self.assertIn("`eta_min` | 1..240", api)
        self.assertIn("`ttl_min` | 1..120", api)
        self.assertIn("min(120, max(30, eta_min×2))", api)

    def test_epoch_claim_fields_are_valid_record_fields(self):
        base = {"id": 1, "file": "/x.tex", "lo": 1, "hi": 2, "claim_ts": 1.5, "eta_ts": 2.5, "claim_until": 3.0}
        self.assertTrue(ps.valid_rec(base))
        self.assertFalse(ps.valid_rec(dict(base, eta_ts="soon")))
        self.assertFalse(ps.valid_rec(dict(base, claim_ts="20:02")))


# ---------------------------------------------------------------- 배지 문구: 뜻이 드러나는 말(겹침·위치 일치율)·pins.md 표시
# '#20 안'·'일치 100%'·'⊂#N' 은 뜻을 알 수 없었다(저자 지적 2026-09-23). 겹침은 '#20 범위 안'·'#20과 같은 범위'·'#20과 일부 겹침',
# 위치 일치율은 90% 이상이면 숨기고 낮을 때만 '위치 불확실'. pins.md 번호 칸도 같은 말을 ' · ' 로 잇는다.
class BadgeWording(Base):
    NUMS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 19, 20, 100, 1000, 21, 32]

    def test_josa_follows_korean_reading(self):
        got = [ps.josa(n, "과", "와") for n in self.NUMS]
        self.assertEqual(got, ["과", "와", "과", "와", "와", "과", "과", "과", "와", "과", "과", "와", "와", "와", "과", "과", "과",
                               "과", "와"])
        if shutil.which("node"):
            js = extract_js_fn("josa") + "\nconsole.log(JSON.stringify(%s.map(n=>josa(n,'과','와'))));" % json.dumps(self.NUMS)
            self.assertEqual(json.loads(run_node(js)), got)

    def test_rel_badge_prefers_same_range_then_inside_then_partial(self):
        by_id = {1: {"lo": 4, "hi": 9}, 2: {"lo": 4, "hi": 9}, 3: {"lo": 5, "hi": 6}, 20: {"lo": 8, "hi": 12}}
        self.assertEqual(ps.rel_badge([{"id": 1, "rel": "contains"}], by_id, {"id": 2, "lo": 4, "hi": 9}), "#1과 같은 범위")
        self.assertEqual(ps.rel_badge([{"id": 2, "rel": "inside"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "#2와 같은 범위")
        self.assertEqual(ps.rel_badge([{"id": 1, "rel": "inside"}, {"id": 2, "rel": "inside"}], by_id,
                                      {"id": 3, "lo": 5, "hi": 6}), "#1 범위 안")
        self.assertEqual(ps.rel_badge([{"id": 20, "rel": "partial"}], by_id, {"id": 3, "lo": 5, "hi": 9}), "#20과 일부 겹침")
        self.assertEqual(ps.rel_badge([{"id": 2, "rel": "partial"}], by_id, {"id": 9, "lo": 8, "hi": 12}), "#2와 일부 겹침")
        self.assertEqual(ps.rel_badge([{"id": 3, "rel": "contains"}], by_id, {"id": 1, "lo": 4, "hi": 9}), "")

    def test_js_rel_badge_matches_server(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")
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
            self.skipTest("node 없음")
        js = "\n".join([extract_js_fn("josa"), extract_js_fn("overlapVerb"), r"""
            console.log(JSON.stringify([['equal',4],['inside',20],['contains',4],['contains',20],['partial',2]].map(a=>'#'+a[1]+overlapVerb(a[0],a[1]))));
            """])
        self.assertEqual(json.loads(run_node(js)),
                         ["#4와 같은 범위입니다", "#20 범위 안입니다", "#4를 감쌉니다", "#20을 감쌉니다", "#2와 일부 겹칩니다"])

    def test_pins_md_number_column_uses_words(self):
        a = self.add(4, 9)
        b = self.add(4, 9)
        c = self.add(5, 6)
        ps.edit_pin(c, {"note": "고침", "base_rev": self.pin(c)["rev"]}, dict(ps.LOCAL_ACTOR))
        ps.claim_pin(c, {"login": "k", "name": "Kim"}, *ps.clean_claim_body({"eta_min": 10}))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("| %d · #%d와 같은 범위 |" % (a, b), md)
        self.assertIn("| %d · #%d과 같은 범위 |" % (b, a), md)
        self.assertIn("| %d · #%d 범위 안 · 처리 중(Kim, 약 10분) · 수정됨 |" % (c, a), md)
        for sym in ("⊂", "∩", "⏳", "✎", "⚠"):
            self.assertNotIn(sym, md)
        self.assertIn("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다", md)

    def test_skill_symbol_table_uses_words(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        table = skill[skill.index("### 번호 칸의 표시"):skill.index("### 규칙")]
        for row in ("| `#N 범위 안` |", "| `#N과 같은 범위` |", "| `#N과 일부 겹침` |", "| `처리 중(<이름>, 약 N분)` |",
                    "| `수정됨` |", "| `위치 잃음` |"):
            self.assertIn(row, table)
        self.assertNotRegex(table, r"^\| `[⊂∩⏳✎⚠]", )


class FrontendToolbarOneRow(unittest.TestCase):
    """1400px 데스크톱(기본 430px 패널)에서 긴 이름표('Long-DemoPaper1')여도 도구 줄이 한 줄이다(Playwright 실측,
    references/design.md §디자인 토큰 · 도구 줄). [핀 다시 읽기]는 열린 핀 목록 머리로 옮겼고 compact 에서는 [더보기] 안에 있다."""

    def test_reload_lives_in_list_head_not_toolbar(self):
        bar = ps.HTML[ps.HTML.index('<div class="bar" id="bar1"'):ps.HTML.index('<div class="bar" id="bar2"')]
        self.assertNotIn('id="btn-reload"', bar)
        head = ps.HTML[ps.HTML.index('<div class="list-head">'):ps.HTML.index('<div id="pins">')]
        self.assertRegex(head, r'<button id="btn-reload" class="sec btn-sm" data-act="reload" aria-label="핀 다시 읽기"')

    def test_label_chip_truncates_and_tip_has_full_label(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#bar1 .chip{height:var(--control-h-sm);display:block;", css)
        self.assertIn("flex:0 1 auto;min-width:40px}", css)
        self.assertIn("text-overflow:ellipsis", re.search(r"\n\.chip\{[^}]*\}", css).group(0))
        self.assertIn("body.compact #bar1 .chip{flex:0 50 auto;min-width:28px}", css)   # compact 는 이름표가 먼저 준다
        out = ps.build_html("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('data-tip="Long-DemoPaper1 — 이 창이 다루는 논문', out)

    def test_fold_closed_moves_label_into_more_and_keeps_doc_name(self):
        # 접은 폴드(344px)에서 이름표가 'C…', 문서 버튼이 '본..' 으로 줄어 읽을 수 없었다(2026-09-23).
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn("body.lay-narrow #bar1 #btn-doc{flex:none;overflow:visible}", css)
        self.assertIn("body.lay-narrow #btn-doc .nm{overflow:visible;text-overflow:clip", css)
        more = ps.HTML[ps.HTML.index('<dialog id="more"'):ps.HTML.index("</dialog>", ps.HTML.index('<dialog id="more"'))]
        self.assertIn('<span id="more-label" class="chip" data-tip="__LABEL__ — ', more)
        out = ps.build_html("Long-DemoPaper1", "#1d4ed8")
        self.assertIn('<dialog id="more" aria-label="더보기 · Long-DemoPaper1">', out)
        self.assertIn("#more .more-head .chip{background:var(--brand);", css)

    def test_fold_open_also_hides_toolbar_chip_and_relies_on_more(self):
        # 회귀: 펼친 폴드(884px)도 #bar1 이 flex-wrap:nowrap 압박을 받아 이름표가 'CE-iTra…'(71px)까지 줄어
        # 읽을 수 없었다(터치 QA 실측). narrow 와 같은 처방 — 도구 줄 칩은 숨기고 [더보기] 안 #more-label 로만
        # 전체 이름을 보인다. #more(더보기) 는 레이아웃 조건 없는 공용 마크업이라 mid 에서도 그대로 쓸 수 있다.
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.lay-narrow #bar1 .chip,body.lay-mid #bar1 .chip{display:none}", css)
        self.assertIn('id="btn-more" class="cmp btn-icon"', ps.HTML)   # [더보기] 는 compact(=mid·narrow) 공용


class FrontendToolbarSize(unittest.TestCase):
    """도구 줄 '쪽' 칸이 버튼과 같은 높이·글자 크기인지(데스크톱 28px, 터치 44px). 실측은 Playwright 로 했다."""

    def test_page_field_matches_toolbar_buttons(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("#bar1{flex-wrap:wrap;gap:var(--space-1);padding:var(--space-2) 10px;--tb-h:var(--control-h)}", css)
        self.assertIn("--control-h:28px", css)
        self.assertIn("--control-h-touch:44px", css)
        self.assertIn("#bar1>button,#bar1>input{height:var(--tb-h)}", css)
        self.assertIn("#bar1 input.n{width:40px;flex:none;padding:0 var(--space-1);font-size:var(--text-base);", css)
        self.assertIn("#bar1 button.btn-icon{padding:0;width:var(--tb-h);min-width:var(--tb-h)}", css)
        coarse = css[css.index("@media (pointer:coarse){"):]
        self.assertIn("#bar1{flex-wrap:wrap;--tb-h:var(--control-h-touch)}", coarse)
        self.assertIn("#bar1 input.n{width:52px;font-size:var(--text-xl)}", coarse)
        self.assertRegex(ps.HTML, r'<input class="n sec" id="jump" placeholder="쪽"')
        self.assertIn('id="m-jump" inputmode="numeric" placeholder="쪽"', ps.HTML)


class FrontendSaveWhilePicking(unittest.TestCase):
    """P0c 수선: 드래그 직후 SyncTeX pick 이 끝나기 전(~1.1s)에 [핀 저장]을 누르면 CUR 이 아직 없어
    savePin() 이 조용히 아무 일도 안 하고 메모가 사라졌다(실측). 이제는 그 요청을 큐에 담아
    pick 이 끝나면 자동 저장한다. 구조 단언(옛 무음 조기 return 이 없어졌는지) + node 로 실제
    savePin()/pick() 소스를 돌려 큐잉·자동저장·실패시 취소·토글 취소까지 행동으로 검증한다."""

    def test_save_pin_no_longer_silently_drops_missing_cur(self):
        body = extract_js_fn("savePin")
        self.assertNotIn("if(!CUR||SAVING)return;", body)
        self.assertIn("if(SAVING)return;", body)
        self.assertIn("if(!CUR){if(PICKING)togglePendingSave(); return;}", body)

    def test_pick_triggers_queued_save_on_success_and_clears_on_error(self):
        pick_body = extract_js_fn("pick")
        self.assertIn("if(PEND_SAVE){clearPendingSave(); savePin();}", pick_body)
        # 실패 경로(catch·d.error)도 대기 중이던 저장을 비운다 — 조용히 저장해버리지 않는다.
        self.assertIn("clearPendingSave();", pick_body)
        self.assertRegex(pick_body, r"catch\(e\)\{if\(seq!==PICKSEQ\)return; setBusy\(false\); if\(!rp\)\{PICKING=false; clearPendingSave\(\);\}")

    def _harness(self, extra_body):
        stub = r"""
            const MQ_COARSE={matches:false}; const IS_MAC=false;
            function el(){return {hidden:true,textContent:'',innerHTML:'',value:'',dataset:{},
              scrollTop:0,disabled:false,classList:{toggle(){}},focus(){},remove(){}};}
            const els={}; const $=s=>(els[s]=els[s]||el());
            let PICKSEQ=0, PENDING=null, CUR=null, SAVING=false, PICKING=false, PEND_SAVE=false, REPICK=null;
            let LAYOUT='wide', LAST_PTR='mouse', OVERLAP_DISMISSED=null, SNIP_OPEN=false, PINS=[], EDIT=null, DOC=undefined;
            let KIND_NEW='fix'; function setKind(k){KIND_NEW=k==='question'?'question':'fix';} function mentionHints(){return [];}
            const ASSIGN_NEW={v:'agent',touched:false}; function renderAssignNew(){} function mentionPreview(){}
            function setBusy(){} function renderComposer(){} function overlapsFor(){return [];}
            async function loadPins(){} function useLevel(){} function isRegion(){return false;} function kindFor(){return 'line';}
            function banner(){} function bannerRepick(){} function bannerCompare(){} function revealBox(){}
            async function refreshDoc(){} function setSide(){} function setSelMode(){} function toast(){} function dropPin(){}
            const apiCalls=[]; let pickResolve=null, pickReject=null, pinResolve=null;
            function api(url){apiCalls.push(url);
              if(url==='/api/pick')return new Promise((res,rej)=>{pickResolve=res;pickReject=rej;});
              if(url==='/api/pin')return new Promise(res=>{pinResolve=res;});
              return Promise.resolve({data:{}});}
            """
        return "\n".join([
            stub,
            extract_js_fn("saveBtnLabel"), extract_js_fn("togglePendingSave"), extract_js_fn("clearPendingSave"),
            extract_js_fn("savePin"), extract_js_fn("cancelSelection"), extract_js_fn("pick"),
            extra_body,
        ])

    def test_queued_save_fires_automatically_once_pick_resolves(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              out.pickingWhileWaiting = PICKING;
              savePin();   // 사용자가 pick 이 끝나기 전에 [핀 저장]을 누름
              out.queued = PEND_SAVE;
              out.btnPendingLabel = /위치 찾는 중.*저장 대기/.test(els['#btn-save'].innerHTML);
              out.pinCallsBeforeResolve = apiCalls.filter(u=>u==='/api/pin').length;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:5,hi:5,raw_lo:5,raw_hi:5,page:1,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p;
              out.autoSaved = PEND_SAVE===false;
              out.pinCallsAfterResolve = apiCalls.filter(u=>u==='/api/pin').length;
              out.curSetBeforeSave = !!CUR || out.pinCallsAfterResolve>0;
              pinResolve({data:{id:42}});
              await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel();
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        data = json.loads(out)
        self.assertTrue(data["pickingWhileWaiting"])
        self.assertTrue(data["queued"])
        self.assertTrue(data["btnPendingLabel"])
        self.assertEqual(data["pinCallsBeforeResolve"], 0)   # pick 해소 전엔 저장 요청을 보내지 않는다
        self.assertTrue(data["autoSaved"])
        self.assertEqual(data["pinCallsAfterResolve"], 1)    # pick 이 풀리자 큐에 담긴 저장이 자동으로 나간다
        self.assertTrue(data["btnLabelRestored"])

    def test_pick_failure_clears_queued_save_without_saving(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queuedBeforeFailure = PEND_SAVE;
              pickResolve({data:{error:'못 찾음'}});
              await p;
              out.queuedAfterFailure = PEND_SAVE;
              out.pinCalls = apiCalls.filter(u=>u==='/api/pin').length;
              out.errorShown = els['#c-err'].hidden===false && els['#c-err'].textContent==='못 찾음';
              out.composerStillOpen = els['#composer'].hidden!==true || true;   // 실제 hidden 토글은 composer 표시측이 이미 맡는다
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        data = json.loads(out)
        self.assertTrue(data["queuedBeforeFailure"])
        self.assertFalse(data["queuedAfterFailure"])
        self.assertEqual(data["pinCalls"], 0)   # pick 이 실패하면 저장하지 않는다
        self.assertTrue(data["errorShown"])

    def test_clicking_save_again_cancels_the_queued_save(self):
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p = pick({page:1,x0:0,y0:0,x1:1,y1:1});
              await Promise.resolve(); await Promise.resolve();
              savePin();
              out.queued = PEND_SAVE;
              savePin();   // 같은 버튼을 다시 누르면 대기를 취소(토글)
              out.canceled = PEND_SAVE===false;
              out.btnLabelRestored = els['#btn-save'].innerHTML===saveBtnLabel();
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:5,hi:5,raw_lo:5,raw_hi:5,page:1,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p;
              out.noAutoSaveAfterCancel = apiCalls.filter(u=>u==='/api/pin').length===0;
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        data = json.loads(out)
        self.assertTrue(data["queued"])
        self.assertTrue(data["canceled"])
        self.assertTrue(data["btnLabelRestored"])
        self.assertTrue(data["noAutoSaveAfterCancel"])

    def test_reselecting_during_pick_queues_save_for_new_location_not_stale_one(self):
        # 회귀: 이미 CUR 이 있는 상태(첫 선택 완료)에서 다시 길게 눌러 새 선택을 시작하면, 그 응답이 오기 전에
        # [핀 저장]을 눌러도 옛 CUR 이 즉시 저장되지 않고 PEND_SAVE 큐로 가서 새 위치가 저장돼야 한다.
        js = self._harness(r"""
            (async()=>{
              const out={};
              const p1 = pick({page:1,x0:0,y0:0.3,x1:1,y1:0.31});
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:717,hi:741,raw_lo:717,raw_hi:741,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p1;
              out.curAfterFirstPick = CUR && CUR.lo;
              const p2 = pick({page:1,x0:0,y0:0.7,x1:1,y1:0.71});
              await Promise.resolve(); await Promise.resolve();
              out.curClearedOnNewPick = (CUR===null);
              savePin();   // 스피너가 도는 동안(새 위치 응답 전) [핀 저장]을 누름
              out.pinCallsWhileWaiting = apiCalls.filter(u=>u==='/api/pin').length;
              out.queued = PEND_SAVE;
              pickResolve({data:{file:'/m.tex',name:'m.tex',lo:900,hi:920,raw_lo:900,raw_hi:920,page:5,
                default_level:null,overlaps:[],via:null,score:1,frac:0,quote:'',kind:'line'}});
              await p2;
              out.autoSaved = PEND_SAVE===false;
              out.pinCallsAfterSecondResolve = apiCalls.filter(u=>u==='/api/pin').length;
              console.log(JSON.stringify(out));
            })();
            """)
        out = run_node(js)
        if out is None:
            self.skipTest("node 가 없다")
        data = json.loads(out)
        self.assertEqual(data["curAfterFirstPick"], 717)
        self.assertTrue(data["curClearedOnNewPick"])
        self.assertEqual(data["pinCallsWhileWaiting"], 0)   # 새 응답 전엔 옛 CUR 로 저장하지 않는다
        self.assertTrue(data["queued"])
        self.assertTrue(data["autoSaved"])
        self.assertEqual(data["pinCallsAfterSecondResolve"], 1)   # 새 위치 응답이 오자 큐에 담긴 저장이 나간다


class FrontendResponsiveBrowser(unittest.TestCase):
    """Real Chromium layout and keyboard regression; API/PDF rendering is outside this oracle.

    Run with uv run --no-project --with playwright python -m unittest discover
    -s tests/manuscript_pin_picker -p test_pin_server.py -k FrontendResponsiveBrowser.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright unavailable")
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            raise unittest.SkipTest("Chromium unavailable")
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
        cls.html = ps.build_html("Long-DemoPaper1", "#2563eb").replace("\nboot();", "\n")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open_viewer(self, width, touch=False, preferences=None):
        context = self.browser.new_context(viewport={"width": width, "height": 900},
                                           is_mobile=touch, has_touch=touch)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=self.html)
                   if route.request.url == "http://viewer.test/" else route.abort())
        page.goto("http://viewer.test/")
        page.evaluate("""preferences => {
          localStorage.setItem('pinPrefs',JSON.stringify(preferences||{}));
          DOC='main';DEFAULT_DOC='main';
          DOCS=[{key:'main',name:'본문',path:'main.tex',n_pages:28},
                {key:'reply',name:'하이라이트',path:'reply.tex',n_pages:1},
                {key:'cover',name:'커버레터',path:'cover.tex',n_pages:1}];
          document.body.classList.add('docs-multi');
          applyTheme();applyLayout();applySideWidth();applyOutlineState();drawDocTabs();
          META={pages:[{}, {}, {}]};
          document.querySelector('#doc').innerHTML=[1,2,3].map(n=>
            '<div class="pg" id="p'+n+'" data-page="'+n+'" style="aspect-ratio:612/792;background:white"></div>').join('');
          relayout();
        }""", preferences)
        return page

    def test_toggle_stays_in_place_without_overflow_for_mouse_and_touch(self):
        for touch in (False, True):
            for width in (720, 820, 900, 1024, 1180, 1440):
                with self.subTest(width=width, touch=touch):
                    page = self.open_viewer(width, touch)
                    if touch:
                        page.evaluate("coach('touch','길게 누르면 문단을 고릅니다')")
                    self.assertEqual(page.evaluate("SIDE_OPEN"), width > 900)
                    toggle = page.locator('#nav-toc-toggle')
                    self.assertEqual(page.locator('[data-act="outline"]').count(), 1)
                    before = toggle.bounding_box()
                    self.assertGreaterEqual(before['y'], 0)
                    page.evaluate("document.querySelector('#left').scrollTop=480")
                    anchor = page.evaluate("topAnchor()")
                    toggle.click()  # Coach is still visible during this real hit test.
                    after = toggle.bounding_box()
                    self.assertEqual((before['x'], before['y']), (after['x'], after['y']))
                    self.assertEqual(page.evaluate("document.activeElement.id"), 'nav-toc-toggle')
                    current = page.evaluate("topAnchor()")
                    self.assertEqual(anchor['page'], current['page'])
                    self.assertAlmostEqual(anchor['frac'], current['frac'], delta=.003)
                    self.assertGreaterEqual(page.locator('#pdf-center').bounding_box()['width'], 480)
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
                    self.assertFalse(page.evaluate("document.querySelector('#doc-nav').scrollWidth>document.querySelector('#doc-nav').clientWidth"))
                    if width < 1100:
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')
                        self.assertFalse(page.evaluate("SIDE_OPEN"))
                        page.keyboard.press('Escape')
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        toggle.press('Enter')
                        page.locator('#btn-side').click()
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        self.assertTrue(page.evaluate("SIDE_OPEN"))
                    else:
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'false')
                        toggle.press('Enter')
                        self.assertEqual(toggle.get_attribute('aria-expanded'), 'true')

    def test_mid_action_bar_and_tabs_stay_put_when_panel_toggles(self):
        # 회귀(2026-09-24, 폴드 7 사용자): mid 에서 [핀 N] 이 패널을 펴면 오른쪽 위(y 56), 접으면 오른쪽 아래(y 693)로
        # 뛰었고, 문서 옆 패널(901–1099px)이 탐색 줄을 패널 폭만큼 잘랐다. 지금은 동작 줄이 화면 아래 전체 폭에 고정되고
        # 탐색 줄은 위 전체 폭이며, 패널은 그 사이에서만 편다.
        probe = """() => {
          const r = s => document.querySelector(s).getBoundingClientRect();
          const hit = e => {const b=e.getBoundingClientRect(), p=e.closest('#doc-links'), q=p?p.getBoundingClientRect():b;
            if(b.right<=q.left||b.left>=q.right)return true;   // 가로로 밀려 난 링크는 스크롤 영역 밖이다
            const x=Math.max(q.left+2,Math.min(q.right-2,b.left+b.width/2)), h=document.elementFromPoint(x,b.top+b.height/2);
            return !!h&&(h===e||e.contains(h));};
          const ctl = [...document.querySelectorAll('#bar1 button,#doc-nav button')].filter(e=>e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
          return {side:r('#btn-side'), bar:r('#bar1'), nav:r('#doc-nav'), right:r('#right'), open:SIDE_OPEN,
                  pos:getComputedStyle(document.querySelector('#bar1')).position,
                  blocked:ctl.filter(e=>!hit(e)).map(e=>e.id||e.textContent.trim()),
                  clipped:ctl.filter(e=>e.scrollWidth>e.clientWidth+1).map(e=>e.id||e.textContent.trim())};
        }"""
        for width in (720, 820, 884, 968, 1024):
            with self.subTest(width=width):
                page = self.open_viewer(width, True)
                a = page.evaluate(probe)
                page.locator('#btn-side').click()
                b = page.evaluate(probe)
                self.assertNotEqual(a['open'], b['open'])
                for s in (a, b):
                    self.assertEqual(s['pos'], 'fixed')
                    self.assertEqual((s['bar']['x'], s['bar']['width'], s['bar']['y'] + s['bar']['height']), (0, width, 900))
                    self.assertEqual((s['nav']['x'], s['nav']['width']), (0, width))
                    self.assertEqual(s['blocked'], [])
                    self.assertEqual(s['clipped'], [])
                    self.assertLess(s['side']['x'] + s['side']['width'], width)
                    self.assertGreater(s['side']['x'] + s['side']['width'], width - 40)   # 오른쪽 아래 끝(오른손 엄지)
                opened = a if a['open'] else b
                self.assertGreaterEqual(opened['right']['y'], opened['nav']['y'] + opened['nav']['height'] - 1)
                self.assertLessEqual(opened['right']['y'] + opened['right']['height'], opened['bar']['y'] + 1)
                for k in ('x', 'y', 'width', 'height'):
                    self.assertAlmostEqual(a['side'][k], b['side'][k], delta=1)

    def test_overlay_defaults_follow_width_but_explicit_choice_and_draft_survive(self):
        page = self.open_viewer(820)
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.set_viewport_size({'width': 1024, 'height': 900})
        page.wait_for_function("SIDE_OPEN")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("!SIDE_OPEN")
        page.locator('#btn-side').click()
        self.assertFalse(page.evaluate("prefs().midClosed"))
        page.set_viewport_size({'width': 1024, 'height': 900})
        page.wait_for_function("!MID_OVERLAY")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        page = self.open_viewer(1024)
        page.evaluate("document.querySelector('#composer').hidden=false")
        page.set_viewport_size({'width': 820, 'height': 900})
        page.wait_for_function("MID_OVERLAY")
        self.assertTrue(page.evaluate("SIDE_OPEN"))

    def test_saved_widths_clamp_without_overwriting_and_mobile_keeps_sheet(self):
        page = self.open_viewer(1180, preferences={'side': 430})
        self.assertEqual(page.locator('#right').bounding_box()['width'], 430)
        page = self.open_viewer(1024, preferences={'sideMid': 600})
        self.assertGreaterEqual(page.locator('#pdf-center').bounding_box()['width'], 480)
        self.assertEqual(page.evaluate("prefs().sideMid"), 600)
        page.locator('#grip').focus()
        page.keyboard.press('End')
        self.assertEqual(page.locator('#right').bounding_box()['width'], 300)
        page = self.open_viewer(390, True)
        self.assertFalse(page.locator('#doc-nav').is_visible())
        self.assertTrue(page.locator('#btn-doc').is_visible())
        self.assertFalse(page.evaluate("SIDE_OPEN"))
        page.locator('#btn-side').click()
        self.assertTrue(page.evaluate("SIDE_OPEN"))
        self.assertEqual(page.locator('#right').bounding_box()['width'], 390)
        page.locator('#btn-doc').click()
        self.assertTrue(page.locator('#docs-menu').is_visible())


# ---------------------------------------------------------------- 핀 종류(수정 요청/질문)·스레드·답글(references/api.md §스레드)
# A-DEMO 42건 중 10건(24%)이 고칠 곳이 아니라 질문이었다(#30 '구간이 0을 포함한다는 게 뭐지?' 등). 답을 남길 곳이 닫기 사유 한 칸뿐이라
# 되물을 수 없었다. kind_req 로 종류를 가르고, 핀마다 thread 를 두어 사람·에이전트가 주고받는다. 새 필드는 모두 선택이다.
class KindAndThread(Base):
    S = {"login": "bob@example.com", "name": "Bob Park"}

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        out = self.talk(req("POST", path, json.dumps(body).encode(), h))
        code, _, raw = split_resp(out)
        return code, json.loads(raw)

    def test_kind_req_stored_only_when_given_and_validated(self):
        q = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
                       dict(self.S))
        f = self.add()
        self.assertEqual(self.pin(q)["kind_req"], "question")
        self.assertNotIn("kind_req", self.pin(f))                 # 옛 호출(에이전트 curl)은 필드가 없다 = 수정 요청
        with self.assertRaises(ps.HTTPError) as cm:
            ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "kind_req": "ask"}, dict(self.S))
        self.assertEqual(cm.exception.code, 400)

    def test_edit_switches_kind_even_on_closed_pin(self):
        pid = self.add()
        p = ps.edit_pin(pid, {"kind_req": "question", "base_rev": 0}, dict(self.S))
        self.assertEqual(p["kind_req"], "question")
        ps.set_done(pid, True, dict(self.S))
        p = ps.edit_pin(pid, {"kind_req": "fix", "base_rev": self.pin(pid)["rev"]}, dict(self.S))
        self.assertEqual(p["kind_req"], "fix")

    def test_reply_endpoint_appends_message_with_header_identity(self):
        pid = self.add()
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "  0 은 전 구간 평균입니다\r\n두 번째 줄 "},
                            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]})
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(d["msg"]["id"], 1)
        self.assertEqual(d["msg"]["text"], "0 은 전 구간 평균입니다\n두 번째 줄")   # CRLF → LF, 앞뒤 공백 제거
        self.assertEqual(d["msg"]["by"], {"login": self.S["login"], "name": self.S["name"]})
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "에이전트 답"})
        self.assertEqual(d["msg"]["id"], 2)
        self.assertEqual(d["msg"]["by"]["login"], "local")
        p = self.pin(pid)
        self.assertEqual([m["id"] for m in p["thread"]], [1, 2])
        self.assertFalse(p.get("done"))                          # 답글은 상태를 바꾸지 않는다
        self.assertEqual(p["rev"], 2)

    def test_reply_validation(self):
        pid = self.add()
        for body in ({}, {"text": ""}, {"text": "   "}, {"text": 5}, {"text": "x" * (ps.THREAD_TEXT_MAX + 1)}):
            code, d = self.post("/api/pins/%d/reply" % pid, body)
            self.assertEqual(code, 400, body)
        self.assertNotIn("thread", self.pin(pid))
        code, d = self.post("/api/pins/%d/reply" % pid, {"text": "x" * ps.THREAD_TEXT_MAX})
        self.assertEqual(code, 200)
        code, d = self.post("/api/pins/999/reply", {"text": "없음"})
        self.assertEqual((code, d["ok"], d["pin"]), (200, False, None))   # 없는 id 는 다른 경로와 같은 관례

    def test_control_characters_are_stripped_but_newlines_kept(self):
        self.assertEqual(ps.clean_thread_text("a\x00b\x1b[31m\tc\nd"), "ab[31m\tc\nd")

    def test_thread_is_capped(self):
        pid = self.add()
        with mock.patch.object(ps, "THREAD_MAX", 2):
            ps.reply_pin(pid, "1", dict(self.S))
            ps.reply_pin(pid, "2", dict(self.S))
            with self.assertRaises(ps.HTTPError) as cm:
                ps.reply_pin(pid, "3", dict(self.S))
            self.assertEqual(cm.exception.code, 409)
            ps.set_done(pid, True, dict(self.S), "닫음")          # 상태 전환 기록은 상한과 무관하다
        self.assertEqual([m.get("ev") for m in self.pin(pid)["thread"]], [None, None, "close"])

    def test_close_reply_is_appended_to_thread_once(self):
        pid = self.add()
        ps.reply_pin(pid, "질문이 있어요", dict(self.S))
        ps.set_done(pid, True, dict(self.S), "제목을 고침", "PR #227")
        ps.set_done(pid, True, dict(self.S), "두 번째 닫기")      # 이미 닫힘 — 아무것도 붙지 않는다
        th = self.pin(pid)["thread"]
        self.assertEqual([(m["id"], m.get("ev"), m["text"], m.get("ref")) for m in th],
                         [(1, None, "질문이 있어요", None), (2, "close", "제목을 고침", "PR #227")])
        self.assertEqual(self.pin(pid)["close_reply"], "제목을 고침")   # 옛 필드도 그대로 남는다(옛 뷰어·에이전트 호환)

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
        self.assertNotIn("state", ps.read_pins()[0][0])           # 계산 필드 — 저장하지 않는다

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
                  "close_reply": "고침", "anchor": ps.anchor_of(ps.tex_lines(self.main), 4, 5),
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
        q = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "구간의 정의는?", "kind_req": "question"},
                       dict(self.S))
        for i in range(5):
            ps.reply_pin(q, "답글 %d\n둘째 줄 | 파이프" % i, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(l for l in md.splitlines() if l.startswith("| %d " % q))
        self.assertIn("| %d · 질문 |" % q, row)
        self.assertIn("[스레드 5건, 앞 2건은 GET /api/pins/%d]" % q, row)
        self.assertIn("Bob Park: 답글 4 둘째 줄 \\| 파이프", row)   # 줄바꿈은 접고 | 는 이스케이프
        self.assertNotIn("답글 1", row)
        self.assertEqual(row.count("|") - row.count("\\|"), 6)          # 5열 표 그대로
        self.assertIn("/api/pins/N/reply", md)
        self.assertIn("'질문' = 고칠 곳이 아니라 물음이다", md)
        ps.set_done(q, True, dict(self.S), "답했다")
        ps.set_done(q, False, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(l for l in md.splitlines() if l.startswith("| %d " % q))
        self.assertNotIn("[스레드", row)                                  # 닫기 전 차례의 글은 싣지 않는다


class FrontendThread(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def run_js(self, script, layout="wide"):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            function who(a){return (a&&(a.name||a.login))||'';} function avatar(){return '<i class="av"></i>';}
            let LAYOUT='%s', REPLY=null, META=null; const THREAD_OPEN=new Set();
            """ % layout, js_icons(), extract_js_fn("arcTime"), js_thread(), script])
        return json.loads(run_node(js))

    def test_wide_shows_last_three_compact_shows_last_one(self):
        out = self.run_js(r"""
            const th=[1,2,3,4,5].map(i=>({id:i,by:{name:'S'},at:'2026-09-24 10:0'+i+':00',text:'m'+i}));
            const p={id:9,thread:th};
            const w=threadHtml(p,true), c=threadHtml(p,false); THREAD_OPEN.add(9); const all=threadHtml(p,false);
            const n=s=>(s.match(/class="msg"/g)||[]).length;
            console.log(JSON.stringify([n(w),/이전 2건 보기/.test(w),/m5/.test(w),/m2/.test(w),n(c),/이전 4건 보기/.test(c),/m5/.test(c),
              n(all),/스레드 접기/.test(all),threadHtml({id:1},true)]));
            """)
        self.assertEqual(out, [3, True, True, False, 1, True, True, 5, True, ""])

    def test_messages_escape_and_events_read_as_history(self):
        out = self.run_js(r"""
            const a=msgHtml({id:1,by:{name:'<b>x</b>'},at:'2026-09-24 10:00:00',text:'<img src=x onerror=1>'});
            const b=msgHtml({id:2,by:{name:'로컬/에이전트'},at:'2026-09-24 10:05:00',text:'고쳤다',ev:'close',ref:'PR #9'});
            const c=msgHtml({id:3,by:{name:'S'},at:'2026-09-24 10:06:00',text:'',ev:'confirm'});
            console.log(JSON.stringify([/&lt;img/.test(a),!/<img/.test(a),/&lt;b&gt;x/.test(a),/class="msg ev ev-close"/.test(b),
              /닫음 · PR #9/.test(b),/>고쳤다</.test(b),/>확인</.test(c),!/msg-t/.test(c),/09-24 10:05/.test(b)]));
            """)
        self.assertEqual(out, [True] * 9)

    def test_reply_slot_rendered_for_open_editor(self):
        out = self.run_js(r"""
            REPLY={id:4,mode:'reply'};
            console.log(JSON.stringify([/reply-slot/.test(threadHtml({id:4},true)),threadHtml({id:5},true)]));
            """)
        self.assertEqual(out, [True, ""])

    def test_card_has_question_badge_reply_button_and_thread_count(self):
        body = extract_js_fn("card")
        self.assertIn("if(isQuestion(p))tags.unshift(", body)
        self.assertIn('data-act="reply-open"', body)
        self.assertIn("threadHtml(p,LAYOUT==='wide')", body)
        self.assertIn("ic('message-square')", body)

    def test_reply_editor_survives_redraw_and_save_sends_kind(self):
        dp = extract_js_fn("drawPins")
        self.assertIn("slot.replaceWith(REPLY.el)", dp)
        self.assertIn("rta.focus()", dp)
        self.assertIn("body.kind_req=KIND_NEW;", extract_js_fn("savePin"))
        self.assertIn("setKind('fix')", extract_js_fn("cancelSelection"))
        self.assertIn("KIND_NEW==='question'?'무엇이 궁금한지 적어 주세요'", extract_js_fn("setKind"))
        self.assertIn("if(REPLY){closeReply();return;}", ps.HTML)          # Esc 가 입력 칸부터 닫는다
        self.assertIn('id="c-kind"', ps.HTML)
        send = extract_js_fn("sendReply")
        self.assertIn("'/api/pins/'+R.id+'/'+(R.mode==='reopen'?'reopen':'reply')", send)
        self.assertIn("{reason:text}", send)

    def test_compact_collapsed_card_hides_thread(self):
        css = ps.HTML[ps.HTML.index("<style>"):ps.HTML.index("</style>")]
        self.assertIn("body.compact .pin:not(.open):not(.editing) :is(.tags,.au,.note,.acts,.head>.sp,.thread){display:none}", css)


# ---------------------------------------------------------------- 검토 대기(references/api.md §검토 대기)
# 에이전트가 닫은 핀을 작성자가 다시 연 일이 42건 중 2건(#28·#42)이었고, 사람이 결과를 봤다는 기록이 없었다. 에이전트(신원 헤더 없음)가
# 닫으면 done=true·review=true(검토 대기), 테일넷 사람이 닫으면 바로 완료다. review 가 없는 옛 done:true 는 그대로 완료다.
class ReviewState(Base):
    S = {"login": "bob@example.com", "name": "Bob Park"}
    W = {"login": "alice@example.com", "name": "Alice Kim"}

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
        self.assertEqual(d["state"], "review")                      # 테일넷 주소로 닫는 원격 에이전트
        code, d = self.post("/api/pins/%d/close" % b, {"review": False})
        self.assertEqual(d["state"], "done")
        code, d = self.post("/api/pins/%d/close" % self.add(), {"review": "yes"})
        self.assertEqual(code, 400)

    def test_review_pins_are_not_open_for_agents(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), "고침")
        _, _, raw = split_resp(self.talk(req("GET", "/api/pins")))
        self.assertEqual(json.loads(raw), [])                         # 열린 핀 목록(옛 계약)에 없다
        with self.assertRaises(ps.HTTPError) as cm:
            ps.claim_pin(pid, dict(ps.LOCAL_ACTOR), 30)
        self.assertEqual(cm.exception.body["error"], "done")
        m = ps.meta(dict(ps.LOCAL_ACTOR))
        self.assertEqual((m["n_open"], m["n_review"], m["n_done"]), (0, 1, 0))

    def test_confirm_and_idempotence(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), "고침")
        W = {"Tailscale-User-Login": self.W["login"], "Tailscale-User-Name": self.W["name"]}
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["state"]), (200, "done"))
        p = self.pin(pid)
        self.assertEqual(p["confirmed_by"], self.W)                   # 작성자가 아니어도 확인할 수 있다
        self.assertTrue(p["confirmed_at"])
        self.assertEqual(p["thread"][-1]["ev"], "confirm")
        rev = p["rev"]
        code, d = self.post("/api/pins/%d/confirm" % pid, None, W)
        self.assertEqual((code, d["ok"], self.pin(pid)["rev"]), (200, True, rev))   # 이미 완료 — 그대로
        code, d = self.post("/api/pins/%d/confirm" % self.add(), None, W)
        self.assertEqual((code, d["error"]), (409, "open"))
        code, d = self.post("/api/pins/999/confirm", None, W)
        self.assertEqual((code, d["ok"]), (200, False))

    def test_agent_cannot_confirm(self):
        # 결함 실측: 신원 헤더 없는(에이전트/로컬 curl) 요청이 /confirm 을 성공시켰다 — 검토 대기는 '사람이
        # 봤다'는 기록이라 에이전트 스스로의 확인은 그 취지를 무너뜨린다.
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), "고침")
        code, d = self.post("/api/pins/%d/confirm" % pid)             # 헤더 없음 = 에이전트
        self.assertEqual(code, 403)
        self.assertIn("확인은 사람이 합니다", d.get("error", ""))
        self.assertEqual(ps.pin_state(self.pin(pid)), "review")       # 상태는 바뀌지 않는다
        with self.assertRaises(ps.HTTPError) as cm:
            ps.confirm_pin(pid, dict(ps.LOCAL_ACTOR))
        self.assertEqual(cm.exception.code, 403)

    def test_reopen_with_reason_appends_to_thread_and_clears_review(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), "고침")
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "식 번호가 아직 틀림"},
                            {"Tailscale-User-Login": self.S["login"], "Tailscale-User-Name": self.S["name"]})
        self.assertEqual(d["state"], "open")
        p = self.pin(pid)
        self.assertNotIn("review", p)
        self.assertEqual([(m.get("ev"), m["text"]) for m in p["thread"]], [("close", "고침"), ("reopen", "식 번호가 아직 틀림")])
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(l for l in md.splitlines() if l.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)
        self.assertIn("다시 연 이유(Bob Park): 식 번호가 아직 틀림", row)
        code, d = self.post("/api/pins/%d/reopen" % pid, {"reason": "x" * (ps.THREAD_TEXT_MAX + 1)})
        self.assertEqual(code, 400)
        code, d = self.post("/api/pins/%d/reopen" % pid)              # 본문 없는 옛 reopen 도 된다(이미 열림 — 스레드 그대로)
        self.assertEqual(code, 200)
        self.assertEqual(len(self.pin(pid)["thread"]), 2)

    def test_reopen_after_confirm_drops_confirmation(self):
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR))
        ps.confirm_pin(pid, dict(self.S))
        ps.set_done(pid, False, dict(self.S), reason="다시")
        p = self.pin(pid)
        self.assertNotIn("confirmed_by", p)
        self.assertEqual(ps.pin_state(p), "open")

    def test_legacy_done_is_done_not_review(self):
        self.assertEqual(ps.pin_state({"done": True}), "done")
        self.assertEqual(ps.pin_state({"done": True, "review": False}), "done")
        self.assertEqual(ps.pin_state({"done": True, "review": True}), "review")
        self.assertEqual(ps.pin_state({"review": True}), "open")    # 열린 핀에 남은 review 는 뜻이 없다
        self.assertFalse(ps.valid_rec({"id": 1, "file": str(self.main), "lo": 1, "hi": 1, "review": "y"}))

    def test_pins_md_review_section_and_header(self):
        a = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "note": "q", "kind_req": "question"}, dict(self.S))
        b = self.add(8, 9)
        ps.set_done(a, True, dict(ps.LOCAL_ACTOR), "구간은 0 을 포함 | 유의하지 않음", "PR #12")
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertIn("열린 핀 1건  ·  검토 대기 1건(맨 아래, 처리하지 않는다)  ·  닫힌 핀 0건", md)
        sec = md[md.index("## 검토 대기 1건"):]
        self.assertIn("| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |", sec)
        self.assertIn("| %d · 질문 | `main.tex L4-L5` | Bob Park | 구간은 0 을 포함 \\| 유의하지 않음 (PR #12) |" % a, sec)
        opn = md[:md.index("## 검토 대기")]
        starts = [l.split("|")[1].strip() for l in opn.splitlines() if l.startswith("| ") and not l.startswith("| #")]
        self.assertEqual(starts, [str(b)])                             # 열린 표에는 열린 핀만
        self.assertIn("`\"review\":true`", md)
        self.assertIn("검토 대기 핀은 다시 처리하지 않는다", md)
        ps.confirm_pin(a, dict(self.S))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        self.assertNotIn("## 검토 대기", md)
        self.assertIn("열린 핀 1건  ·  닫힌 핀 1건", md)                # 검토 대기가 없으면 머리줄은 예전 모양


class FrontendReview(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_review_card_suggests_author_and_offers_confirm_reopen(self):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            const T={stale:'s',n:'n',loc:'l',view:'v',edit:'e',close:'c',drop:'d',review:'r',confirm:'k',rvReopen:'o',reply:'y'};
            let EDIT=null, PINS=[], META={me:{login:'bob@example.com',name:'Bob Park'}};
            const OPEN_CARDS=new Set();
            function viaTag(){return null;} function relBadge(){return null;} function claimActive(){return false;}
            function authorTip(){return 'tip';} function who(a){return a?(a.name||a.login):'';} function avatar(){return '';}
            let SHOW_ALL=false, DOCS=[], DOC='main', DEFAULT_DOC='main', LAYOUT='wide', REPLY=null; function docInfo(){return null;}
            const THREAD_OPEN=new Set();
            """, extract_js_fn("rng"), extract_js_fn("multiDoc"), extract_js_fn("pdoc"), extract_js_fn("isRegion"),
            extract_js_fn("locText"), extract_js_fn("locCopy"), extract_js_fn("docChip"), extract_js_fn("arcTime"), js_thread(),
            extract_js_fn("card"), js_icons(), r"""
            const base={id:3,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n',done:true,review:true,state:'review',
              closed_by:{login:'local',name:'로컬/에이전트'},thread:[{id:1,by:{name:'로컬/에이전트'},at:'2026-09-24 10:00:00',text:'고침',ev:'close'}]};
            const mine=card(Object.assign({},base,{author:{login:'bob@example.com',name:'Bob Park'}}));
            const other=card(Object.assign({},base,{author:{login:'w@x',name:'Alice Kim'}}));
            const open=card({id:4,file:'/m.tex',name:'m.tex',lo:1,hi:2,page:1,note:'n'});
            console.log(JSON.stringify([/class="pin card review/.test(mine),/내 확인 차례/.test(mine),/b-confirm btn-soft/.test(mine),
              /Alice Kim님 확인 필요/.test(other),/class="btn-sm b-confirm"/.test(other),/data-act="rv-reopen"/.test(other),
              !/data-act="close"/.test(other),!/data-act="drop"/.test(other),/ev-close/.test(other),!/review/.test(open)]));
            """])
        self.assertEqual(json.loads(run_node(js)), [True] * 10)

    def test_review_toast_and_partition(self):
        js = "\n".join([r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const TOASTS=[]; function toast(m,k){TOASTS.push(m);} function restorePin(){}
            const MY_ACTIONS=new Map();
            """, extract_js_fn("markMine"), extract_js_fn("consumeMine"), extract_js_fn("diffToast"), extract_js_fn("pinState"),
            extract_js_fn("reviewToast"), r"""
            diffToast([{id:1},{id:2}],[{id:1,done:true,review:true},{id:2,done:true}],[]);
            reviewToast([{id:5},{id:6},{id:7}],[{id:5,done:true,confirmed_by:{name:'W'}},{id:6,done:false},{id:7,done:true,review:true}]);
            markMine(8); reviewToast([{id:8}],[{id:8,done:true}]);
            console.log(JSON.stringify(TOASTS));
            """])
        out = json.loads(run_node(js))
        self.assertEqual(out, ["#2 이 완료되었습니다", "#1 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요",
                               "#5 확인됨 · W", "#6 다시 열림"])
        body = extract_js_fn("loadPins")
        self.assertIn("REVIEW_ALL=d.filter(p=>pinState(p)==='review')", body)
        self.assertIn("DONE_ALL=d.filter(p=>pinState(p)==='done')", body)
        self.assertIn('id="sec-review"', ps.HTML)
        self.assertIn('id="side-rv"', ps.HTML)

    def test_review_card_reply_hint_and_reopen_hint(self):
        # 결함 실측: 검토 대기 카드의 답글 칸이 일반 답글과 같은 안내를 써서, 답글을 남겨도 에이전트가
        # 다시 집지 않는다는 사실이 드러나지 않았다(§검토 대기 — 다시 처리하지 않는다).
        body = extract_js_fn("replyEl")
        self.assertIn("review?'에이전트에게 다시 맡기려면 [다시 열기]':'답글", body)
        self.assertIn("mode==='reply'&&!!p&&pinState(p)==='review'", extract_js_fn("openReply"))


# ---------------------------------------------------------------- [변경 보기](references/design.md §변경 보기)
class FrontendChangeView(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def run_js(self, script):
        js = "\n".join([extract_js_fn(n) for n in ("matchRevision", "pinFileIndex", "hunkRanges", "touchesPin", "revisionFiles")]
                       + [script])
        return json.loads(run_node(js))

    def test_ref_picks_commit_by_sha_then_pr_number(self):
        revs = [{"id": "0a569cc" + "1" * 33, "subject": "Clarify experimental questions (#238)"},
                {"id": "2cb7240" + "2" * 33, "subject": "Resolve manuscript viewer pins 19–41 (#236)"},
                {"id": "f47c6bf" + "3" * 33, "subject": "manuscript: 원고 핀 12건 반영 (#235)"},
                {"id": "1d422a6" + "4" * 33, "subject": "Merge pull request #203 from example-lab/docs"}]
        out = self.run_js("const revs=%s; console.log(JSON.stringify(['PR #235 (f47c6bf)','paper PR #236; code PR #75',"
                          "'paper PR #236','#203','PR #999','', 'abcdef1'].map(r=>{const m=matchRevision(r,revs);return m&&[m.id.slice(0,7),m.via];})));"
                          % json.dumps(revs))
        self.assertEqual(out, [["f47c6bf", "sha"], ["2cb7240", "pr"], ["2cb7240", "pr"], ["1d422a6", "pr"], None, None, None])

    def test_pin_file_and_line_overlap(self):
        patch = ("diff --git a/manuscript/1st/x.tex b/manuscript/1st/x.tex\n--- a/manuscript/1st/x.tex\n+++ b/manuscript/1st/x.tex\n"
                 "@@ -10,3 +10,4 @@ ctx\n a\n+b\n c\n d\n@@ -80 +81 @@\n-x\n+y\n"
                 "diff --git a/manuscript/1st/y.tex b/manuscript/1st/y.tex\n@@ -1 +1 @@\n-q\n+r\n")
        out = self.run_js("const f=revisionFiles(%s); console.log(JSON.stringify([pinFileIndex(f,'/home/u/paper/manuscript/1st/x.tex'),"
                          "pinFileIndex(f,'/home/u/paper/manuscript/1st/zz.tex'), hunkRanges(f[0].text),"
                          "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:15,hi:16}), touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:40,hi:41}),"
                          "touchesPin(f,{file:'/p/manuscript/1st/x.tex',lo:84,hi:90}), touchesPin(f,{file:'/p/other.tex',lo:1,hi:1})]));"
                          % json.dumps(patch))
        self.assertEqual(out, [0, -1, [[10, 13], [81, 81]], True, False, True, False])

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('data-act="change"', extract_js_fn("doneCard"))
        self.assertIn('data-act="change"', extract_js_fn("card"))
        self.assertIn("case 'change':if(id!=null)showChange(id);break;", h)
        self.assertIn('id="revision-pin"', h)
        self.assertIn("showRevision(pick.id,'source')", extract_js_fn("loadRevisions"))
        fmt = extract_js_fn("setRevisionFormat")
        self.assertIn("REVISION_PDF_COMMIT!==REVISION_COMMIT", fmt)       # 비교 PDF 는 그 형식을 볼 때만 만든다
        css = h[h.index("<style>"):h.index("</style>")]
        self.assertIn("body.revision-open #revision-view{display:block}", css)   # 접은 폴드에서도 열린다


# ---------------------------------------------------------------- @태그·people.json·events.jsonl(references/api.md §@태그·사람·이벤트)
class MentionsPeopleEvents(Base):
    S = {"login": "bob@example.com", "name": "Bob Park"}
    W = {"login": "alice@example.com", "name": "Alice Kim"}
    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
    HW = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}

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
        ppl = self.people(({"login": "wkim@x.com", "name": "Alice Kim"}, {"login": "sy@x.com", "name": "박서준"}))
        R = ps.resolve_mentions
        self.assertEqual(R("@Bob Park 확인 부탁", ppl), [self.S["login"]])
        self.assertEqual(R("@bob park님 이거요", ppl), [self.S["login"]])            # 대소문자·한글 조사
        self.assertEqual(R("@Bob 봐 주세요", ppl), [self.S["login"]])               # 이름 첫 단어(하나뿐)
        self.assertEqual(R("@Alice 어때요", ppl), [])                                   # 첫 단어가 둘 — 모호하면 풀지 않는다
        self.assertEqual(R("@Alice 어때요", ppl, [self.W["login"]]), [self.W["login"]])  # 뷰어가 고른 힌트로 가른다
        self.assertEqual(R("메일 bob@example.com 로", ppl), [])                     # 메일 주소는 태그가 아니다
        self.assertEqual(R("@Bobx", ppl), [])                                         # 영문 이름 뒤 영문 = 다른 말
        self.assertEqual(R("@박서준님 @Alice Kim @박서준", ppl), ["sy@x.com", self.W["login"]])
        self.assertEqual(R("@nobody", ppl), [])

    def test_people_json_records_humans_only_and_throttles(self):
        self.assertFalse(ps.record_person(dict(ps.LOCAL_ACTOR)))
        self.assertFalse(ps.C.people_file.exists())
        self.assertTrue(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1000))
        self.assertFalse(ps.record_person(dict(self.S, pic="https://p/s.png"), now=1100))   # 10분 안 같은 값 — 쓰지 않는다
        self.assertTrue(ps.record_person(dict(self.S, name="Bob P."), now=1101))        # 이름이 바뀌면 쓴다
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
        with mock.patch.object(ps.os, "replace", side_effect=OSError("disk full")):
            self.assertFalse(ps.record_person(dict(self.W), now=2000))
        self.assertEqual(ps.C.people_file.read_bytes(), before)         # 옛 파일 그대로(반쪽 파일 없음)
        with mock.patch.object(ps.os, "replace", side_effect=OSError("disk full")):
            ps.emit_events([{"type": "mention", "pin": 1, "to": ["x"]}])
        self.assertFalse(ps.C.events_file.exists())

    def test_viewer_open_records_person_and_people_api_merges_pin_actors(self):
        self.talk(req("GET", "/", headers=self.HW))
        self.talk(req("GET", "/api/meta?light=1", headers=self.HS))     # 폴링은 쓰지 않는다
        self.assertEqual([p["login"] for p in ps.load_people()], [self.W["login"]])
        ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "x"}, dict(self.S))
        code, _, raw = split_resp(self.talk(req("GET", "/api/people", headers=self.HW)))
        d = json.loads(raw)
        self.assertEqual(sorted(p["login"] for p in d["people"]), sorted([self.S["login"], self.W["login"]]))
        self.assertEqual(d["me"]["login"], self.W["login"])
        self.assertNotIn("local", [p["login"] for p in d["people"]])

    def test_mentions_stored_on_pin_and_message_with_events(self):
        ps.record_person(dict(self.W))
        code, d = self.post("/api/pin", {"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "kind_req": "question",
                                        "note": "@Alice Kim 구간의 정의는?"}, self.HS)
        pid = d["id"]
        p = self.pin(pid)
        self.assertEqual(p["mentions"], [self.W["login"]])
        self.assertEqual(p["note"], "@Alice Kim 구간의 정의는?")       # 글은 그대로
        ev = self.events()
        self.assertEqual([(e["type"], e["pin"], e["to"], e["by"]["login"]) for e in ev],
                         [("mention", pid, [self.W["login"]], self.S["login"])])
        self.assertEqual(ev[0]["kind_req"], "question")
        self.assertEqual(ev[0]["seq"], 1)
        self.assertIn("구간의 정의는?", ev[0]["excerpt"])
        # 에이전트 답글 → 작성자와 불린 사람에게 replied
        self.post("/api/pins/%d/reply" % pid, {"text": "구간은 95% 신뢰구간입니다"})
        e = self.events()[-1]
        self.assertEqual((e["type"], sorted(e["to"]), e["msg"]), ("replied", sorted([self.S["login"], self.W["login"]]), 1))
        # 불린 사람이 답하면 자기 자신은 빠진다
        self.post("/api/pins/%d/reply" % pid, {"text": "@Bob Park 맞아요"}, self.HW)
        types = [(x["type"], x["to"]) for x in self.events()[2:]]
        self.assertEqual(types, [("mention", [self.S["login"]])])       # 이 글로 불린 작성자는 mention 하나만(replied 와 겹치지 않는다)
        self.assertEqual(self.pin(pid)["thread"][-1]["mentions"], [self.S["login"]])
        # 에이전트가 닫으면 작성자에게 review_requested, 작성자가 이유와 함께 다시 열면 reopened 는 자기 자신이라 없다
        self.post("/api/pins/%d/close" % pid, {"reply": "답함"})
        self.assertEqual(self.events()[-1]["type"], "review_requested")
        self.assertEqual(self.events()[-1]["to"], [self.S["login"]])
        n = len(self.events())
        self.post("/api/pins/%d/reopen" % pid, {"reason": "@Alice Kim 한 번 더 봐 주세요"}, self.HS)
        tail = self.events()[n:]
        self.assertEqual([(x["type"], x["to"]) for x in tail], [])       # 민수은 이미 불렸고, 작성자는 자기 자신
        self.post("/api/pins/%d/close" % pid, {"reply": "다시 답함"})
        self.post("/api/pins/%d/reopen" % pid, {"reason": "아직"}, self.HW)
        self.assertEqual((self.events()[-1]["type"], self.events()[-1]["to"]), ("reopened", [self.S["login"]]))
        seqs = [x["seq"] for x in self.events()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_edit_adds_mention_event_only_for_new_names(self):
        ps.record_person(dict(self.W)); ps.record_person(dict(self.S))
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Alice Kim 봐 주세요"}, dict(ps.LOCAL_ACTOR))
        ps.edit_pin(pid, {"note": "@Alice Kim @Bob Park 봐 주세요", "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual([(e["type"], e["to"]) for e in self.events()],
                         [("mention", [self.W["login"]]), ("mention", [self.S["login"]])])
        ps.edit_pin(pid, {"note": "그냥 메모", "base_rev": 1}, dict(ps.LOCAL_ACTOR))
        self.assertNotIn("mentions", self.pin(pid))

    def test_pins_md_marks_human_addressed_pins_and_tells_agents_to_skip(self):
        ps.record_person(dict(self.W))
        a = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Alice Kim 이 구간 맞나요?", "kind_req": "question"},
                       dict(self.S))
        self.add(8, 9)
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(l for l in md.splitlines() if l.startswith("| %d " % a))
        self.assertIn("| %d · → @Alice Kim · 질문 |" % a, row)   # 우선순위: 다시 열림 > → @ > 질문
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("명시적으로 시키지 않으면 건너뛴다", md)
        rows = ps.pins_payload(ps.snapshot_pins(), True)
        self.assertEqual(next(r for r in rows if r["id"] == a)["addressed"], [self.W["login"]])

    # ---- 담당(assignee) — references/api.md §담당. 글에서 짐작하던 건너뛰기 규칙이 모호했다(A-DEMO #43).
    def test_assignee_person_is_addressed_agent_is_fyi_and_legacy_falls_back(self):
        ps.record_person(dict(self.W)); ps.record_person(dict(self.S))
        note = "이거 콜링 제대로 작동하나 @Bob Park 확인 부탁합니다"
        legacy = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": note}, dict(self.W))
        person = ps.add_pin({"file": str(self.main), "lo": 8, "hi": 9, "note": note, "assignee": self.S["login"]}, dict(self.W))
        agent = ps.add_pin({"file": str(self.main), "lo": 2, "hi": 3, "note": "@Bob Park 질문 참고", "kind_req": "question",
                            "assignee": "agent"}, dict(self.W))
        rows = {r["id"]: r for r in ps.pins_payload(ps.snapshot_pins(), True)}
        self.assertNotIn("assignee", rows[legacy])                        # 옛 핀: 필드 없음 → #87 추론(수정 요청 = 참고)
        self.assertEqual((rows[legacy]["addressed"], rows[legacy]["fyi"]), ([], [self.S["login"]]))
        self.assertEqual((rows[person]["addressed"], rows[person]["fyi"]), ([self.S["login"]], []))
        self.assertEqual((rows[agent]["addressed"], rows[agent]["fyi"]), ([], [self.S["login"]]))   # 질문이어도 담당이 에이전트면 참고
        md = ps.C.pins_md.read_text(encoding="utf-8")
        line = lambda i: next(l for l in md.splitlines() if l.startswith("| %d " % i))
        self.assertIn("| %d · 참고 @Bob Park |" % legacy, line(legacy))
        self.assertIn("| %d · → @Bob Park |" % person, line(person))
        self.assertIn("| %d · 참고 @Bob Park · 질문 |" % agent, line(agent))
        self.assertIn("`→ @이름` 이 붙은 핀 1건은 담당이 사람인", md)
        self.assertIn("'→ @이름' = 담당이 사람인 핀", md)

    def test_assignee_validation_and_events(self):
        ps.record_person(dict(self.W)); ps.record_person(dict(self.S))
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
                         [("assigned", (self.S["login"],)), ("mention", (self.S["login"],))])   # 불린 사람은 알림도 받는다
        self.assertNotIn("thread", self.pin(pid))                        # 만들 때의 담당은 스레드 기록이 아니다
        # 담당을 에이전트로 바꾸면 ev=assign 이 남고 이벤트는 없다. 다시 사람으로 바꾸면 assigned.
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
        self.assertIn("담당 바꿈(Alice Kim): 담당: @Bob Park", md)
        self.assertIn("assigned", ps.NOTIFY_TYPES)

    def test_legacy_pins_read_without_rewrite(self):
        ps.record_person(dict(self.S))
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Bob Park 확인 부탁"}, dict(self.W))
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
        self.assertEqual(ps.addressed_to(r), ["b"])
        self.assertEqual(ps.pin_mentions_all(r), ["a", "b"])
        self.assertEqual(ps.fyi_mentions_to(r), [])       # 질문 핀은 fyi 가 아니라 addressed 로만 잡힌다
        fix = dict(r, kind_req="fix")
        self.assertEqual(ps.addressed_to(fix), [])         # 수정 요청 핀은 @태그가 있어도 건너뛰지 않는다
        self.assertEqual(ps.fyi_mentions_to(fix), ["b"])   # 대신 참고용으로만 잡힌다

    def test_reopen_after_confirm_marks_reopened_symbol_not_just_first_round_msg(self):
        # 결함 실측: 확인(confirm) 뒤 다시 열면 차례가 [confirm, reopen, ...] 로 시작해 '다시 열림' 표시가
        # 빠졌다(옛 판정은 '차례의 첫 글이 reopen 인가'만 봤다). pin_reopened_in_round() 는 confirm 을 건너뛴다.
        pid = self.add()
        ps.set_done(pid, True, dict(ps.LOCAL_ACTOR), "고침")
        ps.confirm_pin(pid, dict(self.S))
        ps.set_done(pid, False, dict(self.S), reason="다시 봐 주세요")
        self.assertTrue(ps.pin_reopened_in_round(self.pin(pid)))
        md = ps.C.pins_md.read_text(encoding="utf-8")
        row = next(l for l in md.splitlines() if l.startswith("| %d " % pid))
        self.assertIn("다시 열림", row)

    def test_self_mention_never_becomes_addressed(self):
        ps.record_person(dict(self.W)); ps.record_person(dict(self.S))
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "note": "@Alice Kim 셀프 태그",
                          "kind_req": "question"}, dict(self.W))
        p = self.pin(pid)
        self.assertNotIn("mentions", p)                    # 자기 자신 @태그는 저장되지 않는다
        self.assertEqual(ps.addressed_to(p), [])
        msg = ps.reply_pin(pid, "@Bob Park 님 확인 부탁드립니다 @Alice Kim", dict(self.W))[1]
        self.assertEqual(msg["mentions"], [self.S["login"]])  # 답글 글쓴이 자신(W)은 빠진다

    def test_mention_hints_validated(self):
        with self.assertRaises(ps.HTTPError):
            ps.clean_mention_hints("x")
        with self.assertRaises(ps.HTTPError):
            ps.clean_mention_hints(["a"] * (ps.MENTION_MAX + 1))
        self.assertEqual(ps.clean_mention_hints(None), [])

    def test_events_are_capped_but_seq_keeps_rising(self):
        with mock.patch.object(ps, "EVENTS_KEEP", 3):
            for i in range(5):
                ps.emit_events([{"type": "mention", "pin": i, "to": ["x"]}])
        self.assertEqual([e["seq"] for e in self.events()], [3, 4, 5])


class FrontendMentions(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def run_js(self, script):
        js = "\n".join([r"""
            const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
            let PEOPLE=[{login:'w@x',name:'Alice Kim'},{login:'wo@x',name:'Alice'},{login:'s@x',name:'Bob Park'},{login:'k@x',name:'김<b>'}];
            let META={me:{login:'s@x',name:'Bob Park'}};
            function threadOf(p){return Array.isArray(p&&p.thread)?p.thread:[];}
            const PINSET={12:1,3:1}; function findAnyPin(id){return PINSET[id]?{id}:null;} let DROPPED=[{id:40}];
            function ic(n){return '<svg class="ic ic-'+n+'"></svg>';}
            """] + [extract_js_fn(n) for n in ("peopleName", "mentionToks", "reEsc", "meLogin", "pinRefExists", "fmtText", "mentionsMe",
                                               "mentionQuery", "mentionMatches", "mentionHints", "mentionScan", "defaultAssignee", "assignPeople")]
            + [script])
        return json.loads(run_node(js))

    def test_highlight_does_not_double_wrap_and_escapes(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Alice Kim 와 @Alice <i>',['w@x','wo@x']), fmtText('@김<b> 안녕',['k@x']),
              fmtText('@Bob Park',[])]));""")
        tip = lambda n: ' data-tip="@태그 — %s에게 알림이 갑니다"' % n
        self.assertEqual(out, ['<span class="mention"%s>@Alice Kim</span> 와 <span class="mention"%s>@Alice</span> &lt;i&gt;' % (tip("Alice Kim"), tip("Alice")),
                               '<span class="mention"%s>@김&lt;b&gt;</span> 안녕' % tip("김&lt;b&gt;"), '@Bob Park'])

    def test_mention_of_me_is_stronger_and_unresolved_stays_plain(self):
        # 저자 지적(2026-09-24): 부른 것인지 평문인지 구분이 안 됐다. 풀린 태그만 토큰, 나를 부르면 .me, 풀리지 않은 '@말'은 평문.
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText('@Bob Park 봐 주세요 @홍길동',['s@x']), fmtText('mail a@Bob Park',['s@x']),
              fmtText('@Bob Parkx',['s@x']), fmtText('@bob park',['s@x'])]));""")
        self.assertEqual(out[0], '<span class="mention me" data-tip="나를 부름 — 이 핀 알림이 나에게 옵니다">@Bob Park</span> 봐 주세요 @홍길동')
        self.assertEqual(out[1], 'mail a@Bob Park')                       # 메일 주소 모양은 태그가 아니다
        self.assertNotIn("mention", out[2])                                   # 이름 뒤에 영문이 이어지면 다른 말
        self.assertIn('class="mention me"', out[3])                          # 대소문자 없이(서버와 같다)

    def test_pin_refs_link_only_existing_pins_and_skip_entities(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([fmtText("#12 과 #99 그리고 it's (#3) #40",[]), fmtText('a#12 &#12;',[])]));""")
        self.assertEqual(out[0].count('data-act="pin-ref"'), 3)             # 12·3·40(삭제한 핀) — 없는 99 는 평문
        self.assertIn('data-ref="12"', out[0]); self.assertIn('data-ref="40"', out[0]); self.assertNotIn('data-ref="99"', out[0])
        self.assertIn("it&#39;s", out[0])                                     # 이스케이프 &#39; 는 링크가 아니다
        self.assertNotIn("pin-ref", out[1])

    def test_scan_lists_who_gets_notified_and_unresolved_words(self):
        out = self.run_js(r"""
            console.log(JSON.stringify([mentionScan('@Bob Park 와 @홍길동 그리고 @Alice Kim',new Set()), mentionScan('a@b.com',new Set()),
              mentionScan('@Alice 봐',new Set(['wo@x']))]));""")
        self.assertEqual(out[0], {"hit": ["s@x", "w@x"], "bad": ["홍길동"], "first": "s@x"})
        self.assertEqual(out[1], {"hit": [], "bad": [], "first": None})
        self.assertEqual(out[2]["hit"][0], "wo@x")

    def test_default_assignee_rules(self):
        # 메모가 풀린 @태그로 시작하면 그 사람 · 아니면 질문 핀의 첫 @태그 · 아니면 에이전트. 나(s@x)는 고를 수 없다.
        out = self.run_js(r"""
            console.log(JSON.stringify([
              defaultAssignee('@Alice Kim 확인 부탁','fix',new Set()),
              defaultAssignee('  @Alice Kim 확인 부탁','fix',new Set()),
              defaultAssignee('이거 콜링 작동하나 @Alice Kim 확인 부탁','fix',new Set()),
              defaultAssignee('이 구간이 뭔가요 @Alice Kim','question',new Set()),
              defaultAssignee('@Bob Park 메모','fix',new Set()),
              defaultAssignee('@Bob Park @Alice Kim 뭔가요','question',new Set()),
              defaultAssignee('@홍길동 확인','fix',new Set()),
              defaultAssignee('그냥 메모','question',new Set()),
              assignPeople('@Bob Park @Alice Kim 봐 주세요',new Set()),
              assignPeople('메모',new Set(),'k@x')]));""")
        self.assertEqual(out, ["w@x", "w@x", "agent", "w@x", "agent", "w@x", "agent", "agent", ["w@x"], ["k@x"]])

    def test_assign_controls_in_composer_edit_and_card(self):
        h = ps.HTML
        self.assertIn('<div id="c-assign" class="assign-row" role="radiogroup" aria-label="담당" hidden></div>', h)
        self.assertIn("'<div class=\"e-assign assign-row\" role=\"radiogroup\" aria-label=\"담당\" hidden></div>'", h)
        self.assertIn("body.assignee=ASSIGN_NEW.v||'agent';", extract_js_fn("savePin"))
        self.assertIn("if(E.assignee&&E.assignee!==E.orig.assignee)body.assignee=E.assignee;", extract_js_fn("saveEdit"))
        self.assertIn("assignChip(p)+thn+au", extract_js_fn("card"))
        self.assertIn("const adr=p.assignee?'':addressedTag(p);", extract_js_fn("card"))
        self.assertIn("assigned:5", h)
        self.assertIn("assign:'담당 바꿈'", h)

    def test_preview_row_under_every_mention_field(self):
        h = ps.HTML
        self.assertIn('<div id="note-mentions" class="m-preview" aria-live="polite" hidden></div>', h)
        self.assertEqual(h.count('</textarea><div class="m-preview" aria-live="polite" hidden></div>'), 2)   # 편집·답글
        body = extract_js_fn("mentionPreview")
        self.assertIn("등록된 사람이 아님", body)
        self.assertIn("ic('at-sign')+'알림</span>'", body)
        css = h[h.index("<style>"):h.index("</style>")]
        self.assertRegex(css, r"\.mention\{color:var\(--primary\);font-weight:600;background:color-mix\(in srgb,var\(--primary\) 12%")
        self.assertIn(".mention.me{background:color-mix(in srgb,var(--primary) 28%", css)
        self.assertIn(".mention-bad{", css)

    def test_query_matches_and_hints(self):
        out = self.run_js(r"""
            const ta=(v,pos)=>({value:v,selectionStart:pos==null?v.length:pos,selectionEnd:pos==null?v.length:pos});
            const q=[mentionQuery(ta('안녕 @Won')),mentionQuery(ta('mail a@b')),mentionQuery(ta('@')),mentionQuery(ta('@Won ch'))];
            const m=mentionMatches('won',PEOPLE,'s@x').map(p=>p.login), mine=mentionMatches('',PEOPLE,'s@x').map(p=>p.login);
            const t=ta('@Alice Kim 봐 주세요'); t._mentions=new Set(['w@x','s@x']);
            console.log(JSON.stringify([q,m,mine.includes('s@x'),mentionHints(t),
              mentionsMe({addressed:['s@x']}),mentionsMe({addressed:['w@x']}),mentionsMe({mentions:['s@x'],thread:[{mentions:['s@x']}]})]));""")
        self.assertEqual(out, [[{"start": 3, "q": "Won"}, None, {"start": 0, "q": ""}, None], ["wo@x", "w@x"], False,
                               ["w@x"], True, False, False])
        # mentionsMe 는 서버가 미리 계산한 p.addressed(질문 핀·현재 차례)만 본다 — 옛 mentions/thread 전체 훑기가 아니다
        # (결함 실측: 옛 차례의 @태그가 다시 열려도 계속 '나를 부른 핀'으로 남았다).

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('id="mention-pop"', h)
        self.assertIn('id="mention-filter"', h)
        self.assertIn("const mh=mentionHints($('#note')); if(mh.length)body.mentions=mh;", extract_js_fn("savePin"))
        self.assertIn("mentionHints(ta)", extract_js_fn("sendReply"))
        self.assertIn("fmtText(p.note,p.mentions)", extract_js_fn("card"))
        self.assertIn("window.addEventListener('keydown',e=>{if(!MENTION.ta", h)   # 자동 완성이 Enter·Esc 를 먼저 받는다(capture)


# ---------------------------------------------------------------- 브라우저 알림(references/design.md §브라우저 알림)
class NotifyServer(Base):
    HS = {"Tailscale-User-Login": "bob@example.com", "Tailscale-User-Name": "Bob Park"}
    HW = {"Tailscale-User-Login": "alice@example.com", "Tailscale-User-Name": "Alice Kim"}

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
        self.assertIn("postMessage({type:'open-pin'", js)
        self.assertNotIn("'fetch'", js)                                   # 앱 데이터를 캐시하지 않는다
        code, _, _ = self.get("/sw.js", {"Host": "evil.example"})
        self.assertEqual(code, 403)
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_event_cursor_in_light_meta(self):
        ps.emit_events([{"type": "mention", "pin": 1, "doc": "main", "to": ["alice@example.com"], "by": {"login": "bob@example.com"}},
                        {"type": "replied", "pin": 1, "doc": "main", "to": ["bob@example.com"], "by": {"login": "local"}},
                        {"type": "mention", "pin": 2, "doc": "main", "to": ["alice@example.com"], "by": {"login": "alice@example.com"}}])
        _, _, raw = self.get("/api/meta?light=1", self.HW)
        d = json.loads(raw)
        self.assertEqual(d["ev_seq"], 3)
        self.assertNotIn("events", d)                                     # 커서 없이는 싣지 않는다
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual([(e["seq"], e["type"], e["doc_name"]) for e in json.loads(raw)["events"]], [(1, "mention", "본문")])
        _, _, raw = self.get("/api/meta?light=1&ev=1", self.HW)
        self.assertEqual(json.loads(raw)["events"], [])                   # 자기 자신이 한 일(seq 3)은 오지 않는다
        _, _, raw = self.get("/api/meta?light=1&ev=0", self.HS)
        self.assertEqual([e["seq"] for e in json.loads(raw)["events"]], [2])
        _, _, raw = self.get("/api/meta?light=1&ev=0")
        self.assertEqual(json.loads(raw)["events"], [])                   # 로컬/에이전트에게는 싣지 않는다
        code, _, _ = self.get("/api/meta?light=1&ev=x", self.HW)
        self.assertEqual(code, 400)
        before = sorted(p.name for p in ps.C.state.iterdir())
        self.get("/api/meta?light=1&ev=0", self.HW)
        self.assertEqual(sorted(p.name for p in ps.C.state.iterdir()), before)   # 폴링은 쓰지 않는다


class FrontendNotify(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def harness(self, script):
        rank = re.search(r"^const NOTIFY_RANK=.*;$", ps.HTML, re.M).group(0)
        return "\n".join([rank, r"""
            function who(a){return (a&&(a.name||a.login))||'';}
            const store={}; const localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v);}};
            let NOTIFY=true; function notifyOn(){return NOTIFY;}
            let META={me:{login:'w@x',name:'Alice Kim'},label:'DEMO-B'}; const SHOWN=[];
            function notifyShow(e){SHOWN.push([e.pin,e.type]);}
            """] + [extract_js_fn(n) for n in ("notifyCursor", "setNotifyCursor", "notifyQuery", "pickNotifications",
                                               "notifyText", "notifyHandle")] + [script])

    def test_trigger_selection_self_suppression_and_dedupe(self):
        js = self.harness(r"""
            const me={login:'w@x'}, S={login:'s@x',name:'Bob Park'};
            const evs=[{seq:1,type:'replied',pin:5,to:['w@x'],by:S},{seq:2,type:'mention',pin:5,to:['w@x'],by:S},
              {seq:3,type:'review_requested',pin:6,to:['w@x'],by:{login:'local'}},{seq:4,type:'replied',pin:7,to:['s@x'],by:S},
              {seq:5,type:'mention',pin:8,to:['w@x'],by:{login:'w@x'}},{seq:6,type:'confirmed',pin:9,to:['w@x'],by:S},
              {seq:7,type:'reopened',pin:6,to:['w@x'],by:S}];
            const a=pickNotifications(evs,me,0).map(e=>[e.pin,e.type]);
            const b=pickNotifications(evs,me,2).map(e=>[e.pin,e.type]);
            const c=pickNotifications(evs,{login:'local'},0);
            console.log(JSON.stringify([a,b,c,notifyText(evs[1]),notifyText({type:'review_requested',pin:6,excerpt:'답했다\n둘째',doc_name:'본문'})]));
            """)
        out = json.loads(run_node(js))
        self.assertEqual(out[0], [[5, "mention"], [6, "reopened"]])          # 핀마다 하나 — 부름·다시 엶이 이긴다
        self.assertEqual(out[1], [[6, "reopened"]])
        self.assertEqual(out[2], [])
        self.assertEqual(out[3], {"title": "핀 #5 · DEMO-B", "body": "Bob Park님이 불렀습니다: "})
        self.assertEqual(out[4], {"title": "핀 #6 · 본문", "body": "검토 대기: 답했다"})

    def test_cursor_prevents_refire_across_reloads_and_tabs(self):
        js = self.harness(r"""
            const S={login:'s@x',name:'S'};
            notifyHandle({ev_seq:4});                                   // 처음 켠 브라우저 — 지난 이벤트는 건너뛴다
            const c0=notifyCursor(), q=notifyQuery();
            const d={ev_seq:6,events:[{seq:5,type:'mention',pin:1,to:['w@x'],by:S},{seq:6,type:'replied',pin:2,to:['w@x'],by:S}]};
            notifyHandle(d);                                            // 탭 A
            notifyHandle(d);                                            // 탭 B 가 같은 응답을 늦게 받음(같은 localStorage)
            notifyHandle({ev_seq:6,events:[]});                         // 새로고침 뒤
            NOTIFY=false; notifyHandle({ev_seq:9,events:[{seq:9,type:'mention',pin:3,to:['w@x'],by:S}]});
            console.log(JSON.stringify([c0,q,SHOWN,notifyCursor(),notifyQuery()]));
            """)
        self.assertEqual(json.loads(run_node(js)), [4, "&ev=4", [[1, "mention"], [2, "replied"]], 6, ""])

    def test_wiring(self):
        h = ps.HTML
        self.assertIn('id="m-notify"', h)
        self.assertIn('id="btn-notify"', h)
        tog = extract_js_fn("notifyToggle")
        self.assertIn("Notification.requestPermission()", tog)
        self.assertEqual(html_without_comments(h).count("requestPermission("), 1)   # 클릭 경로에서만 묻는다
        self.assertIn("reg.showNotification(", extract_js_fn("notifyShow"))
        self.assertNotIn("new Notification(", html_without_comments(h))
        self.assertIn("tag:'pin-'+e.pin", extract_js_fn("notifyShow"))
        self.assertIn("document.visibilityState==='visible'&&document.hasFocus()", extract_js_fn("notifyShow"))
        self.assertIn("notifyQuery()", extract_js_fn("pollLightOnce"))
        self.assertIn("navigator.serviceWorker.register('/sw.js'", extract_js_fn("notifyRegister"))
