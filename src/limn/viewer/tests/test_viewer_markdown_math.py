"""TeX math drawn by the bundled KaTeX (docs/adr/0036-markdown-drawn-math.md, docs/handbook/viewer.md §수식).

The real viewer against the in-process server (BrowserBase) on a math fixture close to test_viewer_markdown.py's, whose
Math class refuses the bundle and holds the undrawn side of the same document (ADR-0036 D2's first fallback):

- Drawn: every formula is drawn, each in a box carrying its source TeX on data-tex and standing where its characters
  stood - one that the worker cut at a source line end is put back together and drawn once, in the line it starts in,
  carrying the lines it covers; the formulas that are not drawn keep every character - one KaTeX refuses and one with a
  character that hides or reorders text (D2);
- Lines: the drawn document names every source line that has text, the display math is one block over its lines, and a
  formula over a line end covers both of them, so the drawing changed nothing a pin is saved by (D3);
- Quote: a drag over a line with drawn math, a drag cutting into the middle of a drawn formula, a tap on a drawn display
  block and a drag over a formula that runs past a line end all quote the manuscript's TeX, never the glyphs; the saved
  pin is md:math over the block's lines, and the formula over a line end is saved over both of its lines (D4);
- Policy: the sent page policy names no new source and admits no inline style (D7) - a violation would fail any browser
  test here through the autouse no_csp_violation fixture;
- Budget: three thousand formulas pass MD_LIMITS.elements and the document falls back to the source-line view (D6);
- Quiet: a document without math asks for neither the module nor the stylesheet (D1);
- Compare: a render context that does not draw math draws none, whatever the document view did (D3);
- DrawnFirefox, DrawnWebkit, QuoteFirefox: the same in the other two engines.

The bundle's provenance and its serving are in test_vendor_katex.py; the rules that decide what may be drawn are in
test_md_surface.py; math with hidden characters is also in test_viewer_markdown_hidden.py.

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_markdown_math.py
"""

import json

from limn.administration import serve_documents as startup_documents
from limn.viewer import assemble

from helpers import ps, req
from helpers_browser import VIEWPORTS, BrowserBase, settle
from helpers_figure import BUILD1, viewer_build

DRAWN = "typeof MD!=='undefined'&&MD.shown===DOC&&!!document.querySelector('#md')&&!MD.job"
# The renderer has answered: it is ready, or it is off for good (ADR-0036 D2).
SETTLED = "typeof MD_TEX!=='undefined'&&MD_TEX.state!=='none'"
ORIGIN = "http://viewer.test"
RLO = "‮"  # U+202E, one of the characters that reorder text (ADR-0029 D5): a formula holding one is never drawn
# The math fixture: the lab's t-star pair; currency, escaped dollars and a code span, which are no math; display math over
# three lines; inline math over a line end (two pieces, neither TeX on its own); a formula KaTeX refuses; a formula with a
# reordering character in it; math in a table and in a list.
FIXTURE = (
    r"""# 수식 노트

중단 시점 $t^*$ 는 오차가 처음 늘어나는 달이고, $t^*=\infty$ 는 끝까지 늘지 않는다는 뜻이다.
가격은 $5 와 $10 이고, 이스케이프한 \$x\$ 는 글자다.
`$code$` 는 코드다.

$$
\mathrm{Gain}(t) = \frac{\mathrm{MSE}_{\text{no-TL}} - \mathrm{MSE}_{\text{arm}}}{\mathrm{MSE}_{\text{no-TL}}}
$$

여러 줄에 걸친 $a_1 +
b_2$ 뒤 문장.

거부되는 수식 $\thisisnotatexcommand{x}$ 뒤.
숨은 문자가 든 수식 $x"""
    + RLO
    + r"""y$ 뒤.

| 기호 | 뜻 |
| --- | --- |
| $x_i$ | 건물 $i$ 의 *부하* |

- 목록의 $\Delta_{ij}$ 와 \(y_{i,t}\)
"""
)
LINES = FIXTURE.split("\n")
MATH_LINE = LINES.index("$$") + 1  # the display math's opening line
PIECES_LINE = LINES.index(r"여러 줄에 걸친 $a_1 +") + 1
REFUSED_LINE = LINES.index(r"거부되는 수식 $\thisisnotatexcommand{x}$ 뒤.") + 1
HIDDEN_LINE = REFUSED_LINE + 1
LIST_LINE = LINES.index(r"- 목록의 $\Delta_{ij}$ 와 \(y_{i,t}\)") + 1
# The block's content as the block rule gives it: its lines without the last line feed (markdown-it getLines, keepLastLF
# false), which is what data-tex carries.
DISPLAY_TEX = (
    "$$\n\\mathrm{Gain}(t) = \\frac{\\mathrm{MSE}_{\\text{no-TL}} - "
    "\\mathrm{MSE}_{\\text{arm}}}{\\mathrm{MSE}_{\\text{no-TL}}}\n$$"
)
# Every drawn formula, in document order: [its source TeX, the source lines it is on, its tag]. A box that carries its own
# range answers with it - a display block, and an inline formula the worker cut at a line end; otherwise the line span it
# stands in answers, and null is a table cell's inline token, which has no map of its own.
BOXES = (
    "[...document.querySelectorAll('#md .md-tex')].map(e=>{const own=e.dataset.lo?[+e.dataset.lo,+e.dataset.hi]:null;"
    "const l=e.closest('[data-line]');"
    "return [e.getAttribute('data-tex'),own||(l?+l.dataset.line:null),e.tagName];})"
)
# Every formula left as characters, in document order: [its text, the source line it stands on].
PLAIN = (
    "[...document.querySelectorAll('#md code.md-math:not(.md-tex),#md pre.md-math-block')].map(e=>{"
    "const l=e.closest('[data-line]')||e; return [e.textContent,l.dataset.line?+l.dataset.line:null];})"
)
# Every source line the drawing claims, through a line span or a block's range.
SHOWN = (
    "[...document.querySelectorAll('#md [data-line],#md [data-lo]')].flatMap(e=>e.dataset.line?[+e.dataset.line]:"
    "Array.from({length:+e.dataset.hi-+e.dataset.lo+1},(_,i)=>+e.dataset.lo+i))"
)


class MathBase(BrowserBase):
    """BrowserBase with the Markdown document nt (notes.md, MD_TEXT) first and the LaTeX manuscript ms second, so the
    viewer opens on the Markdown document."""

    MD_TEXT = FIXTURE

    def setUp(self):
        super().setUp()
        self.src = self.main.parent
        self.md = self.src / "notes.md"
        self.md.write_text(self.MD_TEXT, encoding="utf-8")
        docs = startup_documents.make_docs(["nt=노트:notes.md", "ms=본문:main.tex"], self.src, ps.APP.C.paths)
        assert isinstance(docs, list), docs
        ps.APP.set_docs(docs)
        self.nt, self.ms = docs
        viewer_build(self.ms, BUILD1)

    def open_md(self, **kw):
        """The viewer on the Markdown document, once it is drawn and the renderer has answered."""
        page = self.open(0, **kw)
        page.wait_for_function(DRAWN, timeout=20000)
        page.wait_for_function(SETTLED, timeout=20000)
        settle(page)
        return page

    def records(self):
        """The live pin records in the state folder."""
        f = ps.APP.C.state / "pins.jsonl"
        return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def quote_over(self, page, js_range):
        """The quote the surface's own pick builds over the range js_range gives: the selection is set, mdSelectionPick
        runs as a mouse release runs it, and the composer's quote is read."""
        page.evaluate(
            "(()=>{const r=%s,sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r);"
            "mdSelectionPick(null);})()" % js_range
        )
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        quote = page.evaluate("COMPOSE.current.quote")
        page.keyboard.press("Escape")
        page.wait_for_function("!COMPOSE.current", timeout=5000)
        return quote


class Drawn(MathBase):
    """What the drawn document holds."""

    def test_every_formula_is_drawn_with_its_source_tex_where_it_stood(self):
        """The eight formulas are drawn, each in a box carrying its source TeX on data-tex, on the line its characters
        stood on - for display math, one block (a div, not a code box) over its three lines, kind math; for the formula
        the worker cut at a line end, one code box in the line it starts in, carrying both of its lines. The stylesheet
        comes from this origin at the bundled version. Mutation: leave data-tex off in mdTexBox -> null here and the
        quote tests fail."""
        page = self.open_md()
        self.assertEqual(
            page.evaluate(BOXES),
            [
                ["$t^*$", 3, "CODE"],
                ["$t^*=\\infty$", 3, "CODE"],
                [DISPLAY_TEX, [MATH_LINE, MATH_LINE + 2], "DIV"],
                ["$a_1 +\nb_2$", [PIECES_LINE, PIECES_LINE + 1], "CODE"],
                ["$x_i$", None, "CODE"],  # a table cell's inline token has no map: its row's range stands for it
                ["$i$", None, "CODE"],
                ["$\\Delta_{ij}$", LIST_LINE, "CODE"],
                ["\\(y_{i,t}\\)", LIST_LINE, "CODE"],
            ],
        )
        self.assertEqual(page.evaluate("mdRxOf(document.querySelector('#md')).tex"), 8)
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-tex .katex').length"), 8)
        self.assertEqual(page.evaluate("MD_TEX.state"), "ready")
        self.assertEqual(
            page.evaluate("[...document.styleSheets].map(s=>s.href).filter(h=>h&&h.includes('/vendor/katex/'))"),
            ["%s/vendor/katex/katex.css?v=%s" % (ORIGIN, assemble.KATEX_VERSION)],
        )

    def test_the_formulas_that_are_not_drawn_keep_every_character(self):
        """ADR-0036 D2: TeX KaTeX refuses and a formula holding a character that hides or reorders text stay as their
        source characters in the code face, on their own lines - as they were before this renderer, the hidden character
        in its box. Mutation: drop the CC_ANY test from mdTexBox -> the reordering character is drawn away and its box is
        gone, fails."""
        page = self.open_md()
        self.assertEqual(
            page.evaluate(PLAIN),
            [
                ["$\\thisisnotatexcommand{x}$", REFUSED_LINE],
                ["$x" + RLO + "y$", HIDDEN_LINE],
            ],
        )
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md code.md-math:not(.md-tex) .cc')].map(e=>e.dataset.cc)"),
            ["U+202E"],
        )

    def test_an_inline_formula_sits_in_the_sentence_and_a_block_on_the_paragraphs_rhythm(self):
        """The measured rules of viewer.md §수식: a drawn inline formula takes the surrounding text's font size (KaTeX's
        own face inside it) and carries no tint; a drawn display block has the bottom margin every other block has and
        scrolls inside itself rather than widening the column; the MathML copy is out of any selection."""
        page = self.open_md()
        got = page.evaluate(
            "(()=>{const i=document.querySelector('#md code.md-math.md-tex'),p=i.closest('p,td,li'),"
            "b=document.querySelector('#md .md-math-block.md-tex'),q=document.querySelector('#md p'),"
            "gi=getComputedStyle(i),gb=getComputedStyle(b);"
            "return {size:[gi.fontSize,getComputedStyle(p).fontSize],tint:gi.backgroundColor,"
            "inner:getComputedStyle(i.querySelector('.katex')).fontFamily,"
            "margin:[gb.marginBottom,getComputedStyle(q).marginBottom],overflow:gb.overflowX,"
            "mathml:getComputedStyle(b.querySelector('.katex-mathml')).userSelect,"
            "fits:b.clientWidth<=document.querySelector('#md').clientWidth};})()"
        )
        self.assertEqual(got["size"][0], got["size"][1])
        self.assertEqual(got["tint"], "rgba(0, 0, 0, 0)")
        self.assertIn("KaTeX", got["inner"])
        self.assertEqual(got["margin"][0], got["margin"][1])
        self.assertEqual(got["overflow"], "auto")
        self.assertEqual(got["mathml"], "none")
        self.assertTrue(got["fits"])


class Lines(MathBase):
    """The drawn document names the same source lines as the undrawn one (ADR-0036 D3)."""

    def test_every_source_line_with_text_is_still_named_and_the_block_is_its_lines(self):
        """Drawing changes what is on screen, never which source lines the screen claims: every line that has text is
        named by a line span or a block's range, as it is in the undrawn document (test_viewer_markdown.py Math), and the
        display math is one block over exactly its three lines. Inside that block no line can be chosen any more - it is
        the smallest thing there, as a one-line '$$ … $$' already was. Mutation: leave mdMap off the drawn block -> its
        lines are claimed by nothing, fails."""
        page = self.open_md()
        lines = self.md.read_bytes().decode("utf-8").splitlines()
        self.assertEqual(sorted(set(page.evaluate(SHOWN))), [n for n, text in enumerate(lines, 1) if text.strip()])
        block = page.evaluate(
            "(()=>{const b=document.querySelector('#md [data-kind=math]'); return {tag:b.tagName,lo:+b.dataset.lo,"
            "hi:+b.dataset.hi,inside:b.querySelectorAll('[data-line],[data-lo]').length};})()"
        )
        self.assertEqual(block, {"tag": "DIV", "lo": MATH_LINE, "hi": MATH_LINE + 2, "inside": 0})
        # The formula written over a line end stands in the span of the line it starts in, but speaks for both lines:
        # kind 'lines', the run its two lines could not be told apart in (the same kind an inline token with line ends
        # that could not be followed already used, mdInline).
        run = page.evaluate(
            '(()=>{const e=document.querySelector("#md code.md-tex[data-lo]");'
            "return {kind:e.dataset.kind,lo:+e.dataset.lo,hi:+e.dataset.hi,"
            "line:+e.closest('[data-line]').dataset.line,inside:e.querySelectorAll('[data-line],[data-lo]').length};})()"
        )
        self.assertEqual(
            run, {"kind": "lines", "lo": PIECES_LINE, "hi": PIECES_LINE + 1, "line": PIECES_LINE, "inside": 0}
        )


class Quote(MathBase):
    """A pin's quote over drawn math is the manuscript's TeX (ADR-0036 D4)."""

    def test_a_drag_over_drawn_math_quotes_the_source_tex(self):
        """The whole line, and a drag that starts inside the drawn formula: both quote the line's own text with each
        formula as its source TeX, never the glyphs KaTeX drew or the MathML beside them. Mutation: take the [data-tex]
        substitution out of mdRangeText -> the quote holds the glyphs and not '$t^*$', fails; take mdTexWiden out -> the
        half drag's quote loses the formula."""
        page = self.open_md()
        whole = self.quote_over(
            page,
            "(()=>{const r=document.createRange();"
            "r.selectNodeContents(document.querySelector(\"#md [data-line='3']\")); return r;})()",
        )
        self.assertIn("$t^*$", whole)
        self.assertIn("$t^*=\\infty$", whole)
        self.assertNotIn("∞", whole)
        half = self.quote_over(
            page,
            "(()=>{const f=document.querySelector(\"#md [data-line='3'] .md-tex\"),ln=f.closest('[data-line]');"
            "const r=document.createRange(); r.setStart(f.querySelector('.katex-html'),0);"
            "r.setEnd(ln,ln.childNodes.length); return r;})()",
        )
        self.assertIn("$t^*$", half)
        self.assertNotIn("∞", half)

    def test_a_formula_past_a_line_end_is_quoted_whole_over_both_its_lines(self):
        """A formula written over two source lines is one drawn box. A drag inside it quotes the whole formula, both
        pieces and the delimiters, with the line end between them read as the space a quote makes of every line end (a
        quote is one line - a drawn display block already reads this way); the pin offered and saved covers both of the
        lines the formula took, so the quote and the range say the same thing. Mutation: leave the box's data-lo/hi off
        in mdInline -> the pin covers only the line the formula starts in while its quote holds both lines, fails."""
        page = self.open_md()
        page.evaluate(
            '(()=>{const f=document.querySelector("#md code.md-tex[data-lo]");const r=document.createRange();'
            "r.selectNodeContents(f.querySelector('.katex-html'));"
            "const sel=window.getSelection(); sel.removeAllRanges(); sel.addRange(r); mdSelectionPick(null);})()"
        )
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        got = page.evaluate("({lo:COMPOSE.current.lo,hi:COMPOSE.current.hi,quote:COMPOSE.current.quote})")
        self.assertEqual(got["quote"], "$a_1 + b_2$")
        self.assertEqual((got["lo"], got["hi"]), (PIECES_LINE, PIECES_LINE + 1))
        n = page.evaluate("PINS.length")
        page.fill("#note", "두 줄에 걸친 수식")
        page.click("#btn-save")
        page.wait_for_function("PINS.length>%d" % n, timeout=8000)
        rec = self.records()[-1]
        self.assertEqual((rec["lo"], rec["hi"]), (PIECES_LINE, PIECES_LINE + 1))
        self.assertIn("$a_1 +", rec["quote"])
        self.assertIn("b_2$", rec["quote"])

    def test_a_tap_on_drawn_display_math_picks_the_block_and_saves_md_math(self):
        """A tap on the drawn block offers the block and the section - the chosen lines are the block's, so that rung
        merges into it, as a one-line '$$ … $$' already did; its quote is the TeX as written; the saved pin is the
        block's lines, kind md:math, scope block, and pins.md names it."""
        page = self.open_md()
        page.locator("#md .md-math-block.md-tex").click()
        page.wait_for_function("COMPOSE.current&&COMPOSE.current.lo>0", timeout=5000)
        got = page.evaluate(
            "({lo:COMPOSE.current.lo,hi:COMPOSE.current.hi,scope:COMPOSE.current.scope,quote:COMPOSE.current.quote,"
            "levels:COMPOSE.current.levels.map(l=>[l.level,l.lo,l.hi,l.env||null])})"
        )
        self.assertEqual((got["lo"], got["hi"], got["scope"]), (MATH_LINE, MATH_LINE + 2, "block"))
        self.assertEqual(got["levels"][0], ["block", MATH_LINE, MATH_LINE + 2, "math"])
        self.assertEqual(got["levels"][1][0], "section")
        self.assertTrue(got["quote"].startswith("$$ \\mathrm{Gain}(t)"), got["quote"])
        self.assertTrue(got["quote"].endswith("$$"), got["quote"])
        n = page.evaluate("PINS.length")
        page.fill("#note", "고쳐 주세요")
        page.click("#btn-save")
        page.wait_for_function("PINS.length>%d" % n, timeout=8000)
        rec = self.records()[-1]
        self.assertEqual(
            (rec["lo"], rec["hi"], rec["kind"], rec["scope"]), (MATH_LINE, MATH_LINE + 2, "md:math", "block")
        )
        self.assertIn("\\mathrm{Gain}", rec["quote"])
        md = self.talk(req("GET", "/pins.md"))[2].decode()
        row = next(ln for ln in md.splitlines() if ln.startswith("| ") and "L%d-L%d" % (MATH_LINE, MATH_LINE + 2) in ln)
        self.assertIn("md:math", row)


class Policy(MathBase):
    """The page policy is not widened (ADR-0036 D7)."""

    def test_the_sent_policy_names_no_new_source_and_the_drawing_reports_nothing(self):
        """KaTeX gives its boxes their sizes through the CSSOM, which the policy does not reach, and the stylesheet is a
        same-origin link, so 'self' already covers both. A violation would fail this test - and every other browser test
        here - through the autouse no_csp_violation fixture. Mutation: write the sizes with setAttribute('style', …) ->
        every formula reports, fails."""
        page = self.open_md()
        self.assertGreater(page.evaluate("document.querySelectorAll('#md .katex').length"), 0)
        policy = self.talk(req("GET", "/"))[1]["content-security-policy"]
        for absent in ("unsafe-inline", "unsafe-eval", "katex", "nonce-"):
            self.assertNotIn(absent, policy)
        for present in ("default-src 'self'", "script-src 'self' 'sha256-", "style-src 'self' 'sha256-"):
            self.assertIn(present, policy)


class Budget(MathBase):
    """The elements KaTeX builds count against the limit (ADR-0036 D6)."""

    MD_TEXT = "# 많은 수식\n\n" + ("".join("$x_{%d}$ " % i for i in range(20)) + "\n\n") * 150

    def test_three_thousand_formulas_pass_the_limit_and_fall_back_to_the_source_lines(self):
        """Three thousand formulas are past MD_LIMITS.elements (60,000): the document becomes the
        plain source-line view with every source line in it, and says which limit it hit, as a document of too many
        elements already did. Mutation: leave the drawn elements out of the count in mdTexBox -> the document is drawn
        past the limit, fails."""
        page = self.open_md()
        self.assertEqual(page.evaluate("document.querySelector('#md').dataset.limit"), "elements")
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .katex').length"), 0)
        self.assertEqual(
            page.evaluate("[...document.querySelectorAll('#md .md-src .ln')].map(e=>+e.dataset.line)"),
            list(range(1, len(self.MD_TEXT.splitlines()) + 1)),
        )


class Quiet(MathBase):
    """A document with no math asks for no bundle (ADR-0036 D1)."""

    MD_TEXT = "# 수식 없는 글\n\n가격은 $5 와 $10 이고 `$code$` 는 코드다.\n\n- 목록\n"

    def setUp(self):
        super().setUp()
        self.asked = []

    def route(self, route):
        if "/vendor/katex/" in route.request.url:
            self.asked.append(route.request.url)
        return super().route(route)

    def test_neither_the_module_nor_the_stylesheet_is_asked_for(self):
        """Mutation: ask for the renderer whatever the document holds (drop the mdTexWanted test in mdBuild) -> two
        requests, fails."""
        page = self.open(0)
        page.wait_for_function(DRAWN, timeout=20000)
        settle(page)
        self.assertEqual(self.asked, [])
        self.assertEqual(page.evaluate("MD_TEX.state"), "none")
        self.assertEqual(page.evaluate("document.querySelectorAll('#md .md-tex').length"), 0)


class Narrow(MathBase):
    """A drawn formula wider than the column stays reachable on the narrowest screen (ADR-0037 D5)."""

    # One formula far wider than a 320 px column, one that fits, and one of the wide one written over a line end.
    WIDE = (
        r"\alpha_1 \beta_2 \gamma_3 \delta_4 \epsilon_5 \zeta_6 \eta_7 \theta_8 "
        r"\iota_9 \kappa_{10} \lambda_{11} \mu_{12} \nu_{13} \xi_{14} \pi_{15} \rho_{16}"
    )
    MD_TEXT = "# 넓은 수식\n\n한 줄: $%s$ 끝.\n\n접은 줄: $%s\n%s$ 끝.\n\n짧은 것: $x_1$ 끝.\n" % (
        WIDE,
        WIDE[: WIDE.index(r"\iota_9")].rstrip(),
        WIDE[WIDE.index(r"\iota_9") :],
    )

    def test_a_formula_wider_than_the_column_scrolls_inside_itself(self):
        """On a 320 px screen a drawn inline formula wider than the column - written on one line or over a line end -
        is given `md-tex-wide`: it is held to the column and scrolls inside itself, so every glyph is reachable, and no
        part of it is past the screen's edge, where the page (which does not scroll sideways) would put it out of reach.
        A formula that fits is left alone and keeps the sentence's baseline, which a scrolling box would not.

        Mutation: drop the mdTexFit call from mdShow (or widen its test to every formula) -> either the wide formulas
        reach past the screen edge, which fails here, or the short formula gets `vertical-align: bottom`, which fails
        here too. This is the hole 0.4.56 had: it drew such a formula 328 px wide with its right edge at 380 px on a
        320 px screen."""
        page = self.open_md(**VIEWPORTS["phone 320x720"])
        got = page.evaluate(
            """() => {
              const md = document.querySelector('#md');
              const room = Math.round(md.clientWidth), vw = window.innerWidth;
              return [...md.querySelectorAll('code.md-math.md-tex')].map(e => {
                const r = e.getBoundingClientRect(), k = e.querySelector('.katex');
                return {wide: e.classList.contains('md-tex-wide'),
                        natural: Math.round(k.getBoundingClientRect().width),
                        w: Math.round(r.width), room, pastScreen: r.right > vw + 1,
                        scrolls: e.scrollWidth > e.clientWidth + 1,
                        align: getComputedStyle(e).verticalAlign,
                        tex: e.dataset.tex.replace(/\\n/g, ' ')};
              });
            }"""
        )
        self.assertEqual(len(got), 3, got)
        wide = [g for g in got if g["wide"]]
        fits = [g for g in got if not g["wide"]]
        self.assertEqual(len(wide), 2, got)  # the one-line formula and the one written over a line end
        self.assertEqual(len(fits), 1, got)
        for g in wide:
            self.assertGreater(g["natural"], g["room"], g)  # it really is wider than the column
            self.assertLessEqual(g["w"], g["room"], g)  # yet the box is held to the column
            self.assertFalse(g["pastScreen"], g)
            self.assertTrue(g["scrolls"], g)  # so the rest of it can be reached
        self.assertFalse(fits[0]["scrolls"], fits[0])
        self.assertEqual(fits[0]["align"], "baseline", fits[0])  # a box that scrolls would sit on its bottom edge

    def test_the_fit_follows_the_column_when_it_gets_wider(self):
        """The same document on a desktop column: the formulas fit, so none is told to scroll and every one keeps the
        baseline. Mutation: fit once at build time only and never again (drop mdTexFit from the column's
        ResizeObserver) -> this still passes, but the pane-collapse case a reader meets does not; the measurement here
        is what makes the rule depend on the column, not on the build."""
        page = self.open_md(**VIEWPORTS["desktop 1440x900"])
        got = page.evaluate(
            """() => [...document.querySelectorAll('#md code.md-math.md-tex')].map(e => ({
                 wide: e.classList.contains('md-tex-wide'), align: getComputedStyle(e).verticalAlign}))"""
        )
        self.assertEqual(len(got), 3, got)
        self.assertEqual([g["wide"] for g in got], [False, False, False], got)
        self.assertEqual({g["align"] for g in got}, {"baseline"}, got)


class Compare(MathBase):
    """A render context that does not draw math draws none (ADR-0036 D3)."""

    def test_a_context_of_its_own_keeps_the_source_characters(self):
        """The rendered compare builds each side with mdRx, whose tex is null: its block keys and its word diff read the
        drawn text, and a formula's TeX is what a reader compares between two revisions. Mutation: give mdRx a count
        instead of null -> the compare draws formulas and the display math block has no lines to compare, fails."""
        page = self.open_md()
        self.assertGreater(page.evaluate("document.querySelectorAll('#md .md-tex').length"), 0)
        got = page.evaluate(
            "(()=>{const cx=mdRx(['$x$']);"
            "return {tex:cx.tex,box:mdTexBox('code','md-math md-tex','$x$','x',false,cx),els:cx.els};})()"
        )
        self.assertEqual(got, {"tex": None, "box": None, "els": 0})


class DrawnFirefox(Drawn):
    """The same drawing in Firefox."""

    BROWSER_ENGINE = "firefox"


class DrawnWebkit(Drawn):
    """The same drawing in WebKit."""

    BROWSER_ENGINE = "webkit"


class QuoteFirefox(Quote):
    """The quote in Firefox, whose innerText reads a clipped box differently."""

    BROWSER_ENGINE = "firefox"


if __name__ == "__main__":
    import unittest

    unittest.main()
