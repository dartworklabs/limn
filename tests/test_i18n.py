"""Viewer UI language: the English message table (src/limn/ui_en.json) and its wiring.

The Korean strings in the HTML template are the source. In English mode the viewer swaps every string
found in the table, and composed strings go through tl() with a parameterised key ('{n}쪽'). The agent
contract (pins.md, API) is not translated.
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
import struct
import zlib
from unittest import mock
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "limn"
spec = importlib.util.spec_from_file_location("limn_server_i18n", PKG / "server.py")
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

HANGUL = re.compile(r"[가-힣]")
UI_ATTRS = ("data-tip", "aria-label", "title", "placeholder")


def static_ui_strings(html):
    """Korean text nodes and UI attributes of the static markup (body up to the first <script>)."""
    body = html[html.index("<body"):html.index("<script>", html.index("<body"))]
    found = set()

    class P(HTMLParser):
        skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("svg", "style"):
                self.skip += 1
            for k, v in attrs:
                if k in UI_ATTRS and v and HANGUL.search(v):
                    found.add(v.strip())

        def handle_endtag(self, tag):
            if tag in ("svg", "style") and self.skip:
                self.skip -= 1

        def handle_data(self, d):
            d = d.strip()
            if not self.skip and d and HANGUL.search(d) and not d.startswith("__"):
                found.add(d)

    P().feed(body)
    return found


LIT = re.compile(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"")


def first_arg(src, i):
    """src[i] is '(' - the text of the first call argument (up to the top-level ',' or ')')."""
    depth, j, q = 0, i, None
    while j < len(src):
        c = src[j]
        if q:
            if c == "\\":
                j += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
        elif c == "," and depth == 1:
            return src[i + 1:j]
        j += 1
    return ""


def composed_keys(html):
    """Korean string literals passed (directly or through a ?: choice) as the key of tl() or tr() in the viewer script."""
    keys = set()
    for m in re.finditer(r"(?<![\w.$])t[lr]\(", html):
        for lm in LIT.finditer(first_arg(html, m.end() - 1)):
            k = lm.group(1) if lm.group(1) is not None else lm.group(2)
            k = k.replace("\\'", "'").replace("\\\\", "\\")
            if HANGUL.search(k):
                keys.add(k.strip())
    return keys


class MessageTable(unittest.TestCase):
    def test_table_loads_and_values_are_english(self):
        self.assertGreater(len(ps.UI_EN), 300)
        for k, v in ps.UI_EN.items():
            self.assertTrue(HANGUL.search(k), k)
            for form in (v.values() if isinstance(v, dict) else [v]):
                self.assertFalse(HANGUL.search(form), (k, v))
                self.assertTrue(form.strip(), k)

    def test_templates_keep_their_placeholders(self):
        # A composed key ('{n}쪽') and its English value use the same {name} slots; the English side may drop
        # a Korean-only slot (the particle {p}). Plural forms are {"one", "other"}, chosen by the n the caller passes.
        slots = re.compile(r"\{(\w+)\}")
        for k, v in ps.UI_EN.items():
            forms = list(v.values()) if isinstance(v, dict) else [v]
            if isinstance(v, dict):
                self.assertEqual(set(v) - {"one", "other"}, set(), k)
                self.assertIn("other", v, k)
            for form in forms:
                self.assertLessEqual(set(slots.findall(form)), set(slots.findall(k)), (k, form))
                if set(slots.findall(k)) - {"p"}:
                    self.assertTrue(set(slots.findall(form)), (k, form))

    def test_plural_values_are_rejected_when_malformed(self):
        path = PKG / "ui_en.json"
        good = ps.load_ui_messages()
        self.assertEqual(good["{n}줄"], {"one": "{n} line", "other": "{n} lines"})
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "server.py"
            (Path(d) / "ui_en.json").write_text(json.dumps({"가": "A", "{n}나": {"one": "x"}, "{n}다": {"other": "y", "few": "z"}},
                                                           ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(ps, "__file__", str(fake)):
                self.assertEqual(ps.load_ui_messages(), {"가": "A"})
        self.assertTrue(path.exists())

    def test_every_composed_key_has_a_translation(self):
        used = composed_keys(ps.HTML)
        self.assertGreater(len(used), 150)
        self.assertEqual(sorted(k for k in used if k not in ps.UI_EN), [])

    def test_every_static_ui_string_has_a_translation(self):
        html = ps.build_html("A-DEMO", "#2563eb")
        def covered(s):   # same lookup as trMsg(): the whole string, else each part around ' — ' or ' · '
            if s in ps.UI_EN:
                return True
            for sep in (" — ", " · "):
                if s.find(sep) > 0:
                    return all(p in ps.UI_EN or not HANGUL.search(p) for p in s.split(sep))
            return False
        missing = sorted(s for s in static_ui_strings(html) if not covered(s))
        self.assertEqual(missing, [])

    def test_chrome_strings_are_covered(self):
        for s in ("PDF 재빌드", "도움말", "더보기", "선택", "닫힌 핀", "Limn — 사용법", "화면 언어를 바꿉니다 (한국어 / English)"):
            self.assertIn(s, ps.UI_EN)


class Wiring(unittest.TestCase):
    def test_table_is_embedded_and_script_safe(self):
        html = ps.build_html("A-DEMO", "#2563eb")
        self.assertNotIn("__UI_EN_JSON__", html)
        self.assertFalse([k for k in ps.UI_EN if "__" in k])   # build_html fills placeholders; keys must not contain them
        m = re.search(r"I18N_EN=(\{.*?\}), I18N_ATTRS=", html, re.S)
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(1).replace("<\\/", "</")), ps.UI_EN)
        self.assertNotIn("</script", m.group(1))

    def test_language_choice_order(self):
        head = ps.HTML[:ps.HTML.index("<body")]
        i_q, i_saved, i_nav = (head.index(x) for x in ("get('lang')", "getItem('limnLang')", "navigator.language"))
        self.assertLess(i_q, i_saved)
        self.assertLess(i_saved, i_nav)
        self.assertIn("indexOf('ko')===0?'ko':'en'", head)

    def test_toasts_boot_and_switch_are_wired(self):
        self.assertIn("function toast(msg,kind,action,dd){msg=trMsg(msg);", ps.HTML)
        self.assertIn("async function boot(){i18nStart();", ps.HTML)
        self.assertIn('id="m-lang"', ps.HTML)
        self.assertIn("case 'lang':switchLang();break;", ps.HTML)


class BrowserLanguage(unittest.TestCase):
    """Real Chromium: ?lang=en switches the chrome to English, ko keeps Korean."""

    @classmethod
    def setUpClass(cls):
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        cls.pw = sync_playwright().start()
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e
        cls.html = ps.build_html("A-DEMO", "#2563eb").replace("\nboot();", "\n")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, query, locale):
        context = self.browser.new_context(locale=locale)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=self.html)
                   if route.request.url.startswith("http://viewer.test/") else route.abort())
        page.goto("http://viewer.test/" + query)
        page.evaluate("i18nStart()")
        return page

    def test_query_parameter_english(self):
        page = self.open("?lang=en", "ko-KR")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
        self.assertEqual(page.text_content("#btn-rebuild .lbl").strip(), ps.UI_EN["PDF 재빌드"])
        self.assertEqual(page.get_attribute("#btn-help", "aria-label"), ps.UI_EN["도움말"])
        self.assertEqual(page.text_content("#m-lang").strip(), "한국어")
        page.evaluate("toast('저장을 되돌렸습니다','ok')")
        self.assertIn("Reverted the save", page.text_content("body"))

    def test_browser_language_decides_without_a_choice(self):
        page = self.open("", "en-US")
        self.assertEqual(page.evaluate("LANG"), "en")
        page = self.open("", "ko-KR")
        self.assertEqual(page.evaluate("LANG"), "ko")
        self.assertEqual(page.text_content("#btn-rebuild .lbl").strip(), "PDF 재빌드")
        self.assertEqual(page.text_content("#m-lang").strip(), "English")

    def test_saved_choice_wins_over_browser_language(self):
        page = self.open("?lang=ko", "en-US")
        self.assertEqual(page.evaluate("LANG"), "ko")
        page2 = page.context.new_page()
        page2.route("**/*", lambda route: route.fulfill(content_type="text/html", body=self.html)
                    if route.request.url.startswith("http://viewer.test/") else route.abort())
        page2.goto("http://viewer.test/")
        self.assertEqual(page2.evaluate("LANG"), "ko")


def extract_js_fn(name: str) -> str:
    """One 'function NAME(...){...}' definition out of the viewer script (braces balanced as written)."""
    src = ps.HTML
    i = src.index("function %s(" % name)
    j = src.index("{", i)
    depth, k = 0, j
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1


class ComposedMessages(unittest.TestCase):
    """tl(): Korean template in ko, the table's English template (or plural form) in en."""

    def run_js(self, lang, body):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        js = "\n".join(["var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(ps.UI_EN, ensure_ascii=False)),
                        extract_js_fn("tr"), extract_js_fn("tl"), "console.log(JSON.stringify(%s));" % body])
        r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_korean_fills_the_key_itself(self):
        out = self.run_js("ko", "[tl('{n}쪽',{n:1}),tl('{n}쪽',{n:25}),tl('{name}님 확인 필요',{name:'Bob'}),tl('검토 대기 {n}',{n:6}),"
                                "tl('#{id}{p} 같은 범위',{id:4,p:'와'}),tr('완료'),tl('없는 키 {x}',{x:1})]")
        self.assertEqual(out, ["1쪽", "25쪽", "Bob님 확인 필요", "검토 대기 6", "#4와 같은 범위", "완료", "없는 키 1"])

    def test_english_uses_templates_and_plurals(self):
        out = self.run_js("en", "[tl('{n}쪽',{n:1}),tl('{n}쪽',{n:25}),tl('{page}쪽',{page:3}),tl('{name}님 확인 필요',{name:'Bob'}),"
                                "tl('{n}시간 전',{n:22}),tl('{n}일 전',{n:1}),tl('이전 {n}건 보기',{n:2}),tl('#{id}{p} 같은 범위',{id:4,p:'와'}),"
                                "tr('완료'),tl('없는 키 {x}',{x:1})]")
        self.assertEqual(out, ["1 p.", "25 pp.", "p. 3", "Needs Bob's review", "22 hr ago", "1 day ago", "Show 2 earlier",
                               "Same range as #4", "Done", "없는 키 1"])


def _png(w, h):
    """A white 8-bit grayscale PNG (the viewer only needs real page images and their size)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


TEX = "\\documentclass{article}\n\\begin{document}\n" + "".join("Line %d of the demo manuscript.\n" % i for i in range(3, 40)) + "\\end{document}\n"
ALICE = {"login": "alice@example.com", "name": "Alice Kim"}
BOB = {"login": "bob@example.com", "name": "Bob Lee"}
SEOJUN = {"login": "seojun@example.com", "name": "김서준"}
# User content in the fixture: document tab names, a note, a reply and a person's name in Korean. Everything
# else on screen is chrome and must be English in English mode. '한국어' is the switch back to Korean.
USER_TEXT = ("본문", "답변서", "이 문장을 다듬어 주세요", "표 설명을 줄였습니다", "김서준")
CHROME_ALLOWED = ("한국어",)
VISIBLE_HANGUL_JS = """() => {
  const out=[]; const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); let n;
  const vis=el=>{if(!el||!el.getClientRects().length)return false; const cs=getComputedStyle(el); return cs.visibility!=='hidden'&&cs.display!=='none';};
  while((n=w.nextNode())){const t=n.nodeValue.trim(); if(t&&/[가-힣]/.test(t)&&vis(n.parentElement)&&!n.parentElement.closest('.av'))   // .av = a person's initial
    out.push({t, where:(n.parentElement.id||n.parentElement.className||n.parentElement.tagName)});}
  document.querySelectorAll('input[placeholder],textarea[placeholder]').forEach(e=>{if(vis(e)&&/[가-힣]/.test(e.placeholder))out.push({t:e.placeholder,where:e.id||'placeholder'});});
  out.push({t:document.title,where:'title'});
  return out;}"""


def chrome_hangul(found):
    """Items whose text still has Hangul once user content and the allowed chrome strings are removed."""
    bad = []
    for x in found:
        rest = x["t"]
        for u in USER_TEXT + CHROME_ALLOWED:
            rest = rest.replace(u, "")
        if HANGUL.search(rest):
            bad.append("%s :: %s" % (x["where"], x["t"][:80]))
    return bad


class EnglishChrome(unittest.TestCase):
    """The real viewer against a real (in-process) server, in English: no Hangul left in the chrome.

    Requests are routed from Chromium straight into the request handler over a socketpair (no port is opened),
    with a tailnet identity, so the chrome shows a person, an agent, open/claimed/question/review/done/dropped
    pins, threads with relative times, @mentions and two documents."""

    @classmethod
    def setUpClass(cls):
        required = os.environ.get("LIMN_TEST_REQUIRE_BROWSER") == "1"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            if required:
                raise
            raise unittest.SkipTest("Playwright unavailable") from None
        cls.pw = sync_playwright().start()
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e) from e
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved_html = ps.HTML
        cls.make_state(Path(cls.tmp.name))
        ps.HTML = ps.build_html("Demo", "#2563eb")

    @classmethod
    def tearDownClass(cls):
        ps.HTML = cls.saved_html
        ps.set_docs(None)
        cls.tmp.cleanup()
        cls.browser.close()
        cls.pw.stop()

    @classmethod
    def make_state(cls, root):
        src = root / "ms"
        src.mkdir()
        for name in ("main.tex", "reply.tex"):
            (src / name).write_text(TEX, encoding="utf-8")
        C = ps.C
        C.src, C.main = src, src / "main.tex"
        C.state = root / "state"
        C.state.mkdir()
        C.build = C.state / "build"
        C.port, C.dpi, C.timeout = 18999, 150, 60
        C.envs = tuple(ps.DEFAULT_ENVS.split(","))
        C.allow, C.origin_check, C.git_pull, C.pdfjs_dir = frozenset(), True, False, None
        C.label, C.accent, C.repo = "Demo", ps.ACCENT_PALETTE[0], None
        ps.set_docs(ps.make_docs(["ms=본문:main.tex", "rr=답변서:reply.tex"], src))
        ps.init_seq()
        page = _png(1275, 1650)            # a letter page at 150 dpi
        for D in ps.DOCS:
            pages = D.dir / "pages-20260925100000"
            pages.mkdir(parents=True)
            for i in (1, 2, 3):
                (pages / ("page-%d.png" % i)).write_bytes(page)
            (D.dir / "pages.cur").write_text(pages.name)
            (D.dir / "built_at.txt").write_text("2026-09-25 10:00:00")
            (D.dir / "head.txt").write_text("abc1234")
        agent = dict(ps.LOCAL_ACTOR)
        for who in (ALICE, BOB, SEOJUN):
            ps.record_person(who)
        ms, rr = ps.DOCS

        def add(lo, hi, note, actor, **kw):
            d = dict(file=str(C.main), lo=lo, hi=hi, page=1 + lo // 20, note=note, **kw)
            return ps.add_pin(d, actor)
        with ps.using_doc(ms):
            claimed = add(4, 5, "Tighten this sentence", ALICE)
            ps.claim_pin(claimed, agent, *ps.clean_claim_body({"eta_min": 10}))
            korean = add(8, 9, "이 문장을 다듬어 주세요", SEOJUN)
            ps.reply_pin(korean, "Working on it", ALICE)
            add(12, 16, "Is this the right table? @Bob Lee", ALICE, kind_req="question", mentions=[BOB["login"]])
            add(4, 5, "Same spot again", BOB)
            add(20, 21, "Ask Bob about the wording", ALICE, assignee=BOB["login"])
            add(22, 23, "Agent note", agent)
            for author in (ALICE, BOB):
                pid = add(24, 25, "Shorten the caption", author)
                ps.set_done(pid, True, agent, reply="표 설명을 줄였습니다", ref="PR #7")
            done = add(26, 27, "Fix the unit", ALICE)
            ps.set_done(done, True, ALICE)
            dropped = add(28, 29, "Wrong spot", ALICE)
            ps.drop_pin(dropped, ALICE)
        with ps.using_doc(rr):
            ps.add_pin(dict(file=str(src / "reply.tex"), lo=4, hi=5, page=1, note="Reply letter wording"), ALICE)

        def age(rows):               # threads and pins from yesterday and a few hours ago, so relative times show
            for i, r in enumerate(rows):
                r["at"] = "2026-09-2%d 09:%02d:00" % (3 + i % 2, i)
                for m in r.get("thread") or []:
                    m["at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 3 * 3600))
            return None, True
        ps.transact(age)

    def talk(self, raw):
        a, b = socket.socketpair()
        t = threading.Thread(target=lambda: (ps.Handler(b, ("127.0.0.1", 0), None), b.close()), daemon=True)
        t.start()
        a.sendall(raw)
        a.shutdown(socket.SHUT_WR)
        a.settimeout(20)
        out = b""
        while True:
            chunk = a.recv(65536)
            if not chunk:
                break
            out += chunk
        a.close()
        t.join(20)
        head, _, body = out.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        hdrs = dict((k.strip().lower(), v.strip()) for k, _, v in (ln.partition(":") for ln in lines[1:]))
        return int(lines[0].split()[1]), hdrs, body

    def route(self, route):
        req = route.request
        u = urlparse(req.url)
        if u.netloc != "viewer.test":
            return route.abort()
        body = req.post_data_buffer or b""
        h = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": ALICE["login"], "Tailscale-User-Name": ALICE["name"]}
        if req.headers.get("content-type"):
            h["Content-Type"] = req.headers["content-type"]
        if body:
            h["Content-Length"] = str(len(body))
        if req.method == "POST":
            h["Origin"] = "http://127.0.0.1:18999"
        raw = ("%s %s HTTP/1.1\r\n" % (req.method, u.path + ("?" + u.query if u.query else ""))
               + "".join("%s: %s\r\n" % kv for kv in h.items()) + "\r\n").encode("latin-1") + body
        code, hdrs, data = self.talk(raw)
        route.fulfill(status=code, headers={"content-type": hdrs.get("content-type", "application/octet-stream")}, body=data)

    def open(self, lang, **device):
        context = self.browser.new_context(**device)
        self.addCleanup(context.close)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s#doc=ms" % lang)
        page.wait_for_function("typeof OPEN_ALL!=='undefined'&&OPEN_ALL.length>=6&&REVIEW_ALL.length===2", timeout=20000)
        page.wait_for_timeout(300)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    def assert_english(self, page, where):
        bad = chrome_hangul(page.evaluate(VISIBLE_HANGUL_JS))
        self.assertEqual(bad, [], "Hangul left in the English chrome (%s)" % where)

    def test_desktop_chrome_is_english(self):
        page = self.open("en", viewport={"width": 1400, "height": 850})
        self.assert_english(page, "desktop list")
        page.click("#done-toggle")
        page.evaluate("SHOW_ALL=true; drawPins()")
        page.evaluate("document.querySelectorAll('.th-more').forEach(b=>b.click())")
        self.assert_english(page, "desktop archive, all documents")
        page.click("#trash-link")
        page.wait_for_selector("#trash[open]")
        self.assert_english(page, "desktop Trash")
        page.click("#trash [data-act=trash-close]")
        page.evaluate("openEdit(PINS.find(p=>p.note==='Tighten this sentence').id)")
        page.wait_for_timeout(300)
        self.assert_english(page, "desktop edit")
        page.evaluate("openReply(REVIEW_ALL[0].id)")
        page.fill("#review-pins textarea.r-text", "x")
        self.assert_english(page, "desktop reply on a pin awaiting review (outcome line, keep state)")

    def test_touch_chrome_is_english(self):
        for name, device in (("fold", {"viewport": {"width": 842, "height": 758}, "is_mobile": True, "has_touch": True}),
                             ("phone", {"viewport": {"width": 384, "height": 832}, "is_mobile": True, "has_touch": True})):
            with self.subTest(device=name):
                page = self.open("en", **device)
                self.assert_english(page, name)
                page.evaluate("setSide(true)")
                page.wait_for_timeout(200)
                self.assert_english(page, name + " panel open")
                page.click("#btn-more")
                self.assert_english(page, name + " more menu")

    def test_korean_default_is_unchanged(self):
        page = self.open("ko", viewport={"width": 1400, "height": 850})
        self.assertEqual(page.evaluate("document.documentElement.lang"), "ko")
        text = page.text_content("body")
        for s in ("열린 핀 6", "검토 대기 2", "3쪽", "Bob Lee님 확인 필요", "내 확인 차례", "로컬/에이전트", "변경 보기", "3시간 전", "PDF 재빌드"):
            self.assertIn(s, text)
        self.assertRegex(page.title(), r"^Limn · Demo · 본문 · 열린 6 · 검토 2$")
        self.assertEqual(page.get_attribute("#jump", "placeholder"), "쪽 이동")

    def test_toolbar_fits_one_row_in_both_languages(self):
        for lang in ("ko", "en"):
            with self.subTest(lang=lang):
                page = self.open(lang, viewport={"width": 1400, "height": 850})
                self.assertEqual(page.evaluate("Math.round(document.querySelector('#right').getBoundingClientRect().width)"), 348)
                tops = page.evaluate("[...document.querySelectorAll('#bar1>*')].filter(e=>e.getClientRects().length&&!e.classList.contains('sp'))"
                                     ".map(e=>Math.round(e.getBoundingClientRect().top))")
                self.assertGreaterEqual(len(tops), 8)
                self.assertEqual(len(set(tops)), 1, tops)
                self.assertFalse(page.evaluate("[...document.querySelectorAll('#bar1 button')].some(b=>b.scrollWidth>b.clientWidth+1)"))
                self.assertGreaterEqual(page.evaluate("document.querySelector('#jump').getBoundingClientRect().width"), 40)
