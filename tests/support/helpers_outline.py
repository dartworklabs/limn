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
