"""A PDF whose bookmarks are given as a tree, for the outline tests: the real PDF.js reads it, so what the viewer does with a
long or a deep outline is tested on the bytes a PDF carries. Test modules import fixtures only from helpers modules, never
from one another (tests/support/helpers.py).

A node is (title, page index from 0, children). outline_pdf() writes every bookmark with an explicit XYZ destination at
the top of its page, so the viewer's entries have a place on the page (frac) like a LaTeX manuscript's.
"""

from typing import TypeAlias

Node: TypeAlias = tuple[str, int, list["Node"]]


def grouped_tree(n: int, pages: int, group: int = 10) -> list[Node]:
    """n bookmarks over `pages` pages in document order: a heading `S<k>` followed by up to `group` children `S<k>.<j>`,
    then the next heading - so the outline has two levels and exactly n entries."""
    tree: list[Node] = []
    for i in range(n):
        page = min(pages - 1, i * pages // n)
        if i % (group + 1) == 0:
            tree.append(("S%d" % (len(tree) + 1), page, []))
        else:
            head = tree[-1]
            head[2].append(("S%d.%d" % (len(tree), len(head[2]) + 1), page, []))
    return tree


def chain_tree(levels: int, page: int = 0) -> list[Node]:
    """One bookmark nested inside the one above it, `levels` deep: 'L1' at the top level down to 'L<levels>'."""
    node: Node = ("L%d" % levels, page, [])
    for level in range(levels - 1, 0, -1):
        node = ("L%d" % level, page, [node])
    return [node]


def _hex(title: str) -> bytes:
    """A PDF text string: UTF-16BE with a byte order mark, as hex."""
    return b"<FEFF" + title.encode("utf-16-be").hex().upper().encode() + b">"


def outline_pdf(pages: int, tree: list[Node]) -> bytes:
    """A valid PDF of `pages` A5-ish pages (pdf.js renders it) with the bookmarks `tree`, each pointing at its page."""
    objs: list[bytes] = [b"", b"", b""]  # 1 catalog, 2 page tree, 3 outline root: filled below
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 4
    page_ids = []
    for p in range(pages):
        stream = b"BT /F1 24 Tf 40 200 Td (Page %d) Tj ET" % (p + 1)
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 595] /Contents %d 0 R"
            b" /Resources << /Font << /F1 4 0 R >> >> >>" % len(objs)
        )
        page_ids.append(len(objs))
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % i for i in page_ids) + b"] /Count %d >>" % pages

    def emit(nodes: list[Node], parent: int) -> tuple[int, int, int]:
        """The bookmark objects of nodes under object `parent`: (first, last, how many bookmarks they and theirs are)."""
        ids, total = [], 0
        for _ in nodes:
            objs.append(b"")
            ids.append(len(objs))
        for i, (title, page, kids) in enumerate(nodes):
            first, last, below = emit(kids, ids[i]) if kids else (0, 0, 0)
            body = (
                b"<< /Title "
                + _hex(title)
                + b" /Parent %d 0 R /Dest [%d 0 R /XYZ 20 %d null]"
                % (
                    parent,
                    page_ids[page],
                    560 - (total % 7) * 40,
                )
            )
            if kids:
                body += b" /First %d 0 R /Last %d 0 R /Count %d" % (first, last, below)
            if i > 0:
                body += b" /Prev %d 0 R" % ids[i - 1]
            if i + 1 < len(ids):
                body += b" /Next %d 0 R" % ids[i + 1]
            objs[ids[i] - 1] = body + b" >>"
            total += 1 + below
        return ids[0], ids[-1], total

    first, last, count = emit(tree, 3)
    objs[2] = b"<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (first, last, count)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R /Outlines 3 0 R >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# The open navigation sheet against every edge a row can be cut at (docs/handbook/viewer.md §모바일 레이아웃): the head's bottom (the
# search row is in the head) and the sheet's bottom for the documents, the view, the page field and the outline's filter row, and for
# the rows of the page list and of the outline - each a list that scrolls on its own - that list's top and bottom as well. `cut` names
# the rows an edge runs through; `current` whether the outline's current row shows whole in its list; `doc` where the current
# document's row is: 'whole' and drawn on top (pinned over a row a step of the sheet brought under it), 'under' the head wholly,
# 'cut', or 'none' with one document; the sheet's and the outline list's scrollTop; the focus.
SHEET_ROWS = """() => {const d = document.querySelector('#nav-sheet'), R = e => e.getBoundingClientRect(), vis = e => !!e && e.getClientRects().length > 0;
  const head = R(d.querySelector('.ns-head')).bottom, D = R(d), list = d.querySelector('#ns-outline-items'), L = R(list), pages = d.querySelector('#ns-pages'), P = R(pages);
  const cut = [], check = (e, name, edges) => {const r = R(e);
    if (r.height > 0) for (const y of edges) if (r.top < y - 0.5 && r.bottom > y + 0.5) cut.push(name + '@' + Math.round(y));};
  d.querySelectorAll('#ns-docs .dm-item').forEach((e, i) => vis(e) && check(e, 'doc' + i, [head, D.bottom]));
  for (const s of ['#ns-view', '#ns-page', '#ns-outline .ns-oh']) {const e = d.querySelector(s); if (vis(e)) check(e, s, [head, D.bottom]);}
  const inside = (e, B) => {const r = R(e); return vis(e) && r.bottom > B.top && r.top < B.bottom;};
  [...pages.children].forEach((e, i) => inside(e, P) && check(e, 'page' + i, [head, D.bottom, P.top, P.bottom]));
  [...list.querySelectorAll(':scope>button')].forEach(e => inside(e, L) && check(e, 'row' + e.dataset.index, [head, D.bottom, L.top, L.bottom]));
  const c = list.querySelector('.ol-active'), C = c ? R(c) : null, on = d.querySelector('.dm-item.on');
  let doc = 'none';
  if (vis(on)) {const O = R(on), at = document.elementFromPoint(O.left + 8, (O.top + O.bottom) / 2);
    doc = O.bottom <= head + 0.5 ? 'under' : O.top >= head - 0.5 && O.bottom <= D.bottom + 0.5 && !!at && at.closest('.dm-item') === on ? 'whole' : 'cut';}
  const a = document.activeElement;
  return {cut, index: c ? +c.dataset.index : null, doc, sheet: d.scrollTop, list: list.scrollTop, focus: a.id || a.tagName,
    current: !!C && C.top >= Math.max(head, L.top) - 0.5 && C.bottom <= Math.min(D.bottom, L.bottom) + 0.5,
    middle: C ? Math.abs((C.top + C.bottom) / 2 - (L.top + L.bottom) / 2) : null, rowH: C ? C.height : null};}"""
