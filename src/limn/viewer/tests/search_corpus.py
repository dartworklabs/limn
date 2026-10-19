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
happened to fit on one line would pass while testing nothing, so each is written longer than a column holds.
Each document is also long enough to fill both columns; `rows` keeps it that way, since a document that quietly
stopped being set in two columns would pass a weaker corpus.
"""

# A plain two-column body with a page-wide caption standing right under a paragraph. That is the shape ADR-0017
# measured: the caption joins the body's block and gives it the width of both columns, so the body's own line
# breaks stop joining. The queries below say what the source means regardless of that.
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
also carries ordinary running text above the caption, which the table
below places across the full width of the page.

\begin{table}[b]
\begin{tabular}{l}
\end{tabular}
\caption{The gauge and its housing by the door of the station house}
\end{table}

\noindent A closing paragraph stands under the caption so that the caption
falls within one line pitch of body text, which is the arrangement the
handbook records as a limitation of the block rule.
\end{document}
"""

# Shapes that must not join. A two-column nomenclature list, a page-wide table whose cells are one phrase each,
# and ordinary prose on the same page as a positive case. Joining any cell pair would highlight a phrase that is
# in no sentence of the source - the failure the project ranks as worse than a missed one.
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

# A list whose entries each take a whole line, standing next to ordinary full-width prose. This is the shape
# that caught candidate D in ADR-0017: the block holds short entries and one full-column line, so the shipped
# rule holds every entry to the long line's right edge and none of them reaches it. A rule that drops the wide
# line from the measure shrinks the edge onto the longest entry, which then joins the entry below it into a
# phrase no sentence of the source contains. Cell pairs *within* one row cannot test this - a row cut at a wide
# gap is not plain, so no edge rule can ever join it.
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
# apart from the first entry and an entry's title apart from its own page number.
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


# Each case: the document, the least number of lines each half of the text area must hold (so the page really is
# set in two columns), queries that must be found across a line break, and queries that must find nothing. A case
# whose document needs a class outside the base TeX install names that file in `cls`.
CASES = (
    {
        "name": "two-column body with a page-wide caption",
        "tex": BODY,
        "rows": 8,
        "spans": (
            "sends the record on by the evening post, because the harbour trust",
            "wants the tide logged before the boats are iced and the hull",
            "the same gauge, which the keeper has read since the year the station",
            "fill the first column and spill into the second, because a document",
        ),
        "absent": (
            # across the caption into the paragraph below it, and from the section title into the body
            "housing by the door of the station house A closing paragraph",
            "Tidal observations of the harbour The keeper of the quay",
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
            # consecutive entries of the list, each a whole line of its own
            "single stage with",
            "with thermal conductivity",
            "thermal conductivity expansion valve",
            "expansion valve heat exchanger",
            # the last entry into the wide line below it
            "heat exchanger Authorized licensed use limited",
        ),
    },
    {
        "name": "a list whose entries each take a whole line",
        "tex": LIST,
        "rows": 8,
        "spans": (
            "list below gives one symbol to a line, which is how a nomenclature",
            "ordinary running text at the full width of the column",
        ),
        "absent": (
            # consecutive entries of the list: each is a whole line, so only the edge rule stands between them
            "single stage with",
            "with thermal conductivity",
            "thermal conductivity watt per metre kelvin",
            "watt per metre kelvin expansion valve",
            "expansion valve heat exchanger",
            # the last entry into the paragraph that follows it
            "heat exchanger The paragraph after the list",
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
            "all the seasons since then, through storms that took the roof",
            # a line this class's column width makes TeX end with a hyphen ("is in-" / "spected")
            "instrumentation of the station is inspected every spring",
            "the columns of this page fill to the bottom the way a journal page",
        ),
        "absent": (
            # the title into the author line below it, and the abstract and the index terms into their neighbours
            "beside the station house Alice Keeper",
            "washed down for the winter. Index Terms",
            "station house, tide. I. Introduction",
            # a paragraph's short last line into the first line of the paragraph after it
            "to the foot of the second column. A paragraph of ordinary",
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
            "the record of the winter. h =",  # a paragraph's last line into the formula standing below it
            "lines of its own below the formula. w =",
            "rather than one. A third paragraph gives",  # the left column's last line into the right column's first
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
            "Contents 1 Tidal observations of the harbour",  # the heading into the first entry
            # one entry into the next: the page number of the first and then the number and title of the second.
            # An entry's own title and page number are not asked for - the leaders between them are a gap wider
            # than the font, and a query does not cross such a gap, which the handbook records as a limitation.
            "1 2 The weather of the inner basin",
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
            "single stage with",  # two cells of one row
            "with thermal conductivity",  # across a row end
            "expansion valve heat exchanger",
            "watt per metre kelvin expansion valve",
            "operating point power optimization",
            "power optimization hot water tank",
            "metabolic rate air temperature",
            "hot water tank metabolic rate",
        ),
    },
)
