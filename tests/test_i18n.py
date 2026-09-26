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

from limn import access
from limn.scope import ScopeUnreadable
from limn.web import parse
from limn.web.errors import scope_http_error
from test_server import add_pin, shut_wr

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
        """Keys are Korean UI strings, or reason:<code> for an API error reason (tests/test_errors.py); values are English."""
        self.assertGreater(len(ps.UI_EN), 300)
        for k, v in ps.UI_EN.items():
            self.assertTrue(HANGUL.search(k) or re.fullmatch(r"reason:[a-z][a-z0-9_]*", k), k)
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


def pick_warning_sentences():
    """The Korean sentences pick() and _pick_region() put into `warn`, as templates: each %d / %.0f becomes {x}."""
    import ast
    tree = ast.parse(Path(ps.__file__).read_text(encoding="utf-8"))
    out = set()
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in ("pick", "_pick_region")):
        for asg in (n for n in ast.walk(fn) if isinstance(n, ast.Assign)):
            if not any(isinstance(t, ast.Name) and t.id in ("warn", "stale_note") for t in asg.targets):
                continue
            for n in ast.walk(asg.value):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and HANGUL.search(n.value):
                    out.add(re.sub(r"%(?:\.0f|d)", "{x}", n.value).replace("%%", "%"))
    return out


class PickWarnings(unittest.TestCase):
    """The pick's `warn` is a Korean UI hint (not an error body) that the server composes from up to three sentences.
    warnText() shows it in English by matching each sentence to its template in PICK_WARNS and filling it via tl()."""

    def run_js(self, lang, body):
        """Run the viewer's real tr/tl/warnText (and its PICK_WARNS table) under node in lang; the JSON of body."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        table = re.search(r"const PICK_WARNS=\[.*?\];", ps.HTML, re.S)
        self.assertIsNotNone(table)
        js = "\n".join(["var LANG=%s,I18N_EN=%s;" % (json.dumps(lang), json.dumps(ps.UI_EN, ensure_ascii=False)),
                        table.group(0), extract_js_fn("tr"), extract_js_fn("tl"), extract_js_fn("warnText"),
                        "console.log(JSON.stringify(%s));" % body])
        r = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_every_server_sentence_has_a_template_with_english(self):
        """Each warning sentence in pick()/_pick_region() is in PICK_WARNS (placeholders aside) and in the table."""
        table = re.search(r"const PICK_WARNS=\[(.*?)\];", ps.HTML, re.S)
        self.assertIsNotNone(table)
        templates = re.findall(r"'((?:[^'\\]|\\.)*)'", table.group(1))
        self.assertEqual(sorted(re.sub(r"\{\w+\}", "{x}", t) for t in templates), sorted(pick_warning_sentences()))
        self.assertEqual([t for t in templates if not isinstance(ps.UI_EN.get(t), str)], [])

    def test_english_translates_each_joined_sentence(self):
        """A warning of three joined sentences, with its numbers, comes out as three English sentences, no Hangul."""
        warn = ("화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요. "
                "이 영역은 원문 대조가 약합니다(23%). 줄 범위를 눈으로 확인하세요. 빌드 중이라 결과가 흔들릴 수 있습니다.")
        out = self.run_js("en", "[warnText(%s),warnText('두 경로가 다른 곳을 가리킵니다(L12 / L480). 확인이 필요합니다.'),"
                                "warnText(''),warnText('모르는 문장입니다.')]" % json.dumps(warn, ensure_ascii=False))
        self.assertFalse(HANGUL.search(out[0]), out[0])
        self.assertIn("23%", out[0])
        self.assertIn("L12", out[1])
        self.assertIn("L480", out[1])
        self.assertFalse(HANGUL.search(out[1]), out[1])
        self.assertEqual(out[2:], ["", "모르는 문장입니다."])

    def test_korean_shows_the_server_warning_unchanged(self):
        """ko: exactly the server's text."""
        warn = "이 영역은 원문 대조가 약합니다(23%). 줄 범위를 눈으로 확인하세요. 빌드 중이라 결과가 흔들릴 수 있습니다."
        self.assertEqual(self.run_js("ko", "warnText(%s)" % json.dumps(warn, ensure_ascii=False)), warn)


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
VERA = {"login": "vera@example.com", "name": "Vera Park"}       # a view-only member: her changes are refused (403)
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
        access.member_add(C.state, VERA["login"], "viewer", VERA["name"], ps.PEOPLE_FORMAT, ps.cli_audit(C.state))
        ms, rr = ps.DOCS

        def add(lo, hi, note, actor, **kw):
            d = dict(file=str(C.main), lo=lo, hi=hi, page=1 + lo // 20, note=note, **kw)
            return add_pin(d, actor, ps).record["id"]
        claimed = add(4, 5, "Tighten this sentence", ALICE)
        ps.claim_pin(claimed, agent, *parse.parse_claim_body({"eta_min": 10}))
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
        add_pin(dict(file=str(src / "reply.tex"), lo=4, hi=5, page=1, note="Reply letter wording"), ALICE, ps, doc=rr).record["id"]

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
        shut_wr(a)
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
        """Serve one browser request from the in-process handler as the test's person (self.who, Alice by default), or
        with a canned (status, body) from self.canned for a path that needs state this fixture does not build."""
        req = route.request
        u = urlparse(req.url)
        if u.netloc != "viewer.test":
            return route.abort()
        canned = getattr(self, "canned", {}).get(u.path)
        if canned:
            return route.fulfill(status=canned[0], content_type="application/json", body=json.dumps(canned[1]))
        who = getattr(self, "who", ALICE)
        body = req.post_data_buffer or b""
        h = {"Host": "127.0.0.1:18999", "Tailscale-User-Login": who["login"], "Tailscale-User-Name": who["name"]}
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

    def error_toasts(self, lang):
        """Drive the common refusals through the viewer's own functions and collect each error toast as
        (reason, the server's Korean error text, the toast's title, the toast's description). The requests are
        refused, so the shared fixture state never changes."""
        page = self.open(lang, viewport={"width": 1400, "height": 850})
        pid = page.evaluate("PINS.find(p=>p.note==='Tighten this sentence').id")
        scope = scope_http_error(ScopeUnreadable())      # built by the worker; no git in this fixture
        self.canned = {"/api/revision-build": (scope.code, scope.body)}
        self.addCleanup(lambda: (setattr(self, "canned", {}), setattr(self, "who", ALICE)))
        cases = (
            ("viewer_only", "보기 권한(viewer)만 있는 계정입니다 — 핀·답글·닫기 같은 변경은 할 수 없습니다.", VERA,
             "closePin(%d)" % pid),                                            # 403: a view-only member presses [완료]
            ("conflict", "conflict", ALICE, "undoAppend(%d,'x',999)" % pid),     # 409: undo with a stale base_rev
            ("note_append_too_long", "덧붙일 메모가 너무 깁니다(2000자 이하).", ALICE,
             "appendToPin(%d,'x'.repeat(2001))" % pid),                       # 400: validation
            ("pin_not_found", "핀 #999999 이 없습니다.", ALICE, "undoAppend(999999,'x',0)"),   # 404: the pin is gone
            ("scope_failed", scope.body["error"], ALICE,                        # 422: pin-scoped comparison
             "api('/api/revision-build',{method:'POST',body:{commit:'a'.repeat(40),doc:'ms',pin:%d},what:'비교 PDF 만들기'})"
             ".catch(()=>{})" % pid),
        )
        out = []
        for reason, server_text, who, call in cases:
            self.who = who
            page.evaluate("document.querySelector('#toasts').replaceChildren()")
            page.evaluate("async()=>{await %s;}" % call)
            page.wait_for_selector("#toasts .toast.err")
            title, desc = page.evaluate("(()=>{const t=document.querySelector('#toasts .toast.err');"
                                        "return [t.querySelector('.t-title').textContent,(t.querySelector('.t-desc')||{}).textContent||''];})()")
            out.append((reason, server_text, title, desc))
        return page, out

    def test_error_toasts_are_english(self):
        """en: each refusal's toast shows the English message for its reason code, with no Hangul left in it."""
        page, toasts = self.error_toasts("en")
        for reason, _, title, desc in toasts:
            with self.subTest(reason=reason):
                self.assertEqual(desc, ps.UI_EN["reason:" + reason])
                self.assertFalse(HANGUL.search(title + desc), (title, desc))
        self.assert_english(page, "after the error toasts")

    def test_error_toasts_keep_the_server_text_in_korean(self):
        """ko: each refusal's toast shows the server's Korean error text exactly, as before."""
        _, toasts = self.error_toasts("ko")
        for reason, server_text, _, desc in toasts:
            with self.subTest(reason=reason):
                self.assertEqual(desc, server_text)

    def test_the_limn_mark_survives_boot_and_pin_marks(self):
        """After boot has drawn the pins' boxes on the PDF (.mark, removed and redrawn by marks()), the three Limn marks
        (top bar, [더보기] label, help header) are still in the page - a first cut shared the .mark class and lost them."""
        page = self.open("en", viewport={"width": 1400, "height": 850})
        page.evaluate("marks()")
        self.assertEqual(page.evaluate("document.querySelectorAll('svg.limn-mark').length"), 3)
        self.assertEqual(page.evaluate("document.querySelector('#paper-identity-mark svg').getBoundingClientRect().width"), 16)

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
