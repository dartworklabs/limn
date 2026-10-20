"""Real two-column manuscripts and what the source says the search must find in them.

Each case is a LaTeX document this repository owns, built by latexmk in the CI `tex` job, plus queries whose
answers are read off the source rather than computed from the viewer's rules: a sentence written as one sentence
must be findable across the line break TeX happens to put in it, and two cells of a table must not join into a
phrase nobody wrote. So the expectations stay an independent oracle even when the rules change.

Most documents use no packages at all: the CI `tex` job installs texlive-latex-base, texlive-plain-generic and
texlive-xetex, so a `\\usepackage` outside that set would make the corpus unbuildable there. A case that needs a
publisher's document class names the file in `cls`, and the test skips it where that file is not installed (and
fails under LIMN_TEST_REQUIRE_TEX=1, which the `tex` job sets, since there it is installed on purpose).

A `spans` query must be found *and* its hit must lie on more than one line. Without that second half a query TeX
happened to fit on one line would pass while testing nothing, so each is written longer than a column holds -
except one, which is written to cross a hyphen TeX puts inside a word and says so where it stands.

An `absent` query must be a phrase the rules could produce if they were wrong: written in the order the page is
read in, between two things that are both still in the document. `present` holds the second half of that - the
elements the `absent` queries are about - because a query whose text has gone from the document passes while
testing nothing. `rows` keeps each document set in two columns on its first page.

What cannot be asked for here is the limitation itself. On a page where a line wider than the column stands
within one line pitch of body text, the shipped rule stops joining that body's lines on purpose
(docs/handbook/viewer.md §찾는 규칙, ADR-0017). Writing that as `spans` would demand the rule change; writing it
as `absent` would make the oracle copy the rule. So the corpus holds the geometry around that shape and leaves
the shape's own joins out.
"""

# A plain two-column body with a float caption at the foot of a column. What it tests is the ordinary case: body
# text in a real two-column measure joins across whatever line breaks TeX chooses, and the caption below does not
# fuse into the paragraph above it. A `table` without a star is one column wide and `[b]` sends it to the foot of
# the column, so the caption stands in a block of its own, a long way under the body - this document does NOT
# hold the shape ADR-0017 measured, and no document here can hold it as a `spans` expectation: on a page where a
# page-wide line stands within one line pitch of body text, the shipped rule loses those joins on purpose. STAMP
# holds that geometry with the wide line kept clear of the prose, which is what lets it test an edge rule.
BODY = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that a few paragraphs fill the left
% column and spill into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\section{Tidal observations of the harbour}
The keeper of the quay reads the gauge twice a day and sends the record
on by the evening post, because the harbour trust wants the tide logged
before the boats are iced and the hull is washed down for the winter.

A second paragraph carries on about the same gauge, which the keeper has
read since the year the station house was built, and which the trust has
never once replaced in all the seasons since then, through storms that
took the roof off the shed and a winter that froze the inner basin
solid for a fortnight.

The third paragraph is here to fill the first column and spill into the
second, because a document that fits in one column is not set in two and
would let this corpus pass without ever testing a two-column page. It
therefore runs on at some length about the quay, the gauge, the keeper
and the weather, none of which matters except that the words continue.

A fourth paragraph continues in the same vein so that the second column
also carries ordinary running text of its own above the float that the
table below sends to the foot of the column.

\begin{table}[b]
\begin{tabular}{l}
\end{tabular}
\caption{The gauge and its housing by the door of the station house}
\end{table}

\noindent A closing paragraph ends the running text, and the caption of
the float stands below it with a clear run of white paper between the
two, which is where this class puts a bottom float.
\end{document}
"""

# Shapes that must not join. Page 1 holds a nomenclature list inside a column and ordinary prose, so a positive
# case stands beside the negative ones; the page-wide table is a `table*` float and TeX puts it alone on page 2.
# Joining any cell pair would highlight a phrase that is in no sentence of the source - the failure the project
# ranks as worse than a missed one.
TABLES = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that a few paragraphs fill the left
% column and spill into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\section{Nomenclature}
\begin{tabular}{ll}
single stage & with \\
thermal conductivity & watt per metre kelvin \\
expansion valve & heat exchanger \\
\end{tabular}

\noindent The paragraph after the list is ordinary running text, and it
wraps across a line break of its own so the corpus holds a positive case
on the same page as the negative ones, which is what keeps a rule that
simply stopped joining anything from passing this file.

The second paragraph fills the rest of the first column and spills into
the second, so the page is genuinely set in two columns rather than
holding one short column and a great deal of white paper beside it.

A third paragraph continues past the column break and goes on long
enough that the right-hand column carries running text of its own, above
the table that the next block sets across both columns of the page.

A fourth paragraph is needed because the third ended just as the first
column filled, which left the right-hand column holding a single line
and the page only barely set in two columns at all.

A fifth paragraph therefore carries the text well into the right-hand
column, so that both halves of the page hold enough running lines for
the structural check to mean something about the layout.

\begin{table*}[t]
\begin{tabular}{lll}
operating point & power optimization & hot water tank \\
metabolic rate & air temperature & clothing insulation \\
\end{tabular}
\caption{A table set across both columns}
\end{table*}
\end{document}
"""

# A list whose entries each take a whole line, standing next to ordinary full-width prose. The shipped rule
# holds every entry to the right edge the full-column lines set, and no entry reaches it, so a rule that
# loosened the edge gate would join one entry to the next into a phrase no sentence of the source contains.
# Candidate D, the rule ADR-0017 rejected, is not what this catches: the entries share their block with the
# prose, so dropping the one over-wide line leaves the edge where it was (measured - STAMP is the case that
# catches D). Cell pairs *within* one row test something else again: a row cut at a wide gap is two pieces at
# the same height, so no join rule can put them together, and it is the cut itself they hold (see TABLES).
LIST = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that a few paragraphs fill the left
% column and spill into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\section{Symbols of the station}
The list below gives one symbol to a line, which is how a nomenclature
block is usually set, and it stands directly against the paragraph that
follows it without a blank line of its own in between.

\noindent
\begin{tabular}{l}
single stage \\
with \\
thermal conductivity \\
watt per metre kelvin \\
expansion valve \\
heat exchanger \\
\end{tabular}
The paragraph after the list is ordinary running text at the full width
of the column, so the block holds both the short entries above and a
long line, which is the arrangement that decides the measure.

A second paragraph keeps the page in two columns by carrying the text
past the column break, and it says nothing that any query below looks
for, beyond filling the lines it fills.

A third paragraph finishes the page so that the right-hand column holds
running text of its own rather than a single stranded line above a great
deal of white paper.

A fourth paragraph is here only to give the right-hand column the few
further lines that the structural check asks for, so that neither half
of the page is thin enough to make the check meaningless.
\end{document}
"""


# The geometry that decides an edge rule, built on purpose. A list of short entries stands on its own, a blank
# run of vertical space away from the prose above and below, with one line wider than the column immediately
# under it - the shape a publisher's download stamp makes at the foot of a page. The block is therefore mostly
# short lines plus one wide one, which is where the shipped rule and the rule ADR-0017 rejected disagree: the
# shipped rule holds every entry to the wide line's right edge, so none reaches it; a rule that drops the wide
# line from the measure puts the edge on the longest entry, which then joins the entry below it.
STAMP = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that a few paragraphs fill the left
% column and spill into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\section{Readings at the station}
The opening paragraph runs at the full width of the column and is kept a
clear run of vertical space away from the list below, so that the list
and the wide line under it make a block of their own.

\vspace{30pt}
\noindent
\begin{tabular}{l}
single stage \\
with \\
thermal conductivity \\
expansion valve \\
heat exchanger \\
\end{tabular}

\noindent\makebox[\textwidth][l]{\footnotesize Authorized licensed use limited to the harbour trust. Downloaded in the winter of the year.}

\vspace{30pt}
\noindent The closing paragraph is again full-column running text, a
clear space below the wide line, and it carries on past the column
break so the right-hand column holds lines of its own.

A further paragraph gives the right-hand column the rest of the lines it
needs, and says nothing that any query looks for beyond filling them.

A last paragraph is here for the same reason, so that neither half of
the page is thin enough to make the structural check meaningless, and
then the document ends.
\end{document}
"""


# A page of a publisher's own class, set the way the class sets it rather than the way the other documents here
# ask a plain `article` to. IEEEtran gives the narrow journal column, a page-wide title and author block over the
# two columns, a 9pt abstract, an index-terms line, a footnote rule and the identifier line it prints at the foot
# of the first page. The queries say what the source means in that setting: sentences the class's own line breaks
# cut - including one TeX hyphenates - must still be findable, and the furniture around the body must not fuse
# into phrases the source never wrote. The class is not in the base TeX install, so this case names it in `cls`.
IEEE = r"""\documentclass[journal]{IEEEtran}
% One paragraph of filler, repeated below, is what fills both columns of a real journal page to the bottom. A
% page of this class holds about eighty lines, and writing eighty lines of distinct prose would say nothing the
% repetition does not; what the queries need is that the columns are full and the line breaks are the class's.
\newcommand{\filler}{A paragraph of ordinary running text carries on about the
quay, the gauge and the weather, so that the columns of this page fill to the
bottom the way a journal page fills, and none of it matters except that the
words continue to the foot of the second column.\par}
\begin{document}
\title{Tidal observations of the harbour and the gauge beside the station house}
\author{Alice~Keeper and Bob~Quay%
\thanks{The authors are with the harbour trust of the northern basin.}}
\IEEEpubid{0000--0000/00\$00.00~\copyright~2026 Harbour Trust}
\maketitle

\begin{abstract}
The keeper of the quay reads the gauge twice a day and sends the record on by
the evening post, because the trust wants the tide logged before the boats are
iced and the hull is washed down for the winter.
\end{abstract}

\begin{IEEEkeywords}
Gauge, harbour, station house, tide.
\end{IEEEkeywords}

\section{Introduction}
\IEEEPARstart{T}{he} gauge by the door of the station house has been read since
the year the roof was first slated, and the trust has never once replaced it in
all the seasons since then, through storms that took the roof off the shed and a
winter that froze the inner basin solid for a fortnight.

The meteorological instrumentation of the station is inspected every spring by
the representatives of the harbour trust, who copy the extraordinarily
uninterrupted readings of the gauge into a ledger of their own.

\filler\filler\filler
\IEEEpubidadjcol
\filler\filler\filler\filler\filler\filler\filler\filler\filler\filler
\end{document}
"""


# Display formulas between paragraphs, and a column break. Each formula stands on a row of its own with its
# number against the right margin, which is a gap wider than the font, so the row is cut there and neither piece
# joins anything - the same rule that keeps a table's cells apart. The queries hold that: the sentence before a
# formula must not run into it, and the last line of the left column must not run into the first of the right.
EQUATIONS = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that a few paragraphs fill the left
% column and spill into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\section{The height of the tide}
The keeper of the quay reads the gauge twice a day and writes the height
of the water in the ledger of the station house, where the trust keeps
the record of the winter.

\begin{equation}
h = a + b t + c t t
\end{equation}

\noindent The paragraph after the display is ordinary running text again,
and it carries on about the ledger and the gauge so that the column holds
lines of its own below the formula.

\begin{equation}
w = p q + r
\end{equation}

\noindent A second paragraph after a second display fills the rest of the
first column and spills into the second, so that the page is genuinely set
in two columns rather than one.

A third paragraph gives the right-hand column running text of its own, and
says nothing that any query looks for beyond filling the lines it fills so
that neither half of the page is thin.

A fourth paragraph is here for the same reason, so that the structural
check has lines enough to count on both sides of the text area.

A fifth paragraph closes the page, and leaves the right-hand column with a
few lines more than the check asks for, and then the document ends.
\end{document}
"""


# A table of contents, whose entries are the one shape in this corpus that reaches both edges of the column: the
# number at the left margin, the page number at the right, and dot leaders or white between them. The leaders are
# a gap wider than the font, so each entry is cut into pieces that join nothing. The queries hold the heading
# apart from the first entry, and one entry apart from the next; an entry's own title and page number are not
# asked for, since the gap between them is the one a query does not cross by design.
CONTENTS = r"""\documentclass[twocolumn,10pt]{article}
\pagestyle{empty}
% A short text block, set with a TeX primitive rather than a package, so that the contents fill the left column
% and the body spills into the right. Without it a document this length is set in one column and tests nothing.
\textheight=220pt
\begin{document}
\tableofcontents

\section{Tidal observations of the harbour}
\subsection{The gauge beside the station house}
The keeper of the quay reads the gauge twice a day and sends the record
on by the evening post, because the harbour trust wants the tide logged
before the boats are iced.
\subsection{The ledger of the winter readings}
A second paragraph carries on about the same gauge, which the keeper has
read since the year the station house was built.
\section{The weather of the inner basin}
\subsection{Storms that took the roof off the shed}
The third paragraph is here to fill the first column and spill into the
second, because a document that fits in one column is not set in two.
\subsection{The fortnight the basin froze solid}
A fourth paragraph continues in the same vein so that the second column
also carries ordinary running text of its own.
\end{document}
"""


# Each case: the document, the least number of lines each half of the first page's text area must hold (so that
# page really is set in two columns), queries that must be found across a line break, queries that must find
# nothing, and the elements those queries are about, which must still be found somewhere. A case whose document
# needs a class outside the base TeX install names that file in `cls`.
CASES = (
    {
        "name": "two-column body with a float caption at the foot of a column",
        "tex": BODY,
        "rows": 8,
        "spans": (
            "sends the record on by the evening post, because the harbour trust",
            "wants the tide logged before the boats are iced and the hull",
            "the same gauge, which the keeper has read since the year the station",
            "fill the first column and spill into the second, because a document",
        ),
        "absent": (
            # The order is the order the page is read in: the closing paragraph first, the float's caption after
            # it. Held apart by the pitch (the float is a long way below) and by the short line that ends the
            # paragraph. A query written the other way round could never match, whatever the rules did.
            "where this class puts a bottom float. Table 1",
            # the section title into the first body line: held by the edges, the plain flag, the pitch and the size
            "Tidal observations of the harbour The keeper of the quay",
        ),
        "present": (
            "The gauge and its housing by the door",  # the caption itself: without it the query above is vacuous
        ),
    },
    {
        "name": "short entries under a line wider than the column",
        "tex": STAMP,
        "rows": 8,
        "spans": (
            "opening paragraph runs at the full width of the column and is kept",
            "closing paragraph is again full-column running text, a clear space",
        ),
        "absent": (
            # Consecutive entries of the list, each a whole line of its own. These four are the edge-rule test of
            # this corpus: the only thing between them is that no entry reaches the block's right edge, which the
            # wide line below set. They are what catches the rule ADR-0017 rejected.
            "single stage with",
            "with thermal conductivity",
            "thermal conductivity expansion valve",
            "expansion valve heat exchanger",
            # The last entry into the wide line below it. The stamp is \footnotesize, so the size gate holds this
            # pair as well as the edges - it is a weaker test of the edge rule than the four above.
            "heat exchanger Authorized licensed use limited",
        ),
        "present": (
            "Authorized licensed use limited",  # the wide line that sets the block's edge
            "thermal conductivity",  # the entries
        ),
    },
    {
        "name": "a list whose entries each take a whole line",
        "tex": LIST,
        "rows": 8,
        "spans": (
            "list below gives one symbol to a line, which is how a nomenclature",
            "ordinary running text at the full width of the column, so the block holds",
        ),
        "absent": (
            # Consecutive entries of the list: each is a whole line, and the edges are what stands between them -
            # loosen the edge gate and all five join. Candidate D, the rule ADR-0017 rejected, does NOT join
            # them: the entries share a block with the full-column prose above, so dropping the one over-wide
            # line does not shrink the edge onto the longest entry. STAMP is the case that catches D.
            "single stage with",
            "with thermal conductivity",
            "thermal conductivity watt per metre kelvin",
            "watt per metre kelvin expansion valve",
            "expansion valve heat exchanger",
            # The last entry into the paragraph that follows it. `tabular` is a box inside the paragraph, so that
            # paragraph's first line sits beside the list and above its last entry: the pitch gate's lower bound
            # holds this pair, not the edges.
            "heat exchanger The paragraph after the list",
        ),
        "present": (
            "watt per metre kelvin",  # the entries the queries above are about
            "The paragraph after the list",
        ),
    },
    {
        "name": "a journal page set by the publisher's own class",
        "tex": IEEE,
        "cls": "IEEEtran.cls",
        "rows": 8,
        "spans": (
            # the 9pt abstract, the body text under the drop cap, and the filler that fills the columns
            "sends the record on by the evening post, because the trust wants",
            "never once replaced it in all the seasons since then, through storms",
            # A line this class's column width makes TeX end with a hyphen ("is in-" / "spected"). This one is
            # shorter than the column holds on purpose: what it has to cross is the hyphen, not the line's end.
            "instrumentation of the station is inspected every spring",
            "the columns of this page fill to the bottom the way a journal page",
        ),
        "absent": (
            # The class's front matter against its neighbours. Each of these is held by more than the edges, which
            # is worth knowing when reading what this case proves: the title into the author line by the pitch
            # (23.3pt against a 23.9pt title) and the size, the abstract into the index terms by the pitch, the
            # index terms into the section title by the pitch and the size.
            "beside the station house Alice Keeper",
            "washed down for the winter. Index Terms",
            "station house, tide. I. Introduction",
            # A paragraph's short last line into the first line of the paragraph after it - this one the edges
            # hold on their own, and it is what this case contributes to the edge-rule side.
            "to the foot of the second column. A paragraph of ordinary",
        ),
        "present": (
            "Index Terms",  # the front matter the queries above are about
            "Alice Keeper",
        ),
    },
    {
        "name": "display formulas between paragraphs",
        "tex": EQUATIONS,
        "rows": 8,
        "spans": (
            "writes the height of the water in the ledger of the station house",
            "carries on about the ledger and the gauge so that the column holds",
        ),
        "absent": (
            # A paragraph's last line into the formula standing below it. Three things hold this pair: the row of
            # the formula is cut at the gap before its number and so is not plain, the paragraph's last line is
            # short of the block's right edge, and the gap down to the formula is wider than the pitch allows.
            # Take any two away and it still does not join, which is what makes it a weak test of any one of them.
            "the record of the winter. h =",
            "lines of its own below the formula. w =",
            # The left column's last line into the right column's first. The right column's first line is near the
            # top of the page, so this pair is held by the pitch gate's lower bound: the next line is above.
            "rather than one. A third paragraph gives",
        ),
        "present": (
            "h = a",  # the formulas themselves
            "w = pq",
        ),
    },
    {
        "name": "a table of contents with dot leaders",
        "tex": CONTENTS,
        "rows": 8,
        "spans": (
            "reads the gauge twice a day and sends the record on by the evening",
            "the same gauge, which the keeper has read since the year the station",
        ),
        "absent": (
            # The heading into the first entry (held by the plain flag, the pitch and the size), and one entry
            # into the next: the page number of the first, then the number and title of the second (the plain flag
            # and the pitch). An entry's own title and page number are not asked for - the leaders between them
            # are a gap wider than the font, and not carrying a query over such a gap is a limitation the
            # handbook records, not something to require.
            "Contents 1 Tidal observations of the harbour",
            "1 2 The weather of the inner basin",
        ),
        "present": (
            "Contents",  # the contents themselves, and an entry the query above reads
            "The weather of the inner basin",
        ),
    },
    {
        "name": "nomenclature list and a table across both columns",
        "tex": TABLES,
        "rows": 8,
        "spans": (
            "list is ordinary running text, and it wraps across a line break",
            "fills the rest of the first column and spills into the second",
        ),
        "absent": (
            # Two cells of ONE row. No change to the join rules can make these match - the pitch gate's lower
            # bound needs the next line below, and two pieces of one row are at the same height. What they test
            # is the other rule: searchLines cuts a row at a gap wider than the font, and if that cut ever went
            # away the two cells would be one line and the phrase would be found inside it. They are the only
            # thing in this corpus that notices, and issue #231 left that cut in on purpose.
            "single stage with",
            "expansion valve heat exchanger",
            "operating point power optimization",
            "power optimization hot water tank",
            "metabolic rate air temperature",
            # Across a row end - a cell of one row into a cell of the next. These are the join side: the edges
            # and the plain flag hold them.
            "with thermal conductivity",
            "watt per metre kelvin expansion valve",
            "hot water tank metabolic rate",
        ),
        "present": (
            # The page-wide table is a float and lands on a page of its own. Without these the eight queries
            # above would all pass on a document that had quietly stopped setting the table at all.
            "operating point",
            "metabolic rate",
            "single stage",
        ),
    },
)
