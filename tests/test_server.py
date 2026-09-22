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

    def test_origin_ok_matches_actual_host_port_not_server_port(self):
        # 결함(P0b 수선): origin_ok 가 루프백 Origin 의 포트를 언제나 서버 자신의 바인딩 포트(C.port)와
        # 비교했다. SSH -L 로 다른 로컬 포트에 포워딩하면(예: 9000 → 18999) 브라우저는 Host 도 Origin 도
        # 포워딩 포트(9000)로 보낸다 — host_ok 는 루프백 포트를 안 보므로 GET 은 통과하지만, origin_ok 가
        # 9000 != 18999 로 POST 를 전부 403 처리했다. 이제는 Origin 의 포트를 '이 요청이 실제로 실린 Host'
        # 의 포트와 맞춘다(브라우저 기준 동일 출처) — 교차 포트 출처(다른 로컬 앱 등)는 여전히 막는다.
        self.assertTrue(ps.origin_ok("http://127.0.0.1:9000", "localhost:9000"))    # 포워딩 포트끼리는 동일 출처
        self.assertTrue(ps.origin_ok("http://localhost:18999", "127.0.0.1:18999"))  # 포워딩 없는 직접 접속도 그대로
        self.assertFalse(ps.origin_ok("http://127.0.0.1:3000", "localhost:9000"))   # Host 와도 다른 포트는 거부
        self.assertTrue(ps.origin_ok("http://127.0.0.1:18999", None))               # Host 헤더가 없으면 서버 포트로 폴백

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

    def test_ssh_forwarded_cross_port_origin_still_rejected(self):
        # 포워딩 포트(9000)와 다른 출처(예: 로컬의 다른 앱, 3000)는 Host 완화와 무관하게 여전히 막는다.
        body = json.dumps({"file": str(self.main), "lo": 4, "hi": 4}).encode()
        out = self.talk(req("POST", "/api/pin", body, {"Host": "localhost:9000",
                                                         "Origin": "http://localhost:3000",
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

    def test_add_pin_stamps_frac_build(self):
        # must-2(P0b 수선): frac 이 가리키는 좌표계를 벽시계가 아니라 '어느 빌드였는지'로 못박는다.
        pid = self.add()
        self.assertEqual(self.pin(pid)["frac_build"], ps.cur_pages().name)

    def test_edit_loc_with_new_frac_restamps_frac_build(self):
        pid = ps.add_pin({"file": str(self.main), "lo": 4, "hi": 5, "page": 1, "frac": [0, 0, 1, 1]},
                         dict(ps.LOCAL_ACTOR))
        old_build = self.pin(pid)["frac_build"]
        (ps.C.state / "pages-20260101000000").mkdir()
        ps.C.pages_ptr.write_text("pages-20260101000000")
        p = ps.edit_pin(pid, {"loc": {"file": str(self.main), "lo": 4, "hi": 5,
                                       "frac": [0.1, 0.1, 0.2, 0.2]}, "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertNotEqual(p["frac_build"], old_build)
        self.assertEqual(p["frac_build"], "pages-20260101000000")

    def test_edit_note_only_does_not_touch_frac_build(self):
        # 결함(must-2 갈래 a): 메모만 고쳐도 edited_at 이 지금으로 튀어(옛 로직) '추정' 표시가 꺼졌다.
        # frac 자체는 안 바뀌었으니 frac_build 도 그대로여야 한다.
        pid = self.add()
        old_build = self.pin(pid)["frac_build"]
        (ps.C.state / "pages-20260101000000").mkdir()
        ps.C.pages_ptr.write_text("pages-20260101000000")
        p = ps.edit_pin(pid, {"note": "고친 메모", "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["frac_build"], old_build)

    def test_note_append_does_not_touch_frac_build(self):
        pid = self.add()
        old_build = self.pin(pid)["frac_build"]
        (ps.C.state / "pages-20260101000000").mkdir()
        ps.C.pages_ptr.write_text("pages-20260101000000")
        p = ps.edit_pin(pid, {"note_append": "덧붙임"}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["frac_build"], old_build)

    def test_lo_hi_only_edit_does_not_touch_frac_build(self):
        # frac 없이 lo/hi 만 손으로 옮기면(scope='lines') frac 좌표 자체를 다시 찍은 게 아니므로
        # frac_build 도 그대로 옛 값이어야 한다(뷰어가 옛 마크를 계속 '추정'으로 보여줘야 한다).
        pid = self.add()
        old_build = self.pin(pid)["frac_build"]
        (ps.C.state / "pages-20260101000000").mkdir()
        ps.C.pages_ptr.write_text("pages-20260101000000")
        p = ps.edit_pin(pid, {"lo": 4, "hi": 6, "base_rev": 0}, dict(ps.LOCAL_ACTOR))
        self.assertEqual(p["frac_build"], old_build)

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

    def test_overlaps_for_range_same_range_is_inside_not_dropped(self):
        # 결함: _range_rel 은 범위가 같으면 'contains'(a 기준)를 내는데, 클라이언트 pickOverlap 은
        # 'contains' 를 무시해서 같은 문단을 두 번 찍어도 겹침 배너가 안 떴다. 기존 핀을 항상 바깥으로
        # 보고 'inside' 로 판정해야 pickOverlap 의 insides 필터에 걸려 배너가 뜬다.
        pid = self.add(4, 9, note="first")
        ov = ps.overlaps_for_range(str(self.main), 4, 9)
        self.assertEqual(ov, [{"id": pid, "lo": 4, "hi": 9, "rel": "inside"}])

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
        self.assertEqual(cut, "x" * 60 + "…")
        self.assertEqual(len(cut), 61)
        self.assertEqual(ps.truncate_quote("x" * 60, 60), "x" * 60)   # 정확히 경계면 안 붙는다

    def test_quote_truncated_with_ellipsis_in_pins_md(self):
        # 결함: 인용문이 60자 넘게 잘려도 말줄임표가 없어서 완전한 문장처럼 보였다.
        long_line = "y" * 650
        f = self.src / "long2.tex"
        f.write_text(long_line + "\n", encoding="utf-8")
        pid = ps.add_pin({"file": str(f), "lo": 1, "hi": 1, "page": 1, "note": "n", "scope": "raw",
                          "quote": "가" * 90}, dict(ps.LOCAL_ACTOR))
        stored = self.pin(pid)["quote"]
        self.assertEqual(stored, "가" * 60 + "…")
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


# ---------------------------------------------------------------- 프런트엔드 순수 로직(node 로 실제 소스 실행)
#
# 서버는 표준 라이브러리·127.0.0.1 만 쓰지만, 이 테스트들은 회귀 검증을 위해 node 로 클라이언트 JS 를
# 그대로 돌린다(서버 자체를 바꾸지 않는다). node 가 없는 환경에서는 스킵한다.

class FrontendLogic(unittest.TestCase):
    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node 없음")

    def test_is_estimated_checks_build_src_mtime_when_sync_ok(self):
        # 결함(.est 가 사라짐): sync 가 ok 로 돌아오면 isEstimated 가 항상 false 였다 — build_src_mtime
        # 이 핀 자신의 시각보다 나중이면(트리 전체가 다시 빌드됨) sync 와 무관하게 추정이어야 한다.
        js = "\n".join([
            extract_js_fn("builtAtEpoch"),
            extract_js_fn("pinAtEpoch"),
            extract_js_fn("isEstimated"),
            r"""
            let META=null;
            function run(m,p){META=m;return isEstimated(p);}
            const out=[];
            // sync=ok 인데 build_src_mtime 이 핀 시각보다 나중 → true (핵심 회귀)
            out.push(run({built_at:"2026-09-22 10:00:00",
                           build_src_mtime: Date.parse("2026-09-22T09:30:00")/1000},
                          {at:"2026-09-22 09:00:00", sync:"ok"}));
            // sync=ok 이고 build_src_mtime 이 핀 시각보다 이르면(다른 파일만 바뀜) → false(오탐 아님)
            out.push(run({built_at:"2026-09-22 10:00:00",
                           build_src_mtime: Date.parse("2026-09-22T08:00:00")/1000},
                          {at:"2026-09-22 09:00:00", sync:"ok"}));
            // sync!=ok(이동) 는 그대로 true — 기존 동작 유지
            out.push(run({built_at:"2026-09-22 10:00:00", build_src_mtime: null},
                          {at:"2026-09-22 09:00:00", sync:"moved +3"}));
            // 핀이 built_at 보다 나중에 편집됐으면(재확정) 항상 false
            out.push(run({built_at:"2026-09-22 10:00:00",
                           build_src_mtime: Date.parse("2026-09-22T09:30:00")/1000},
                          {at:"2026-09-22 10:30:00", sync:"ok"}));
            console.log(JSON.stringify(out));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out, [True, False, True, False])

    def test_is_estimated_uses_frac_build_identity_not_wall_clock(self):
        # must-2(P0b 수선): frac_build 가 있으면 벽시계(at/edited_at, built_at/build_src_mtime)를 아예
        # 보지 않고 '지금 화면의 빌드와 같은가'만 본다 — 문자열 비교라 시간대와 무관하다.
        js = "\n".join([
            extract_js_fn("builtAtEpoch"),
            extract_js_fn("pinAtEpoch"),
            extract_js_fn("isEstimated"),
            r"""
            let META=null;
            function run(m,p){META=m;return isEstimated(p);}
            const out=[];
            // 벽시계로는 '추정 아님'(pa>=ba)처럼 보여도 frac_build 가 다르면 무조건 추정이다.
            out.push(run({built_at:"2026-09-22 09:00:00", pages_build:"pages-B", build_src_mtime:null},
                          {at:"2026-09-22 10:00:00", sync:"ok", frac_build:"pages-A"}));
            // frac_build 가 지금 화면과 같으면, 벽시계로는 '추정'처럼 보여도(pa<ba) 추정이 아니다.
            out.push(run({built_at:"2026-09-22 10:00:00", pages_build:"pages-A", build_src_mtime:null},
                          {at:"2026-09-22 09:00:00", sync:"ok", frac_build:"pages-A"}));
            // sync!=ok 는 frac_build 가 같아도 여전히 추정이다.
            out.push(run({built_at:"2026-09-22 10:00:00", pages_build:"pages-A", build_src_mtime:null},
                          {at:"2026-09-22 09:00:00", sync:"moved +3", frac_build:"pages-A"}));
            console.log(JSON.stringify(out));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out, [True, False, True])

    def test_is_estimated_note_edit_does_not_clear_estimated_flag(self):
        # 결함(must-2 갈래 a): 메모만 고쳐 edited_at 이 지금으로 튀어도(옛 로직이면 '추정 아님'으로
        # 뒤집혔다), frac_build 가 여전히 다르면 추정 표시가 그대로 유지돼야 한다.
        js = "\n".join([
            extract_js_fn("builtAtEpoch"),
            extract_js_fn("pinAtEpoch"),
            extract_js_fn("isEstimated"),
            r"""
            const META={built_at:"2026-09-22 09:00:00", pages_build:"pages-B", build_src_mtime:null};
            const p={at:"2026-09-22 08:00:00", edited_at:"2026-09-22 10:30:00", sync:"ok", frac_build:"pages-A"};
            console.log(JSON.stringify(isEstimated(p)));
            """,
        ])
        self.assertEqual(json.loads(run_node(js)), True)

    def test_is_estimated_frac_build_path_ignores_browser_timezone(self):
        # 결함(must-2 갈래 c): 벽시계 비교는 브라우저 시간대에 따라 갈렸다(영국 공저자에게는 .est 가 전혀
        # 안 보임). frac_build 경로는 Date.parse 를 전혀 안 쓰므로 시간대를 바꿔도 같은 결과가 나와야 한다.
        js = "\n".join([
            extract_js_fn("builtAtEpoch"),
            extract_js_fn("pinAtEpoch"),
            extract_js_fn("isEstimated"),
            r"""
            const META={built_at:"2026-09-22 09:00:00", pages_build:"pages-B", build_src_mtime:null};
            const p={at:"2026-09-22 08:00:00", sync:"ok", frac_build:"pages-A"};
            console.log(JSON.stringify(isEstimated(p)));
            """,
        ])
        seoul = json.loads(run_node(js, tz="Asia/Seoul"))
        london = json.loads(run_node(js, tz="Europe/London"))
        la = json.loads(run_node(js, tz="America/Los_Angeles"))
        self.assertEqual([seoul, london, la], [True, True, True])

    def test_pick_overlap_treats_contains_as_bannerable(self):
        # must-1(P0b 수선): 감싸는 선택(contains)도 배너가 떠야 한다 — 전에는 inside·partial 만 보고
        # contains 는 조용히 무시했다.
        js = "\n".join([
            extract_js_fn("pickOverlap"),
            r"""
            const out=[];
            out.push(pickOverlap([{id:6,lo:241,hi:243,rel:'contains'}]));
            // inside 가 있으면 여전히 inside 를 우선한다.
            out.push(pickOverlap([{id:1,lo:1,hi:100,rel:'contains'},{id:2,lo:10,hi:20,rel:'inside'}]));
            // contains 가 여럿이면 범위가 더 큰(더 비슷한 크기의) 쪽을 고른다.
            out.push(pickOverlap([{id:1,lo:1,hi:5,rel:'contains'},{id:2,lo:1,hi:9,rel:'contains'}]));
            console.log(JSON.stringify(out));
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out[0]["id"], 6)
        self.assertEqual(out[1]["id"], 2)
        self.assertEqual(out[2]["id"], 2)

    def test_refresh_overlap_updates_cur_and_ignores_stale_target(self):
        # must-1(P0b 수선): 단계 전환·▲▼ 뒤 가벼운 /api/overlaps 재조회가 CUR.overlaps 를 갱신하고
        # 배너를 다시 그린다. 그 사이 CUR 이 다른 선택으로 바뀌었으면(응답이 늦게 옴) 반영하지 않는다.
        js = "\n".join([
            r"""
            let OVSEQ=0, CUR=null; const calls=[];
            async function api(url){calls.push(url); return {data:{overlaps:[{id:9,lo:1,hi:2,rel:'inside'}]}};}
            function renderOverlapBanner(){calls.push('render');}
            """,
            extract_js_fn("refreshOverlap"),
            r"""
            (async()=>{
              const o={file:'main.tex',lo:4,hi:5};
              CUR=o;
              await refreshOverlap(o);
              const fresh={overlaps:o.overlaps, calls:calls.slice()};
              calls.length=0;
              const o2={file:'main.tex',lo:1,hi:1};
              CUR=o2;                       // o 는 더 이상 CUR 이 아니다 — 응답이 와도 무시해야 한다
              await refreshOverlap(o);
              console.log(JSON.stringify({fresh, staleIgnored: calls.length===0, o2Untouched: o2.overlaps===undefined}));
            })();
            """,
        ])
        out = json.loads(run_node(js))
        self.assertEqual(out["fresh"]["overlaps"], [{"id": 9, "lo": 1, "hi": 2, "rel": "inside"}])
        self.assertIn("render", out["fresh"]["calls"])
        self.assertTrue(out["staleIgnored"])
        self.assertTrue(out["o2Untouched"])

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
        self.assertNotIn("setInterval(pollBuild", m.group(1))   # 무조건 거는 코드가 없어야 한다
        self.assertIn("pollBuild()", m.group(1))                # 부팅 시 한 번은 확인한다

        m2 = re.search(r"async function pollBuild\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m2)
        body = m2.group(1)
        self.assertIn("if(document.hidden)return", body.replace(" ", ""))   # 탭 숨으면 요청 자체를 안 보낸다
        self.assertIn("if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000)", body.replace(" ", ""))
        self.assertIn("clearInterval(BUILD_TIMER)", body)       # 할 일이 없으면 폴링을 멈춘다

    def test_light_poll_kicks_off_build_polling_when_running(self):
        m = re.search(r"async function pollLight\(\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1).replace(" ", "")
        self.assertIn("d.build&&d.build.state==='running'", body)
        self.assertIn("pollBuild()", body)

    def test_build_err_panel_auto_shown_not_only_via_toast(self):
        # 결함: ok_errors|fail 이어도 패널이 자동으로 열리지 않고 토스트의 '자세히' 버튼에만 걸려 있었다
        # — 토스트가 6초 뒤 사라지면 다시 볼 길이 없었다.
        m = re.search(r"async function pollBuild\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1)
        self.assertIn("showBuildErr(b)", body)          # toast(...) 콜백이 아니라 직접 호출된다
        self.assertNotIn("fn:()=>showBuildErr(b)", body)  # 예전 패턴(클릭해야만 열림)이 남아 있지 않다

    def test_build_err_reopen_affordance_exists(self):
        self.assertIn('id="build-err-chip"', ps.HTML)
        self.assertIn('data-act="build-err-reopen"', ps.HTML)
        self.assertIn("case 'build-err-reopen'", ps.HTML)
        self.assertIn("function hideBuildErr()", ps.HTML)
        self.assertIn("case 'err-close':hideBuildErr()", ps.HTML)

    def test_pick_resets_overlap_dismissed_for_new_selection(self):
        # must-1(P0b 수선): [별도 핀으로 저장]을 한 번 누르면 OVERLAP_DISMISSED 가 true 로 남아, 그
        # 뒤로 새로 드래그해도(pick() 이 새 CUR 을 받아도) 배너가 영구히 꺼져 있었다.
        m = re.search(r"async function pick\(r\)\{(.*?)\n\}", ps.HTML, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        cur_idx = body.index("CUR=d;")
        dismissed_idx = body.index("OVERLAP_DISMISSED=false")
        self.assertGreater(dismissed_idx, cur_idx)   # 새 CUR 을 받은 뒤에(재드래그마다) 리셋한다

    def test_level_and_nudge_refresh_overlap_only_for_composer(self):
        # must-1(P0b 수선): 단계 전환(useLevel)·▲▼(nudge)로 범위가 바뀌면 겹침을 다시 물어야 배너가
        # 따라간다. 편집 카드(EDIT)에는 겹침 배너가 없으므로 !inEdit 일 때만 부른다.
        m = re.search(r"case 'level':\{(.*?)\}\s*\n", ps.HTML)
        self.assertIsNotNone(m)
        self.assertIn("if(!inEdit)refreshOverlap(o)", m.group(1).replace(" ", ""))
        m2 = re.search(r"case 'nudge':\{(.*?)\}\s*\n", ps.HTML)
        self.assertIsNotNone(m2)
        self.assertIn("if(!inEdit)refreshOverlap(o)", m2.group(1).replace(" ", ""))

    def test_pollLight_catches_build_finished_between_polls(self):
        # should(P0b 수선): 5초 틈새 안에 다른 클라이언트가 시작~종료까지 끝낸 빌드는 'running'을 한
        # 번도 못 보고 최종 상태로 나타난다 — started_at 이 이 탭이 처리한 값과 다르면 다시 받는다.
        m = re.search(r"async function pollLight\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1).replace(" ", "")
        self.assertIn("d.build.started_at!==LAST_SEEN_BUILD", body)
        self.assertIn("pollBuild()", body)

    def test_pollBuild_shows_panel_silently_on_boot(self):
        # should(P0b 수선): 새로고침해서 처음 연 탭도 이미 fail|ok_errors 로 멈춰 있는 빌드를 배지/패널로
        # 보여줘야 한다 — 단 '방금 실패했다'는 토스트는 울리지 않는다(그 일이 지금 일어난 게 아니므로).
        m = re.search(r"async function pollBuild\(\)\{(.*?)\n\}", ps.HTML, re.S)
        body = m.group(1).replace(" ", "")
        self.assertIn("!BUILD_BOOTED&&(b.state==='fail'||b.state==='ok_errors')", body)
        self.assertIn("BUILD_BOOTED=true", m.group(1))


if __name__ == "__main__":
    unittest.main()
