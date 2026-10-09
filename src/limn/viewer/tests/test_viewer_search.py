"""In-document text search in the viewer (docs/handbook/viewer.md §본문 검색).

The pure parts - folding text for matching, grouping PDF.js text items into lines, joining a page's lines into the text a
query runs over, finding across line breaks, stepping, the field's width rule and a hit's box - run under node on the
served source. The rest runs in Chromium against the in-process server with hand-built PDFs (search_pdf): Latin in
Helvetica and Hangul in a CID font that only a ToUnicode map names, so PDF.js reads real text without any TeX tool.
Three fixtures: a three-page PDF with one case per matching rule (PAGES), a fourteen-page PDF with an outline
(long_pages) for the phone's navigation sheet, and five documents in the nav bar (five_docs) for a crowded bar.

The browser tests drive the search as a person does - the shortcut, typing, Enter, the buttons - and read what a person
sees (the count, the boxes on the page, where the focus is) or a screen reader reads (the live region, names and
roles). Three things have no such outcome and are read from the page's own state instead, each said where it is used:
how often PDF.js is asked for a page's text (the cache), that no text is read while a page is drawn, and the arrival of
a new build (refreshDoc(), which the build poll calls).

Run: uv run pytest -q src/limn/viewer/tests/test_viewer_search.py
"""

import base64
import json
import shutil
import unicodedata
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

import helpers_figure
from helpers import blank_png, extract_js_fn, minimal_pdf, ps, run_node
from helpers_browser import MISSES_44, VIEWPORTS, BrowserBase, booted, fonts_ready, settle, watch_idle

NBSP, SHY, FI, LSQ, RSQ, EN_DASH = chr(0xA0), chr(0xAD), chr(0xFB01), chr(0x2018), chr(0x2019), chr(0x2013)

# ---------------------------------------------------------------- the fixture PDFs

LETTER = (612, 792)
# The three-page fixture: each line is (x, baseline y, [(font, text)]) at 12pt on a US Letter page. F1 is Helvetica (Latin),
# F2 the CID font (anything; every character is its own glyph one em wide). What each line is for:
PAGES = [
    [
        (72, 700, [("F1", "Shore station notes")]),
        (72, 676, [("F1", "The tide turns twice a day and the Tide table hangs by the door.")]),  # two hits, one line
        (72, 652, [("F1", "A quiet dawn; the first")]),  # 'first reading' breaks across these two lines
        (72, 628, [("F1", "reading comes later.")]),
        (72, 604, [("F1", "Tide "), ("F2", "조류"), ("F1", " height")]),  # one line, three text items
        (72, 580, [("F2", "관측소의 조류 기록")]),
        (72, 556, [("F2", unicodedata.normalize("NFD", "한낮 관측"))]),  # stored as conjoining jamo
        (72, 532, [("F2", unicodedata.normalize("NFD", "résumé") + " of the day")]),  # e + combining acute
        (72, 508, [("F1", "A long ob-")]),  # 'observation' hyphenated across a line break
        (72, 484, [("F1", "servation")]),
        (72, 460, [("F2", "물때가 바뀌")]),  # Hangul breaks inside a word: '바뀌고'
        (72, 436, [("F2", "고 수위가 달라진다")]),
        (72, 412, [("F1", "This page ends with harbour")]),  # 'harbour master' breaks across pages
    ],
    [
        (72, 700, [("F1", "master of the quay. Midday: the tide is high.")]),
        (72, 676, [("F2", "조류는 하루에 두 번 바뀐다")]),
        (72, 652, [("F1", "wind   speed   4.1")]),  # runs of spaces (narrower than an em: one cell)
        (420, 628, [("F1", "the far lighthouse")]),  # at the page's right: off to the side once the page is zoomed
    ],
    [
        (72, 700, [("F1", "Evening tide. TIDE. tide")]),
        (72, 676, [("F2", "a long and narrow breakwater")], (330 / 336, 0, 0, 1)),  # a full line: 'breakwater shelters'
        (72, 661, [("F2", "shelters the boats.")]),  # crosses into the next one, near the page's top
        (72, 300, [("F1", "The last line of the fixture mentions the ebb once.")]),
    ],
]
N_LONG = 14


def long_pages(n=N_LONG):
    """n pages for the long fixture: page k has a heading 'Section k', one 'tide', one '조류', its own word 'markerK'
    and 'quayside' at its right edge."""
    return [
        [
            (72, 720, [("F1", "Section %d" % k)]),
            (72, 690, [("F1", "The tide table of section %d holds marker%d." % (k, k))]),
            (72, 666, [("F2", "구간의 조류 기록")]),
            (470, 520, [("F1", "quayside")]),
            (72, 300, [("F1", "Foot of page %d." % k)]),
        ]
        for k in range(1, n + 1)
    ]


def search_pdf(pages=PAGES, outline=False):
    """A PDF of `pages` (the PAGES shape; a line may carry a fourth item, the text matrix's a b c d - (0, 1, -1, 0) runs it
    upward) that PDF.js reads as text: F1 is the standard Helvetica, F2 an unembedded CID
    font whose ToUnicode map gives each code its character, so Hangul - composed or as jamo - and combining marks come
    back from getTextContent() exactly as written here. With outline, one top-level outline entry per page, named by the
    page's first line."""
    chars = sorted({c for page in pages for line in page for font, text in line[2] if font == "F2" for c in text})
    cid = {c: i + 1 for i, c in enumerate(chars)}

    def utf16(c):
        """The character as UTF-16BE hex, a ToUnicode map's target."""
        return c.encode("utf-16-be").hex().upper()

    def show(font, text):
        """The operators that set `font` at 12pt and show `text` in it."""
        if font == "F2":
            return "/F2 12 Tf <%s> Tj" % "".join("%04X" % cid[c] for c in text)
        return "/F1 12 Tf (%s) Tj" % text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    maps = ["<%04X> <%s>" % (n, utf16(c)) for c, n in cid.items()]
    blocks = [maps[i : i + 100] for i in range(0, len(maps), 100)]
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        + "".join("%d beginbfchar\n%s\nendbfchar\n" % (len(b), "\n".join(b)) for b in blocks)
        + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    ).encode("ascii")

    def stream(data):
        """A stream object's body for `data`."""
        return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"

    n = len(pages)
    root = 8 + 2 * n  # the outline's root object, after the pages and their contents
    kids = " ".join("%d 0 R" % (8 + 2 * i) for i in range(n))
    catalog = "<< /Type /Catalog /Pages 2 0 R%s >>" % (" /Outlines %d 0 R" % root if outline else "")
    objs = [
        catalog.encode(),
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /LimnFixture /Encoding /Identity-H"
        b" /DescendantFonts [5 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /LimnFixture"
        b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>"
        b" /FontDescriptor 6 0 R /DW 1000 /CIDToGIDMap /Identity >>",
        b"<< /Type /FontDescriptor /FontName /LimnFixture /Flags 4 /FontBBox [0 -200 1000 900]"
        b" /ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>",
        stream(cmap),
    ]
    for i, page in enumerate(pages):
        body = "\n".join(
            "BT %s %d %d Tm %s ET"
            % (
                " ".join(map(str, line[3] if len(line) > 3 else (1, 0, 0, 1))),
                line[0],
                line[1],
                " ".join(show(f, t) for f, t in line[2]),
            )
            for line in page
        )
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R"
                " /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (*LETTER, 9 + 2 * i)
            ).encode()
        )
        objs.append(stream(body.encode("ascii")))
    if outline:
        objs.append(("<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (root + 1, root + n, n)).encode())
        for i, page in enumerate(pages):
            title = "".join(text for _, text in page[0][2])
            links = "".join(
                " /%s %d 0 R" % (k, root + 1 + j) for k, j in (("Prev", i - 1), ("Next", i + 1)) if 0 <= j < n
            )
            objs.append(
                (
                    "<< /Title (%s) /Parent %d 0 R%s /Dest [%d 0 R /XYZ 72 740 0] >>" % (title, root, links, 8 + 2 * i)
                ).encode("ascii")
            )
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


# ---------------------------------------------------------------- the pure parts, under node


def node_json(test, js):
    """Run js under node and return what it printed as JSON; skip the calling test when node is missing."""
    if not shutil.which("node"):
        test.skipTest("node not available")
    return json.loads(run_node(js))


def fns(*names):
    """The served source of the named viewer functions, joined."""
    return "\n".join(extract_js_fn(n) for n in names)


def consts(*names):
    """The source lines of search.js that define the named constants (`const NAME=...;` on one line), joined."""
    src = (Path(__file__).resolve().parents[1] / "js" / "search.js").read_text(encoding="utf-8")
    found = [line for line in src.splitlines() for n in names if line.startswith("const %s=" % n)]
    assert len(found) == len(names), names
    return "\n".join(found)


class SearchLogic(unittest.TestCase):
    """The search's pure functions on the served source: what counts as the same text, what a line is, what a query
    finds across line breaks, how the hits wrap, how wide the field is, which key is the shortcut and where a hit's box
    lies."""

    def test_fold_ignores_case_width_composition_and_runs_of_spaces(self):
        """Upper case, a non-breaking space and a run of spaces, Hangul stored as jamo, a letter with a combining
        accent, the fi ligature and curly quotes or an en dash all fold to what a person types; a soft hyphen goes."""
        samples = [
            "The  TIDE" + NBSP + "\t turns",
            unicodedata.normalize("NFD", "한낮 관측"),
            unicodedata.normalize("NFD", "Résumé"),
            "de" + FI + "ne " + LSQ + "it" + RSQ + " 2009" + EN_DASH + "2010",
            "soft" + SHY + "hyphen",
        ]
        js = fns("searchFold") + "\nconsole.log(JSON.stringify(%s.map(s=>searchFold(s).t)));" % json.dumps(samples)
        self.assertEqual(
            node_json(self, js),
            ["the tide turns", "한낮 관측", "résumé", "define 'it' 2009-2010", "softhyphen"],
        )

    def test_fold_maps_every_folded_character_back_to_its_source(self):
        """at[i] is where the source cluster of folded character i starts, and at ends with the source's length: the
        syllable built from three jamo points at the first, and both letters of a ligature at the ligature."""
        src = "A " + unicodedata.normalize("NFD", "한") + FI + "  x"
        js = fns("searchFold") + "\nconsole.log(JSON.stringify(searchFold(%s)));" % json.dumps(src)
        self.assertEqual(node_json(self, js), {"t": "a 한fi x", "at": [0, 1, 2, 5, 5, 6, 8, 9]})

    @settings(max_examples=25, deadline=None)
    @given(st.lists(st.text(), min_size=1, max_size=30))
    def test_fold_keeps_its_map_in_step_for_any_text(self, values):
        """For any strings: the map has one entry per folded UTF-16 unit plus the end, never steps back and stays inside
        the source, and the folded text has no run of spaces."""
        js = fns("searchFold") + (
            "\nconsole.log(JSON.stringify(%s.map(s=>{const f=searchFold(s);return [f.t,f.at];})));" % json.dumps(values)
        )
        for value, (text, at) in zip(values, node_json(self, js), strict=True):
            units = len(value.encode("utf-16-le")) // 2
            self.assertEqual(len(at), len(text.encode("utf-16-le")) // 2 + 1, value)
            self.assertEqual(at, sorted(at), value)
            self.assertEqual(at[-1], units, value)
            self.assertTrue(all(0 <= i <= units for i in at), value)
            self.assertNotIn("  ", text)

    def test_lines_join_the_items_of_a_line_and_end_at_its_break(self):
        """Items up to one marked hasEOL are one line - whatever their fonts - with where each item's text starts; an
        empty item that only carries the mark ends the line too, and marked content (no str) is skipped."""
        items = [
            {"str": "Tide ", "hasEOL": False},
            {"type": "beginMarkedContent"},
            {"str": "조류", "hasEOL": False},
            {"str": " height", "hasEOL": True},
            {"str": "first", "hasEOL": False},
            {"str": "", "hasEOL": True},
            {"str": "reading", "hasEOL": False},
        ]
        js = fns("searchFold", "searchLines") + (
            "\nconsole.log(JSON.stringify(searchLines(%s).map(l=>[l.t,l.parts])));" % json.dumps(items)
        )
        self.assertEqual(
            node_json(self, js),
            [
                ["tide 조류 height", [{"i": 0, "from": 0}, {"i": 2, "from": 5}, {"i": 3, "from": 7}]],
                ["first", [{"i": 4, "from": 0}]],
                ["reading", [{"i": 6, "from": 0}]],
            ],
        )

    def found(self, lines, queries):
        """What each query finds in a page of these lines: each line is its text - a full line of a 12pt paragraph at
        x 72-500, each 14pt below the one before - or (text, x0, x1, baseline y[, size, plain]) standing there. The hits
        as lists of [line, from, to] pieces, one piece a line the hit lies on."""
        segs = []
        for i, line in enumerate(lines):
            text, x0, x1, y, size, plain = (
                (line, 72, 500, 700 - 14 * i, 12, True) if isinstance(line, str) else (*line, 12, True)[:6]
            )
            segs.append({"text": text, "plain": plain, "box": {"x0": x0, "x1": x1, "y": y, "size": size, "ang": 0}})
        js = (
            consts("SEARCH_BREAK", "SEARCH_CJK", "SEARCH_EDGE_PT")
            + "\n"
            + fns("searchFold", "searchEdges", "searchJoin", "searchFlow", "searchPattern", "searchFind")
            + (
                "\nconst F=searchFlow(%s.map(s=>({t:searchFold(s.text).t,end:s.text.trimEnd().slice(-1),plain:s.plain,box:s.box})));"
                "console.log(JSON.stringify(%s.map(q=>searchFind(F,searchPattern(searchFold(q).t.trim())))));"
                % (json.dumps(segs), json.dumps(queries))
            )
        )
        return node_json(self, js)

    def counts(self, lines, queries):
        """How many hits each query finds on a page of these lines (found)."""
        return dict(zip(queries, [len(h) for h in self.found(lines, queries)], strict=True))

    def test_a_line_break_between_latin_letters_is_a_word_space_and_beside_hangul_may_be_none(self):
        """Between full lines of a paragraph: TeX never breaks a Latin word without a hyphen, so a break between two Latin
        letters or digits is a word space - 'first reading' crosses it, 'firstreading' and 'into' (in / to) do not. With
        Hangul on either side the break may be a space or nothing ('바뀌고', '바뀌 고', and 'tide조류' across tide /
        조류). A line-final hyphen may be typed or left out ('observation', 'ob-servation'); a line-final dash (en dash,
        folded to -) must be typed and stands with no space ('2009-2010', not '20092010'). A hit that crosses a break is
        one hit with a piece on each line. A space inside a line is not optional."""
        lines = [
            "the first",
            "reading of ob-",
            "servation in",
            "to 2009" + EN_DASH,
            "2010 물때가 바뀌",
            "고 달라진다 tide",
            "조류 기록",
        ]
        queries = [
            "first reading",
            "firstreading",
            "into",
            "in to",
            "observation",
            "ob-servation",
            "2009-2010",
            "20092010",
            "2009 2010",
            "바뀌고",
            "바뀌 고",
            "tide조류",
            "tide 조류",
            "the  first",
            "of ob",
        ]
        got = dict(zip(queries, self.found(lines, queries), strict=True))
        self.assertEqual(got["first reading"], [[[0, 4, 9], [1, 0, 7]]])
        self.assertEqual((got["firstreading"], got["into"]), ([], []))
        self.assertEqual(got["in to"], [[[2, 10, 12], [3, 0, 2]]])
        self.assertEqual(got["observation"], [[[1, 11, 14], [2, 0, 9]]])
        self.assertEqual(got["ob-servation"], got["observation"])
        self.assertEqual(got["2009-2010"], [[[3, 3, 8], [4, 0, 4]]])
        self.assertEqual((got["20092010"], got["2009 2010"]), ([], []))
        self.assertEqual(got["바뀌고"], [[[4, 9, 11], [5, 0, 1]]])
        self.assertEqual(got["바뀌 고"], got["바뀌고"])
        self.assertEqual(got["tide조류"], [[[5, 7, 11], [6, 0, 2]]])  # Latin on one side, Hangul on the other
        self.assertEqual(got["tide 조류"], got["tide조류"])
        self.assertEqual(got["the  first"], [[[0, 0, 9]]])  # a query is folded first: its runs of spaces are one
        self.assertEqual(got["of ob"], [[[1, 8, 13]]])

    def test_a_hyphen_u2010_or_a_soft_hyphen_ending_a_line_may_be_left_out(self):
        """A line that ends in U+2010 (a typeset hyphen) or in a soft hyphen was hyphenated, as one ending in '-': the
        word is found with the hyphen left out ('wellknown', 'email'); a line ending in an en dash is not hyphenated
        ('20092010' finds nothing)."""
        lines = ["a well" + chr(0x2010), "known pier and an e" + SHY, "mail from 2009" + EN_DASH, "2010 on"]
        self.assertEqual(
            self.counts(lines, ["wellknown", "email", "20092010", "2009-2010"]),
            {"wellknown": 1, "email": 1, "20092010": 0, "2009-2010": 1},
        )

    def test_only_consecutive_lines_of_a_wrapped_paragraph_are_joined(self):
        """Each pair below is a full line (it reaches the column's right edge at 500) and a line under it that would
        continue it, but for one thing - and so is not joined: the next line 2 font sizes lower (a looser pitch than one
        line), of another font size, starting with a hanging indent of 2.5 font sizes (a list item), or above; the
        first line short (ends at 400, a paragraph's last line), starting mid-column (a right-aligned line), or cut in
        pieces (a table row, an \\hfill line). The control pair - 14pt lower, at the left edge - and one with a paragraph
        indent of 1.25 font sizes are joined."""
        cases = {
            "control": ([("alpha one", 72, 500, 700), ("beta", 72, 300, 686)], 1),
            "indent": ([("alpha one", 72, 500, 700), ("beta", 87, 300, 686)], 1),
            "two sizes lower": ([("alpha one", 72, 500, 700), ("beta", 72, 300, 676)], 0),
            "another size": ([("alpha one", 72, 500, 700), ("beta", 72, 300, 686, 10)], 0),
            "hanging indent": ([("alpha one", 72, 500, 700), ("beta", 102, 300, 686)], 0),
            "above": ([("alpha one", 72, 500, 700), ("beta", 72, 300, 714)], 0),
            "short first": ([("alpha one", 72, 400, 700), ("beta", 72, 500, 686)], 0),
            "right-aligned": ([("alpha one", 300, 500, 700), ("beta", 72, 500, 686), ("gamma", 72, 500, 600)], 0),
            "cut in pieces": (
                [("alpha one", 300, 500, 700, 12, False), ("beta", 72, 500, 686), ("gamma", 72, 500, 600)],
                0,
            ),
        }
        for name, (lines, want) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.counts(lines, ["one beta"])["one beta"], want)

    def test_find_lists_every_occurrence_without_overlap_and_reads_a_query_literally(self):
        """Occurrences are listed in reading order and never overlap; an empty query finds nothing; characters that mean
        something in a pattern are plain characters in a query."""
        got = self.found(
            ["tide and tide. tide", "aaaa", "a.b a*b (c) [d] a+b $4 c:\\x ^y a|b"],
            ["tide", "aa", "", "a.b", "a*b", "(c)", "[d]", "a+b", "$4", "c:\\x", "^y", "a|b", ".", "x"],
        )
        self.assertEqual(got[0], [[[0, 0, 4]], [[0, 9, 13]], [[0, 15, 19]]])
        self.assertEqual(got[1], [[[1, 0, 2]], [[1, 2, 4]]])
        self.assertEqual(got[2], [])
        self.assertEqual([len(g) for g in got[3:12]], [1] * 9)
        self.assertEqual(len(got[12]), 2)  # the two full stops, not every character
        self.assertEqual(len(got[13]), 1)

    def test_step_wraps_both_ways(self):
        """Next after the last hit is the first and previous before the first is the last; with no current hit the
        first step forward is the first hit and backward the last; with no hits there is none."""
        js = fns("searchStep") + (
            "\nconsole.log(JSON.stringify([searchStep(0,3,1),searchStep(2,3,1),searchStep(0,3,-1),"
            "searchStep(-1,3,1),searchStep(-1,3,-1),searchStep(0,0,1)]));"
        )
        self.assertEqual(node_json(self, js), [1, 0, 2, 0, 2, -1])

    def test_width_is_full_then_the_room_down_to_the_minimum_then_none(self):
        """With room for it the field is its full width; with less it takes the room, in whole pixels, down to the
        minimum; under the minimum it is 0 - the magnifier alone."""
        js = fns("searchWidth") + (
            "\nconsole.log(JSON.stringify([400,240,239.6,200,199.9,0,-30].map(r=>searchWidth(r,240,200))));"
        )
        self.assertEqual(node_json(self, js), [240, 240, 239, 200, 0, 0, 0])

    def test_the_shortcut_is_the_key_that_types_f_or_the_f_key_of_a_layout_without_latin_letters(self):
        """Cmd+F on an Apple platform and Ctrl+F elsewhere, by the letter the key types: on Dvorak the key that types f
        (physical Y) is taken and the physical F key, which types u, is not; with a Korean layout's IME on the key
        types no Latin letter and the physical F key is taken. Shift, Alt or the other platform's modifier are not it."""
        keys = [
            {"key": "f", "code": "KeyF", "ctrlKey": True},
            {"key": "F", "code": "KeyF", "ctrlKey": True},
            {"key": "f", "code": "KeyY", "ctrlKey": True},
            {"key": "u", "code": "KeyF", "ctrlKey": True},
            {"key": "ㄹ", "code": "KeyF", "ctrlKey": True},
            {"key": "Process", "code": "KeyF", "ctrlKey": True},
            {"key": "ㄹ", "code": "KeyG", "ctrlKey": True},
            {"key": "f", "code": "KeyF", "ctrlKey": True, "shiftKey": True},
            {"key": "f", "code": "KeyF", "ctrlKey": True, "altKey": True},
            {"key": "f", "code": "KeyF", "metaKey": True},
            {"key": "f", "code": "KeyF"},
        ]
        js = fns("searchKey") + (
            "\nconst ks=%s; console.log(JSON.stringify([ks.map(k=>searchKey(k,false)),ks.map(k=>searchKey(k,true))]));"
            % json.dumps(keys)
        )
        other, apple = node_json(self, js)
        self.assertEqual(other, [True, True, True, False, True, True, False, False, False, False, False])
        self.assertEqual(apple, [False] * 9 + [True, False])

    def test_box_is_the_run_of_characters_on_the_page(self):
        """A 12pt item at (72, 700) on a 612x792 page, 100pt wide, measured at ten units a character: characters 2-5
        of ten lie 20-50pt along it, between the font's ascent above and its descent below the baseline; a quarter
        turn puts the same run along the page's height."""
        js = fns("searchBox") + (
            "\nconst m=s=>s.length*10,st={ascent:0.9,descent:-0.2,fontFamily:'serif'},vt=[1,0,0,-1,0,792];"
            "const up={str:'abcdefghij',width:100,transform:[12,0,0,12,72,700]};"
            "const turned={str:'abcdefghij',width:100,transform:[0,12,-12,0,72,700]};"
            "const r=b=>b.map(v=>Math.round(v*1e4)/1e4);"
            "console.log(JSON.stringify([r(searchBox(up,st,vt,612,792,2,5,m)),r(searchBox(turned,st,vt,612,792,2,5,m)),"
            "r(searchBox(up,{},vt,612,792,0,10,m))]));"
        )
        got = node_json(self, js)
        self.assertEqual(
            got[0], [round(92 / 612, 4), round((92 - 10.8) / 792, 4), round(30 / 612, 4), round(13.2 / 792, 4)]
        )
        self.assertEqual(
            got[1], [round((72 - 10.8) / 612, 4), round((92 - 50) / 792, 4), round(13.2 / 612, 4), round(30 / 792, 4)]
        )
        self.assertEqual(got[2][0], round(72 / 612, 4))  # no font metrics: the whole item, with a default ascent
        self.assertEqual(got[2][2], round(100 / 612, 4))


# ---------------------------------------------------------------- the real viewer


def device(w, h, touch=True, dpr=2):
    """A w x h CSS px viewport at device scale factor dpr: a touch screen (coarse pointer) unless touch is False."""
    d = {"viewport": {"width": w, "height": h}, "device_scale_factor": dpr}
    if touch:
        d.update({"is_mobile": True, "has_touch": True})
    return d


DESKTOP = VIEWPORTS["desktop 1440x900"]
# The viewports with a nav bar, and the phones (no nav bar): the fixed list of helpers_browser.VIEWPORTS.
BARS = {k: v for k, v in VIEWPORTS.items() if not k.startswith(("phone", "fold outer"))}
PHONES = {k: v for k, v in VIEWPORTS.items() if k.startswith(("phone", "fold outer"))}
# The crowded bars: where five document links leave the field no room and it folds to its magnifier.
CROWDED = {
    "tablet 768x1024": VIEWPORTS["tablet 768x1024"],
    "fold inner 673x841": VIEWPORTS["fold inner 673x841"],
    "fold inner 841x673": VIEWPORTS["fold inner 841x673"],
    "mouse 760x800": device(760, 800, touch=False),
    "mouse 760x800 at scale 1": device(760, 800, touch=False, dpr=1),
}

# Until the PDF is open and no page is being drawn: the search reads the open document's text.
PDF_READY = "typeof VEC!=='undefined'&&!!VEC.doc&&!VEC.pumping&&!VEC.cur"
# The count once every page has been read: 'n/m' and nothing after it.
COUNTED = "/^\\d+\\/\\d+$/.test(document.querySelector('#search-count').textContent)"
# The count while pages are still to be read: 'n/m…'.
COUNTING = "/^\\d+\\/\\d+…$/.test(document.querySelector('#search-count').textContent)"
# A fallback for the interface font in place of the bundled Pretendard: the given generic family alone.
FONT = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent=':root:root{--font-sans:%s}';document.head.append(s);});"
)

# The nav bar as drawn: its box and the band its controls are centred in (from the stripe's bottom to the bar's bottom),
# the visible children in order, each named control's box, and how far the bar's content spills past it.
BAR = """() => {const q = s => document.querySelector(s), vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const R = e => {const r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height, m: (r.top + r.bottom) / 2};};
  const nav = q('#doc-nav'), cs = getComputedStyle(nav), out = {nav: R(nav), kids: [...nav.children].filter(vis).map(e => e.id)};
  out.band = {t: q('#brand-stripe').getBoundingClientRect().bottom, b: out.nav.b};
  out.padL = parseFloat(cs.paddingLeft); out.padR = parseFloat(cs.paddingRight); out.gap = parseFloat(cs.columnGap);
  out.spill = nav.scrollWidth - nav.clientWidth;
  for (const [k, s] of [['box', '#search-box'], ['search', '#doc-search'], ['open', '#search-open'], ['icon', '#search-field .ic'],
      ['q', '#search-q'], ['hint', '#search-hint'], ['count', '#search-count'], ['prev', '#search-prev'], ['next', '#search-next'],
      ['close', '#search-close'], ['toc', '#nav-toc-toggle'], ['tocIcon', '#nav-toc-toggle .ic'], ['links', '#doc-links'],
      ['view', '#view-switch'], ['viewLbl', '#view-manuscript .lbl'], ['otherLbl', '#view-revisions .lbl'], ['page', '#nav-page'], ['side', '#nav-side']])
    out[k] = vis(q(s)) ? R(q(s)) : null;
  out.mode = q('#doc-search').dataset.mode; out.linksCut = q('#doc-links').scrollWidth - q('#doc-links').clientWidth;
  return out;}"""

# The vertical centre of the ink in each box of a screenshot (base64 PNG at device scale factor dpr; boxes [l, t, r, b] in
# the shot's CSS px): the device rows holding a pixel that differs from the box's commonest luminance, the first and
# last counted by how strongly they differ. null for a box with no ink.
INK_MID = """async ([b64, dpr, boxes]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  return boxes.map(([l, t, r, b]) => {const X0 = Math.floor(l * dpr), X1 = Math.ceil(r * dpr), Y0 = Math.floor(t * dpr), Y1 = Math.ceil(b * dpr), W = X1 - X0, H = Y1 - Y0;
    if (W < 1 || H < 1) return null; const D = x.getImageData(X0, Y0, W, H).data, lum = i => 0.2126 * D[i] + 0.7152 * D[i + 1] + 0.0722 * D[i + 2];
    const seen = new Map(); for (let i = 0; i < D.length; i += 4) {const v = Math.round(lum(i)); seen.set(v, (seen.get(v) || 0) + 1);}
    let bg = 0, best = -1; for (const [v, n] of seen) if (n > best) {best = n; bg = v;}
    const rows = []; let mx = 0; for (let y = 0; y < H; y++) {let m = 0; for (let xx = 0; xx < W; xx++) m = Math.max(m, Math.abs(lum((y * W + xx) * 4) - bg)); rows.push(m); mx = Math.max(mx, m);}
    if (mx < 12) return null; let f = -1, la = -1; rows.forEach((v, i) => {if (v / mx > 0.15) {if (f < 0) f = i; la = i;}});
    return ((Y0 + f + 1 - Math.min(1, rows[f] / mx)) + (Y0 + la + Math.min(1, rows[la] / mx))) / 2 / dpr;});}"""

# Makes PDF.js hand out each page's text only when the test lets it (window.__text.open(n) or .all()), and counts the
# requests: __text.asked lists the pages whose text was asked for, in order; __text.fail(n) makes page n's next request
# reject. Installed on the open document, so it lasts for that build; each page is gated once, however often it is got.
TEXT_GATE = """() => {const doc = VEC.doc, get = doc.getPage.bind(doc), T = window.__text = {asked: [], held: new Map(), free: false, bad: new Set()};
  T.open = n => {const go = T.held.get(n); if (go) {T.held.delete(n); go();}}; T.all = () => {T.free = true; [...T.held.keys()].forEach(T.open);};
  T.fail = n => T.bad.add(n);
  doc.getPage = async n => {const p = await get(n); if (p.__gated) return p; p.__gated = true; const text = p.getTextContent.bind(p);
    p.getTextContent = (...a) => {T.asked.push(n); if (T.bad.delete(n)) return Promise.reject(new Error('no text'));
      return T.free ? text(...a) : new Promise(go => T.held.set(n, go)).then(() => text(...a));};
    return p;};}"""


def build_dir(doc):
    """The page directory of the build on screen for doc."""
    return Path(doc.dir) / (Path(doc.dir) / "pages.cur").read_text().strip()


def put_build(doc, name, pdf, pages):
    """Put build `name` of doc on screen: `pages` blank page images and pdf as its PDF copy."""
    d = Path(doc.dir) / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, pages + 1):
        (d / ("page-%d.png" % i)).write_bytes(blank_png(1275, 1650))
    (d / doc.pdf_name).write_bytes(pdf)
    (Path(doc.dir) / "pages.cur").write_text(name)
    (Path(doc.dir) / "built_at.txt").write_text("2026-09-25 10:00:00")
    (Path(doc.dir) / "head.txt").write_text("abc1234")
    return d


class SearchBase(BrowserBase):
    """BrowserBase with the three-page fixture PDF as the build on screen, and the helpers that drive the search as a
    person does and read what a person sees or a screen reader reads."""

    def setUp(self):
        """The manuscript's build gets a third page image and search_pdf() as its PDF copy."""
        super().setUp()
        self.doc = ps.APP.docs[0]
        self.pages_dir = put_build(self.doc, build_dir(self.doc).name, search_pdf(), 3)

    def view(self, dev=DESKTOP, lang="ko", dark=False, init=None):
        """The viewer on dev, booted, its PDF open and its pages drawn, settled; first-visit hints are pre-seen."""
        prefs = {"coach": {"touch": 1, "mouse": 1, "sel": 1, "side": 1}, "theme": "dark" if dark else "light"}
        context = self.browser.new_context(**dev)
        self.addCleanup(context.close)
        context.add_init_script(
            "try{if(!sessionStorage.getItem('__t')){sessionStorage.setItem('__t','1');"
            "localStorage.setItem('pinPrefs',%s);}}catch(e){}" % json.dumps(json.dumps(prefs))
        )
        if init:
            context.add_init_script(init)
        watch_idle(context)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=%s" % lang)
        page.wait_for_function(booted(0), timeout=20000)
        page.wait_for_function(PDF_READY, timeout=20000)
        settle(page)
        page.wait_for_function(
            PDF_READY, timeout=20000
        )  # a redraw the settling queued (fonts, a re-fit) has finished too
        self.addCleanup(lambda: self.assertEqual(errors, []))
        return page

    @staticmethod
    def touch(page):
        """Whether the page's screen is a touch screen."""
        return page.evaluate("matchMedia('(pointer:coarse)').matches")

    def press(self, page, selector):
        """Tap (touch) or click (mouse) the element."""
        (page.tap if self.touch(page) else page.click)(selector)

    def disclose(self, page):
        """Bring the field up as a person does and leave the focus in it: on a phone through the navigation sheet's
        row, in a bar by the magnifier when the field is folded, else by pressing the field."""
        if page.evaluate("document.body.classList.contains('band-phone')"):
            page.tap("#btn-pos")
            page.wait_for_selector("#nav-sheet[open]")
            settle(page)
            page.tap("#ns-search")
            page.wait_for_function("!document.querySelector('#nav-sheet').open")
        elif page.is_visible("#search-open"):
            self.press(page, "#search-open")
        else:
            self.press(page, "#search-field")
        page.wait_for_function("document.activeElement===document.querySelector('#search-q')")
        settle(page)

    def search(self, page, text, final=COUNTED):
        """Type text into the field (bringing it up first when it is not showing) and wait until every page has been read
        and the count is final."""
        if not page.is_visible("#search-q"):
            self.disclose(page)
        page.fill("#search-q", text)
        page.wait_for_function(final, timeout=8000)
        settle(page)

    @staticmethod
    def count(page):
        """The count as shown."""
        return page.text_content("#search-count")

    @staticmethod
    def said(page):
        """What the search's live region holds - what a screen reader reads out."""
        return page.text_content("#search-sr")

    @staticmethod
    def hits(page):
        """The hit boxes drawn on the pages near the view: [{page, cur, box: [x, y, w, h] as page fractions}]."""
        return page.evaluate(
            """() => [...document.querySelectorAll('.pg .search-hit')].map(h => {const g = h.parentElement, p = g.getBoundingClientRect(), r = h.getBoundingClientRect();
              return {page: +g.dataset.page, cur: h.classList.contains('cur'),
                box: [(r.left - p.left - g.clientLeft) / g.clientWidth, (r.top - p.top - g.clientTop) / g.clientHeight, r.width / g.clientWidth, r.height / g.clientHeight]};})"""
        )

    @staticmethod
    def current(page):
        """The current hit as drawn: its page and, for each of its boxes, where it is in the viewport and whether its
        centre and two corners show (nothing else is drawn over them); None with no current hit drawn."""
        return page.evaluate(
            """() => {const hs = [...document.querySelectorAll('.search-hit.cur')]; if (!hs.length) return null; const L = document.querySelector('#left');
              const shows = (x, y) => {if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false; const e = document.elementFromPoint(x, y); return !!e && (e === L || L.contains(e));};
              return {page: +hs[0].parentElement.dataset.page, boxes: hs.map(h => {const r = h.getBoundingClientRect();
                return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                  shows: shows((r.left + r.right) / 2, (r.top + r.bottom) / 2) && shows(r.left + 1, r.top + 1) && shows(r.right - 1, r.bottom - 1)};})};}"""
        )

    def walk(self, page):
        """Step through every hit with Enter, from the current one round to it again: the page each is announced on, in
        order, starting with the current hit's."""
        total = int(self.count(page).split("/")[1])
        pages = []
        for _ in range(total):
            pages.append(int(self.said(page).rsplit(" · ", 1)[1].rstrip("쪽")))
            page.keyboard.press("Enter")
        return pages


class SearchFinds(SearchBase):
    """What a query finds in the three-page fixture and how its hits are shown and stepped through."""

    def test_latin_hits_are_counted_across_pages_whatever_their_case(self):
        """'tide' is on page 1 three times, page 2 once and page 3 three times - 'Tide' and 'TIDE' included: 1/7, the
        first one current and announced with its page, the pages near the view carry one box a hit, and stepping
        through them all names pages 1, 1, 1, 2, 3, 3, 3."""
        page = self.view()
        self.search(page, "tide")
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(self.said(page), "7개 중 1번째 · 1쪽")
        drawn = self.hits(page)
        self.assertEqual([h["page"] for h in drawn if h["page"] == 1], [1, 1, 1])
        self.assertEqual([h["cur"] for h in drawn if h["page"] == 1], [True, False, False])
        self.assertEqual(self.walk(page), [1, 1, 1, 2, 3, 3, 3])

    def test_a_hit_box_lies_on_its_words(self):
        """The first 'tide' of page 1's second line: it starts 24pt after the line's left edge at x=72pt ('The ' in
        12pt Helvetica) and is 19pt wide, and its box holds the baseline at y=676pt with the letters above it."""
        page = self.view()
        self.search(page, "tide")
        x, y, w, h = self.hits(page)[0]["box"]
        self.assertAlmostEqual(x, 96 / 612, delta=0.012)
        self.assertAlmostEqual(w, 19.3 / 612, delta=0.012)
        base = (792 - 676) / 792
        self.assertLess(y, base - 0.6 * 12 / 792)  # reaches above the x-height
        self.assertGreater(y, base - 1.3 * 12 / 792)  # and not into the line above
        self.assertGreaterEqual(y + h, base - 0.001)
        self.assertLess(y + h, base + 0.5 * 12 / 792)

    def test_hangul_is_found_composed_or_as_jamo_and_latin_with_a_combining_accent(self):
        """'조류' is on page 1 twice and page 2 once; '한낮' and 'résumé' are stored decomposed in the PDF and found by
        the composed text a person types."""
        page = self.view()
        self.search(page, "조류")
        self.assertEqual(self.count(page), "1/3")
        self.assertEqual(self.walk(page), [1, 1, 2])
        self.search(page, "한낮")
        self.assertEqual(self.count(page), "1/1")
        self.search(page, "résumé")
        self.assertEqual(self.count(page), "1/1")
        box = self.hits(page)[0]["box"]
        self.assertGreater(box[2], 5 * 12 / 612)  # all six letters and their accents, one em each

    def test_a_query_spans_the_text_items_of_a_line_and_runs_of_spaces(self):
        """'tide 조류 height' crosses three text items of one line and is one hit with one box over all three; runs of
        spaces in the PDF match one space in the query."""
        page = self.view()
        self.search(page, "Tide 조류 height")
        self.assertEqual(self.count(page), "1/1")
        (hit,) = self.hits(page)
        self.assertAlmostEqual(hit["box"][0], 72 / 612, delta=0.004)
        self.assertGreater(hit["box"][2], 80 / 612)
        self.search(page, "wind speed 4.1")
        self.assertEqual(self.count(page), "1/1")

    def test_ragged_lines_far_apart_are_not_joined(self):
        """The three-page fixture's lines are ragged and 24pt apart - twice their font size, not one line pitch: no query
        crosses them ('first reading', 'observation' over 'ob-' / 'servation', '바뀌고'), while each word is found."""
        page = self.view()
        for query, words in (("first reading", "reading"), ("observation", "servation"), ("바뀌고", "바뀌")):
            with self.subTest(query=query):
                self.search(page, query)
                self.assertEqual(self.count(page), "0/0")
                self.search(page, words)
                self.assertNotEqual(self.count(page), "0/0")

    def test_a_page_break_is_not_crossed(self):
        """'harbour master' ends page 1 and begins page 2: not found - 0/0, no box, the arrows off, and the screen
        reader is told there is no result."""
        page = self.view()
        self.search(page, "harbour master")
        self.assertEqual(self.count(page), "0/0")
        self.assertEqual(self.hits(page), [])
        self.assertTrue(page.is_disabled("#search-next") and page.is_disabled("#search-prev"))
        self.assertEqual(self.said(page), "결과 없음")

    def test_enter_goes_on_shift_enter_goes_back_and_both_wrap(self):
        """From 1/7: Enter twice is 3/7, Shift+Enter three times wraps to 7/7 on page 3, Enter wraps to 1/7 on page 1;
        each time the current hit shows in the PDF area. The arrows do the same, and one hit is current."""
        page = self.view()
        self.search(page, "tide")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        self.assertEqual(self.count(page), "3/7")
        for _ in range(3):
            page.keyboard.press("Shift+Enter")
        settle(page)
        self.assertEqual(self.count(page), "7/7")
        cur = self.current(page)
        self.assertEqual((cur["page"], [b["shows"] for b in cur["boxes"]]), (3, [True]))
        page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(self.count(page), "1/7")
        cur = self.current(page)
        self.assertEqual((cur["page"], [b["shows"] for b in cur["boxes"]]), (1, [True]))
        page.click("#search-prev")
        self.assertEqual(self.count(page), "7/7")
        page.click("#search-next")
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(len(self.current(page)["boxes"]), 1)

    def test_a_hit_over_two_lines_is_shown_whole(self):
        """'breakwater shelters' lies on two lines near the top of page 3. Scrolled so that its first line sits just above
        the foot of the PDF area and its second line below it (checked), searching for it scrolls until both lines show
        - not only the first."""
        page = self.view()
        line = "y => {const g = document.getElementById('p3'), r = g.getBoundingClientRect(); return r.top + g.clientTop + (792 - y) / 792 * g.clientHeight;}"
        page.evaluate(
            "line => {const L = document.querySelector('#left'), a = selPopArea(), at = eval(line); L.scrollTop += at(676 - 3) - (selPopArea().bottom - 14);}",
            line,
        )
        settle(page)
        where = page.evaluate(
            "line => {const at = eval(line); return [at(676 - 3), at(661 - 3), selPopArea().bottom];}", line
        )
        self.assertLess(where[0], where[2] - 8)  # the first line shows ...
        self.assertGreater(where[1], where[2])  # ... and the second does not
        self.search(page, "breakwater shelters")
        cur = self.current(page)
        self.assertEqual((cur["page"], [b["shows"] for b in cur["boxes"]]), (3, [True, True]))

    def test_the_first_hit_is_the_first_one_from_the_page_on_screen(self):
        """Scrolled to page 3, 'tide' starts at its first hit there: 5/7."""
        page = self.view()
        page.evaluate("document.getElementById('p3').scrollIntoView()")
        settle(page)
        self.search(page, "tide")
        self.assertEqual(self.count(page), "5/7")
        self.assertEqual(self.current(page)["page"], 3)

    def test_a_hit_off_to_the_side_of_a_zoomed_page_is_brought_into_view(self):
        """Zoomed in six steps and scrolled to its left edge, the page has 'lighthouse' - at the right edge of page 2 -
        off the PDF area's right side: searching for it scrolls it into view sideways, its box showing whole."""
        page = self.view()
        for _ in range(6):
            page.click("#btn-zoom-in")
        settle(page)
        page.evaluate("document.querySelector('#left').scrollLeft=0")
        settle(page)
        off = page.evaluate(
            "(()=>{const L=document.querySelector('#left'),l=L.getBoundingClientRect(),g=document.getElementById('p2').getBoundingClientRect();"
            "return [g.left+g.width*444/612,l.left+L.clientLeft+L.clientWidth];})()"
        )
        self.assertGreater(off[0], off[1])  # the word's first letters start past the area's right edge
        self.search(page, "lighthouse")
        self.assertEqual(self.count(page), "1/1")
        cur = self.current(page)
        self.assertEqual((cur["page"], [b["shows"] for b in cur["boxes"]]), (2, [True]))
        self.assertGreater(page.evaluate("document.querySelector('#left').scrollLeft"), 0)

    def test_no_text_is_read_while_a_page_is_being_drawn(self):
        """While a page is being drawn no page's text is asked for and the count says it is not final ('…'); once the
        drawing is done the pages are read and the count ends at 1/7.

        No outcome on screen tells a reader that waits from one that has not started, so this reads the page's own
        state: VEC.pumping (set here as the drawing loop sets it) and the requests PDF.js gets for text (TEXT_GATE).
        The 400ms is a bounded wait for something that must not happen: reading the three pages takes a few ms."""
        page = self.view()
        page.evaluate(TEXT_GATE)
        page.evaluate("window.__text.all(); VEC.pumping=true")
        page.click("#search-q")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTING)
        page.wait_for_timeout(400)
        self.assertEqual(page.evaluate("window.__text.asked"), [])
        self.assertEqual(self.count(page), "0/0…")
        page.evaluate("VEC.pumping=false")
        page.wait_for_function(COUNTED, timeout=8000)
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(sorted(page.evaluate("window.__text.asked")), [1, 2, 3])

    def test_the_text_is_read_once_a_build(self):
        """A second query asks PDF.js for no page's text again: the text of the build on screen is kept. (The cache
        has no outcome on screen; this counts the requests PDF.js gets, TEXT_GATE.)"""
        page = self.view()
        page.evaluate(TEXT_GATE)
        page.evaluate("window.__text.all()")
        self.search(page, "tide")
        self.assertEqual(sorted(page.evaluate("window.__text.asked")), [1, 2, 3])
        self.search(page, "조류")
        self.assertEqual(self.count(page), "1/3")
        self.assertEqual(len(page.evaluate("window.__text.asked")), 3)

    def test_the_count_grows_page_by_page_and_is_announced_only_when_final(self):
        """With page 1 read and pages 2 and 3 still to come the count shows its hits and an ellipsis and the screen
        reader has been told nothing; with every page read the count is final and is announced once."""
        page = self.view()
        page.evaluate(TEXT_GATE)
        page.click("#search-q")
        page.keyboard.type("tide")
        page.wait_for_function("window.__text.held.has(1)")
        page.evaluate("window.__text.open(1)")
        page.wait_for_function("document.querySelector('#search-count').textContent==='1/3…'")
        self.assertEqual(self.said(page), "")
        self.assertEqual(len([h for h in self.hits(page) if h["page"] == 1]), 3)
        page.evaluate("window.__text.all()")
        page.wait_for_function(COUNTED, timeout=8000)
        self.assertEqual((self.count(page), self.said(page)), ("1/7", "7개 중 1번째 · 1쪽"))

    def test_a_page_whose_text_cannot_be_read_is_said_and_read_again_on_the_next_query(self):
        """Page 2's text fails once: the other pages are still read, the count ends with its hits and says in words
        that a page was left out - on screen and to the screen reader - and the next query reads page 2 again and
        counts it."""
        page = self.view()
        page.evaluate(TEXT_GATE)
        page.evaluate("window.__text.all(); window.__text.fail(2)")
        self.search(page, "tide", final="document.querySelector('#search-count').textContent.includes('못 읽은 쪽')")
        self.assertEqual(self.count(page), "1/6 · 못 읽은 쪽 1")
        self.assertEqual(self.said(page), "6개 중 1번째 · 1쪽 · 못 읽은 쪽 1")
        self.assertEqual(sorted(page.evaluate("window.__text.asked")), [1, 2, 3])
        self.search(page, "tides")
        self.assertEqual(self.count(page), "0/0")
        self.search(page, "tide")
        self.assertEqual(self.count(page), "1/7")
        self.assertEqual(page.evaluate("window.__text.asked.filter(n=>n===2).length"), 2)


class SearchKeys(SearchBase):
    """The shortcut, Esc, the focus and what typing in the field leaves alone."""

    @staticmethod
    def watch_keys(page):
        """Record, for each keydown that reaches the window, whether the viewer prevented its default."""
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")

    @staticmethod
    def focus_id(page):
        """The id of the element that has the focus ('' for the body)."""
        return page.evaluate("document.activeElement===document.body?'':document.activeElement.id")

    def test_ctrl_f_focuses_the_field_and_a_second_one_is_the_browsers(self):
        """Outside Apple platforms Ctrl+F from another control focuses the field and is not the browser's; pressed
        again in the field it is left to the browser's own find. The hint names the key."""
        page = self.view()
        self.watch_keys(page)
        page.focus("#jump")
        page.keyboard.press("Control+f")
        self.assertEqual(self.focus_id(page), "search-q")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", True], ["f", False]])
        self.assertEqual(page.text_content("#search-hint"), "Ctrl F")

    def test_on_an_apple_platform_the_shortcut_is_command_f(self):
        """With navigator.platform MacIntel, ⌘F focuses the field, Ctrl+F does not, and the hint reads ⌘F."""
        page = self.view(init="Object.defineProperty(navigator,'platform',{get:()=>'MacIntel'});")
        self.watch_keys(page)
        page.keyboard.press("Control+f")
        self.assertNotEqual(self.focus_id(page), "search-q")
        page.keyboard.press("Meta+f")
        self.assertEqual(self.focus_id(page), "search-q")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False], ["f", True]])
        self.assertEqual(page.text_content("#search-hint"), "⌘F")

    def test_the_shortcut_follows_the_letter_the_key_types(self):
        """Keydowns as other layouts send them: Dvorak's Ctrl+U (the physical F key) is left to the browser and its
        Ctrl+F (the physical Y key) focuses the field; with a Korean layout's IME on (the key types ㄹ) the physical F
        key focuses it."""
        page = self.view()
        send = "([key,code])=>{const e=new KeyboardEvent('keydown',{key,code,ctrlKey:true,bubbles:true,cancelable:true}); document.activeElement.dispatchEvent(e); return e.defaultPrevented;}"
        for key, code, taken in (("u", "KeyF", False), ("f", "KeyY", True), ("ㄹ", "KeyF", True)):
            with self.subTest(key=key, code=code):
                page.focus("#jump")
                self.assertEqual(page.evaluate(send, [key, code]), taken)
                self.assertEqual(self.focus_id(page), "search-q" if taken else "jump")

    def test_under_an_open_dialog_the_shortcut_is_the_browsers(self):
        """With the help open, Ctrl+F is not taken and the focus stays in the dialog."""
        page = self.view()
        page.keyboard.press("?")
        page.wait_for_selector("#help[open]")
        self.watch_keys(page)
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False]])
        self.assertTrue(page.evaluate("document.querySelector('#help').contains(document.activeElement)"))

    def test_esc_clears_the_search_and_gives_the_focus_back(self):
        """Esc in the field empties it, removes every hit box and the count, and returns the focus to the control
        that had it."""
        page = self.view()
        page.focus("#jump")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        self.assertGreater(len(self.hits(page)), 0)
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual((self.count(page), self.said(page)), ("", ""))
        self.assertEqual(self.focus_id(page), "jump")
        self.assertFalse(page.is_visible("#search-close"))

    def test_esc_returns_to_what_had_the_focus_before_this_visit_to_the_field(self):
        """Ctrl+F from the page field and a query; the focus then moves to the outline's search field (the query stays
        in the bar) and Ctrl+F again: Esc returns to the outline's field, not to the page field of the first visit."""
        page = self.view()
        page.focus("#jump")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.click("#outline-search")
        self.assertEqual(page.input_value("#search-q"), "tide")
        page.keyboard.press("Control+f")
        self.assertEqual(self.focus_id(page), "search-q")
        page.keyboard.press("Escape")
        self.assertEqual(self.focus_id(page), "outline-search")

    def test_esc_goes_to_the_pdf_when_nothing_can_take_the_focus_back(self):
        """The field entered with the mouse (nothing had the focus) and Esc pressed on [이전 결과]: the search closes and
        the focus is on the PDF's scroller - not left in the closed search - so the next Esc is the viewer's again. The
        scroller draws no ring (it is not a stop a person tabs to; a ring round the whole PDF read as the select mode's
        frame), and the next Tab shows the ring where the focus goes."""
        page = self.view()
        page.click("#search-q")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.focus("#search-prev")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.focus_id(page), "left")
        ring = "(e=>{const c=getComputedStyle(e); return [c.outlineStyle,c.outlineWidth,c.boxShadow];})(document.activeElement)"
        self.assertEqual(page.evaluate(ring)[0], "none")
        self.assertEqual(page.evaluate(ring)[2], "none")
        self.watch_keys(page)
        page.keyboard.press("Escape")
        self.assertEqual(page.evaluate("window.__kd"), [["Escape", False]])
        page.keyboard.press("Tab")
        self.assertNotEqual(self.focus_id(page), "left")
        self.assertEqual(page.evaluate(ring)[:2], ["solid", "2px"])

    def test_the_close_button_does_what_esc_does(self):
        """[검색 닫기] empties the field, removes the hits and returns the focus."""
        page = self.view()
        page.focus("#jump")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.click("#search-close")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual(self.focus_id(page), "jump")

    def test_typing_in_the_field_runs_no_viewer_shortcut(self):
        """'?' typed in the field is a character, not help; Ctrl+= and Ctrl+\\ there neither zoom the page nor fold
        the panel."""
        page = self.view()
        shown = "[document.querySelector('.pg').getBoundingClientRect().width,document.querySelector('#right').getBoundingClientRect().width]"
        before = page.evaluate(shown)
        page.click("#search-q")
        page.keyboard.type("a?")
        page.keyboard.press("Control+=")
        page.keyboard.press("Control+\\")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "a?")
        self.assertFalse(page.is_visible("#help"))
        self.assertEqual(page.evaluate(shown), before)

    def drag_a_region(self, page):
        """Drag a region on page 1 with the mouse and type a note in the popover by the box."""
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect(); return [r.left+r.width*0.2,r.top+r.height*0.4,r.left+r.width*0.5,r.top+r.height*0.45];})()"
        )
        page.mouse.move(box[0], box[1])
        page.mouse.down()
        page.mouse.move(box[2], box[3], steps=4)
        page.mouse.up()
        page.wait_for_selector("#sel-pop:not([hidden])", timeout=8000)
        page.wait_for_function("document.querySelector('#c-loc').textContent.trim()!==''", timeout=8000)
        page.keyboard.type("초안 메모")
        settle(page)

    def test_a_draft_its_selection_and_the_note_popover_survive_a_search(self):
        """With a region picked and a note half written in the popover by the box, Ctrl+F, a query, Enter and Esc
        leave the composer open on the same lines, the dashed box drawn, the note as typed in both fields, and put
        the focus back in the popover's note."""
        page = self.view()
        self.drag_a_region(page)
        where = page.text_content("#c-loc")
        page.keyboard.press("Control+f")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED)
        page.keyboard.press("Enter")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.text_content("#c-loc"), where)
        self.assertTrue(page.is_visible("#composer"))
        self.assertEqual(page.locator(".pg .sel").count(), 1)
        self.assertEqual(page.input_value("#note"), "초안 메모")
        self.assertEqual(page.input_value("#sel-pop textarea"), "초안 메모")
        self.assertTrue(page.is_visible("#sel-pop"))
        self.assertTrue(page.evaluate("document.activeElement===document.querySelector('#sel-pop textarea')"))

    def test_esc_with_the_note_popover_scrolled_away_brings_it_back_with_the_focus_in_its_note(self):
        """The popover's note had the focus, then a hit two pages away scrolled the popover out of view: Esc closes the
        search, brings the selection and its popover back into view and puts the focus in the popover's note with the
        draft as typed - so the next Esc, from where the person was writing, is the one that cancels the selection."""
        page = self.view()
        self.drag_a_region(page)
        page.keyboard.press("Control+f")
        page.keyboard.type("ebb")
        page.wait_for_function(COUNTED)
        settle(page)
        shown = "(e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden')(document.querySelector('#sel-pop'))"
        self.assertFalse(page.evaluate(shown))
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate(shown))
        self.assertTrue(page.evaluate("document.activeElement===document.querySelector('#sel-pop textarea')"))
        self.assertEqual(page.input_value("#sel-pop textarea"), "초안 메모")
        self.assertEqual(page.input_value("#note"), "초안 메모")
        box = page.evaluate(
            "(()=>{const b=document.querySelector('.pg .sel').getBoundingClientRect(),a=selPopArea(); return [b.top>=a.top,b.bottom<=a.bottom];})()"
        )
        self.assertEqual(box, [True, True])  # the selection box is on screen with it

    def test_select_mode_stays_on_through_a_search(self):
        """On a tablet with [선택] on, a search opened, typed and closed leaves the mode on and its bar showing."""
        page = self.view(BARS["tablet 1024x768"])
        page.tap("#btn-select")
        page.wait_for_selector("#sel-bar", state="visible")
        self.search(page, "tide")
        page.tap("#search-close")
        settle(page)
        self.assertEqual(page.get_attribute("#btn-select", "aria-pressed"), "true")
        self.assertTrue(page.is_visible("#sel-bar"))


class SearchComposition(SearchBase):
    """Typing Hangul through an input method: the states between keystrokes are not results."""

    def setUp(self):
        """A CDP session per page drives the input method (Input.imeSetComposition, Input.insertText)."""
        super().setUp()
        self.cdp = None

    def ime(self, page, text):
        """The input method shows `text` as the composition in the focused field (not committed)."""
        self.cdp = self.cdp or page.context.new_cdp_session(page)
        self.cdp.send("Input.imeSetComposition", {"text": text, "selectionStart": len(text), "selectionEnd": len(text)})

    def commit(self, page, text):
        """The input method commits `text` in place of the composition."""
        self.cdp.send("Input.insertText", {"text": text})

    def test_a_lone_jamo_being_composed_is_not_searched_and_nothing_is_announced_meanwhile(self):
        """After '조류' (the second of three hits current, announced), composing ㄱ leaves the count, the current hit
        and the announcement as they were; composing on to 기 searches '조류기' (no hit) without a word to the screen
        reader; committing announces the result."""
        page = self.view()
        self.search(page, "조류")
        page.keyboard.press("Enter")
        self.assertEqual((self.count(page), self.said(page)), ("2/3", "3개 중 2번째 · 1쪽"))
        self.ime(page, "ㄱ")
        settle(page)
        self.assertEqual(page.input_value("#search-q"), "조류ㄱ")
        self.assertEqual((self.count(page), self.said(page)), ("2/3", "3개 중 2번째 · 1쪽"))
        self.ime(page, "기")
        page.wait_for_function("document.querySelector('#search-count').textContent==='0/0'")
        self.assertEqual(self.said(page), "3개 중 2번째 · 1쪽")
        self.commit(page, "기")
        page.wait_for_function("document.querySelector('#search-sr').textContent==='결과 없음'")

    def test_a_composition_that_ends_where_it_began_keeps_the_current_hit(self):
        """On the second of the three '조류' hits, a syllable is composed after the query (no hit) and deleted again:
        the current hit is the second again, not the first."""
        page = self.view()
        self.search(page, "조류")
        page.keyboard.press("Enter")
        self.assertEqual(self.count(page), "2/3")
        self.ime(page, "가")
        page.wait_for_function("document.querySelector('#search-count').textContent==='0/0'")
        self.ime(page, "")
        page.wait_for_function(COUNTED + "&&document.querySelector('#search-count').textContent!=='0/0'")
        self.assertEqual(self.count(page), "2/3")

    def test_enter_while_composing_does_not_step(self):
        """The Enter that an input method uses to commit (a keydown marked as composing, or with key code 229) leaves
        the current hit where it is; a plain Enter afterwards steps."""
        page = self.view()
        self.search(page, "tide")
        send = "(o)=>document.querySelector('#search-q').dispatchEvent(new KeyboardEvent('keydown',Object.assign({key:'Enter',bubbles:true,cancelable:true},o)))"
        page.evaluate(send, {"isComposing": True})
        page.evaluate(send, {"keyCode": 229})
        self.assertEqual(self.count(page), "1/7")
        page.keyboard.press("Enter")
        self.assertEqual(self.count(page), "2/7")


class SearchShortcutFocus(SearchBase):
    """The shortcut is taken only when the field takes the focus (docs/handbook/viewer.md §본문 검색 키와 초점): where the
    field's row is hidden for typing it comes back for it; where the field cannot take the focus the key is the browser's;
    the search is never left open without the focus in its field."""

    def long_press(self, page, x, y):
        """A long press on the PDF at (x, y): a region is picked and the composer opens with its location."""
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        page.wait_for_selector("#composer", state="visible", timeout=8000)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function("document.querySelector('#c-loc').textContent.trim()!==''", timeout=8000)
        settle(page)

    def test_from_the_composers_note_on_a_landscape_phone_the_row_comes_back_for_the_field(self):
        """On a landscape phone (844x390, 908x411, a keyboard attached) a note is being written in the composer, so the
        top row is hidden for typing. Ctrl+F brings the row back and puts the focus in the field: what is typed next is
        the query, not the note; Esc closes the search and gives the focus back to the note with the draft as written."""
        for name, dev in (("short 844x390", device(844, 390)), ("short 908x411", device(908, 411))):
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.long_press(page, 200, 200)
                page.focus("#note")
                page.keyboard.type("draft")
                settle(page)
                self.assertFalse(page.is_visible("#doc-nav"))  # hidden while the note is typed in
                page.keyboard.press("Control+f")
                self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
                self.assertTrue(page.is_visible("#search-q"))
                page.keyboard.type("tide")
                page.wait_for_function(COUNTED, timeout=8000)
                self.assertEqual((page.input_value("#search-q"), page.input_value("#note")), ("tide", "draft"))
                page.keyboard.press("Escape")
                settle(page)
                self.assertEqual(page.evaluate("document.activeElement.id"), "note")
                self.assertEqual(page.input_value("#note"), "draft")
                self.assertTrue(page.is_visible("#composer"))

    def test_from_the_note_popover_in_a_landscape_mouse_window_the_field_takes_the_typing(self):
        """In an 844x390 mouse window a region is dragged and a note typed in the popover by it; Ctrl+F puts the focus in
        the field and the typing goes there; Esc gives the focus back to the popover's note, the draft as written."""
        page = self.view(device(844, 390, touch=False))
        box = page.evaluate(
            "(()=>{const r=document.getElementById('p1').getBoundingClientRect(); return [r.left+r.width*0.2,r.top+r.height*0.12,r.left+r.width*0.5,r.top+r.height*0.17];})()"
        )  # inside the 390px-high window
        page.mouse.move(box[0], box[1])
        page.mouse.down()
        page.mouse.move(box[2], box[3], steps=4)
        page.mouse.up()
        page.wait_for_selector("#sel-pop:not([hidden])", timeout=8000)
        page.wait_for_function("document.querySelector('#c-loc').textContent.trim()!==''", timeout=8000)
        page.keyboard.type("draft")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-q")
        page.keyboard.type("tide")
        page.wait_for_function(COUNTED, timeout=8000)
        self.assertEqual((page.input_value("#search-q"), page.input_value("#sel-pop textarea")), ("tide", "draft"))
        page.keyboard.press("Escape")
        settle(page)
        self.assertTrue(page.evaluate("document.activeElement===document.querySelector('#sel-pop textarea')"))
        self.assertEqual(page.input_value("#note"), "draft")

    def test_where_the_field_cannot_take_the_focus_the_shortcut_is_the_browsers(self):
        """With the field's row out of the layout (a state where no rule brings it back - here the bar is taken out by a
        style), Ctrl+F is not intercepted - the browser's find - and the search does not open."""
        page = self.view()
        page.add_style_tag(content="#doc-nav{display:none!important}")
        page.focus("#jump")
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False]])
        self.assertEqual(
            page.evaluate("[document.body.classList.contains('search-open'),document.activeElement.id]"),
            [False, "jump"],
        )


class SearchScope(SearchBase):
    """Where the search ends: a new build, the changes view, a PDF that cannot be read."""

    def new_build(self, page, pdf, pages):
        """A new build of the document arrives: `pages` page images and `pdf`, shown as the build poll shows it
        (refreshDoc(): what the poll calls when it finds a new build - the arrival itself has no control to press)."""
        newer = put_build(self.doc, "pages-20260925110000", pdf, pages)
        page.evaluate("refreshDoc()")
        page.wait_for_function("META.pages_build==='%s'&&%s" % (newer.name, PDF_READY), timeout=8000)
        settle(page)

    def test_a_rebuild_clears_the_search(self):
        """A new build of the document on screen removes the query, its hits, the count and the announcement."""
        page = self.view()
        self.search(page, "tide")
        self.new_build(page, search_pdf(), 3)
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual((self.count(page), self.said(page)), ("", ""))

    def test_the_changes_view_has_no_search_and_ctrl_f_is_the_browsers_there(self):
        """Entering the changes view clears and hides the field, and Ctrl+F is left to the browser; back in the
        manuscript the field is there again, empty, with no hit box."""
        page = self.view()
        self.search(page, "tide")
        page.click("#view-revisions")
        page.wait_for_selector("#revision-view", state="visible")
        settle(page)
        self.assertFalse(page.is_visible("#doc-search"))
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False]])
        page.click("#view-manuscript")
        settle(page)
        self.assertTrue(page.is_visible("#search-q"))
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])

    def test_a_pdf_that_cannot_be_opened_has_no_search(self):
        """With the build's PDF unreadable the pages show as images ('PNG 보기') and there is no text to search: the
        field is not shown and Ctrl+F is the browser's."""
        (self.pages_dir / self.doc.pdf_name).write_bytes(b"%PDF-1.4\nnot a pdf\n")
        context = self.browser.new_context(**DESKTOP)
        self.addCleanup(context.close)
        watch_idle(context)
        page = context.new_page()
        page.route("**/*", self.route)
        page.goto("http://viewer.test/?lang=ko")
        page.wait_for_function(booted(0), timeout=20000)
        page.wait_for_selector("#vec-chip", state="visible", timeout=20000)
        settle(page)
        self.assertFalse(page.is_visible("#doc-search"))
        page.evaluate("window.__kd=[]; addEventListener('keydown',e=>window.__kd.push([e.key,e.defaultPrevented]))")
        page.keyboard.press("Control+f")
        self.assertEqual(page.evaluate("window.__kd.filter(k=>k[0]==='f')"), [["f", False]])


def full(x, y, text, width=288):
    """A full line of a paragraph: `text` in F2 (12pt, one em a character) at (x, y), squeezed sideways to `width`pt so
    that it reaches the column's right edge as a justified line does (squeezed, never stretched: its spaces stay within
    one em, so the line is one piece)."""
    assert 12 * len(text) >= width, text
    return (x, y, [("F2", text)], (round(width / (12 * len(text)), 6), 0, 0, 1))


# The break-rule page: the column is x 72-360 (full lines are 288pt wide; nothing on it reaches further), lines 15pt apart
# (1.25 of the 12pt font: one line pitch). What is joined and what is not is stated per query in EDGE_EXPECTED.
EDGE = [
    [
        full(72, 740, "the boats wait and we stand in"),
        full(72, 725, "to the cold water and do not"),
        full(72, 710, "ice the hull while the cat"),
        full(72, 695, "alog lists each little boat for"),
        (72, 680, [("F2", "mat review.")]),
        full(72, 650, "the guide called it a well-"),
        full(72, 635, "known spot on the map from 2009" + EN_DASH),
        full(72, 620, "2010 and then he wrote an e" + chr(0x2010)),
        full(72, 605, "mail to the pier and the sta" + SHY),
        (72, 590, [("F2", "tion five.")]),
        full(72, 560, "관측소의 조류 기록은 여섯 분마다 적는다. 그날 바닷"),
        full(72, 545, "물의 높이를 적은 그 기록의 이름은 tide"),
        (72, 530, [("F2", "조류 표.")]),
        (72, 500, [("F2", "the short line ends")]),  # a paragraph's last line: it stops short of the edge
        full(72, 485, "here and goes on below it"),
        (72, 460, [("F2", "Tables")], (4, 0, 0, 1.5)),  # a heading: 18pt, as wide as the column
        full(72, 442, "tables of the keeper begin here"),
        full(72, 410, "1. the first item of the list"),
        (102, 395, [("F2", "wraps onto a second.")]),  # a list item's hanging indent: 2.5 font sizes in
        full(87, 365, "an indented paragraph starts", 273),  # a paragraph's first line, indented 1.25 font sizes
        (72, 350, [("F2", "here and runs on.")]),
        (240, 320, [("F2", "North cell")]),  # a right-aligned table: one cell a row, each ending on the column's edge
        (276, 305, [("F2", "Harbour")]),
        (90, 275, [("F2", "Station")]),  # a centred table: three cells a row, apart by more than an em
        (200, 275, [("F2", "North")]),
        (290, 275, [("F2", "Gauge")]),
        (84, 260, [("F2", "Harbour")]),
        (206, 260, [("F2", "Tide")]),
        (302, 260, [("F2", "Bay")]),
        (72, 230, [("F2", "Port Office")]),  # a letter head: the date set to the right edge by \\hfill
        (228, 230, [("F2", "12 May 2010")]),
        (72, 215, [("F2", "Pier Road")]),
        full(72, 180, "the gauge reads low at the"),  # two full lines 30pt apart: a looser pitch than one line
        full(72, 150, "ebb and rises with the flood"),
        (520, 100, [("F2", "turned text ends with harbour")], (0, 288 / 348, -1, 0)),  # a block set sideways, its lines
        (535, 100, [("F2", "lights in its column")], (0, 1, -1, 0)),  # running up: a full line and the one after
    ]
]
# What the rule gives on EDGE, query by query, with the reason - counted by hand from the text above, not computed.
EDGE_EXPECTED = [
    ("into", 0, "'in' / 'to' are Latin words at a break: a word space must be typed"),
    ("in to", 1, "the same break with its space typed"),
    ("notice", 0, "'not' / 'ice': a word space between Latin letters"),
    ("not ice", 1, "with the space"),
    ("catalog", 0, "'cat' / 'alog': a word space between Latin letters"),
    ("cat alog", 1, "with the space"),
    ("format", 0, "'for' / 'mat': a word space between Latin letters"),
    ("for mat", 1, "with the space; the second line need not be full"),
    ("well-known", 1, "'well-' / 'known': a line-final hyphen may be typed"),
    ("wellknown", 1, "... or left out"),
    ("2009-2010", 1, "'2009' + en dash / '2010': a dash runs on with no space"),
    ("20092010", 0, "a dash is not a hyphen: it must be typed"),
    ("2009 2010", 0, "nor is it a space"),
    ("e-mail", 1, "'e' + U+2010 / 'mail': a typeset hyphen, typed"),
    ("email", 1, "... or left out"),
    ("station", 1, "'sta' + soft hyphen / 'tion': hyphenated"),
    ("바닷물의", 1, "'바닷' / '물의': Hangul breaks inside a word"),
    ("바닷 물의", 1, "... and a space there is allowed"),
    ("tide조류", 1, "'tide' / '조류': with Hangul on one side the break may be nothing"),
    ("tide 조류", 1, "... or a space"),
    ("ends here", 0, "'the short line ends' does not reach the column's edge: a paragraph's last line"),
    ("tables tables", 0, "the 18pt heading 'Tables' and the 12pt line under it differ in size"),
    ("list wraps", 0, "the list item's next line starts 2.5 font sizes in: a hanging indent, not the column's edge"),
    ("starts here", 1, "a paragraph's indented first line (1.25 font sizes) is full; the next starts at the edge"),
    ("cell harbour", 0, "a right-aligned table's rows start mid-column"),
    ("north harbour", 0, "... nor across its rows"),
    ("station north", 0, "a centred table's cells are pieces of one line, apart by more than an em"),
    ("gauge harbour", 0, "... and its rows are never joined"),
    ("bay", 1, "each cell is still found"),
    ("2010 pier road", 0, "the letter head's date is a piece of an \\hfill line ('Port Office ... 12 May 2010')"),
    ("pier road", 1, "the next line itself is found"),
    ("the ebb", 0, "two full lines 30pt apart: more than one line pitch"),
    ("harbour lights", 1, "the sideways block's full line and the one after it, read in their own direction"),
]


class SearchBreakRule(SearchBase):
    """A query crosses a line's end only between consecutive lines of one wrapped paragraph (docs/handbook/viewer.md
    §본문 검색 찾는 규칙), on a page of the cases that are and are not, against counts stated by hand (EDGE_EXPECTED)."""

    def setUp(self):
        """The manuscript's build is the one-page EDGE fixture (the three-page build's other page images go)."""
        super().setUp()
        for extra in ("page-2.png", "page-3.png"):
            (self.pages_dir / extra).unlink()
        put_build(self.doc, build_dir(self.doc).name, search_pdf(EDGE), 1)

    def test_the_count_of_every_case_is_the_stated_one(self):
        """Each case of EDGE_EXPECTED shows its stated count: Latin words glued across a break find nothing, the same
        words with their space find one; hyphens (-, U+2010, soft) may be left out, a dash may not; Hangul breaks are
        optional; a short line, a heading, a hanging indent, tables, an \\hfill line and a loose pitch are never
        crossed; a block set sideways reads in its own direction."""
        page = self.view()
        for query, stated, why in EDGE_EXPECTED:
            with self.subTest(query=query):
                self.search(page, query)
                self.assertEqual(int(self.count(page).split("/")[1]), stated, why)

    def test_a_hit_over_a_break_draws_a_box_on_each_of_its_lines(self):
        """'in to' crosses from the first line's end to the second's start: one hit, counted once, drawn as two boxes -
        the first at the end of the full line, the second at the next line's start one pitch (15pt) lower - both the
        current hit; Enter stays on it."""
        page = self.view()
        self.search(page, "in to")
        self.assertEqual((self.count(page), self.said(page)), ("1/1", "1개 중 1번째 · 1쪽"))
        upper, lower = sorted(self.hits(page), key=lambda h: h["box"][1])
        self.assertTrue(upper["cur"] and lower["cur"])
        self.assertAlmostEqual(lower["box"][1] - upper["box"][1], 15 / 792, delta=0.002)
        self.assertAlmostEqual(lower["box"][0], 72 / 612, delta=0.004)
        self.assertGreater(upper["box"][0], 300 / 612)
        page.keyboard.press("Enter")
        self.assertEqual([h["cur"] for h in self.hits(page)], [True, True])


FIVE = [
    "ms=본문 원고:main.tex",
    "rr=Response letter:rr.pdf",
    "hl=Highlights:hl.pdf",
    "cl=Cover letter:cl.pdf",
    "ap=부록 자료:ap.pdf",
]


def five_docs(app, src):
    """Serve five documents from app, named as a submission's are - the manuscript (본문 원고), a response letter,
    highlights, a cover letter and an appendix (부록 자료) - so the nav bar carries five links. The manuscript's build is
    the fourteen-page fixture with its outline; the others are view-only PDFs, the response letter's holding the
    three-page fixture's first two pages. Returns the documents, the manuscript first."""
    for name in ("rr", "hl", "cl", "ap"):
        (src / (name + ".pdf")).write_bytes(search_pdf(PAGES[:2]) if name == "rr" else minimal_pdf(name))
    docs = helpers_figure.startup_documents.make_docs(FIVE, src, app.C.paths)
    assert isinstance(docs, list), docs
    app.set_docs(docs)
    for D in docs[1:]:
        helpers_figure.viewer_build(D, helpers_figure.BUILD1)
    put_build(docs[0], helpers_figure.BUILD1, search_pdf(long_pages(), outline=True), N_LONG)
    return docs


class FiveDocsBase(SearchBase):
    """SearchBase with five documents in the nav bar and the fourteen-page manuscript with an outline (five_docs)."""

    def setUp(self):
        """Five documents; the manuscript is the one on screen."""
        super().setUp()
        self.docs = five_docs(ps.APP, ps.APP.C.src)
        self.doc = self.docs[0]
        self.addCleanup(ps.APP.set_docs, None)


class SearchAcrossDocuments(FiveDocsBase):
    """Several documents: the search belongs to the document on screen."""

    def link(self, page, label):
        """Press the nav bar's link of the document named label and wait until its PDF is the one open."""
        page.click("#doc-links button:has-text('%s')" % label)
        page.wait_for_function(
            "document.querySelector('#doc-links [aria-current=page]').textContent.includes('%s')&&%s"
            % (label, PDF_READY)
        )
        settle(page)

    def test_switching_documents_clears_the_search(self):
        """With hits on the manuscript, pressing another document's link empties the field and leaves no hit box, count
        or announcement; back on the manuscript the field is still empty."""
        page = self.view()
        self.search(page, "tide")
        self.assertEqual(self.count(page), "1/14")
        self.link(page, "Response letter")
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])
        self.assertEqual((self.count(page), self.said(page)), ("", ""))
        self.link(page, "본문 원고")
        self.assertEqual(page.input_value("#search-q"), "")
        self.assertEqual(self.hits(page), [])

    def test_text_of_the_document_left_behind_does_not_reach_the_new_search(self):
        """The manuscript's page 1 is still being read when the response letter is opened and searched: the letter's
        own count stands - 1/4 - when the manuscript's late page arrives, and stays."""
        page = self.view()
        page.evaluate(TEXT_GATE)
        page.click("#search-q")
        page.keyboard.type("tide")
        page.wait_for_function("window.__text.held.has(1)")
        self.link(page, "Response letter")
        self.search(page, "tide")
        self.assertEqual(self.count(page), "1/4")
        page.evaluate("window.__text.all()")
        settle(page)
        self.assertEqual(self.count(page), "1/4")
        self.assertEqual(self.said(page), "4개 중 1번째 · 1쪽")

    def test_after_a_longer_build_the_search_marks_the_pages_it_comes_near(self):
        """A search on the response letter (two pages) is closed and the manuscript opened: stepping to the 'tide' on
        page 9 draws the boxes of the pages around it too - page 8 and page 10 - as the view comes near them."""
        page = self.view()
        self.link(page, "Response letter")
        self.search(page, "tide")
        page.keyboard.press("Escape")
        self.link(page, "본문 원고")
        self.search(page, "tide")
        for _ in range(8):
            page.keyboard.press("Enter")
        settle(page)
        self.assertEqual(self.count(page), "9/14")
        self.assertLessEqual({8, 9, 10}, {h["page"] for h in self.hits(page)})


# What is drawn and what answers a press across the nav bar while the field is open: the open box, every child of the bar
# with whether it shows, whether its box meets the open box and where it is, what a press reaches along the rows 2px above and 2px
# below the box (within the box's width), and the Tab order from the field.
OVER_BAR = """() => {const q = s => document.querySelector(s), box = q('#search-box').getBoundingClientRect(), nav = q('#doc-nav');
  const shows = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const meets = r => r.right > box.left + 0.01 && r.left < box.right - 0.01;
  const kids = [...nav.children].filter(e => e.id !== 'doc-search' && e.getClientRects().length).map(e => {const r = e.getBoundingClientRect();
    return {id: e.id, shows: shows(e), meets: meets(r), cut: e.scrollWidth - e.clientWidth, l: r.left, r: r.right};});
  const reach = y => {const ids = new Set(); for (let x = Math.ceil(box.left) + 1; x < box.right - 1; x += 3) {const e = document.elementFromPoint(x, y);
    ids.add(e ? (e.closest('#doc-search') ? 'search' : e.id || (e.closest('#doc-nav>*') || e).id || e.tagName) : 'none');} return [...ids];};
  return {box: [box.left, box.top, box.right, box.bottom], nav: [nav.getBoundingClientRect().left, nav.getBoundingClientRect().right], kids, gap: parseFloat(getComputedStyle(nav).columnGap),
    end: q('#doc-search').getBoundingClientRect().right,
    above: reach(box.top - 2), below: reach(box.bottom + 2), mode: q('#doc-search').dataset.mode};}"""
# The bar's pixels in the strips above and below the open box, within its width: in each strip, how many pixels differ from
# the commonest colour of their own row (the bar's background or its bottom line - each one colour across).
STRAY = """async ([b64, dpr, rows]) => {const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0);
  return rows.map(([l, t, r, b]) => {const X0 = Math.ceil(l * dpr), Y0 = Math.ceil(t * dpr), W = Math.floor(r * dpr) - X0, H = Math.floor(b * dpr) - Y0; if (W < 1 || H < 1) return 0;
    const D = x.getImageData(X0, Y0, W, H).data; let off = 0;
    for (let y = 0; y < H; y++) {const seen = new Map(); for (let i = y * W * 4; i < (y + 1) * W * 4; i += 4) {const k = D[i] + ',' + D[i + 1] + ',' + D[i + 2]; seen.set(k, (seen.get(k) || 0) + 1);}
      let best = 0; for (const n of seen.values()) best = Math.max(best, n); off += W - best;}
    return off;});}"""


class SearchCrowdedBar(FiveDocsBase):
    """A bar with five document links: the field gives way before its neighbours do, and while it is open over them
    nothing of them is left on screen."""

    def test_the_field_shrinks_to_its_minimum_then_folds_to_the_magnifier(self):
        """A mouse window narrowed from 1440 to 710px: the field is its full 240px, then the room that is left, never
        under 200px, then the magnifier alone - and at every width the view switch ends before the search begins, the
        document links are not cut short while the field shows, and the bar does not spill."""
        page = self.view(device(1440, 800, touch=False))
        seen = []
        for width in range(1440, 700, -10):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_function(
                "innerWidth===%d&&document.body.classList.contains('%s')"
                % (width, "lay-wide" if width >= 1100 else "lay-mid")
            )
            settle(page)
            g = page.evaluate(BAR)
            seen.append((g["mode"], round(g["search"]["w"])))
            self.assertLessEqual(g["view"]["r"], g["search"]["l"] + 0.01, width)
            self.assertLessEqual(g["spill"], 0, width)
            if g["mode"] == "inline":
                self.assertLessEqual(g["linksCut"], 0, width)
                self.assertTrue(200 <= g["search"]["w"] <= 240, (width, g["search"]))
            else:
                self.assertEqual((g["mode"], g["box"]), ("icon", None), width)
                self.assertEqual((g["open"]["w"], g["open"]["h"]), (28, 28), width)
        modes = [m for m, _ in seen]
        self.assertEqual(seen[0], ("inline", 240))
        self.assertEqual(modes[-1], "icon")
        self.assertTrue(any(m == "inline" and 200 <= w < 240 for m, w in seen), seen)

    @staticmethod
    def drawn_gaps(g):
        """The open bar as drawn, left to right (OVER_BAR): the gaps between consecutive drawn things - neighbours
        still shown and the open field - as (gap, whether the field is one of the two), and the gap from the last
        neighbour left of the field to the field (None when none is left of it)."""
        things = sorted([(k["l"], k["r"], False) for k in g["kids"] if k["shows"]] + [(g["box"][0], g["box"][2], True)])
        gaps = [(round(b[0] - a[1], 2), a[2] or b[2]) for a, b in zip(things, things[1:], strict=False)]
        before = [k["r"] for k in g["kids"] if k["shows"] and k["r"] <= g["box"][0] + 0.01]
        return gaps, (round(g["box"][0] - max(before), 2) if before else None)

    def open_folded(self, name):
        """The viewer on the crowded viewport `name` with the folded field opened by its magnifier and 'tide' typed.
        The browser's own tap highlight is turned off: Chrome washes the tapped magnifier's 44px box for a while after
        the tap, and that wash is not the page's drawing."""
        page = self.view(CROWDED[name])
        page.add_style_tag(content="*{-webkit-tap-highlight-color:transparent}")
        self.assertEqual(page.evaluate(BAR)["mode"], "icon", name)
        self.search(page, "tide")
        return page

    def test_the_opened_field_leaves_nothing_of_the_neighbours_it_covers(self):
        """With five links the field is folded on the two tablets, the unfolded foldable and a 760px mouse window (at
        scale factors 2 and 1). Opened with a query: every part of the bar that the field's box meets is not drawn and
        answers no press, every part still drawn is whole (not cut, clear of the box), a press 2px above or below the
        box reaches the search or the bare bar, and the rows of pixels above and below the box are the bar's own
        colour - no underline, separator or clipped word left over. The field takes the place of what it took off:
        it starts one bar gap after the last neighbour left on its left and ends where it ended, so no gap in the
        open bar is wider than the bar's gap - no blank run where the neighbours were."""
        for name, dev in CROWDED.items():
            with self.subTest(viewport=name):
                page = self.open_folded(name)
                g = page.evaluate(OVER_BAR)
                for kid in g["kids"]:
                    self.assertFalse(kid["shows"] and kid["meets"], kid)
                    if kid["shows"]:
                        self.assertLessEqual(kid["cut"], 0, kid)
                self.assertLessEqual(set(g["above"]) | set(g["below"]), {"search", "doc-nav"}, g)
                gaps, before = self.drawn_gaps(g)
                self.assertTrue(all(x <= g["gap"] + 0.5 for x, _ in gaps), (name, gaps, g["gap"]))  # no blank run
                self.assertAlmostEqual(before, g["gap"], delta=0.5, msg=name)  # one gap after what is left
                self.assertAlmostEqual(g["box"][2], g["end"], delta=0.01, msg=name)  # it ends where it ended
                self.assertGreaterEqual(g["box"][0], g["nav"][0])
                self.assertLessEqual(g["box"][2], g["nav"][1])
                page.evaluate("document.activeElement.blur()")  # no caret or ring in the shot
                settle(page)
                left, top, right, bottom = g["box"]
                band_t = page.evaluate("document.querySelector('#brand-stripe').getBoundingClientRect().bottom")
                nav_b = page.evaluate("document.querySelector('#doc-nav').getBoundingClientRect().bottom")
                shot = page.screenshot(clip={"x": 0, "y": 0, "width": dev["viewport"]["width"], "height": nav_b})
                stray = page.evaluate(
                    STRAY,
                    [
                        base64.b64encode(shot).decode(),
                        dev["device_scale_factor"],
                        [[left, band_t, right, top - 2], [left, bottom + 2, right, nav_b]],
                    ],
                )
                self.assertEqual(stray, [0, 0], name)

    def test_the_opened_fields_text_stays_put_from_its_first_frame(self):
        """In every crowded bar, from the first frame the field is open in - opened by its magnifier - through typing a
        query and its count arriving, the field's left edge and its text's left edge stay where they are: the field
        takes the neighbours' place in the frame it opens, not a frame later, and the count does not push the text."""
        record = """() => {window.__at = []; window.__stop = false; const tick = () => {
          if (document.body.classList.contains('search-open')) {const q = document.querySelector('#search-q').getBoundingClientRect(), b = document.querySelector('#search-box').getBoundingClientRect();
            window.__at.push([Math.round(b.left * 100) / 100, Math.round(q.left * 100) / 100]);}
          if (!window.__stop) requestAnimationFrame(tick);}; requestAnimationFrame(tick);}"""
        for name, dev in CROWDED.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate(record)
                self.press(page, "#search-open")
                page.wait_for_function("document.activeElement===document.querySelector('#search-q')")
                page.keyboard.type("tide")
                page.wait_for_function(COUNTED, timeout=8000)
                settle(page)
                page.evaluate("window.__stop = true")
                at = page.evaluate("window.__at")
                self.assertGreater(len(at), 2, name)
                self.assertEqual(sorted(set(map(tuple, at))), [tuple(at[-1])], name)

    def test_a_press_just_under_the_opened_field_does_not_reach_a_covered_tab(self):
        """In the 760px mouse window, a click 2px under the open field where [변경사항] lies covered leaves the
        manuscript on screen and the search as it was."""
        page = self.open_folded("mouse 760x800")
        box = page.evaluate(
            "(()=>{const b=document.querySelector('#search-box').getBoundingClientRect(); return [b.left,b.right,b.bottom];})()"
        )
        for x in range(int(box[0]) + 4, int(box[1]) - 4, 12):
            page.mouse.click(x, box[2] + 2)
        settle(page)
        self.assertFalse(page.is_visible("#revision-view"))
        self.assertEqual((page.input_value("#search-q"), self.count(page)), ("tide", "1/14"))

    def test_tab_from_the_opened_field_skips_what_it_covers(self):
        """In the 760px mouse window, Tab from the open field goes through its own three buttons, and Shift+Tab from
        it goes back past the covered tabs and links to a control that is on screen: no covered control takes the
        focus either way."""
        page = self.open_folded("mouse 760x800")
        where = "(e=>e.id||(e.closest('[id]')||e).id||e.tagName)(document.activeElement)"
        seen = []
        for _ in range(3):
            page.keyboard.press("Tab")
            seen.append(page.evaluate(where))
        self.assertEqual(seen, ["search-prev", "search-next", "search-close"])
        page.focus("#search-q")
        back = []
        for _ in range(3):
            page.keyboard.press("Shift+Tab")
            back.append(page.evaluate(where))
            self.assertTrue(
                page.evaluate(
                    "(e=>e===document.body||(e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden'))(document.activeElement)"
                ),
                back,
            )
        self.assertFalse({"doc-links", "view-manuscript", "view-revisions", "view-switch"} & set(back), back)
        self.assertEqual(back[0], "nav-toc-toggle")

    def test_closing_the_opened_field_brings_the_neighbours_back(self):
        """Esc folds the field to its magnifier with the focus on it, and every link and both tabs are drawn again,
        each exactly where it stood before the field opened."""
        page = self.view(CROWDED["mouse 760x800"])
        where = "[...document.querySelectorAll('#doc-nav>*,#doc-links button,#view-switch button')].filter(e=>e.getClientRects().length).map(e=>{const r=e.getBoundingClientRect(); return [e.id||e.textContent,r.left,r.top,r.width,r.height];})"
        rest = page.evaluate(where)
        self.search(page, "tide")
        page.keyboard.press("Escape")
        settle(page)
        self.assertEqual(page.evaluate("document.activeElement.id"), "search-open")
        g = page.evaluate(BAR)
        self.assertEqual((g["mode"], g["box"]), ("icon", None))
        self.assertTrue(g["links"] and g["view"])
        self.assertEqual(page.locator("#doc-links button:visible").count(), 5)
        self.assertEqual(page.evaluate(where), rest)

    def test_what_stays_beside_the_opened_field_keeps_the_bars_gap(self):
        """A mouse window with the field open and a query, narrowed from 1440 to 704px: at every width each neighbour
        still drawn ends at least one bar gap left of the open field, or right of it - nothing stands cramped against
        the field's border - and no neighbour the field meets is drawn. Wherever the field takes neighbours off, it
        starts exactly one bar gap after the last neighbour left on its left and no gap beside it is wider (gaps
        between two neighbours are the bar's own, as at rest: the paper's name keeps its wider margin) - also at
        the widths where only the view switch is taken off and the document links stay."""
        page = self.view(device(1440, 800, touch=False))
        self.search(page, "tide")
        seen = []
        for width in range(1440, 700, -8):
            page.set_viewport_size({"width": width, "height": 800})
            page.wait_for_function("innerWidth===%d" % width)
            settle(page)
            g = page.evaluate(OVER_BAR)
            left, right = g["box"][0], g["box"][2]
            for kid in g["kids"]:
                if not kid["shows"]:
                    continue
                self.assertFalse(kid["meets"], (width, kid))
                self.assertTrue(
                    kid["r"] <= left - g["gap"] + 0.01 or kid["l"] >= right + g["gap"] - 0.01, (width, kid, g["box"])
                )
            hidden = {kid["id"] for kid in g["kids"] if not kid["shows"]}
            if hidden:
                gaps, before = self.drawn_gaps(g)
                self.assertTrue(all(x <= g["gap"] + 0.5 for x, field in gaps if field), (width, gaps, hidden))
                self.assertAlmostEqual(before, g["gap"], delta=0.5, msg=(width, hidden))
                self.assertAlmostEqual(g["box"][2], g["end"], delta=0.01, msg=width)
            seen.append(hidden)
        self.assertIn({"view-switch"}, seen)  # some neighbours off and some left: the document links stay
        self.assertIn({"doc-links", "view-switch"}, seen)

    def test_switching_documents_with_the_focus_elsewhere_closes_the_search_in_the_same_frame(self):
        """In the 760px mouse window, with a query and the focus taken off the field, Ctrl+PgDn opens the next document:
        in the first frame after it the field is closed and empty and every document link - the new current one too -
        is drawn again."""
        page = self.open_folded("mouse 760x800")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        page.keyboard.press("Control+PageDown")
        got = page.evaluate(
            """() => new Promise(r => requestAnimationFrame(() => r({open: document.body.classList.contains('search-open'), value: document.querySelector('#search-q').value,
              covered: [...document.querySelectorAll('#doc-nav>*')].filter(e => getComputedStyle(e).visibility === 'hidden').map(e => e.id),
              box: document.querySelector('#search-box').getClientRects().length})))"""
        )
        self.assertEqual(got, {"open": False, "value": "", "covered": [], "box": 0})
        page.wait_for_function(
            "document.querySelector('#doc-links [aria-current=page]').textContent.includes('Response letter')"
        )
        self.assertEqual(page.locator("#doc-links button:visible").count(), 5)

    def test_closing_the_field_draws_the_neighbours_in_the_same_frame(self):
        """Esc on the open field over the crowded bar: in the first frame after it every neighbour the field had taken
        off is drawn again."""
        for name in ("fold inner 673x841", "mouse 760x800"):
            with self.subTest(viewport=name):
                page = self.open_folded(name)
                page.keyboard.press("Escape")
                hidden = page.evaluate(
                    "new Promise(r=>requestAnimationFrame(()=>r([...document.querySelectorAll('#doc-nav>*')].filter(e=>getComputedStyle(e).visibility==='hidden').map(e=>e.id))))"
                )
                self.assertEqual(hidden, [])

    def test_a_new_build_folds_an_open_field_that_has_no_focus(self):
        """In the 760px mouse window the field is open over the bar with a query and the focus is taken off it; a new
        build of the manuscript arrives (refreshDoc, as the build poll calls it): the query goes and the field folds to
        its magnifier, every document link drawn again - it is not left open, empty, over the bar."""
        page = self.open_folded("mouse 760x800")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        newer = put_build(self.doc, "pages-20260925110000", search_pdf(long_pages(), outline=True), N_LONG)
        page.evaluate("refreshDoc()")
        page.wait_for_function("META.pages_build==='%s'&&%s" % (newer.name, PDF_READY), timeout=8000)
        settle(page)
        g = page.evaluate(BAR)
        self.assertEqual((g["mode"], g["box"], page.input_value("#search-q")), ("icon", None, ""))
        self.assertEqual(page.locator("#doc-links button:visible").count(), 5)

    def test_esc_on_the_closed_search_is_the_viewers(self):
        """In the 760px mouse window the field is closed with Esc (the focus back on the magnifier) and the pin panel
        opened over the page: Esc on the magnifier is the viewer's again and folds the panel away."""
        page = self.open_folded("mouse 760x800")
        page.keyboard.press("Escape")
        settle(page)
        page.click("#btn-side")
        page.wait_for_function("document.body.classList.contains('side-open')")
        settle(page)
        page.focus("#search-open")
        page.keyboard.press("Escape")
        settle(page)
        self.assertFalse(page.evaluate("document.body.classList.contains('side-open')"))

    def test_on_touch_the_folded_magnifier_and_the_opened_field_answer_44px(self):
        """On the foldable's inner screen (673x841) the magnifier is the outline toggle's 44px box and answers 44x44px;
        tapped, the field opens inside the bar, 36px high, and it, its arrows and its close button answer 44x44px."""
        page = self.view(CROWDED["fold inner 673x841"])
        g = page.evaluate(BAR)
        self.assertEqual(g["mode"], "icon")
        self.assertEqual(
            (g["open"]["t"], g["open"]["b"], g["open"]["w"]), (g["toc"]["t"], g["toc"]["b"], g["toc"]["w"])
        )
        self.assertEqual(page.evaluate(MISSES_44, "#search-open"), [])
        self.assertLessEqual(g["spill"], 0)
        self.search(page, "tide")
        g = page.evaluate(BAR)
        self.assertEqual(g["box"]["h"], 36)
        self.assertGreaterEqual(g["box"]["l"], g["nav"]["l"] + g["padL"] - 0.01)
        self.assertLessEqual(g["box"]["r"], g["nav"]["r"] - g["padR"] + 0.01)
        self.assertEqual(page.evaluate(MISSES_44, "#search-field,#search-prev,#search-next,#search-close"), [])

    def test_a_hit_is_never_shown_under_the_overlay_panel(self):
        """On the unfolded foldable (841x673) and in an 841x673 mouse window, with the pin panel open over the page,
        'quayside' - at each page's right edge, under the panel while the page fills the screen's width - is shown in
        the part of the PDF the panel does not cover, every one of the fourteen stepped to: its box's centre and
        corners are the page's, not the panel's. The panel stays open, and closing the search gives the page its
        width back."""
        for name, dev in (("touch", CROWDED["fold inner 841x673"]), ("mouse", device(841, 673, touch=False))):
            with self.subTest(pointer=name):
                page = self.view(dev)
                self.press(page, "#btn-side")
                page.wait_for_function("document.body.classList.contains('side-open')")
                settle(page)
                wide = page.evaluate("document.getElementById('p1').getBoundingClientRect().width")
                panel = page.evaluate("document.querySelector('#right').getBoundingClientRect().left")
                self.assertGreater(
                    8 + wide * 470 / 612, panel
                )  # where the word is drawn before the search: under the panel
                self.search(page, "quayside")
                self.assertEqual(self.count(page), "1/%d" % N_LONG)
                covered = []
                for i in range(N_LONG):
                    cur = self.current(page)
                    if cur is None or not all(b["shows"] for b in cur["boxes"]):
                        covered.append((i + 1, cur))
                    page.keyboard.press("Enter")
                    settle(page)
                self.assertEqual(covered, [])
                self.assertTrue(page.evaluate("document.body.classList.contains('side-open')"))
                self.press(page, "#search-close")
                page.wait_for_function("document.getElementById('p1').getBoundingClientRect().width===%r" % wide)


# The status line (#status) as drawn and as a screen reader meets it: shown or not, its box, its spoken region's text and
# whether that region is in the accessibility tree (not display:none or visibility:hidden on it or an ancestor), and its
# action button's box with what a press at its centre reaches.
STATUS = """() => {const s = document.querySelector('#status'), sr = s.querySelector('[role=status]'), b = s.querySelector('button');
  const tree = e => {for (let x = e; x; x = x.parentElement) {const c = getComputedStyle(x); if (c.display === 'none' || c.visibility === 'hidden') return false;} return true;};
  const R = e => {const r = e.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height};};
  const at = e => {const r = e.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === e || e.contains(h));};
  return {shown: tree(s) && s.getClientRects().length > 0, box: s.getClientRects().length ? R(s) : null, said: sr ? sr.textContent : null, inTree: !!sr && tree(sr),
    action: b ? {box: R(b), reached: at(b), text: b.textContent.trim()} : null, text: s.querySelector('.st-body').textContent.trim()};}"""
# A status message with an action, as the viewer raises one (lineNote): the arrival has no control to press.
NOTE = "lineNote('연결이 끊겼습니다 — 다시 연결하는 중입니다', NOTICE_KIND.WARN, {label: '다시 시도', fn: () => {}})"
# The status line a manuscript newer than its PDF raises, with its action.
STALE = "lineNote('원고 수정됨', NOTICE_KIND.WARN, {label: '재빌드', fn: () => {}})"
# The phone's search rows and the status line over them, measured: the field's box, where the count's text and the status's
# icon start, the icon centres of the rows' last buttons (next, close, the status's dismiss), and the rows' boxes top to
# bottom, with the inner tops (inside their borders) of the status's dock and the rows; with the edge and ink insets in force.
ROWS = """() => {const q = s => document.querySelector(s), R = s => {const e = q(s); if (!e || !e.getClientRects().length) return null; const r = e.getBoundingClientRect();
    return {l: r.left, r: r.right, t: r.top, b: r.bottom, c: (r.left + r.right) / 2};};
  const cs = getComputedStyle(document.body), px = v => parseFloat(cs.getPropertyValue(v));
  const range = document.createRange(), count = q('#search-count'); range.selectNodeContents(count);
  return {W: innerWidth, edge: px('--edge'), ink: px('--edge') + px('--space-3'), gap: px('--space-2'), field: R('#search-field'), count: range.getBoundingClientRect().left,
    next: R('#search-next .ic'), close: R('#search-close .ic'), stX: R('#status .nt-x .ic'), stIcon: R('#status .st-ic'),
    dock: R('#status-dock'), status: R('#status'), nav: R('#doc-nav'), countRow: R('#search-nav'), fieldRow: R('#search-field'),
    dockIn: q('#status-dock').getBoundingClientRect().top + q('#status-dock').clientTop, navIn: q('#doc-nav').getBoundingClientRect().top + q('#doc-nav').clientTop,
    words: (t => t ? t.getBoundingClientRect().top + parseFloat(getComputedStyle(t).paddingTop) : null)(q('#status .st-tx'))};}"""


class SearchStatusLine(FiveDocsBase):
    """The status line stays drawn, pressable and spoken while the search is open (docs/handbook/viewer.md §본문 검색):
    the short band's top row holds it beside the field, and the phone's search rows stand under it."""

    def test_the_short_bands_open_field_leaves_the_status_line_whole_and_spoken(self):
        """On a landscape phone (844x390, 908x411) the status sits in the one top row. With a status up and the field
        opened over the row: the status is drawn, its action answers a press at its centre and its spoken region is in
        the accessibility tree; the field starts one bar gap after it and nothing is drawn between the outline toggle
        and the field wider than the bar's gap. A message arriving while the field is open is shown and said."""
        for name, dev in (("short 844x390", device(844, 390)), ("short 908x411", device(908, 411))):
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate(NOTE)
                settle(page)
                self.assertTrue(page.evaluate(STATUS)["shown"])
                self.press(page, "#search-open")
                page.keyboard.type("tide")
                page.wait_for_function(COUNTED, timeout=8000)
                settle(page)
                st = page.evaluate(STATUS)
                self.assertTrue(st["shown"] and st["inTree"], st)
                self.assertTrue(st["action"]["reached"], st)
                g = page.evaluate(OVER_BAR)
                self.assertIn("status", [k["id"] for k in g["kids"] if k["shows"]])
                self.assertLessEqual(st["box"]["r"], g["box"][0] - g["gap"] + 0.5, (st, g["box"]))
                gaps, before = SearchCrowdedBar.drawn_gaps(g)
                self.assertTrue(all(x <= g["gap"] + 0.5 for x, _ in gaps), (name, gaps))
                self.assertAlmostEqual(before, g["gap"], delta=0.5)
                page.evaluate("lineNote('다시 연결했습니다', NOTICE_KIND.OK)")
                page.wait_for_function(
                    "document.querySelector('#status [role=status]').textContent.includes('다시 연결했습니다')"
                )
                self.assertTrue(page.evaluate(STATUS)["shown"])

    def test_the_short_bands_status_words_stay_whole_beside_the_field(self):
        """On a landscape phone (844x390, 908x411) with '원고 수정됨 [재빌드]' up and 'tide' searched, the status's words
        show whole - not cut to an ellipsis - its action answers a press and the outline toggle stays: the field gave way
        first, down to its minimum query width (120px on touch), then the document links and the view switch, then the
        status's dismiss button; the words come last."""
        for name, dev in (("short 844x390", device(844, 390)), ("short 908x411", device(908, 411))):
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate(STALE)
                settle(page)
                self.press(page, "#search-open")
                page.keyboard.type("tide")
                page.wait_for_function(COUNTED, timeout=8000)
                settle(page)
                words = page.evaluate(
                    "(t=>[t.textContent,t.scrollWidth-t.clientWidth])(document.querySelector('#status .st-tx'))"
                )
                self.assertEqual(words[0], "원고 수정됨")
                self.assertLessEqual(words[1], 0, words)
                st = page.evaluate(STATUS)
                self.assertTrue(st["shown"] and st["action"]["reached"], st)
                self.assertGreaterEqual(
                    page.evaluate("document.querySelector('#search-q').getBoundingClientRect().width"), 120
                )
                g = page.evaluate(OVER_BAR)
                self.assertLessEqual(st["box"]["r"], g["box"][0] - g["gap"] + 0.5)
                self.assertIn("nav-toc-toggle", [k["id"] for k in g["kids"] if k["shows"]])  # the outline toggle stays

    def test_in_every_short_band_and_for_any_message_nothing_overlaps(self):
        """Landscape phones 720x320, 844x390 and 908x411, the field open with 'tide': with the stale-manuscript line, and
        then with a long message arriving while the field is open, the status line and the field never overlap (the
        field starts one bar gap after the status), every button of the status answers a press at its centre, no
        neighbour the field took off is drawn (nor anything under the field), and the status's words are shortened only
        once its dismiss button is
        gone - and the field goes under its least width only once the words are gone too."""
        long = (
            "lineNote('핀 #12 을 다른 사람이 고쳤습니다. 다시 읽은 뒤 저장하세요', NOTICE_KIND.WARN, null, {source: 'edit'});"
            "lineNote('지금 쓰던 메모는 그대로 둡니다', NOTICE_KIND.INFO)"
        )  # two messages: the line shows the first with '+1'
        check = """() => {const s = document.querySelector('#status'), box = document.querySelector('#search-box').getBoundingClientRect(), nav = document.querySelector('#doc-nav');
          const at = e => {const r = e.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === e || e.contains(h));};
          const t = s.querySelector('.st-tx'), x = s.querySelector('.nt-x');
          return {gap: parseFloat(getComputedStyle(nav).columnGap), right: s.getBoundingClientRect().right, left: box.left,
            buttons: [...s.querySelectorAll('button')].filter(b => b.getClientRects().length).map(b => [b.textContent.trim() || b.getAttribute('aria-label'), at(b)]),
            drawnCovered: [...nav.querySelectorAll(':scope>.search-covered')].filter(e => getComputedStyle(e).visibility !== 'hidden').map(e => e.id),
            under: [...nav.children].filter(e => e.id !== 'doc-search' && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden')
              .filter(e => {const r = e.getBoundingClientRect(); return r.width > 0 && r.right > box.left + 0.5 && r.left < box.right - 0.5;}).map(e => e.id),
            cut: t ? t.scrollWidth - t.clientWidth : 0, dismiss: !!x && x.getClientRects().length > 0, words: t ? t.clientWidth : 0,
            query: document.querySelector('#search-q').getBoundingClientRect().width};}"""
        for name, dev in (
            ("short 720x320", device(720, 320)),
            ("short 844x390", device(844, 390)),
            ("short 908x411", device(908, 411)),
        ):
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.assertTrue(page.evaluate("document.body.classList.contains('band-short')"))
                page.evaluate(STALE)
                settle(page)
                self.press(page, "#search-open")
                page.keyboard.type("tide")
                page.wait_for_function(COUNTED, timeout=8000)
                settle(page)
                for message in ("stale", "long", "one long"):
                    if message == "long":
                        page.evaluate(long)
                        settle(page)
                    if message == "one long":
                        page.evaluate("for (const n of [...LINE]) endNotice(n, true)")
                        page.evaluate(
                            "m=>lineNote(m, NOTICE_KIND.WARN, null, {literal: true})",
                            "핀 #12 을 다른 사람이 고쳤습니다. 다시 읽은 뒤 저장하세요 — 지금 쓰던 메모는 그대로 둡니다",
                        )
                        settle(page)
                    m = page.evaluate(check)
                    self.assertLessEqual(m["right"], m["left"] - m["gap"] + 0.5, (message, m))
                    self.assertTrue(all(ok for _, ok in m["buttons"]), (message, m))  # its action, '+N', dismiss
                    self.assertEqual(m["drawnCovered"], [], (message, m))
                    self.assertEqual(m["under"], [], (message, m))  # nothing drawn under the field
                    if m["cut"] > 0:
                        self.assertFalse(m["dismiss"], (message, m))
                    if (
                        m["query"] < 110
                    ):  # the field well under its least width (a 118px query) only once the words are gone
                        self.assertLessEqual(m["words"], 1, (message, m))

    def test_an_empty_search_costs_the_pdf_no_height_with_or_without_a_status_line(self):
        """On each phone, opening the search from the navigation sheet with nothing typed leaves the PDF its visible height
        - the status line and the search row together are as high as the status line and the sheet's bar at rest."""
        free = """() => {const top = document.querySelector('#brand-stripe').getBoundingClientRect().bottom;
          const tops = [...document.querySelectorAll('#right,#doc-nav,#status-dock')].filter(e => e.getClientRects().length && getComputedStyle(e).display !== 'none').map(e => e.getBoundingClientRect().top);
          return Math.min(...tops) - top;}"""
        for name, dev in PHONES.items():
            for status in (False, True):
                with self.subTest(viewport=name, status=status):
                    page = self.view(dev)
                    if status:
                        page.evaluate(STALE)
                        settle(page)
                    rest = page.evaluate(free)
                    self.disclose(page)
                    self.assertEqual(page.evaluate(free), rest)

    def test_the_phones_rows_share_their_edges_and_one_rhythm(self):
        """On each phone, with and without a status line, the search open with a query: the field's box starts on
        --edge and the count's text on --ink, as the status's icon does; the icons of each row's last button - next,
        close and the status's dismiss - stand in one column; and top to bottom the status row, the count row and the
        field row are --space-2 apart; the status row is the sheet's first row, 24px from its top edge, with --space-2
        (within half a pixel) above its words - as the count row has --space-2 above it when there is no status line."""
        for name, dev in PHONES.items():
            for status in (False, True):
                with self.subTest(viewport=name, status=status):
                    page = self.view(dev)
                    if status:
                        page.evaluate(STALE)
                        settle(page)
                    self.search(page, "tide")
                    m = page.evaluate(ROWS)
                    self.assertAlmostEqual(m["field"]["l"], m["edge"], delta=0.5, msg=m)
                    self.assertAlmostEqual(m["count"], m["ink"], delta=0.5, msg=m)
                    self.assertAlmostEqual(m["next"]["c"], m["close"]["c"], delta=0.5, msg=m)
                    self.assertAlmostEqual(m["countRow"]["t"] - m["navIn"], m["gap"], delta=0.5, msg=m)
                    self.assertAlmostEqual(m["fieldRow"]["t"] - m["countRow"]["b"], m["gap"], delta=0.5, msg=m)
                    if status:
                        self.assertAlmostEqual(m["stIcon"]["l"], m["ink"], delta=0.5, msg=m)
                        self.assertAlmostEqual(m["stX"]["c"], m["close"]["c"], delta=0.5, msg=m)
                        self.assertAlmostEqual(
                            m["status"]["t"], m["dockIn"], delta=0.01, msg=m
                        )  # the sheet's first row
                        self.assertAlmostEqual(m["status"]["b"] - m["status"]["t"], 24, delta=0.01, msg=m)
                        self.assertAlmostEqual(
                            m["words"] - m["dockIn"], m["gap"], delta=0.5, msg=m
                        )  # space above the words
                        self.assertAlmostEqual(m["countRow"]["t"] - m["status"]["b"], m["gap"], delta=0.5, msg=m)

    def test_the_phones_status_line_stands_above_the_search_rows(self):
        """On each phone, with a status up and the search open from the navigation sheet with a query: the status line
        is drawn above the result row - its bottom at the rows' top, nothing over it - its action answers a press at
        its centre, its region is spoken, and a hit is shown above it."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                page.evaluate(NOTE)
                settle(page)
                self.search(page, "tide")
                st = page.evaluate(STATUS)
                rows = page.evaluate("document.querySelector('#doc-nav').getBoundingClientRect().top")
                self.assertTrue(st["shown"] and st["inTree"], st)
                self.assertAlmostEqual(st["box"]["b"], rows, delta=1, msg=(name, st["box"], rows))
                self.assertTrue(st["action"]["reached"], st)
                cur = self.current(page)
                self.assertTrue(
                    all(b["shows"] and b["bottom"] <= st["box"]["t"] for b in cur["boxes"]), (cur, st["box"])
                )


# The navigation sheet's search row as a finger meets it: how many px of its height answer a tap down its middle (nothing
# else drawn over them), its height, whether a tap at its centre reaches it, how far the sheet is scrolled, how many
# documents it lists and where the row stands in the sheet.
SHEET_ROW = """() => {const d = document.querySelector('#nav-sheet'), e = document.querySelector('#ns-search'), r = e.getBoundingClientRect(), D = d.getBoundingClientRect();
  const own = y => {if (y < 0 || y >= innerHeight) return false; const h = document.elementFromPoint(r.left + r.width / 2, y); return !!h && (h === e || e.contains(h));};
  let shown = 0; for (let y = Math.round(r.top); y < Math.round(r.bottom); y++) if (own(y + 0.5)) shown++;
  return {shown, h: r.height, reaches: own(r.top + r.height / 2), scrolled: d.scrollTop, docs: document.querySelectorAll('#ns-docs-list .dm-item').length, top: r.top - D.top};}"""


class SearchPhoneSheetRow(FiveDocsBase):
    """The phone's one touch entry to the search - the navigation sheet's row - is on screen whenever the sheet opens."""

    def rows(self, dev, pages):
        """Open the navigation sheet at each of `pages` on dev and read the search row (SHEET_ROW), then scroll the
        sheet to its end and read it again; the sheet is closed between pages."""
        page = self.view(dev)
        out = {}
        for n in pages:
            page.evaluate("n=>document.getElementById('p'+n).scrollIntoView()", n)
            settle(page)
            page.tap("#btn-pos")
            page.wait_for_selector("#nav-sheet[open]")
            settle(page)
            opened = page.evaluate(SHEET_ROW)
            page.evaluate("document.querySelector('#nav-sheet').scrollTop=1e6")
            settle(page)
            out[n] = (opened, page.evaluate(SHEET_ROW))
            page.tap("#nav-sheet [data-act=nav-sheet-close]")
            page.wait_for_function("!document.querySelector('#nav-sheet').open")
        return out

    def test_the_row_shows_whole_with_five_documents_on_any_page(self):
        """Five documents, pages 1, 5, 12 and 14, on the three phones: the row is 44px high, all of it shows and a tap
        at its centre reaches it when the sheet opens - and still when the sheet is scrolled to its end, because the
        row is part of the sheet's head."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                for n, (opened, scrolled) in self.rows(dev, (1, 5, 12, 14)).items():
                    for state in (opened, scrolled):
                        self.assertEqual(
                            (state["docs"], state["h"], state["shown"], state["reaches"]), (5, 44, 44, True), (n, state)
                        )
                    self.assertEqual(opened["top"], scrolled["top"], n)
                    self.assertGreater(scrolled["scrolled"], 0, n)

    def test_the_row_shows_whole_with_one_document_on_any_page(self):
        """The same with the manuscript alone (no document list in the sheet)."""
        ps.APP.set_docs([self.docs[0]])
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                for n, (opened, scrolled) in self.rows(dev, (1, 12)).items():
                    for state in (opened, scrolled):
                        self.assertEqual((state["h"], state["shown"], state["reaches"]), (44, 44, True), (n, state))

    def test_the_sheet_still_turns_to_the_current_section_as_far_as_the_current_document_allows(self):
        """On page 12 the sheet opens scrolled towards the outline's current section, as far as it goes without hiding
        the current document's row: that row is whole and flush under the head - under the search row, not behind
        it - and the outline's current section is the twelfth."""
        page = self.view(PHONES["phone 390x844"])
        page.evaluate("document.getElementById('p12').scrollIntoView()")
        settle(page)
        page.tap("#btn-pos")
        page.wait_for_selector("#nav-sheet[open]")
        settle(page)
        got = page.evaluate(
            """() => {const d = document.querySelector('#nav-sheet'), R = s => d.querySelector(s).getBoundingClientRect(), head = R('.ns-head'), row = R('#ns-search'), on = R('.dm-item.on');
              return {under: on.top - head.bottom, rowInHead: row.bottom <= head.bottom, scrolled: d.scrollTop, section: d.querySelector('#ns-outline-items .ol-active').textContent};}"""
        )
        self.assertAlmostEqual(got["under"], 0, delta=1)
        self.assertTrue(got["rowInHead"])
        self.assertGreater(got["scrolled"], 0)
        self.assertIn("Section 12", got["section"])


class SearchBarGeometry(SearchBase):
    """The field's size and place in the nav bar on every viewport that has one (docs/handbook/viewer.md §본문 검색):
    measured, not judged."""

    def bar(self, dev, dark=False, init=None):
        """The viewer on dev and the bar's geometry (BAR)."""
        page = self.view(dev, dark=dark, init=init)
        self.assertEqual(fonts_ready(page), "loaded")
        return page, page.evaluate(BAR)

    def test_the_search_comes_after_the_view_switch_and_before_the_page_count(self):
        """In every bar the visible controls end ... view switch, search, and then the page count where the band has
        one; nothing spills out of the bar and the search's right neighbour is one bar gap away - or the search ends
        on the bar's content edge."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                _, g = self.bar(dev)
                tail = g["kids"][g["kids"].index("view-switch") :]
                self.assertEqual(tail, ["view-switch", "doc-search"] + (["nav-page"] if g["page"] else []))
                self.assertLessEqual(g["spill"], 0)
                self.assertEqual(g["mode"], "inline")
                self.assertEqual(g["search"]["w"], 240)
                if g["page"]:
                    self.assertAlmostEqual(g["page"]["l"] - g["search"]["r"], g["gap"], delta=0.01)
                    self.assertAlmostEqual(g["page"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
                else:
                    self.assertAlmostEqual(g["search"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
                self.assertGreaterEqual(g["search"]["l"] - g["view"]["r"], g["gap"] - 0.01)

    def test_a_collapsed_wide_panel_keeps_its_toggle_last(self):
        """With the desktop panel folded (Ctrl+\\) the bar ends ... search, [핀 N ‹]: the toggle stays at the bar's right
        end, one gap after the search, on the field's top and bottom."""
        page = self.view()
        page.keyboard.press("Control+\\")
        page.wait_for_selector("#nav-side", state="visible")
        settle(page)
        g = page.evaluate(BAR)
        self.assertEqual(g["kids"][-2:], ["doc-search", "nav-side"])
        self.assertAlmostEqual(g["side"]["l"] - g["search"]["r"], g["gap"], delta=0.01)
        self.assertAlmostEqual(g["side"]["r"], g["nav"]["r"] - g["padR"], delta=0.01)
        self.assertEqual((g["box"]["t"], g["box"]["b"]), (g["side"]["t"], g["side"]["b"]))

    def test_the_field_is_its_rows_control_height_and_centred_in_the_band(self):
        """With a mouse the field is the 28px control, its top and bottom on the outline toggle's; on touch it is drawn
        at 36px, 4px clear of the stripe above and of the bar's line below. Everywhere its centre is the band's, the
        outline toggle's and the view tab's label's, within half a pixel, and its icon is 16px on the same centre."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                _, g = self.bar(dev)
                touch = dev.get("has_touch", False)
                band = (g["band"]["t"] + g["band"]["b"]) / 2
                self.assertEqual(g["box"]["h"], 36 if touch else 28)
                if touch:
                    self.assertEqual((g["box"]["t"] - g["band"]["t"], g["band"]["b"] - g["box"]["b"]), (4, 4))
                else:
                    self.assertEqual((g["box"]["t"], g["box"]["b"]), (g["toc"]["t"], g["toc"]["b"]))
                for k in ("box", "toc", "tocIcon", "viewLbl", "icon"):
                    self.assertAlmostEqual(g[k]["m"], band, delta=0.5, msg=k)
                self.assertEqual((g["icon"]["w"], g["icon"]["h"]), (16, 16))
                self.assertEqual(g["icon"]["t"] % 1, 0)  # icons are drawn on whole pixels

    def test_showing_the_search_moves_nothing_before_it(self):
        """The view switch, the document links and the outline toggle stand where they stand without the search."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                page, g = self.bar(dev)
                page.evaluate("document.querySelector('#doc-search').hidden=true")
                bare = page.evaluate(BAR)
                for k in ("toc", "view", "viewLbl"):
                    self.assertEqual(g[k], bare[k], k)

    def test_spacing_is_on_the_4px_grid(self):
        """Every padding, margin and gap of the search's parts is a multiple of 4px, or a 1px hairline inset; the one
        exception is the search's left margin in the bar, which is the bar's flexible gap."""
        for name, dev in list(BARS.items()) + list(PHONES.items()):
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.search(page, "tide")
                off = page.evaluate(
                    """() => {const bad = []; for (const e of [document.querySelector('#doc-search'), ...document.querySelectorAll('#doc-search *')]) {
                      if (!e.getClientRects().length || e.closest('svg')) continue; const cs = getComputedStyle(e);
                      for (const p of ['paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginRight','marginBottom','marginLeft','columnGap','rowGap']) {
                        if (e.id === 'doc-search' && p === 'marginLeft') continue;
                        const v = parseFloat(cs[p]); if (!isNaN(v) && Math.abs(v) > 1 && v % 4 !== 0) bad.push((e.id || e.tagName) + ' ' + p + ' ' + cs[p]);}}
                      return bad;}"""
                )
                self.assertEqual(off, [])

    def test_the_hint_is_small_muted_right_aligned_and_gone_with_a_query(self):
        """On the desktop the empty field shows the shortcut at the smallest text size in the muted colour, its right
        end one 8px step inside the field's border and its centre on the field's; focusing the field keeps it, the
        first character removes it. Touch screens show no shortcut."""
        page, g = self.bar(DESKTOP)
        style = page.evaluate(
            "(()=>{const h=getComputedStyle(document.querySelector('#search-hint')),r=getComputedStyle(document.documentElement),"
            "p=document.createElement('i'); p.style.color='var(--muted-foreground)'; document.body.append(p); const c=getComputedStyle(p).color; p.remove();"
            "return [h.fontSize,getComputedStyle(document.querySelector('#search-q')).fontSize,h.color,c,r.getPropertyValue('--text-xs').trim()];})()"
        )
        self.assertEqual(style[0], style[4])
        self.assertLess(float(style[0][:-2]), float(style[1][:-2]))
        self.assertEqual(style[2], style[3])
        self.assertAlmostEqual(g["box"]["r"] - g["hint"]["r"], 8 + 1, delta=0.01)
        self.assertAlmostEqual(g["hint"]["m"], g["box"]["m"], delta=0.5)
        page.click("#search-q")
        self.assertTrue(page.is_visible("#search-hint"))
        page.keyboard.type("t")
        self.assertFalse(page.is_visible("#search-hint"))
        page.keyboard.press("Backspace")
        self.assertTrue(page.is_visible("#search-hint"))
        touch = self.view(BARS["tablet 768x1024"])
        self.assertFalse(touch.is_visible("#search-hint"))

    def test_the_fields_parts_draw_no_box_inside_its_box(self):
        """The field's border is the one outline: the input, the count and the buttons inside it have no border and
        no outline of their own while the field shows its focus ring."""
        page = self.view()
        self.search(page, "tide")
        inner = page.evaluate(
            """() => [...document.querySelectorAll('#search-box *')].filter(e => e.getClientRects().length && !e.closest('svg')).map(e => {
              const cs = getComputedStyle(e); return [e.id || e.tagName, cs.borderTopWidth, cs.borderLeftWidth, cs.outlineStyle];}).filter(x => x[1] !== '0px' || x[2] !== '0px' || x[3] !== 'none')"""
        )
        self.assertEqual(inner, [])
        ring = page.evaluate(
            "(()=>{const c=getComputedStyle(document.querySelector('#search-box')); return [c.outlineStyle,c.outlineWidth,c.borderTopWidth];})()"
        )
        self.assertEqual(ring, ["solid", "2px", "1px"])

    def test_the_query_keeps_its_minimum_width_beside_the_count_and_the_buttons(self):
        """With a query whose count is three digits over four ('tide' written into a long count is stood in for by the
        widest count the fixture gives, then by a made-up one), the part of the field that shows the query is at
        least 80px with a mouse and 120px on touch, and the open field is still inside the bar."""
        for name, dev in BARS.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.search(page, "tide")
                page.evaluate("document.querySelector('#search-count').textContent='888/8888'")
                settle(page)
                g = page.evaluate(BAR)
                self.assertGreaterEqual(g["q"]["w"], 120 if dev.get("has_touch") else 80, g["q"])
                self.assertGreaterEqual(g["box"]["l"], g["nav"]["l"] + g["padL"] - 0.01)
                self.assertAlmostEqual(g["box"]["r"], g["search"]["r"], delta=0.01)

    def test_dark_theme_keeps_the_geometry(self):
        """The dark theme changes colours only: the bar's boxes are those of the light theme."""
        _, light = self.bar(DESKTOP)
        _, dark = self.bar(DESKTOP, dark=True)
        self.assertEqual(light, dark)


class SearchInk(SearchBase):
    """The field's text on the row's ink reference (docs/handbook/viewer.md §글자 가운데): the cap-height centre the
    row's trimmed labels stand on, read from the pixels drawn."""

    def inks(self, page, dpr, typed=None, write=None):
        """Ink centres minus the band's centre (CSS px), read from a screenshot of the bar: the field's text (`typed`
        typed into it, or its placeholder), the two view tabs' labels (with `write` written into [변경사항]'s label,
        as a neighbour showing the same string) and the shortcut hint (None when it does not show)."""
        if write is not None:
            page.evaluate("t=>{document.querySelector('#view-revisions .lbl').textContent=t;}", write)
        if typed is not None:
            page.fill("#search-q", typed)
            page.evaluate("document.activeElement.blur()")
        settle(page)
        self.assertEqual(fonts_ready(page), "loaded")
        g = page.evaluate(BAR)
        shown = page.evaluate(
            "(()=>{const q=document.querySelector('#search-q'),c=document.createElement('canvas').getContext('2d'),cs=getComputedStyle(q);"
            "c.font=cs.fontWeight+' '+cs.fontSize+' '+cs.fontFamily; return c.measureText(q.value||q.placeholder).width;})()"
        )
        shot = page.screenshot(clip={"x": 0, "y": 0, "width": g["nav"]["w"], "height": g["nav"]["b"] + 2})
        band = g["band"]
        boxes = [
            [g["q"]["l"], g["box"]["t"] + 2, min(g["q"]["r"], g["q"]["l"] + shown + 1), g["box"]["b"] - 2],
            [g["viewLbl"]["l"], band["t"] + 1, g["viewLbl"]["r"], band["b"] - 4],
            [g["otherLbl"]["l"], band["t"] + 1, g["otherLbl"]["r"], band["b"] - 4],
        ]
        if g["hint"]:
            boxes.append([g["hint"]["l"], g["box"]["t"] + 2, g["hint"]["r"], g["box"]["b"] - 2])
        mids = page.evaluate(INK_MID, [base64.b64encode(shot).decode(), dpr, boxes])
        centre = (band["t"] + band["b"]) / 2
        field, tab, other = (m - centre for m in mids[:3])
        return {"field": field, "tab": tab, "other": other, "hint": mids[3] - centre if g["hint"] else None}

    def assert_on_the_rows_line(self, dev, dpr, init=None):
        """On dev: the placeholder against the regular-weight tab label beside it, capitals and digits typed against
        the same string in that label, Hangul typed against the Hangul tab label, and the hint against the band's
        centre - each within half a pixel."""
        page = self.view(dev, init=init)
        if not page.is_visible("#search-q"):
            self.disclose(page)
            page.evaluate("document.activeElement.blur()")
        rest = self.inks(page, dpr)
        self.assertLessEqual(abs(rest["field"] - rest["other"]), 0.5, ("placeholder", rest))
        if rest["hint"] is not None:
            self.assertLessEqual(abs(rest["hint"]), 0.5, ("hint", rest))
        caps = self.inks(page, dpr, typed="H1080", write="H1080")
        self.assertLessEqual(abs(caps["field"] - caps["other"]), 0.5, ("capitals and digits", caps))
        hangul = self.inks(page, dpr, typed="원고")
        self.assertLessEqual(abs(hangul["field"] - hangul["tab"]), 0.5, ("Hangul", hangul))

    def test_the_fields_text_is_on_its_neighbours_line_at_every_scale_factor(self):
        """A mouse desktop at device scale factors 1, 1.25, 1.5 and 2, in the bundled Pretendard."""
        for dpr in (1, 1.25, 1.5, 2):
            with self.subTest(scale=dpr):
                self.assert_on_the_rows_line(device(1440, 900, touch=False, dpr=dpr), dpr)

    def test_the_fields_text_is_on_its_neighbours_line_in_fallback_fonts(self):
        """The same with the system's sans-serif (the font stack's last resort) and monospace (metrics far from it) in
        Pretendard's place, at scale factors 1 and 2."""
        for font in ("sans-serif", "monospace"):
            for dpr in (1, 2):
                with self.subTest(font=font, scale=dpr):
                    self.assert_on_the_rows_line(device(1440, 900, touch=False, dpr=dpr), dpr, init=FONT % font)

    def test_the_fields_text_is_on_its_neighbours_line_on_touch(self):
        """A touch tablet's bar (16px text in the field beside 12px labels) at scale factors 2 and 3."""
        for dpr in (2, 3):
            with self.subTest(scale=dpr):
                self.assert_on_the_rows_line(device(768, 1024, dpr=dpr), dpr)

    def test_on_touch_the_layout_is_exact_and_the_paint_within_one_device_pixel(self):
        """16px text in the field beside 12px labels (a touch tablet's bar) and in the phone's row, at scale factors 1,
        1.25, 1.5 and 2. In layout - before painting - the field's cap-height centre is the trimmed reference's (the
        labels' line, the field's middle on the phone) within 0.1px. Painted, the text and the labels are snapped to
        device pixels each in its own way, so the ink centres agree within one device pixel."""
        layout = """() => {const q = document.querySelector('#search-q').getBoundingClientRect(), p = document.querySelector('#search-probe'), R = document.querySelector('#search-ref-row').getBoundingClientRect();
          const base = p.firstElementChild.getBoundingClientRect().bottom - p.getBoundingClientRect().top, own = document.querySelector('#search-ref-own').getBoundingClientRect().height;
          return (q.top + base - own / 2) - (R.top + R.bottom) / 2;}"""
        for name, (w, h) in (("tablet 768x1024", (768, 1024)), ("phone 390x844", (390, 844))):
            for dpr in (1, 1.25, 1.5, 2):
                with self.subTest(viewport=name, scale=dpr):
                    page = self.view(device(w, h, dpr=dpr))
                    if name.startswith("phone"):
                        self.disclose(page)
                    page.fill("#search-q", "H1080")
                    page.evaluate("document.activeElement.blur()")
                    settle(page)
                    self.assertLessEqual(abs(page.evaluate(layout)), 0.1)
                    if name.startswith("tablet"):
                        caps = self.inks(page, dpr, typed="H1080", write="H1080")
                        self.assertLessEqual(abs(caps["field"] - caps["other"]), 1 / dpr + 0.01, caps)


class SearchTouch(SearchBase):
    """Coarse pointers: targets and text size."""

    def test_every_search_target_answers_44px_and_the_field_types_at_16px(self):
        """On each touch viewport, with a query: the field, previous, next and close each answer at least 44x44px
        while drawn smaller - the three buttons at one height, the field's inside (34px in a bar, the 36px row on a
        phone) - and the input's text is 16px so that focusing it does not zoom the page."""
        for name, dev in list(BARS.items())[1:] + list(PHONES.items()):
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.search(page, "tide")
                self.assertEqual(page.evaluate(MISSES_44, "#search-field,#search-prev,#search-next,#search-close"), [])
                drawn = page.evaluate(
                    "['#search-prev','#search-next','#search-close'].map(s=>document.querySelector(s).getBoundingClientRect().height)"
                )
                self.assertEqual(drawn, [36 if name in PHONES else 34] * 3)
                self.assertEqual(
                    page.evaluate("getComputedStyle(document.querySelector('#search-q')).fontSize"), "16px"
                )


class SearchPhone(SearchBase):
    """The phone band (docs/handbook/viewer.md §본문 검색): no field at rest, a row that replaces the bottom bar while
    searching."""

    @staticmethod
    def free(page):
        """The PDF's visible height: from under the stripe to the top of whatever stands at the screen's bottom (the
        sheet, or the search row over it)."""
        return page.evaluate(
            """() => {const top = document.querySelector('#brand-stripe').getBoundingClientRect().bottom, nav = document.querySelector('#doc-nav');
              const tops = [document.querySelector('#right').getBoundingClientRect().top]; if (nav.getClientRects().length) tops.push(nav.getBoundingClientRect().top);
              return Math.min(...tops) - top;}"""
        )

    def test_at_rest_the_phone_shows_no_field_and_gives_up_no_height(self):
        """On each phone the nav bar and the field are not drawn, and the PDF's visible height is the screen less the
        4px stripe and the 53px sheet bar - what it is without the search."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                self.assertFalse(page.is_visible("#doc-nav"))
                self.assertFalse(page.is_visible("#search-q"))
                self.assertEqual(self.free(page), dev["viewport"]["height"] - 4 - 53)

    def test_the_navigation_sheets_row_discloses_the_field_in_place_of_the_bar(self):
        """The navigation sheet's [본문 검색] row closes the sheet and puts the field with a close button where the bar
        was - same height, so the PDF keeps its visible height - with the focus in the field; a query adds one 36px
        row, 8px above it, that holds the count and the two arrows and nothing else, both rows inside the 12px edge
        lines with nothing spilling sideways; [검색 닫기] brings the bar back and the focus to the position button."""
        for name, dev in PHONES.items():
            with self.subTest(viewport=name):
                page = self.view(dev)
                rest = self.free(page)
                self.disclose(page)
                self.assertEqual(self.free(page), rest)
                self.assertTrue(page.is_visible("#search-close"))
                self.assertFalse(page.is_visible("#search-prev"))
                self.assertFalse(
                    page.evaluate(
                        "(()=>{const b=document.querySelector('#btn-pos').getBoundingClientRect(); return document.elementFromPoint(b.left+b.width/2,b.top+b.height/2)===document.querySelector('#btn-pos');})()"
                    )
                )
                self.search(page, "tide")
                self.assertEqual(self.free(page), rest - 44)
                row = page.evaluate(
                    """() => {const R = s => document.querySelector(s).getBoundingClientRect(), f = R('#search-field'), n = R('#search-nav'), c = R('#search-close');
                      return {above: n.bottom <= f.top + 0.01, h: n.height, shown: [...document.querySelector('#search-nav').children].filter(e => e.getClientRects().length).map(e => e.id),
                        field: f.height, closeRow: Math.abs((c.top + c.bottom) / 2 - (f.top + f.bottom) / 2),
                        edges: [f.left, innerWidth - c.right, n.left, innerWidth - n.right], spill: document.documentElement.scrollWidth - innerWidth};}"""
                )
                self.assertEqual(
                    row,
                    {
                        "above": True,
                        "h": 36,
                        "shown": ["search-count", "search-prev", "search-next"],
                        "field": 36,
                        "closeRow": 0,
                        "edges": [12, 12, 12, 12],  # both rows start and end on the phone's 12px edge line
                        "spill": 0,
                    },
                )
                page.tap("#search-close")
                settle(page)
                self.assertFalse(page.is_visible("#doc-nav"))
                self.assertEqual(self.free(page), rest)
                self.assertEqual(page.evaluate("document.activeElement.id"), "btn-pos")

    def test_an_empty_row_folds_when_the_page_is_tapped_and_a_row_with_a_query_stays(self):
        """With nothing typed, a tap on the PDF folds the search row away and the bar is back; with a query the row
        stays through a tap on the PDF, so the hits can be read with the arrows at hand."""
        page = self.view(PHONES["phone 390x844"])
        self.disclose(page)
        page.touchscreen.tap(195, 300)
        settle(page)
        self.assertFalse(page.is_visible("#doc-nav"))
        self.assertTrue(page.is_visible("#btn-pos"))
        self.search(page, "tide")
        page.touchscreen.tap(195, 300)
        settle(page)
        self.assertTrue(page.is_visible("#search-q"))
        self.assertEqual(self.count(page), "1/7")

    def test_a_hit_is_shown_above_the_search_row(self):
        """Stepping to a hit near a page's foot scrolls it into the part of the PDF the search row does not cover."""
        page = self.view(PHONES["phone 390x844"])
        self.search(page, "ebb")
        cur = self.current(page)
        self.assertEqual((cur["page"], [b["shows"] for b in cur["boxes"]]), (3, [True]))
        self.assertLessEqual(
            cur["boxes"][0]["bottom"], page.evaluate("document.querySelector('#doc-nav').getBoundingClientRect().top")
        )

    def test_a_phone_draft_survives_a_search(self):
        """With a region picked by a long press and a note half written in the sheet's composer, a search opened from
        the navigation sheet and closed again leaves the composer open with the note as typed and the sheet up."""
        page = self.view(PHONES["phone 390x844"])
        cdp = page.context.new_cdp_session(page)
        point = [{"x": 150, "y": 250}]
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": point})
        page.wait_for_selector("#composer", state="visible", timeout=8000)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_function("document.querySelector('#c-loc').textContent.trim()!==''", timeout=8000)
        settle(page)
        page.fill("#note", "휴대폰 초안")
        page.evaluate("document.activeElement.blur()")
        settle(page)
        self.search(page, "tide")
        page.tap("#search-close")
        settle(page)
        self.assertEqual(page.input_value("#note"), "휴대폰 초안")
        self.assertTrue(page.is_visible("#composer"))
        self.assertTrue(page.is_visible("#note"))


class SearchAccessible(SearchBase):
    """Names, roles and what is announced."""

    def test_the_search_is_a_landmark_with_a_labelled_field_and_named_buttons(self):
        """A search landmark named 본문 검색 holds a search box of the same name - from a real <label>, and with nothing
        else in its name - and the previous, next and close buttons carry their names; in English every name is
        English."""
        for lang, names in (
            ("ko", ["본문 검색", "이전 결과", "다음 결과", "검색 닫기"]),
            ("en", ["Search the text", "Previous result", "Next result", "Close search"]),
        ):
            with self.subTest(lang=lang):
                page = self.view(lang=lang)
                self.search(page, "tide")
                landmark = page.get_by_role("search", name=names[0], exact=True)
                self.assertEqual(landmark.count(), 1)
                self.assertEqual(landmark.get_by_role("searchbox", name=names[0], exact=True).count(), 1)
                for name in names[1:]:
                    self.assertEqual(landmark.get_by_role("button", name=name, exact=True).count(), 1, name)
                self.assertEqual(page.evaluate("document.querySelector('#search-q').labels.length"), 1)

    def test_the_result_is_announced_politely_once_it_is_known(self):
        """A polite live region says the place among the hits and the page once every page has been read, the new
        place after a step, and that there is none for a query without hits; the count on screen is not read twice."""
        page = self.view()
        live = page.evaluate(
            "(()=>{const e=document.querySelector('#search-sr'); return [e.getAttribute('role'),e.getAttribute('aria-live'),document.querySelector('#search-count').getAttribute('aria-hidden')];})()"
        )
        self.assertEqual(live, ["status", "polite", "true"])
        self.search(page, "tide")
        self.assertEqual(self.said(page), "7개 중 1번째 · 1쪽")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        self.assertEqual(self.said(page), "7개 중 4번째 · 2쪽")
        self.search(page, "nothing here")
        self.assertEqual(self.said(page), "결과 없음")
        english = self.view(lang="en")
        self.search(english, "tide")
        self.assertEqual(self.said(english), "1 of 7 · page 1")


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
