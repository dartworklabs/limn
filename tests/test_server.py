"""pin_server 회귀 테스트 — 포트를 열지 않는다(socketpair 로 핸들러를 직접 돌린다).

실행: python3 -m unittest discover -s skills/manuscript-pin-picker/tests
"""
import importlib.util
import json
import os
import socket
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
        self.assertIn("위치 잃음", md)
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


if __name__ == "__main__":
    unittest.main()
