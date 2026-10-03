"""The viewer writes HTML only as Html from html`` or ic(), and only through setHtml() (docs/handbook/viewer.md §마크업 만들기).

Two halves. Behavior: html`` keeps its literal parts and escapes every value that is not Html, so text a person or a
PDF wrote (a note, a name, an outline heading) never becomes markup; setHtml() refuses anything else. Source: the parts
are read as tokens (helpers_js) to hold the rules a browser cannot - no innerHTML write outside setHtml() beyond the
legacy count each part still has, no Html made outside markup.js, html never called as a plain function, and no html``
result joined with '+' (that turns it back into a string, which html`` would then escape a second time).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markup.py
"""

import html as stdlib_html
import json
import shutil
import unittest

from hypothesis import given, settings, strategies as st

from limn.viewer import assemble

import helpers_js
from helpers import VIEWER, extract_js_fn, js_esc, js_icons, run_node

PARTS = assemble.viewer_manifest(VIEWER)["__APP_JS__"]
MARKUP_PART = "js/markup.js"

# innerHTML writes each part still makes by hand, waiting to move to setHtml(html`...`). A part's count may only go
# down: moving a write lowers it here in the same change, and a part not listed may have none.
LEGACY_SINKS = {
    "js/revisions.js": 8,
}
SINK_PROPS = frozenset(["innerHTML", "outerHTML"])
SINK_CALLS = frozenset(["insertAdjacentHTML", "createContextualFragment", "write", "writeln"])


def part_sources() -> dict[str, str]:
    """Every JS part of the page, by manifest path, in page order."""
    return {name: (VIEWER / name).read_text(encoding="utf-8") for name in PARTS}


def template_end(toks: list[helpers_js.Token], k: int) -> int:
    """Index of the last token of the template literal whose first token is toks[k] (nested templates included)."""
    depth = 0
    for i in range(k, len(toks)):
        t = toks[i]
        if t.kind != "template":
            continue
        opens, closes = t.text.startswith("`"), t.text.endswith("`")
        depth += int(opens and not closes) - int(closes and not opens)
        if depth == 0:
            return i
    raise ValueError("template literal at token %d never closes" % k)


def sink_writes(src: str) -> int:
    """How many HTML sinks src uses: an assignment to .innerHTML or .outerHTML, or a call that parses markup."""
    toks = helpers_js.code(helpers_js.tokenize(src))
    n = 0
    for i, t in enumerate(toks[1:-1], start=1):
        if t.kind != "ident" or toks[i - 1].text not in (".", "?."):
            continue
        after = toks[i + 1].text
        n += (t.text in SINK_PROPS and after in ("=", "+=")) or (t.text in SINK_CALLS and after == "(")
    return n


def markup_misuse(sources: dict[str, str]) -> list[str]:
    """Each place a part breaks the markup rules: Html made outside markup.js, html used other than as a tag, or an
    html`` result that is an operand of '+'. Empty when every part keeps them."""
    found = []
    for name, src in sources.items():
        toks = helpers_js.code(helpers_js.tokenize(src))
        for k, t in enumerate(toks):
            if t.kind != "ident":
                continue
            prev = toks[k - 1].text if k else ""
            nxt = toks[k + 1] if k + 1 < len(toks) else None
            if t.text == "Html" and prev == "new" and name != MARKUP_PART:
                found.append("%s: new Html outside markup.js" % name)
            if t.text != "html" or prev in (".", "?.", "function"):
                continue
            if nxt is None or nxt.kind != "template" or not nxt.text.startswith("`"):
                found.append("%s: html not used as a tag" % name)
                continue
            end = template_end(toks, k + 1)
            after = toks[end + 1].text if end + 1 < len(toks) else ""
            if prev in ("+", "+=") or after in ("+", "+="):
                found.append("%s: html`` joined with '+'" % name)
    return found


def node_or_skip(case: unittest.TestCase) -> None:
    """Skip case when node is not installed: the behavior tests run the served markup.js."""
    if not shutil.which("node"):
        case.skipTest("node not available")


def run_markup(body: str) -> object:
    """Run body after the served esc(), ICONS and markup.js under node, and return what it printed as JSON."""
    return json.loads(run_node("\n".join([js_esc(), js_icons(), body])))


class MarkupValues(unittest.TestCase):
    """html`` keeps its literal markup and turns every value that is not Html into text."""

    def setUp(self):
        node_or_skip(self)

    def test_values_are_escaped_in_content_and_quoted_attributes(self):
        """A value with markup characters reads as text both between tags and inside a quoted attribute."""
        out = run_markup(
            "const v='<img src=x onerror=alert(1)> & \"q\" \\'s\\'';"
            'console.log(JSON.stringify(html`<b title="${v}">${v}</b>`.text));'
        )
        attr = "&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot; &#39;s&#39;"
        self.assertEqual(out, '<b title="%s">%s</b>' % (attr, attr))

    def test_html_and_icons_go_in_as_markup_and_arrays_join(self):
        """Html (an inner html``, an ic()) stays markup; an array joins its items by the same rules."""
        out = run_markup("console.log(JSON.stringify(html`<ul>${['a<',html`<li>b</li>`]}</ul>${ic('x')}`.text));")
        self.assertTrue(out.startswith('<ul>a&lt;<li>b</li></ul><svg class="ic ic-x"'), out)

    def test_null_and_undefined_are_nothing_but_false_and_zero_are_text(self):
        """Only null and undefined vanish, so a boolean attribute value or a count of 0 still shows."""
        out = run_markup("console.log(JSON.stringify(html`${null}|${undefined}|${false}|${0}|${true}`.text));")
        self.assertEqual(out, "||false|0|true")

    def test_plain_call_and_forged_values_are_refused(self):
        """html('...') throws; setHtml() throws for a string or an object shaped like Html; an unknown icon is empty."""
        out = run_markup(
            "const r=f=>{try{f();return 'ok';}catch(e){return e.constructor.name;}};"
            "const el={innerHTML:''};"
            "console.log(JSON.stringify([r(()=>html('<b>x</b>')), r(()=>setHtml(el,'<b>x</b>')),"
            "r(()=>setHtml(el,{text:'<b>x</b>'})), r(()=>setHtml(el,html`<i>${'<'}</i>`)), el.innerHTML, ic('nope').text]));"
        )
        self.assertEqual(out, ["TypeError", "TypeError", "TypeError", "ok", "<i>&lt;</i>", ""])

    @settings(max_examples=25, deadline=None)
    @given(st.lists(st.text(), min_size=1, max_size=40))
    def test_any_text_round_trips_and_opens_no_tag(self, values):
        """For any strings, each value comes back unchanged once the HTML entities are decoded, and its slot holds no
        '<', '>' or quote that could open a tag or leave the attribute."""
        out = run_markup(
            'const vs=%s; console.log(JSON.stringify(vs.map(v=>html`<p title="${v}">${v}</p>`.text)));'
            % json.dumps(values)
        )
        for value, text in zip(values, out, strict=True):
            inner = text[len('<p title="') : -len("</p>")]
            attr, _, content = inner.partition('">')
            for slot in (attr, content):
                self.assertFalse(set(slot) & set("<>\"'"), slot)
                self.assertEqual(stdlib_html.unescape(slot), value)


class MarkupSource(unittest.TestCase):
    """The parts write HTML only through setHtml(), make Html only in markup.js, and use html only as a tag."""

    def test_no_part_writes_html_beyond_its_legacy_count(self):
        """markup.js has exactly setHtml()'s write; every other part has exactly its LEGACY_SINKS count, so a new
        innerHTML write fails here and a moved one must lower the count."""
        counts = {name: sink_writes(src) for name, src in part_sources().items()}
        self.assertEqual(counts.pop(MARKUP_PART), 1)
        self.assertEqual({k: v for k, v in counts.items() if v}, LEGACY_SINKS)

    def test_parts_keep_the_markup_rules(self):
        """No part makes Html outside markup.js, calls html as a function, or joins an html`` result with '+'."""
        self.assertEqual(markup_misuse(part_sources()), [])

    def test_checks_catch_each_injected_violation(self):
        """Each rule rejects a planted break and accepts the legal form beside it."""
        legal = "setHtml(a,html`<b>${x}</b>`); const t=`${y}`+z; o.html=1; f(o.html);"
        self.assertEqual(markup_misuse({"js/a.js": legal}), [])
        self.assertEqual(sink_writes(legal + " el.innerHTML; s=el.innerHTML;"), 0)
        for bad, rule in [
            ("x=new Html(s);", "new Html outside markup.js"),
            ("x=html('<b>'+s+'</b>');", "html not used as a tag"),
            ("x=html;", "html not used as a tag"),
            ("x=html`<b>`+s;", "html`` joined with '+'"),
            ("x='<i>'+html`<b>${html`<u>`}</b>`;", "html`` joined with '+'"),
        ]:
            with self.subTest(bad=bad):
                self.assertEqual(markup_misuse({"js/a.js": bad}), ["js/a.js: %s" % rule])
        for bad in (
            "el.innerHTML=s;",
            "el.outerHTML+=s;",
            "el.insertAdjacentHTML('beforeend',s);",
            "document.write(s);",
        ):
            with self.subTest(bad=bad):
                self.assertEqual(sink_writes(bad), 1)


class MovedMarkup(unittest.TestCase):
    """Parts moved to html`` draw the same markup as before, with what people wrote still escaped."""

    def setUp(self):
        node_or_skip(self)

    def test_more_info_breaks_long_names_after_separators_and_escapes_them(self):
        """[더보기]'s meta keeps each piece whole, allows a break after / . _ - only, and escapes the file and person."""
        out = run_markup(
            "\n".join(
                [
                    extract_js_fn("who"),
                    extract_js_fn("commitShown"),
                    extract_js_fn("moreInfo"),
                    "console.log(JSON.stringify(String(moreInfo({main:'a<b>/c_d.tex',pages:[1,2],head:'-',"
                    "built_at:'2026-01-02T03:04:05'},{name:'Kim & Lee'}))));",
                ]
            )
        )
        self.assertEqual(
            out,
            '<span class="mc">a&lt;b&gt;/<wbr>c_<wbr>d.<wbr>tex</span> · <span class="mc">2쪽</span><br>'
            '<span class="mc">01-<wbr>02 03:04 빌드</span> · <span class="mc">나: Kim &amp; Lee</span>',
        )
