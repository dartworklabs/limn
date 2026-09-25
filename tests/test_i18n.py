"""Viewer UI language: the English message table (src/limn/ui_en.json) and its wiring.

The Korean strings in the HTML template are the source. In English mode the viewer swaps every string
found in the table. The agent contract (pins.md, API) is not translated.
"""
import importlib.util
import json
import os
import re
import shutil
import unittest
from html.parser import HTMLParser
from pathlib import Path

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


class MessageTable(unittest.TestCase):
    def test_table_loads_and_values_are_english(self):
        self.assertGreater(len(ps.UI_EN), 300)
        for k, v in ps.UI_EN.items():
            self.assertTrue(HANGUL.search(k), k)
            self.assertFalse(HANGUL.search(v), (k, v))
            self.assertTrue(v.strip(), k)

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
            raise unittest.SkipTest("Playwright unavailable")
        cls.pw = sync_playwright().start()
        exe = os.environ.get("LIMN_CHROMIUM") or shutil.which("google-chrome") or shutil.which("chromium")
        try:
            cls.browser = cls.pw.chromium.launch(executable_path=exe or None, args=["--no-sandbox"])
        except Exception as e:  # no bundled or system browser
            cls.pw.stop()
            if required:
                raise
            raise unittest.SkipTest("Chromium unavailable: %s" % e)
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
