"""The text surface's pure rules and the hidden-character repertoire every document kind marks: the ladder over a text
document's lines, the hang of a wrapped line, the closing line of an indented block, and which characters are marked by
name and which sequences keep theirs (docs/adr/0029-text-documents.md D3, D5, D7;
docs/superpowers/specs/2026-11-05-text-documents.md §결정 5).

The production parts js/platform/hidden-chars.ts and js/text/view.ts run under node whole, as the page serves them, so every
constant and table the rules read is the served one (no copy here). The browser behaviour - the DOM, the limits, picks,
marks, the composer - is test_viewer_text.py.

Run: uv run pytest -q src/limn/viewer/tests/test_text_surface.py
"""

import json
import shutil
import unittest

from helpers import HTML, VIEWER, extract_js_fn, js_esc, js_markup, run_node
from helpers_js import module_code, module_texts

PARTS = ("js/platform/hidden-chars.ts", "js/text/view.ts")

PY = [
    "import os",  # 1
    "",  # 2
    "class Panel:",  # 3
    '    """Doc."""',  # 4
    "",  # 5
    "    def label(self):",  # 6
    "        x = 1",  # 7
    "        return x",  # 8
    "",  # 9
    "def draw(ax):",  # 10
    "    ax.plot(",  # 11
    "        1,",  # 12
    "    )",  # 13
    "    ax.grid()",  # 14
    "",  # 15
    "main()",  # 16
]
BIB = ["@article{a,", "  title = {T},", "}", "", "@book{b,", "  title = {U},", "}"]


def served_parts() -> str:
    """The two modules exactly as the page's script serves them (each module's code is in the script byte for byte, its
    types, import and export statements taken out), after the markup module markHiddenHtml builds with and markdown/view.ts's lineSnippet,
    which a rung's snippet comes from."""
    parts = [module_code(text) for text in module_texts([VIEWER / name for name in PARTS])]
    for name, text in zip(PARTS, parts, strict=True):
        assert text in HTML, name  # the build joins the modules' code byte for byte (tools/build_viewer.mjs)
    return "\n".join([js_esc(), js_markup(), extract_js_fn("lineSnippet"), *parts])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TextSurfacePure(unittest.TestCase):
    """The ladder, hang and closing lines of a text document, under node."""

    def run_js(self, body: str):
        """Evaluate body (an expression) with the served parts; its JSON value."""
        return json.loads(run_node(served_parts() + "\nconsole.log(JSON.stringify(%s));" % body))

    def blocks(self, lines, picks):
        """indentBlockAround of lines for each [lo, hi] in picks, as [lo, hi] or None."""
        got = self.run_js(
            "%s.map(([a,b])=>{const r=indentBlockAround(%s,a,b); return r&&[r.lo,r.hi];})"
            % (json.dumps(picks), json.dumps(lines))
        )
        return [tuple(r) if r else None for r in got]

    def test_columns_and_hang(self):
        """Tabs advance to the next multiple of four; a blank line has no indentation. The hang is the indentation,
        rounded down to a tab stop only on a line holding a tab, and at most sixteen."""
        got = self.run_js(
            "['abc','  a','\\ta',' \\ta','   ','\\t\\t\\t\\t\\tx','      x'].map(l=>[indentColumns(l),hangColumns(l)])"
        )
        self.assertEqual(got, [[0, 0], [2, 2], [4, 4], [4, 4], [-1, 0], [20, 16], [6, 6]])

    def test_paragraph_widens_to_blank_lines_and_counts_runs(self):
        """A line's paragraph is its run of non-blank lines; a range over a blank line meets two."""
        lines = json.dumps(PY)
        got = self.run_js("[[7,7],[2,2],[8,10],[16,16]].map(([a,b])=>paragraphAround(%s,a,b))" % lines)
        self.assertEqual(
            got, [{"lo": 6, "hi": 8, "n": 1}, None, {"lo": 6, "hi": 14, "n": 2}, {"lo": 16, "hi": 16, "n": 1}]
        )

    def test_indent_block_heads_or_encloses(self):
        """A header line takes the body it heads; a body line takes the block it stands in, closing bracket included;
        a top-level line that heads nothing has no block."""
        lines = json.dumps(PY)
        got = self.run_js(
            "[[6,6],[7,7],[12,12],[11,11],[3,3],[1,1],[16,16]].map(([a,b])=>indentBlockAround(%s,a,b))" % lines
        )
        self.assertEqual(
            got,
            [
                {"lo": 6, "hi": 8, "title": "def label(self):"},
                {"lo": 6, "hi": 8, "title": "def label(self):"},
                {"lo": 11, "hi": 13, "title": "ax.plot("},
                {"lo": 11, "hi": 13, "title": "ax.plot("},
                {"lo": 3, "hi": 8, "title": "class Panel:"},
                None,
                None,
            ],
        )

    def test_a_bib_entry_is_one_block(self):
        """An entry's first line heads its fields, and its closing brace at the header's depth belongs to it."""
        got = self.run_js("[1,2].map(n=>indentBlockAround(%s,n,n))" % json.dumps(BIB))
        self.assertEqual(got, [{"lo": 1, "hi": 3, "title": "@article{a,"}] * 2)

    def test_a_call_or_assignment_spelt_like_a_closing_word_is_not_a_closing_line(self):
        """Python after an if: 'done()', 'done = True', 'done.append(x)', 'end = 3', 'fi()' at the header's depth start the
        next statement; the block is the header and its body alone."""
        for after in ("done()", "done = True", "done.append(x)", "end = 3", "fi()", "esac=1", "end-1", "done.x = 1"):
            with self.subTest(after=after):
                lines = ["if ready:", "    process()", after, "archive()"]
                self.assertEqual(self.blocks(lines, [[1, 1], [2, 2]]), [(1, 2), (1, 2)])

    def test_a_closing_word_or_bracket_alone_closes_its_block(self):
        """Shell's done (with a redirection, a pipe, ';' or a comment), fi and esac, Ruby's and Lua's end (with ')' or
        ','), and a line that starts with a closing bracket ('}', '} else {', '});', ']') belong to the block they close."""
        cases = {
            "for done": ["for f in *; do", "  echo $f", "done", "ls"],
            "while done < file": ["while read l; do", "  echo $l", "done < list.txt", "ls"],
            "done | pipe": ["for f in *; do", "  echo $f", "done | sort", "ls"],
            "done;": ["for f in *; do", "  echo $f", "done;", "ls"],
            "fi # comment": ["if [ -f a ]; then", "  cat a", "fi # done", "ls"],
            "esac": ["case $x in", "  a) echo a;;", "esac", "ls"],
            "ruby end": ["def f", "  1", "end", "f"],
            "lua end)": ["f(function()", "  x()", "end)", "g()"],
            "matlab end % c": ["for k = 1:3", "  disp(k)", "end % loop", "x = 1"],
            "brace": ["function f() {", "  x();", "}", "f();"],
            "} else {": ["if (a) {", "  x();", "} else {", "  y();", "}"],
            "});": ["it('a', () => {", "  ok();", "});", "done();"],
            "]": ["xs = [", "  1,", "]", "y = 2"],
        }
        for name, lines in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.blocks(lines, [[1, 1]]), [(1, 3)])
        lua = ["t = {", "  a = function()", "    x()", "  end,", "  b = 2,", "}"]
        self.assertEqual(self.blocks(lua, [[2, 2], [3, 3]]), [(2, 4), (2, 4)])

    def test_a_block_label_shows_the_headers_hidden_characters_by_name_before_it_is_cut(self):
        """The indent rung's label is '블록 · ' and at most twelve characters of the header, a hidden character's name
        whole (never cut inside it, never the raw character); a header of twelve or fewer characters is not cut."""
        got = self.run_js(
            "(()=>{globalThis.MARKDOWN_VIEW={lines:['def \\u202echeck(x):','    return x','def ok():','    pass']};"
            "return [textLevels({lo:1,hi:1}),textLevels({lo:3,hi:3})].map(ls=>ls.find(l=>l.level==='indent').label);})()"
        )
        self.assertEqual(got, ["블록 · def ⟨U+202E⟩…", "블록 · def ok():"])
        self.assertNotIn("‮", "".join(got))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class HiddenCharacters(unittest.TestCase):
    """The repertoire (HIDDEN_RANGES), its exceptions (isKeptInSequence) and its forms (markHiddenPlain, clipMarkedText, markHiddenHtml,
    countAddedHidden), under node."""

    def run_js(self, body: str):
        """Evaluate body (an expression) with the served parts; its JSON value."""
        return json.loads(run_node(served_parts() + "\nconsole.log(JSON.stringify(%s));" % body))

    def names(self, cases):
        """For each [text, first] the names of the characters findHidden marks."""
        return self.run_js(
            "%s.map(([s,f])=>findHidden(s,f).map(c=>hiddenName(c.ch.codePointAt(0))))"
            % json.dumps(cases, ensure_ascii=False)
        )

    def test_the_repertoire_is_the_unicode_properties_it_names(self):
        """Over every code point, HIDDEN_PATTERN (built from HIDDEN_RANGES) matches exactly Default_Ignorable_Code_Point,
        Bidi_Control, a control but tab and line feed, U+2028, U+2029 and U+FFF9-U+FFFB - as the engine's own Unicode
        tables have them."""
        got = self.run_js(
            "(()=>{const di=/\\p{Default_Ignorable_Code_Point}|\\p{Bidi_Control}|\\p{Cc}/u,re=new RegExp('^'+HIDDEN_PATTERN.source+'$','u'),bad=[];"
            "for(let c=0;c<=0x10ffff;c++){if(c>=0xd800&&c<=0xdfff)continue; const s=String.fromCodePoint(c);"
            "const want=(di.test(s)&&c!==9&&c!==10)||c===0x2028||c===0x2029||(c>=0xfff9&&c<=0xfffb);"
            "if(re.test(s)!==want)bad.push(c.toString(16));} return bad.slice(0,20);})()"
        )
        self.assertEqual(got, [])

    def test_each_kind_of_hidden_character_is_marked_by_name(self):
        """Bidi controls (embedding, override, isolate, marks), zero-width characters, the word joiner and invisible
        operators, the soft hyphen, the combining grapheme joiner, the Hangul fillers, the deprecated format characters,
        tags and the supplementary variation selectors (one name for a surrogate pair), musical format controls, C0 and
        C1 controls and DEL (pictures), line and paragraph separators, interlinear annotation: each is marked."""
        cases = [
            ["a‮b⁦c‏d؜", False],
            ["x​y⁠z⁢w﻿v", False],
            ["co­op͏q", False],
            ["ㅤﾠᅟᅠ", False],
            ["a⁪b᠎c", False],
            ["x\U000e0041\U000e007fy\U000e0100z\U0001d173", False],
            ["a\x1bb\x7fc\x85d\x00e", False],
            ["a b c￹d", False],
            ["tab\tstays", False],
        ]
        self.assertEqual(
            self.names(cases),
            [
                ["U+202E", "U+2066", "U+200F", "U+061C"],
                ["U+200B", "U+2060", "U+2062", "U+FEFF"],
                ["U+00AD", "U+034F"],
                ["U+3164", "U+FFA0", "U+115F", "U+1160"],
                ["U+206A", "U+180E"],
                ["U+E0041", "U+E007F", "U+E0100", "U+1D173"],
                ["␛", "␡", "U+0085", "␀"],
                ["U+2028", "U+2029", "U+FFF9"],
                [],
            ],
        )

    def test_a_sequence_that_needs_its_character_keeps_it(self):
        """Kept: a byte-order mark at the start of line 1; ZWNJ and ZWJ between Persian or Devanagari letters; ZWJ in an
        emoji sequence (family, skin tone, flag with VS16); VS16 after a pictograph and in a keycap; an ideographic
        variation sequence; a Mongolian free variation selector after a Mongolian letter; a Hangul filler beside a real
        jamo. Marked: the same characters elsewhere - a BOM past the start or on another line, ZWJ between ASCII or
        Hangul letters, VS16 after a letter, an IVS after ASCII, both fillers together."""
        kept = [
            ["﻿x", True],
            ["می‌خواهم", False],
            ["क्‍ष", False],
            ["\U0001f468‍\U0001f469‍\U0001f467", False],
            ["\U0001f469\U0001f3fd‍\U0001f4bb", False],
            ["\U0001f3f3️‍\U0001f308", False],
            ["❤️", False],
            ["1️⃣", False],
            ["葛\U000e0100", False],
            ["ᠠ᠋", False],
            ["ᅟᅡ", False],
            ["ᄀᅠ", False],
        ]
        self.assertEqual(self.names(kept), [[]] * len(kept))
        marked = [
            ["x﻿", True],
            ["﻿x", False],
            ["us‍er", False],
            ["변‍수", False],
            ["a‌b", False],
            ["a️", False],
            ["a\U000e0100", False],
            ["a᠋", False],
            ["ᅟᅠ", False],
            ["‍\U0001f469", False],
        ]
        self.assertEqual(
            self.names(marked),
            [
                ["U+FEFF"],
                ["U+FEFF"],
                ["U+200D"],
                ["U+200D"],
                ["U+200C"],
                ["U+FE0F"],
                ["U+E0100"],
                ["U+180B"],
                ["U+115F", "U+1160"],
                ["U+200D"],
            ],
        )

    def test_the_plain_form_names_each_character_and_the_clip_never_cuts_a_name(self):
        """markHiddenPlain puts each name in angle brackets; clipMarkedText counts a name whole, adds '…' only when it cut, and never splits
        a surrogate pair."""
        got = self.run_js(
            "[markHiddenPlain('if a\\u202e b'),clipMarkedText('\\u202eabcdefghijklmnop',12),clipMarkedText('abcdefghij\\u202ek',12),clipMarkedText('short',12),"
            "clipMarkedText('\\u{1F600}'.repeat(14),12),clipMarkedText('abcdefghijkl',12)]"
        )
        self.assertEqual(
            got,
            [
                "if a⟨U+202E⟩ b",
                "⟨U+202E⟩abcd…",
                "abcdefghij…",
                "short",
                "\U0001f600" * 12 + "…",
                "abcdefghijkl",
            ],
        )

    def test_the_markup_keeps_the_character_inside_its_isolating_box(self):
        """markHiddenHtml escapes the text and puts each marked character in a .sr-only child of a .cc box named by it - as its code
        point (data-cp) for setHtml to put in as text, never raw in the markup, where the HTML parser loses a NUL or a CR."""
        got = self.run_js("[markHiddenHtml('<b>\\u202e&').text,markHiddenHtml('a\\u0000b\\rc').text]")
        self.assertEqual(
            got,
            [
                '&lt;b&gt;<span class="cc" data-cc="U+202E"><span class="sr-only" data-cp="202e"></span></span>&amp;',
                'a<span class="cc" data-cc="\u2400"><span class="sr-only" data-cp="0"></span></span>b'
                '<span class="cc" data-cc="\u240d"><span class="sr-only" data-cp="d"></span></span>c',
            ],
        )

    def test_added_counts_what_a_text_has_more_of_than_its_base(self):
        """Per name, the text's count less the base's, in the order the text first has them; kept sequences count
        nothing."""
        got = self.run_js(
            "[countAddedHidden('a\\u202eb\\nc\\u200b\\u202e','a\\u202eb\\nc'),countAddedHidden('x\\u202e','x\\u202e'),"
            "countAddedHidden('\\u{1F468}\\u200d\\u{1F469}',''),countAddedHidden('x\\u{E0041}\\u{E0041}','x')]"
        )
        self.assertEqual(got, [[["U+202E", 1], ["U+200B", 1]], [], [], [["U+E0041", 2]]])


if __name__ == "__main__":
    unittest.main()
