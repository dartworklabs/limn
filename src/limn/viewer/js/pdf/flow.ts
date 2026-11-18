// ------------------------------------------------ In-document text search (docs/handbook/viewer.md §본문 검색)
// The pages are canvases, so the browser's own find has nothing to find in them: the nav bar's field (#doc-search)
// searches the text of the PDF on screen instead. The text comes from PDF.js (a page's getTextContent), read page by
// page only once a query asks for it, after any page that is being drawn, and kept for as long as that document object
// is open (one per build). A hit lies within one page and may run over its line ends; its boxes - one for each line it
// lies on - are drawn over the page from the text items' geometry, in page fractions like a mark. No text layer is
// added - a drag on the page stays a region selection (pdf/flow-open.ts).
// - Matching: searchFold() on both sides (case, Unicode composition and width, runs of spaces, curly quotes and
//   dashes), then searchPattern(): a line break is a space or nothing, and a hyphen that ends a line may be left out.
// - Where the field is: in the nav bar when there is room (inline), folded to a magnifier when there is not (icon), and
//   on the phone - which has no nav bar - a row in place of the sheet's bar, opened from the navigation sheet (dock).
//   searchFit(). While the opened field lies over its neighbours in the bar they are taken off it whole (searchCover).
// - Ends with: Esc or [검색 닫기] (cleared, focus back), another document or a new build (searchClear, from
//   openVectorDocument), the changes view and a PDF that cannot be read (searchOffer hides it).
import { BAND, IS_MAC, MID_OVERLAY, SIDE_OPEN, imeKey } from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { VECTOR_PDF } from './state-vector.ts';
import { relayout, setSide, topAnchor } from '../layout/flow.ts';
import { $, $$, searchToPage, eventElement, findElement, findAll, focusedElement } from '../platform/dom.ts';
import { LAYOUT_BAND } from '../app/rules-tables.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
import { popoverFreeArea } from './view-area.ts';
import { pageSelection } from './state-seams.ts';

// The text as it is matched: Unicode NFKC (Hangul jamo composed, a letter and its combining mark joined, ligatures and
// full-width forms unfolded), lower case, curly quotes and dashes as ' " and -, soft hyphens and zero-width marks
// dropped, every run of white space one space; control characters dropped (the flow's break marks, searchFlow, never
// come from a page). Returns {t, at}: the folded text and, for each of its UTF-16 units, the index in the given text
// where the cluster it came from starts, then its length - so a match in t maps back to a run of the text. Pure.
function searchFold(text: string): { t: string; at: number[] } {
  const plain: Record<string, string> = {
      '\u2018': "'",
      '\u2019': "'",
      '\u201A': "'",
      '\u201C': '"',
      '\u201D': '"',
      '\u201E': '"',
    },
    folded: string[] = [],
    at: number[] = [];
  text = String(text);
  // A cluster: Hangul jamo that compose one syllable, or one character, each with the combining marks after it; or a
  // run of spaces.
  const cluster =
    /[\u1100-\u115F\uA960-\uA97C]+[\u1160-\u11A7\uD7B0-\uD7C6]*[\u11A8-\u11FF\uD7CB-\uD7FB]*\p{M}*|\s+|[^]\p{M}*/gu;
  for (const match of text.matchAll(cluster)) {
    const clusterText = /^\s+$/.test(match[0])
      ? ' '
      : match[0]
          .normalize('NFKC')
          .toLowerCase()
          .replace(/[\u0000-\u0008\u000E-\u001F\u007F\u00AD\u200B-\u200D\u2060\uFEFF]/g, '')
          .replace(/[\u2018\u2019\u201A\u201C\u201D\u201E]/g, (quote) => plain[quote])
          .replace(/[\u2010-\u2015\u2212]/g, '-')
          .replace(/\s+/g, ' ');
    for (let k = 0; k < clusterText.length; k++) {
      if (clusterText[k] === ' ' && folded[folded.length - 1] === ' ') continue;
      folded.push(clusterText[k]);
      at.push(match.index);
    }
  }
  at.push(text.length);
  return { t: folded.join(''), at };
}
// A page's lines from PDF.js text items: the items up to one marked hasEOL are one line, whatever their fonts, so a
// query may span them. A line that jumps across a gap wider than its font's size - a table's cells, a centred row, an
// \hfill, a line TeX had to stretch - is cut there into pieces that are never joined to each other or to the lines
// around them (searchJoin: only a line in one piece is plain). Each piece is {t, at, parts, end, plain, box}: its text
// folded (searchFold: at maps into the piece's unfolded text), per item with text the item's index i and where its text
// starts in the unfolded piece (from), the last character of its own text (end: a line-final hyphen is told from a dash
// by it), whether its line is in one piece, and where it stands in PDF units measured in its own direction - {x0, x1
// along the line, y: across it, up being +, size: font size, ang: the line's angle in whole degrees}, so a page set
// sideways reads as an upright one - or null for text that is skewed, mirrored or of mixed directions. Blank pieces are
// left out. Pure.
function searchLines(items: PdfTextItem[]): SearchLine[] {
  const rows: SearchRowItem[][] = [];
  let row: SearchRowItem[] = [];
  items.forEach((item, index) => {
    if (typeof item.str !== 'string') return;
    const matrix = Array.isArray(item.transform) && item.transform.length === 6 ? item.transform : [0, 0, 0, 0, 0, 0];
    const runScale = Math.hypot(matrix[0], matrix[1]),
      upScale = Math.hypot(matrix[2], matrix[3]),
      ok =
        runScale > 0 &&
        upScale > 0 &&
        matrix[0] * matrix[3] - matrix[1] * matrix[2] > 0 &&
        Math.abs(matrix[0] * matrix[2] + matrix[1] * matrix[3]) <= 1e-3 * runScale * upScale;
    // The line's direction and its up.
    const runX = ok ? matrix[0] / runScale : 1,
      runY = ok ? matrix[1] / runScale : 0,
      upX = ok ? matrix[2] / upScale : 0,
      upY = ok ? matrix[3] / upScale : 1;
    row.push({
      i: index,
      it: item,
      ok,
      x: matrix[4] * runX + matrix[5] * runY,
      w: Number(item.width) || 0,
      y: matrix[4] * upX + matrix[5] * upY,
      size: upScale,
      ang: Math.round((Math.atan2(runY, runX) * 180) / Math.PI),
    });
    if (item.hasEOL) {
      rows.push(row);
      row = [];
    }
  });
  if (row.length) rows.push(row);
  const lines: SearchLine[] = [];
  rows.forEach((rowItems) => {
    const mine: SearchLine[] = [];
    let raw = '',
      parts: { i: number; from: number }[] = [],
      pieceBox: (SearchPieceBox & { ok: boolean }) | null = null;
    const end = () => {
      if (raw.trim()) {
        const folded = searchFold(raw);
        mine.push({
          t: folded.t,
          at: folded.at,
          parts,
          end: raw.trimEnd().slice(-1),
          plain: true,
          box:
            pieceBox && pieceBox.ok
              ? { x0: pieceBox.x0, x1: pieceBox.x1, y: pieceBox.y, size: pieceBox.size, ang: pieceBox.ang }
              : null,
        });
      }
      raw = '';
      parts = [];
      pieceBox = null;
    };
    rowItems.forEach((rowItem) => {
      if (rowItem.it.str.trim()) {
        // A gap wider than the font: another piece.
        if (
          pieceBox &&
          pieceBox.ok &&
          rowItem.ok &&
          rowItem.ang === pieceBox.ang &&
          rowItem.x - pieceBox.x1 > pieceBox.size
        )
          end();
        if (!pieceBox)
          pieceBox = {
            ok: rowItem.ok,
            x0: rowItem.x,
            x1: rowItem.x + rowItem.w,
            y: rowItem.y,
            size: rowItem.size,
            ang: rowItem.ang,
          };
        else {
          pieceBox.ok = pieceBox.ok && rowItem.ok && rowItem.ang === pieceBox.ang;
          if (pieceBox.ok) {
            pieceBox.x0 = Math.min(pieceBox.x0, rowItem.x);
            pieceBox.x1 = Math.max(pieceBox.x1, rowItem.x + rowItem.w);
            pieceBox.size = Math.max(pieceBox.size, rowItem.size);
          }
        }
      }
      if (rowItem.it.str) {
        parts.push({ i: rowItem.i, from: raw.length });
        raw += rowItem.it.str;
      }
    });
    end();
    if (mine.length > 1)
      mine.forEach((linePiece) => {
        linePiece.plain = false;
      });
    lines.push(...mine);
  });
  return lines;
}
// How a line meets the next one in a page's flow (searchFlow), as the mark put between them. A query crosses a line's
// end only between two consecutive lines of one wrapped paragraph, as TeX breaks a paragraph into lines; a false hit -
// a highlight on text that does not hold the query - is worse than a missed one, so everything else is HARD and never
// crossed (headings, centred and short lines, table rows, \hfill lines, equations, captions, another column). Two lines
// are consecutive lines of a paragraph when both are plain (searchLines), run the same way at the same font size, the
// first reaches its column's right edge and starts at the column's left edge or an indent, and the second starts at the
// left edge or an indent directly below - one line pitch of that font lower (1 to 1.5 font sizes). The column's edges
// are the line's (searchEdges), within SEARCH_EDGE_POINTS; two lines are held to a column's measure only when both are
// given the same one (col), and otherwise both to their blocks' edges (blk) - so the last line of one column does not
// run into a page-wide line under it that starts in the other, and a page-wide caption still runs on into its short
// last line; an indent is 1 to 2.5 font sizes in from the left edge - a paragraph's indented first line, or the margin
// a list's lines stand at (\leftmargini is 2.5em in LaTeX's standard classes, so a list item's wrapped line stands 2.5
// font sizes in, not at the edge). Between two such lines: a line that ends in a hyphen (-, U+2010 or a soft hyphen) is
// hyphenated - HYPH, the hyphen may be typed or left out; one that ends in a dash (an en or em dash, folded to -) runs
// on with no space - DASH, the dash must be typed; a Hangul or CJK character on either side - CJK, the break is a space
// or nothing, as such text breaks inside a word; else - SPACE, a word space that a query must type, as TeX never breaks
// a Latin word without a hyphen.
const SEARCH_BREAK = Object.freeze({ SPACE: '\n', CJK: '\u0002', HYPH: '\u0003', DASH: '\u0004', HARD: '\u0005' });
const SEARCH_CJK = /[\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u;
// How near a column's edge a line ends or starts to count as reaching it, in PDF points.
const SEARCH_EDGE_POINTS = 3;
// A page's blocks. Two lines are neighbours when they run the same way, overlap each other sideways and stand within
// one line pitch of each other (1.5 font sizes of the larger - the pitch searchJoin allows, so every pair it could ever
// join are neighbours); a block is a line with every line reachable from it through neighbours. A block is one column's
// run of lines - a paragraph and the paragraphs touching it - or one column of a table; a title, a figure, a caption or
// a table wider than the column, and a page number below the text, stand in blocks of their own, a line pitch away from
// the body. Returns each line's block, numbered from 0 in the order the lines come, and -1 for a line without geometry.
// Pure.
function searchBlocks(lines: SearchLine[]): number[] {
  // -2: in no block yet.
  const blockOf: number[] = lines.map((line) => (line.box ? -2 : -1));
  let blockCount = 0;
  lines.forEach((line, index) => {
    if (blockOf[index] !== -2) return;
    const block = blockCount++,
      queue = [index];
    blockOf[index] = block;
    for (let next = queue.pop(); next !== undefined; next = queue.pop()) {
      const currentBox = lines[next].box;
      if (!currentBox) continue; // only a line with a box is ever in no block yet (-2), so queued
      lines.forEach((otherLine, otherIndex) => {
        const otherBox = otherLine.box;
        if (blockOf[otherIndex] !== -2 || !otherBox || otherBox.ang !== currentBox.ang) return;
        if (
          otherBox.x0 < currentBox.x1 &&
          otherBox.x1 > currentBox.x0 &&
          Math.abs(otherBox.y - currentBox.y) <= 1.5 * Math.max(currentBox.size, otherBox.size) + 0.01
        ) {
          blockOf[otherIndex] = block;
          queue.push(otherIndex);
        }
      });
    }
  });
  return blockOf;
}
// searchGutter's thresholds, in PDF points and fractions.
const SEARCH_GUTTER = Object.freeze({ MIN: 8, MIDDLE: 0.2, SIDE: 0.25, BAR: 0.1 });
// The white band between a page's two columns, as [x0, x1] in PDF units, or null for a page not set in two columns.
// Read from the page's own upright lines alone - no other page, so what a page finds never depends on which pages were
// read before it: count how many lines cover each stretch across the page, and take the widest stretch where that count
// stays at or under a tenth of its peak (SEARCH_GUTTER.BAR), inside the text, its middle within a fifth of the text
// width of the text's middle, at least 8pt wide, and with a quarter or more of the page's line length on each side; a
// page of fewer than 8 upright lines is not read. The band need not be empty: a title, a page-wide caption and a
// running head cross it. The count changes only where a line starts or ends, so it is read there and a column gap is
// measured as wide as it is (LaTeX's default \columnsep is 10pt). Pure.
function searchGutter(lines: SearchLine[]): number[] | null {
  const boxes = lines.map((line) => line.box).filter((box): box is SearchPieceBox => !!box && box.ang === 0);
  if (boxes.length < 8) return null;
  const at = [...new Set(boxes.flatMap((box) => [box.x0, box.x1]))].sort((first, second) => first - second),
    low = at[0],
    high = at[at.length - 1],
    coverChange = new Map<number, number>();
  boxes.forEach((box) => {
    coverChange.set(box.x0, (coverChange.get(box.x0) ?? 0) + 1);
    coverChange.set(box.x1, (coverChange.get(box.x1) ?? 0) - 1);
  });
  // coverCounts[k]: the lines covering the stretch from at[k] to at[k+1] - started at or before at[k] and not yet ended
  // there.
  let running = 0;
  const coverCounts = at.slice(0, -1).map((x) => (running += coverChange.get(x) ?? 0)),
    bar = Math.max(1, Math.floor(SEARCH_GUTTER.BAR * Math.max(...coverCounts)));
  let best: number[] | null = null;
  for (let k = 0; k < coverCounts.length;) {
    if (coverCounts[k] > bar) {
      k++;
      continue;
    }
    let stretchEnd = k;
    while (stretchEnd < coverCounts.length && coverCounts[stretchEnd] <= bar) stretchEnd++;
    if (
      k > 0 &&
      stretchEnd < coverCounts.length &&
      Math.abs((at[k] + at[stretchEnd]) / 2 - (low + high) / 2) <= SEARCH_GUTTER.MIDDLE * (high - low) &&
      (!best || at[stretchEnd] - at[k] > best[1] - best[0])
    )
      best = [at[k], at[stretchEnd]];
    k = stretchEnd;
  }
  if (!best || best[1] - best[0] < SEARCH_GUTTER.MIN) return null;
  const gutter = best,
    middle = (gutter[0] + gutter[1]) / 2;
  const lengthOf = (test: (box: SearchPieceBox) => boolean) =>
      boxes.filter(test).reduce((sum, box) => sum + box.x1 - box.x0, 0),
    all = lengthOf(() => true);
  return lengthOf((box) => box.x1 <= middle) < SEARCH_GUTTER.SIDE * all ||
    lengthOf((box) => box.x0 >= middle) < SEARCH_GUTTER.SIDE * all
    ? null
    : gutter;
}
// The column edges of each line, or null for a line without geometry. The measure a line is held to is its own block's
// (searchBlocks), not the whole page's: the least x0 and the greatest x1 over that block. So one line reaching into a
// column - a full-width title or caption, a table or figure wider than the text, a page number - does not widen the
// column's edges, which would leave no line in it reaching the right edge and break every join in it.
// A line wider than a column that stands within one pitch of body text is a neighbour of it, though: then its block
// holds the body, and on a two-column page often both columns. On a page with a gutter (searchGutter), a block that
// holds a line crossing the gutter gives each of its lines that stands on one side the edges of that side instead: the
// left edge of the block's own lines on that side, the right edge of every line on the page standing on that side (the
// column's measure), both held to the gutter. The column's measure and not the block's, because a list of short entries
// under such a line would otherwise reach its own longest entry and run into the next entry (ADR-0017's rejected
// candidate D). The crossing line keeps its block's edges, and a block that crosses nothing keeps its own. A column's
// measure says whose it is (col: 0 left, 1 right) and carries the block's edges (blk), for searchJoin. Pure.
function searchEdges(
  lines: SearchLine[],
): ({ l: number; r: number; col?: number; blk?: { l: number; r: number } } | null)[] {
  const blockOf = searchBlocks(lines),
    blockEdges: { l: number; r: number }[] = [];
  lines.forEach((line, index) => {
    const block = blockOf[index],
      box = line.box;
    if (block < 0 || !box) return; // a line in a block has a box (searchBlocks)
    blockEdges[block] = blockEdges[block]
      ? { l: Math.min(blockEdges[block].l, box.x0), r: Math.max(blockEdges[block].r, box.x1) }
      : { l: box.x0, r: box.x1 };
  });
  const out = lines.map((line, index) => (blockOf[index] < 0 ? null : blockEdges[blockOf[index]])),
    gutter = searchGutter(lines);
  if (!gutter) return out;
  // Each upright line's side of the gutter: 0 left, 1 right, 2 across it; the measure of each side, held to the gutter.
  const side = lines.map((line) =>
      !line.box || line.box.ang !== 0 ? -1 : line.box.x1 <= gutter[1] ? 0 : line.box.x0 >= gutter[0] ? 1 : 2,
    ),
    low = [-Infinity, gutter[1]],
    high = [gutter[0], Infinity];
  const col = [0, 1].map((sideIndex) =>
    Math.max(
      ...lines
        .filter((line, index): line is SearchLine & { box: SearchPieceBox } => side[index] === sideIndex && !!line.box)
        .map((line) => Math.min(line.box.x1, high[sideIndex])),
    ),
  );
  const crossed = new Set(
      lines.flatMap((line, index) => (side[index] === 2 && blockOf[index] >= 0 ? [blockOf[index]] : [])),
    ),
    left = new Map<string, number>();
  lines.forEach((line, index) => {
    const sideIndex = side[index],
      box = line.box;
    // side 0 or 1 is a line with a box
    if (sideIndex > 1 || sideIndex < 0 || !box || !crossed.has(blockOf[index])) return;
    const key = blockOf[index] + ':' + sideIndex,
      x = Math.max(box.x0, low[sideIndex]);
    left.set(key, Math.min(left.get(key) ?? x, x));
  });
  // a line of side 0 or 1 in a crossed block has its block's edges and its side's left edge (both set above)
  return out.map((edges, index) => {
    const sideIndex = side[index],
      edge = left.get(blockOf[index] + ':' + sideIndex);
    return sideIndex > 1 || sideIndex < 0 || !crossed.has(blockOf[index]) || edge === undefined || !edges
      ? edges
      : { l: edge, r: col[sideIndex], col: sideIndex, blk: edges };
  });
}
// The break between a line and the next one, with their column edges (searchEdges): a SEARCH_BREAK mark. Pure.
function searchJoin(
  line: SearchLine,
  next: SearchLine,
  lineEdges: { l: number; r: number; col?: number; blk?: { l: number; r: number } } | null,
  nextEdges: { l: number; r: number; col?: number; blk?: { l: number; r: number } } | null,
) {
  const lineBox = line.box,
    nextBox = next.box;
  if (
    !lineBox ||
    !nextBox ||
    !lineEdges ||
    !nextEdges ||
    !line.plain ||
    !next.plain ||
    lineBox.ang !== nextBox.ang ||
    Math.abs(lineBox.size - nextBox.size) > 0.1
  )
    return SEARCH_BREAK.HARD;
  // Not both on one column's measure: both on their blocks' edges.
  if (lineEdges.col !== nextEdges.col) {
    lineEdges = lineEdges.blk ?? lineEdges;
    nextEdges = nextEdges.blk ?? nextEdges;
  }
  const pitch = lineBox.y - nextBox.y,
    starts = (x: number, edges: { l: number }, size: number) =>
      x - edges.l <= SEARCH_EDGE_POINTS || (x - edges.l >= size && x - edges.l <= 2.5 * size);
  if (
    pitch < lineBox.size - 0.01 ||
    pitch > 1.5 * lineBox.size + 0.01 ||
    lineEdges.r - lineBox.x1 > SEARCH_EDGE_POINTS ||
    !starts(lineBox.x0, lineEdges, lineBox.size) ||
    !starts(nextBox.x0, nextEdges, nextBox.size)
  )
    return SEARCH_BREAK.HARD;
  if (/[-\u2010\u00AD]/.test(line.end)) return SEARCH_BREAK.HYPH;
  const lastCharacter = line.t.trimEnd().slice(-1),
    firstCharacter = next.t.trimStart().charAt(0);
  if (lastCharacter === '-') return SEARCH_BREAK.DASH;
  return SEARCH_CJK.test(lastCharacter) || SEARCH_CJK.test(firstCharacter) ? SEARCH_BREAK.CJK : SEARCH_BREAK.SPACE;
}
// A page's lines as one flow of text, so a query may run over a line's end: each line's folded text (searchLines),
// trimmed, joined to the next by the mark of how they meet (searchJoin). Returns {t, rows}: the flow and, for each
// line, where it starts in the flow (at), how many folded characters the trim takes off its head (cut) and its trimmed
// length (n). Pure.
function searchFlow(lines: SearchLine[]) {
  let flow = '';
  const rows: { at: number; cut: number; n: number }[] = [],
    edges = searchEdges(lines);
  lines.forEach((line, index) => {
    const body = line.t.trim();
    if (index) flow += searchJoin(lines[index - 1], line, edges[index - 1], edges[index]);
    rows.push({ at: flow.length, cut: line.t.length - line.t.trimStart().length, n: body.length });
    flow += body;
  });
  return { t: flow, rows };
}
// The folded query as a pattern over a page's flow (searchFlow): every character is itself; a space is a space, a SPACE
// break or a CJK one; between two characters there may be a CJK break, a HYPH break (with the line's hyphen before it,
// or after the hyphen when the query types it) or a DASH break. A SPACE break is crossed only by a typed space and a
// HARD one never. null for an empty query. Pure.
function searchPattern(query: string): RegExp | null {
  const characters = [...query];
  if (!characters.length) return null;
  let source = '';
  characters.forEach((character, index) => {
    if (character === ' ') {
      source += '[ \\n\\u0002]';
      return;
    }
    source += /[\\^$.*+?()[\]{}|]/.test(character) ? '\\' + character : character;
    if (index < characters.length - 1 && characters[index + 1] !== ' ') source += '(?:\\u0002|-?\\u0003|\\u0004)?';
  });
  return new RegExp(source, 'gu');
}
// Where a pattern matches in a page's flow, left to right and without overlap. Each hit is its pieces [line, from, to]
// - one for every line it lies on, from-to in that line's folded text - in reading order; nothing without a pattern.
// Pure.
function searchFind(
  flow: { t: string; rows: { at: number; cut: number; n: number }[] },
  pattern: RegExp | null,
): number[][][] {
  const out: number[][][] = [];
  if (!pattern) return out;
  let rowIndex = 0;
  for (const match of flow.t.matchAll(pattern)) {
    const start = match.index,
      end = start + match[0].length,
      pieces: number[][] = [];
    while (rowIndex < flow.rows.length - 1 && flow.rows[rowIndex + 1].at <= start) rowIndex++;
    for (let i = rowIndex; i < flow.rows.length && flow.rows[i].at < end; i++) {
      const row = flow.rows[i],
        from = Math.max(start, row.at),
        to = Math.min(end, row.at + row.n);
      if (to > from) pieces.push([i, from - row.at + row.cut, to - row.at + row.cut]);
    }
    if (pieces.length) out.push(pieces);
  }
  return out;
}
// The hit after (direction 1) or before (direction -1) the current one of count hits, wrapping at both ends; from no
// current hit (current < 0) the first or the last; -1 with no hits. Pure.
function searchStep(current: number, count: number, direction: number) {
  if (!count) return -1;
  if (current < 0) return direction > 0 ? 0 : count - 1;
  return (((current + direction) % count) + count) % count;
}
// The field's width in the nav bar for `room` px left beside its neighbours: its full width, else the room in whole
// pixels down to its minimum, else 0 - it folds to the magnifier rather than squeeze them. Pure.
function searchWidth(room: number, full: number, min: number) {
  return room >= full ? full : room >= min ? Math.floor(room) : 0;
}
// The box of characters [start, end) of a text item on its page, as fractions [x, y, w, h] of the viewportWidth x
// viewportHeight viewport whose transform is viewportTransform: along the item's direction by the measured share of its
// width (measure(text, family) in any unit - the item's own width scales it, as PDF.js's text layer does), across it
// from the font's ascent to its descent (style; 0.8 and -0.2 when the font gives none). A turned item gives the
// bounding box of its turned run. Pure.
function searchBox(
  item: PdfTextItem,
  style: Partial<PdfTextStyle>,
  viewportTransform: number[],
  viewportWidth: number,
  viewportHeight: number,
  start: number,
  end: number,
  measure: (text: string, family: string) => number,
) {
  const matrix = item.transform,
    family = style.fontFamily || 'sans-serif';
  const transformed = [
    viewportTransform[0] * matrix[0] + viewportTransform[2] * matrix[1],
    viewportTransform[1] * matrix[0] + viewportTransform[3] * matrix[1],
    viewportTransform[0] * matrix[2] + viewportTransform[2] * matrix[3],
    viewportTransform[1] * matrix[2] + viewportTransform[3] * matrix[3],
    viewportTransform[0] * matrix[4] + viewportTransform[2] * matrix[5] + viewportTransform[4],
    viewportTransform[1] * matrix[4] + viewportTransform[3] * matrix[5] + viewportTransform[5],
  ];
  const run = Math.hypot(transformed[0], transformed[1]) || 1,
    up = Math.hypot(transformed[2], transformed[3]) || 1,
    itemWidth = item.width * Math.hypot(viewportTransform[0], viewportTransform[1]),
    all = measure(item.str, family) || 1;
  const ascent =
      typeof style.ascent === 'number' ? style.ascent : typeof style.descent === 'number' ? 1 + style.descent : 0.8,
    descent = typeof style.descent === 'number' ? style.descent : -0.2;
  const cornersX: number[] = [],
    cornersY: number[] = [];
  for (const along of [
    (itemWidth * measure(item.str.slice(0, start), family)) / all,
    (itemWidth * measure(item.str.slice(0, end), family)) / all,
  ])
    for (const across of [ascent * up, descent * up]) {
      cornersX.push(transformed[4] + (along * transformed[0]) / run + (across * transformed[2]) / up);
      cornersY.push(transformed[5] + (along * transformed[1]) / run + (across * transformed[3]) / up);
    }
  const x0 = Math.min(...cornersX),
    y0 = Math.min(...cornersY);
  return [
    x0 / viewportWidth,
    y0 / viewportHeight,
    (Math.max(...cornersX) - x0) / viewportWidth,
    (Math.max(...cornersY) - y0) / viewportHeight,
  ];
}
// Whether a keydown is the search shortcut: Cmd on an Apple platform (isMac) and Ctrl elsewhere, alone, with the key
// that types f - whatever its place on the layout (Dvorak's f is the physical Y key; its physical F key types u and is
// not it). A key that types no Latin letter (a Hangul jamo, an input method's 'Process') counts by its place: the
// physical F key. Pure.
function searchKey(
  event: { key?: string; code?: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; shiftKey?: boolean },
  isMac: boolean,
) {
  if (event.altKey || event.shiftKey || (isMac ? !event.metaKey || event.ctrlKey : !event.ctrlKey || event.metaKey))
    return false;
  const key = String(event.key || '');
  return /^\p{Script=Latin}$/u.test(key) ? key.toLowerCase() === 'f' : event.code === 'KeyF';
}

// Where a line piece stands (searchLines): along the line x0 to x1, across it y, with its font size and angle.
// One text item of a line being read (searchLines): its index among the page's items, the item, whether its matrix is
// upright (ok), where it starts along the line (x), how wide it is, where it stands across the line (y), its font size
// and the line's angle in whole degrees.
interface SearchRowItem {
  i: number;
  it: PdfTextItem;
  ok: boolean;
  x: number;
  w: number;
  y: number;
  size: number;
  ang: number;
}
interface SearchPieceBox {
  x0: number;
  x1: number;
  y: number;
  size: number;
  ang: number;
}
// One piece of a line (searchLines): its folded text, the map back to its own text, the items it holds, its last
// character, whether its line is in one piece, and its geometry (null for text that is skewed or mirrored).
interface SearchLine {
  t: string;
  at: number[];
  parts: { i: number; from: number }[];
  end: string;
  plain: boolean;
  box: SearchPieceBox | null;
}
// A page's text as one flow (searchFlow): the flow and, for each line, where it starts, how many characters the trim cuts
// off its head and its trimmed length.
interface SearchFlow {
  t: string;
  rows: { at: number; cut: number; n: number }[];
}
// A page of the document as searchRead keeps it once read.
interface SearchPage {
  items: PdfTextItem[];
  styles: Record<string, PdfTextStyle>;
  vt: number[];
  w: number;
  h: number;
  lines: SearchLine[];
  flow: SearchFlow;
}
// One hit (searchPageHits): its page, where its first piece starts (line, a), its pieces as searchFind gives them and the
// boxes searchBoxes caches.
interface SearchHit {
  page: number;
  line: number;
  a: number;
  pieces: number[][];
  boxes: number[][] | null;
}
// The search on screen. q: the folded query ('' = none) and re its pattern. doc: the PDF.js document the hits are of.
// hits: every hit in document order as {page, line, a, pieces, boxes?} (pieces as searchFind gives them; line and a are
// where the first one starts; boxes cached by searchBoxes). cur: the current hit. ref: where a query looks for its
// current hit from (the page on screen when the search began, then the hit that was last current). reading: the
// document whose pages are being read. failed: the pages whose text could not be read for this query. composing: an
// input method is composing in the field. open: the field is disclosed (focused or holding a query). back: what had the
// focus before the field was entered. away: the window lost the focus while it was in the field. side: the phone's
// sheet was open when the search row took its place. ink: the field's text shift in px (searchInk). near: the pages
// near the view, the only ones that carry hit boxes. text: each open document's pages as read ({items, styles, vt, w,
// h, lines, flow}; null until read).
interface SearchState {
  q: string;
  re: RegExp | null;
  doc: PdfDocument | null;
  hits: SearchHit[];
  cur: SearchHit | null;
  ref: { page: number; line: number; a: number };
  reading: PdfDocument | null;
  failed: Set<number>;
  composing: boolean;
  open: boolean;
  back: HTMLElement | null;
  away: boolean;
  side: boolean;
  ink: number;
  near: Set<number>;
  io: IntersectionObserver | null;
  text: WeakMap<PdfDocument, (SearchPage | null)[]>;
}
const SEARCH: SearchState = {
  q: '',
  re: null,
  doc: null,
  hits: [],
  cur: null,
  ref: { page: 1, line: 0, a: 0 },
  reading: null,
  failed: new Set(),
  composing: false,
  open: false,
  back: null,
  away: false,
  side: false,
  ink: 0,
  near: new Set(),
  io: null,
  text: new WeakMap(),
};
// The pages of document doc as read so far, index 0 for page 1 (null = not read yet); kept until the document is
// closed.
function searchPages(doc: PdfDocument) {
  let pages = SEARCH.text.get(doc);
  if (!pages) {
    pages = new Array<SearchPage | null>(doc.numPages).fill(null);
    SEARCH.text.set(doc, pages);
  }
  return pages;
}
// The hits of a pattern on a read page, number pageNumber, in reading order.
function searchPageHits(page: SearchPage, pageNumber: number, pattern: RegExp | null) {
  return searchFind(page.flow, pattern).map((pieces): SearchHit => ({
    page: pageNumber,
    line: pieces[0][0],
    a: pieces[0][1],
    pieces,
    boxes: null,
  }));
}
// The width of text in a generic font family, in an arbitrary unit (a shared canvas, SEARCH_CONTEXT): searchBox()'s
// measure.
let SEARCH_CONTEXT: CanvasRenderingContext2D | null = null;
function searchMeasure(text: string, family: string) {
  const context = SEARCH_CONTEXT || (SEARCH_CONTEXT = document.createElement('canvas').getContext('2d'));
  if (!context) throw new Error('searchMeasure: no 2D canvas context');
  context.font = '100px ' + family;
  return context.measureText(text).width;
}
// The box of one piece of a hit - characters from to to of line `line`'s folded text - on a read page, as fractions [x,
// y, w, h]: the union of its run in each text item of the line. The folded run maps back to the line's own characters
// through the line's map, to the end of the last character's cluster - both letters of a ligature are the ligature's
// box.
function searchPieceBox(page: SearchPage, [line, from, to]: number[]) {
  const textLine = page.lines[line];
  let endUnit = to;
  while (endUnit < textLine.at.length - 1 && textLine.at[endUnit] <= textLine.at[to - 1]) endUnit++;
  const rawFrom = textLine.at[from],
    rawTo = textLine.at[endUnit];
  let x0 = Infinity,
    y0 = Infinity,
    x1 = -Infinity,
    y1 = -Infinity;
  for (const part of textLine.parts) {
    const item = page.items[part.i],
      start = Math.max(rawFrom, part.from) - part.from,
      end = Math.min(rawTo, part.from + item.str.length) - part.from;
    if (end <= start) continue;
    const box = searchBox(item, page.styles[item.fontName] || {}, page.vt, page.w, page.h, start, end, searchMeasure);
    x0 = Math.min(x0, box[0]);
    y0 = Math.min(y0, box[1]);
    x1 = Math.max(x1, box[0] + box[2]);
    y1 = Math.max(y1, box[1] + box[3]);
  }
  return x1 >= x0 ? [x0, y0, x1 - x0, y1 - y0] : [0, 0, 0, 0];
}
// A hit's boxes on its page, one for each line it lies on. A hit is of the searched document, so none without one.
function searchBoxes(hit: SearchHit): number[][] {
  if (hit.boxes) return hit.boxes;
  const doc = SEARCH.doc;
  if (!doc) return [];
  // A hit is found on a read page and a read page stays read, so the page is there; the type does not say so.
  const page = searchPages(doc)[hit.page - 1];
  if (!page) return [];
  return (hit.boxes = hit.pieces.map((piece) => searchPieceBox(page, piece)));
}
// Draws a page's hit boxes (the current hit's marked, every one of them), or removes them when the page is not near the
// view or has none.
function searchDrawPage(pageNumber: number) {
  const pageBox = document.getElementById('p' + pageNumber);
  if (!pageBox) return;
  pageBox.querySelectorAll('.search-hit').forEach((element) => element.remove());
  if (!SEARCH.near.has(pageNumber)) return;
  for (const hit of SEARCH.hits) {
    if (hit.page !== pageNumber) continue;
    for (const box of searchBoxes(hit)) {
      const hitBox = document.createElement('div');
      hitBox.className = 'search-hit' + (hit === SEARCH.cur ? ' cur' : '');
      Object.assign(hitBox.style, {
        left: box[0] * 100 + '%',
        top: box[1] * 100 + '%',
        width: box[2] * 100 + '%',
        height: box[3] * 100 + '%',
      });
      pageBox.appendChild(hitBox);
    }
  }
}
// Follows which pages are near the view (within one view height) while there is a query: only those carry hit boxes,
// drawn as they come near and removed as they leave, so a common letter in a long document does not fill the page list
// with boxes.
function searchWatch() {
  if (SEARCH.io || !window.IntersectionObserver) return;
  const io = (SEARCH.io = new IntersectionObserver(
    (entries) => {
      for (const en of entries) {
        const pageNumber = Number(en.target instanceof HTMLElement ? en.target.dataset.page : undefined);
        if (en.isIntersecting) SEARCH.near.add(pageNumber);
        else SEARCH.near.delete(pageNumber);
        searchDrawPage(pageNumber);
      }
    },
    { root: $('#left'), rootMargin: '100% 0px' },
  ));
  $$('.pg').forEach((pageBox) => io.observe(pageBox));
}
// Stops following the pages and removes every hit box: the next query follows the pages that are on screen then.
function searchUnwatch() {
  if (SEARCH.io) SEARCH.io.disconnect();
  SEARCH.io = null;
  SEARCH.near.clear();
  $$('.search-hit').forEach((element) => element.remove());
}
// Whether the count is not final yet: the PDF is still opening (another document or build on its way), or pages of the
// searched document are still to be read. A page whose text could not be read for this query is not waited for.
function searchBusy() {
  return (
    !!SEARCH.q &&
    (!SEARCH.doc ||
      searchPages(SEARCH.doc).some((page: SearchPage | null, index: number) => !page && !SEARCH.failed.has(index + 1)))
  );
}
// How many pages of the searched document could not be read for this query: they are left out of the count, and said
// with it.
function searchUnread() {
  return SEARCH.q && SEARCH.doc
    ? searchPages(SEARCH.doc).filter((page: SearchPage | null, index: number) => !page && SEARCH.failed.has(index + 1))
        .length
    : 0;
}
// Hits in document order.
function searchOrder(first: SearchHit, second: SearchHit) {
  return first.page - second.page || first.line - second.line || first.a - second.a;
}
// The part of the PDF area nothing covers (popoverFreeArea), above the phone's search rows - and the status line
// standing on them - while they are up: where a hit is shown.
function searchArea() {
  const area = popoverFreeArea(),
    navigationBar = $('#doc-nav'),
    dock = $('#status-dock');
  if (BAND === LAYOUT_BAND.PHONE && navigationBar.getClientRects().length) {
    area.bottom = Math.min(area.bottom, navigationBar.getBoundingClientRect().top);
    if (dock.getClientRects().length) area.bottom = Math.min(area.bottom, dock.getBoundingClientRect().top);
  }
  return area;
}
// The phone's search rows' height (--search-rows): the status line stands on them while the search is open
// (search.css).
function searchRows() {
  if (BAND === LAYOUT_BAND.PHONE && SEARCH.open)
    document.documentElement.style.setProperty(
      '--search-rows',
      Math.round($('#doc-nav').getBoundingClientRect().height) + 'px',
    );
}
// Scrolls a hit into the free part of the PDF area unless every line of it already is there, with 8px to spare: its
// first line 30% down the area, as [보기] puts a mark, or higher so that its last line still shows when it runs over
// lines; a hit taller than the area shows its first line at the area's top. Sideways only when a zoomed page has its
// start off to a side. Its page counts as near the view from here on. A hit shown as the PDF's text is read can land on
// a jump's way: the jump is over, and the hit is the place the pages settle on, for a glide stopped by a write goes on
// a frame or two and would take it under the bar.
function searchReveal(hit: SearchHit) {
  const shift = searchShift(hit),
    pdfArea = $('#left');
  if (!shift) return;
  if (shift.by || shift.aside)
    endJumpForScroll(() => {
      const shiftNow = searchShift(hit);
      return shiftNow ? pdfArea.scrollTop + shiftNow.by : null;
    });
  if (shift.by) pdfArea.scrollTop += shift.by;
  if (shift.aside) pdfArea.scrollLeft += shift.aside;
  // In view now: its boxes are drawn at once, ahead of the observer.
  SEARCH.near.add(hit.page);
}
// How far the PDF area has to scroll to show a hit as searchReveal does, down and across, 0 where it shows; null
// without its page.
function searchShift(hit: SearchHit) {
  const pageBox = document.getElementById('p' + hit.page);
  if (!pageBox) return null;
  const boxes = searchBoxes(hit),
    area = searchArea();
  const rect = pageBox.getBoundingClientRect(),
    x = rect.left + pageBox.clientLeft,
    y = rect.top + pageBox.clientTop,
    width = pageBox.clientWidth,
    height = pageBox.clientHeight;
  const top = y + Math.min(...boxes.map((box) => box[1])) * height,
    bottom = y + Math.max(...boxes.map((box) => box[1] + box[3])) * height,
    left = x + boxes[0][0] * width,
    right = left + boxes[0][2] * width;
  const want =
    bottom - top > area.bottom - area.top - 16
      ? area.top + 8
      : Math.min(area.top + (area.bottom - area.top) * 0.3, area.bottom - 8 - (bottom - top));
  return {
    by: top < area.top + 8 || bottom > area.bottom - 8 ? top - want : 0,
    aside: left < area.left + 8 || right > area.right - 8 ? (left + right) / 2 - (area.left + area.right) / 2 : 0,
  };
}
// Picks the current hit when there is none: the first at or after the reference, once every page between the two has
// been read (or could not be); the first of all once the pages from the reference on hold none.
function searchPick() {
  const doc = SEARCH.doc;
  if (SEARCH.cur || !SEARCH.hits.length || !doc) return;
  const reference = SEARCH.ref,
    pages = searchPages(doc);
  const candidate = SEARCH.hits.find(
    (hit) =>
      hit.page > reference.page ||
      (hit.page === reference.page &&
        (hit.line > reference.line || (hit.line === reference.line && hit.a >= reference.a))),
  );
  for (let pageNumber = reference.page; pageNumber <= (candidate ? candidate.page - 1 : pages.length); pageNumber++)
    if (!pages[pageNumber - 1] && !SEARCH.failed.has(pageNumber)) return;
  SEARCH.cur = candidate || SEARCH.hits[0];
  searchReveal(SEARCH.cur);
}
// Draws the search's state: the count ('n/m'; with '…' while pages are still to be read, and with how many pages could
// not be read once they have been tried; nothing without a query), the arrows, the hit boxes of the pages near the
// view, and - once the count is final and no input method is composing - the announcement for a screen reader.
function searchPaint() {
  const count = SEARCH.hits.length,
    position = SEARCH.cur ? SEARCH.hits.indexOf(SEARCH.cur) + 1 : 0,
    busy = searchBusy(),
    lost = busy ? 0 : searchUnread();
  const miss = lost ? ' · ' + translateTemplate('못 읽은 쪽 {n}', { n: lost }) : '';
  $('#search-count').textContent = SEARCH.q ? position + '/' + count + (busy ? '…' : miss) : '';
  $('#search-prev').disabled = $('#search-next').disabled = !count;
  SEARCH.near.forEach(searchDrawPage);
  searchCover();
  searchRows();
  if (busy || SEARCH.composing) return;
  const status = $('#search-sr');
  const say = !SEARCH.q
    ? ''
    : (count
        ? translateTemplate('{m}개 중 {n}번째 · {page}쪽', {
            n: position,
            m: count,
            page: SEARCH.cur ? SEARCH.cur.page : 0,
          })
        : translate('결과 없음')) + miss;
  if (status.textContent !== say) status.textContent = say;
}
// A page's text in PDF document doc: its items and styles, and the page's viewport at scale 1. The one place a page's
// text is read - the search reads every page through it, and a selection made with no network the page it was drawn
// on (offline/flow.ts offlineQuote). Rejects as PDF.js does when the page cannot be read.
async function pageText(
  doc: PdfDocument,
  pageNumber: number,
): Promise<{ items: PdfTextItem[]; styles: Record<string, PdfTextStyle>; vp: PdfViewport }> {
  const page = await doc.getPage(pageNumber),
    textContent = await page.getTextContent(),
    viewport = page.getViewport({ scale: 1 });
  return { items: textContent.items, styles: textContent.styles, vp: viewport };
}
// Reads the text of the searched document's unread pages, from the reference page on and then round to the pages
// before it, one page at a time and never while a page is being drawn; each page read adds its hits. Stops when the
// query is cleared or another document is searched. A page whose text cannot be read is left unread and not tried again
// for this query (the next query tries it again); the pages after it are still read.
async function searchRead() {
  const doc = SEARCH.doc;
  if (!doc || SEARCH.reading === doc) return;
  SEARCH.reading = doc;
  const pages = searchPages(doc),
    pageCount = pages.length;
  try {
    for (;;) {
      const from = Math.min(pageCount, Math.max(1, SEARCH.ref.page));
      let pageNumber = 0;
      for (let k = 0; k < pageCount && !pageNumber; k++) {
        const candidate = ((from - 1 + k) % pageCount) + 1;
        if (!pages[candidate - 1] && !SEARCH.failed.has(candidate)) pageNumber = candidate;
      }
      if (!pageNumber) return;
      while (VECTOR_PDF.pumping || VECTOR_PDF.cur) {
        await new Promise((resolve) => setTimeout(resolve, 60));
        if (SEARCH.doc !== doc || !SEARCH.q) return;
      }
      try {
        const { items, styles, vp: viewport } = await pageText(doc, pageNumber),
          lines = searchLines(items);
        pages[pageNumber - 1] = {
          items,
          styles,
          vt: viewport.transform,
          w: viewport.width,
          h: viewport.height,
          lines,
          flow: searchFlow(lines),
        };
      } catch (error) {
        if (VECTOR_PDF.doc !== doc) return;
        if (SEARCH.doc === doc) SEARCH.failed.add(pageNumber);
      }
      if (SEARCH.doc !== doc || !SEARCH.q) return;
      const read = pages[pageNumber - 1],
        more = read ? searchPageHits(read, pageNumber, SEARCH.re) : [];
      if (more.length) SEARCH.hits = SEARCH.hits.concat(more).sort(searchOrder);
      searchPick();
      searchPaint();
    }
  } finally {
    if (SEARCH.reading === doc) SEARCH.reading = null;
    if (SEARCH.doc === doc) searchPaint();
  }
}
// A Hangul jamo standing alone - what an input method shows between the first key of a syllable and its vowel.
const SEARCH_JAMO = /[\u1100-\u11FF\u3131-\u318E\uA960-\uA97F\uD7B0-\uD7FF]/;
// Runs the field's query on the PDF on screen: the hits of the pages already read at once, the rest as searchRead()
// reads them. While an input method composes, a jamo standing alone before the caret is not part of the query yet (the
// syllable has only begun). The current hit is looked for from the hit that was last current - through queries that
// had none - and from the page on screen when the search starts from an empty field or on another document. No query,
// or no PDF: no hits.
function searchRun() {
  const field = $('#search-q'),
    doc = VECTOR_PDF.doc;
  let value = field.value;
  if (SEARCH.composing) {
    const caret = field.selectionStart || 0;
    if (caret > 0 && SEARCH_JAMO.test(value[caret - 1])) value = value.slice(0, caret - 1) + value.slice(caret);
  }
  const query = searchFold(value).t.trim();
  if (query === SEARCH.q && doc === SEARCH.doc) return;
  if (SEARCH.cur && doc === SEARCH.doc) SEARCH.ref = { page: SEARCH.cur.page, line: SEARCH.cur.line, a: SEARCH.cur.a };
  else if (doc !== SEARCH.doc || !SEARCH.q) {
    const anchor = topAnchor();
    SEARCH.ref = { page: anchor ? anchor.page : 1, line: 0, a: 0 };
  }
  SEARCH.q = query;
  SEARCH.re = searchPattern(query);
  SEARCH.doc = doc;
  SEARCH.cur = null;
  SEARCH.hits = [];
  SEARCH.failed.clear();
  $('#doc-search').classList.toggle('has-q', !!query);
  // With a query the overlay panel's width is kept clear of the page (responsive.css), as while composing: re-fit
  // before a hit is shown.
  const body = document.body;
  if (body.classList.contains('searching') !== !!query) {
    body.classList.toggle('searching', !!query);
    if (query && MID_OVERLAY && SIDE_OPEN) relayout();
  }
  if (!query || !doc) {
    searchUnwatch();
    searchPaint();
    return;
  }
  searchPages(doc).forEach((page: SearchPage | null, index: number) => {
    if (page) SEARCH.hits.push(...searchPageHits(page, index + 1, SEARCH.re));
  });
  searchWatch();
  searchPick();
  searchPaint();
  searchRead();
}
// Goes to the next (direction 1) or previous (direction -1) hit, wrapping, and shows it.
function searchGo(direction: 1 | -1) {
  const count = SEARCH.hits.length;
  if (!count) return;
  SEARCH.cur = SEARCH.hits[searchStep(SEARCH.cur ? SEARCH.hits.indexOf(SEARCH.cur) : -1, count, direction)];
  searchReveal(SEARCH.cur);
  searchPaint();
}

// The field's place for the layout now (docs/handbook/viewer.md §본문 검색): on the phone it is the dock; elsewhere its
// width is what the bar leaves beside its neighbours at their full width (searchWidth) - inline, or the magnifier alone
// - and --search-cap is how far the opened field may reach to the left inside the bar. A neighbour that may shrink (the
// paper's name) counts at its whole width, laid out for the moment unshrunk (as docFit counts it): counted as the bar
// has squeezed it, it would leave the field more room, and the field taking it would squeeze it further.
function searchFit() {
  const searchRoot = $('#doc-search'),
    navigationBar = $('#doc-nav');
  if (BAND === LAYOUT_BAND.PHONE) {
    searchRoot.dataset.mode = 'dock';
    searchRoot.style.width = '';
    searchInk();
    searchCover();
    return;
  }
  if (searchRoot.hidden || !navigationBar.getClientRects().length) {
    searchCover();
    return;
  }
  const barStyle = getComputedStyle(navigationBar),
    root = getComputedStyle(document.documentElement),
    px = (value: string) => parseFloat(value) || 0;
  let used = 0,
    counted = 0;
  for (const neighbour of findAll(navigationBar, ':scope > *', HTMLElement)) {
    if (neighbour === searchRoot || !neighbour.getClientRects().length) continue;
    const neighbourStyle = getComputedStyle(neighbour);
    let width = neighbour.getBoundingClientRect().width;
    if (neighbour.id === 'doc-links') width = Math.max(width, neighbour.scrollWidth);
    else if (neighbour.id === 'paper-identity') {
      neighbour.style.flex = 'none';
      width = neighbour.getBoundingClientRect().width;
      neighbour.style.flex = '';
    }
    used += width + px(neighbourStyle.marginLeft) + px(neighbourStyle.marginRight);
    counted++;
  }
  const left = navigationBar.getBoundingClientRect().left + px(barStyle.paddingLeft),
    room =
      navigationBar.clientWidth -
      px(barStyle.paddingLeft) -
      px(barStyle.paddingRight) -
      used -
      px(barStyle.columnGap) * counted;
  const width = searchWidth(room, px(root.getPropertyValue('--search-w')), px(root.getPropertyValue('--search-min')));
  searchRoot.dataset.mode = width ? 'inline' : 'icon';
  searchRoot.style.width = width ? width + 'px' : '';
  searchRoot.style.setProperty('--search-cap', Math.max(0, searchRoot.getBoundingClientRect().right - left) + 'px');
  searchInk();
  searchCover();
}
// While the opened field lies over the bar, every neighbour its box meets - or comes within the bar's gap of - is taken
// off the bar whole (.search-covered: not drawn, no press, no focus; it keeps its place, so closing puts it back as it
// was), and the field takes their place: --search-span widens it to the left, from where it ends to one bar gap after
// the last neighbour left on its left (the bar's content edge when none is), so no blank run is left where they stood.
// The status line is never taken off (the short band holds it in this row): it moves to stand right after what is left
// on the left (.search-kept, flex order) and gives way to the field last (below) - it keeps its icon, its action and,
// as long as anything else can yield, its words: drawn, pressable, spoken. The natural box is measured first and the
// span set in the same task, so the field is drawn at its full span in the frame it opens and its text does not move
// after. Nothing is covered on the phone (it has no bar) or while the field is closed. A neighbour's right end is its
// box's, less what a negative right margin lets it reach into the bar's gap (the document row reaches 2px past its room
// so its links' focus rings stand clear of their words; frame.css): the field keeps one gap from the row's room.
function searchCover() {
  const searchRoot = $('#doc-search'),
    navigationBar = $('#doc-nav'),
    box = $('#search-box'),
    neighbours = findAll(navigationBar, ':scope > *', HTMLElement).filter((neighbour) => neighbour !== searchRoot);
  const right = (neighbour: HTMLElement) =>
    neighbour.getBoundingClientRect().right + Math.min(0, parseFloat(getComputedStyle(neighbour).marginRight) || 0);
  // The natural box first: the span is worked out from it.
  if (searchRoot.style.getPropertyValue('--search-span')) searchRoot.style.removeProperty('--search-span');
  searchRoot.classList.remove('search-squeezed');
  for (const neighbour of neighbours) {
    if (neighbour.matches('.search-covered,.search-left,.search-kept,.search-tight'))
      neighbour.classList.remove('search-covered', 'search-left', 'search-kept', 'search-tight');
    if (neighbour.style.maxWidth) neighbour.style.maxWidth = '';
  }
  const openBox =
    SEARCH.open && !searchRoot.hidden && BAND !== LAYOUT_BAND.PHONE && box.getClientRects().length
      ? box.getBoundingClientRect()
      : null;
  // Closed: nothing is measured.
  if (!openBox) return;
  const barStyle = getComputedStyle(navigationBar),
    gap = parseFloat(barStyle.columnGap) || 0,
    keep: HTMLElement[] = [],
    off: HTMLElement[] = [],
    left: HTMLElement[] = [];
  // Each neighbour before the search in the bar is left in place (it ends a gap short of the field), kept (the status
  // line) or taken off - also one the bar has squeezed to no width (a long status line at rest does that to the
  // document links), which would come back under the field as soon as the status is shortened.
  for (const neighbour of neighbours) {
    if (
      !neighbour.getClientRects().length ||
      !(neighbour.compareDocumentPosition(searchRoot) & Node.DOCUMENT_POSITION_FOLLOWING)
    )
      continue;
    const rect = neighbour.getBoundingClientRect();
    if (rect.width && right(neighbour) <= openBox.left - gap + 0.5) left.push(neighbour);
    else if (rect.width || !(rect.left >= openBox.right))
      (neighbour.matches('[role=status],[aria-live]') || neighbour.querySelector('[role=status],[aria-live]')
        ? keep
        : off
      ).push(neighbour);
  }
  if (!off.length && !keep.length) return;
  off.forEach((neighbour) => neighbour.classList.add('search-covered'));
  left.forEach((neighbour) => neighbour.classList.add('search-left'));
  keep.forEach((neighbour) => neighbour.classList.add('search-kept'));
  const edge = () =>
    [...left, ...keep].reduce(
      (edgeReached, neighbour) => Math.max(edgeReached, right(neighbour) + gap),
      navigationBar.getBoundingClientRect().left + navigationBar.clientLeft + (parseFloat(barStyle.paddingLeft) || 0),
    );
  let span = searchRoot.getBoundingClientRect().right - edge();
  if (!keep.length) {
    searchRoot.style.setProperty('--search-span', Math.max(openBox.width, span) + 'px');
    return;
  }
  // The status line's words are what it says; as the row narrows they give way last. First the field shrinks, down to
  // its least width (the open box's min-content: the query keeps --search-q-min); then the neighbours left of the
  // status are taken off, the nearest first, all but the row's first (the outline toggle); then the status's dismiss
  // button goes (it can be dismissed once the search is closed); only then do its words shorten to an ellipsis.
  const status = keep[keep.length - 1];
  searchRoot.style.setProperty('--search-span', '0px');
  // min-width:min-content holds it there.
  const least = box.getBoundingClientRect().width;
  // The first (the outline toggle) stays.
  while (span < least && left.length > 1) {
    const nearest = left.pop();
    if (!nearest) break;
    nearest.classList.replace('search-left', 'search-covered');
    span = searchRoot.getBoundingClientRect().right - edge();
  }
  if (span < least) {
    status.classList.add('search-tight');
    span = searchRoot.getBoundingClientRect().right - edge();
  }
  if (span < least) {
    // floor: its icon and actions.
    const statusText = status.querySelector('.st-tx'),
      floor = Math.ceil(
        status.getBoundingClientRect().width - (statusText ? statusText.getBoundingClientRect().width : 0),
      );
    // Shortened again while the field still lacks room: a status wider than the bar at rest pushes the search to the
    // right, and each shortening brings it back left by as much.
    for (let attempt = 0; attempt < 4 && span < least; attempt++) {
      const width = status.getBoundingClientRect().width;
      if (width <= floor + 0.5) break;
      status.style.maxWidth = Math.max(floor, Math.floor(width - (least - span))) + 'px';
      span = searchRoot.getBoundingClientRect().right - edge();
    }
  }
  // (The field's right end is measured again each time: a status line wider than the bar at rest pushes the search to
  // the right until it is shortened.) Last, when even the status's icon and actions leave the field less than its least
  // width, the field goes under it (.search-squeezed: its query shorter than --search-q-min) rather than over the
  // status: nothing overlaps.
  searchRoot.classList.toggle('search-squeezed', span < least);
  searchRoot.style.setProperty('--search-span', (span < least ? span : Math.max(least, span)) + 'px');
}
// The field's text on the row's ink reference (docs/handbook/viewer.md §글자 가운데): its neighbours' labels are
// trimmed to their cap height (text-box: trim-both cap alphabetic) and centred, which an <input> cannot be - trimming
// does not reach its text. So the field holds that reference itself: #search-ref-row is a trimmed line at the row
// labels' size and #search-ref-own one at the field's own size, both centred in the field as a label would be.
// --search-ink moves the input, as a transform, from where its line box puts its baseline (#search-probe: the input's
// line laid out as an element, its baseline marked):
// - text of the labels' size (a mouse: 12px): onto the baseline a trimmed label is painted on - its layout baseline
//   rounded to a whole pixel - by whole pixels, so field and labels are painted alike, pixel for pixel;
// - text of another size (touch: 16px beside 12px labels): to where its cap height's centre is the row line's, exactly,
//   in layout; painting snaps the text and the labels to device pixels each in its own way, so their inks agree within
//   one device pixel (a fraction of a pixel in a transform does not blur text: it is drawn on the device grid).
// Without text-box-trim there is no reference and the text stays on its line box. Measured with every fit of the field,
// when it is disclosed and when a font arrives.
function searchInk() {
  const field = $('#search-q'),
    row = $('#search-ref-row'),
    own = $('#search-ref-own'),
    probe = $('#search-probe');
  if (!field.getClientRects().length || !row.getClientRects().length || !probe.getClientRects().length) return;
  let ink = 0;
  if (window.CSS && CSS.supports('text-box-trim', 'trim-both')) {
    const rowRect = row.getBoundingClientRect(),
      ownRect = own.getBoundingClientRect();
    const base =
        findElement(probe, ':scope > *', Element).getBoundingClientRect().bottom - probe.getBoundingClientRect().top,
      stands = field.getBoundingClientRect().top - SEARCH.ink + base;
    ink =
      getComputedStyle(row).fontSize === getComputedStyle(own).fontSize
        ? Math.round(rowRect.bottom) - Math.round(stands)
        : Math.round(((rowRect.top + rowRect.bottom) / 2 + ownRect.height / 2 - stands) * 1000) / 1000;
  }
  if (ink !== SEARCH.ink) {
    SEARCH.ink = ink;
    field.style.setProperty('--search-ink', ink + 'px');
  }
}
// Whether the search is offered: not in the changes view (its PDF is a comparison, not the manuscript) and not while
// the PDF on screen cannot be read (PNG fallback, or not open yet). Hides the field and the navigation sheet's row
// otherwise, and a search that was open ends.
function searchOffer() {
  const off = document.body.classList.contains('revision-open') || !VECTOR_PDF.doc;
  if (off) searchClose(false);
  $('#doc-search').hidden = off;
  $('#ns-search').hidden = off;
  searchFit();
  if (!off) searchRun();
}
// Discloses the field (the dock on the phone, where an open sheet folds away for it; the opened box elsewhere) without
// moving the focus.
function searchShow() {
  if (SEARCH.open) return;
  SEARCH.open = true;
  document.body.classList.add('search-open');
  $('#search-open').setAttribute('aria-expanded', 'true');
  if (BAND === LAYOUT_BAND.PHONE) {
    SEARCH.side = SIDE_OPEN;
    if (SIDE_OPEN) setSide(false);
  }
  // The box is laid out only now where it was folded: it is measured here.
  searchInk();
  searchCover();
  searchRows();
}
// Remembers what had the focus as the field is entered from outside it: that element, or nothing when that is the page,
// the magnifier (which leads here) or a control of a sheet that closes for the search. Moving inside the field changes
// nothing.
function searchFrom(previous: Element | null) {
  if (previous && $('#search-box').contains(previous)) return;
  SEARCH.back =
    previous instanceof HTMLElement &&
    previous !== document.body &&
    previous !== $('#search-open') &&
    !previous.closest('dialog')
      ? previous
      : null;
}
// The shortcut, the magnifier and the navigation sheet's row: discloses the field and puts the focus in it with its
// text selected, remembering what had the focus. The short band hides its top row while a panel field is typed in
// (body.typing, layout/flow.ts): the row comes back for the field - the focus then leaves the panel field, so the class
// would go anyway. Returns false, the search left as it was, when the field does not take the focus: it is not offered
// (the changes view, no PDF), or its row is out of the layout for another reason - the shortcut is then the browser's,
// and the search is never left open without the focus in its field.
function searchOpen() {
  const searchRoot = $('#doc-search'),
    field = $('#search-q'),
    was = SEARCH.open,
    from = document.activeElement;
  if (searchRoot.hidden) return false;
  searchShow();
  if (!field.getClientRects().length && BAND === LAYOUT_BAND.SHORT) document.body.classList.remove('typing');
  field.focus({ preventScroll: true });
  if (document.activeElement !== field) {
    if (!was) searchHide();
    return false;
  }
  searchFrom(from);
  field.select();
  return true;
}
// Folds the disclosed field away; the phone's sheet comes back up if the search row had taken its place.
function searchHide() {
  if (!SEARCH.open) return;
  SEARCH.open = false;
  SEARCH.back = null;
  document.body.classList.remove('search-open');
  $('#search-open').setAttribute('aria-expanded', 'false');
  if (SEARCH.side) {
    SEARCH.side = false;
    if (BAND === LAYOUT_BAND.PHONE && !SIDE_OPEN) setSide(true);
  }
  searchCover();
}
// Whether an element is on screen to take the focus: in the document, laid out, and not hidden by visibility - a
// popover that is hidden that way keeps its boxes.
function searchShown(element: HTMLElement) {
  return (
    document.contains(element) &&
    element.getClientRects().length > 0 &&
    getComputedStyle(element).visibility !== 'hidden'
  );
}
// Brings what the search was opened from back into view when it went out of it meanwhile: the note popover with its
// selection box (scrolled back to where [보기] puts a mark) or the composer's field in its panel.
function searchBringBack(to: HTMLElement) {
  // the box the note popover stands by, read only when the popover holds `to`
  const popoverBox = $('#sel-pop').contains(to) ? pageSelection().popoverBox() : null;
  if (popoverBox) {
    const boxRect = popoverBox.getBoundingClientRect(),
      area = popoverFreeArea(),
      pdfArea = $('#left');
    const off = boxRect.top < area.top + 8 || boxRect.bottom > area.bottom - 8,
      aside = boxRect.left < area.left + 8 || boxRect.right > area.right - 8;
    if (off || aside) endJumpForScroll();
    if (off) pdfArea.scrollTop += boxRect.top - (area.top + (area.bottom - area.top) * 0.3);
    if (aside) pdfArea.scrollLeft += (boxRect.left + boxRect.right) / 2 - (area.left + area.right) / 2;
    pageSelection().placePopover();
  } else if ($('#composer').contains(to)) to.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}
// Esc, [검색 닫기] and leaving the manuscript: the query and its hits go and the field folds away. back moves the focus
// out of the closed field: to what had it before the field was entered if that is still on screen - the note popover or
// the composer is brought back into view for it - else to the PDF's scroller; with nothing remembered, to the control
// that leads to the search (the magnifier, the phone's position button) and without one to the PDF's scroller. The
// focus is never left in the closed field.
function searchClose(back: boolean) {
  const searchRoot = $('#doc-search'),
    field = $('#search-q'),
    had = searchRoot.contains(document.activeElement),
    to = SEARCH.back,
    was = SEARCH.open;
  field.value = '';
  searchRun();
  if (!was) return;
  // Clearing disables the arrows: one that had the focus loses it there, and the field folds at once.
  searchHide();
  if (!back || !had) return;
  if (to && !searchShown(to) && to.closest('#sel-pop,#composer')) searchBringBack(to);
  const next = to
    ? searchShown(to)
      ? to
      : null
    : BAND === LAYOUT_BAND.PHONE
      ? $('#btn-pos')
      : searchRoot.dataset.mode === 'icon'
        ? $('#search-open')
        : null;
  if (next) next.focus({ preventScroll: true });
  // A control that would not take the focus leaves it on the page, never in the field.
  if (!next || document.activeElement !== next) searchToPage();
}
// Another build is on screen (openVectorDocument): the query, its hits and the reading of the old text end; the field
// stays open while it has the focus, else it folds away with the bar whole again.
function searchClear() {
  $('#search-q').value = '';
  searchRun();
  if (SEARCH.open && !$('#doc-search').contains(document.activeElement)) searchHide();
}
// Another document is being opened (switchDoc, by any route): the search ends at once - query, hits and the open field,
// the bar whole again in this frame - and a focus that was in the field goes back as Esc gives it.
function searchLeave() {
  searchClose(true);
}
$('#search-q').addEventListener('input', searchRun);
// An input method composing in the field (Hangul): its states between keys are searched as typed - but for a jamo
// standing alone (searchRun) - and none of them is announced; the result is announced once the composition ends.
$('#search-q').addEventListener('compositionstart', () => {
  SEARCH.composing = true;
});
$('#search-q').addEventListener('compositionend', () => {
  SEARCH.composing = false;
  searchRun();
  searchPaint();
});
// Entering the field (a click or a Tab into it) discloses it and remembers what had the focus - not when the window
// comes back with the focus still in it. It folds away again when the focus leaves the search with nothing typed.
$('#search-box').addEventListener('focusin', (event: FocusEvent) => {
  if (SEARCH.away) {
    SEARCH.away = false;
    return;
  }
  const from = event.relatedTarget instanceof Element ? event.relatedTarget : null;
  if (!(from && $('#search-box').contains(from))) searchFrom(from);
  if (event.target === $('#search-q')) searchShow();
});
$('#doc-search').addEventListener('focusout', (event: FocusEvent) => {
  const to = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (to && $('#doc-search').contains(to)) return;
  // The window lost the focus, not the field.
  if (!document.hasFocus()) {
    SEARCH.away = $('#search-box').contains(eventElement(event));
    return;
  }
  if (SEARCH.open && !SEARCH.q) searchHide();
});
// Keys in the search: Enter is the next hit and Shift+Enter the previous (not while an input method composes); Esc ends
// the search. Neither reaches the viewer's own keys (main.ts), so Esc here never cancels a selection or a draft - but
// with the search closed and empty (the focus on its magnifier) there is nothing to end, and Esc is the viewer's.
$('#doc-search').addEventListener('keydown', (event: KeyboardEvent) => {
  if (imeKey(event)) return;
  if (event.key === 'Escape') {
    if (!SEARCH.open && !SEARCH.q) return;
    event.preventDefault();
    event.stopPropagation();
    searchClose(true);
  } else if (event.key === 'Enter' && event.target === $('#search-q')) {
    event.preventDefault();
    event.stopPropagation();
    searchGo(event.shiftKey ? -1 : 1);
  }
});
// The shortcut (searchKey): the field takes the focus instead of the browser's find, which finds nothing in a canvas.
// Pressed again in the field, under a sheet, or where the search is not offered, it is the browser's.
function searchShortcut(event: KeyboardEvent) {
  if (!searchKey(event, IS_MAC) || isMarkdownDoc()) return; // a Markdown document is searched with the browser's find
  if (document.activeElement === $('#search-q') || document.querySelector('dialog[open]')) return;
  if (searchOpen()) event.preventDefault();
}
document.addEventListener('keydown', searchShortcut);
$('#search-hint').textContent = IS_MAC ? '⌘F' : 'Ctrl F';
// The bar's room changes with its width and with its neighbours (the document links drawn, a page count growing, a font
// arriving), and the opened field's width with its count: fitted again on the next frame, never inside the observer.
if (window.ResizeObserver) {
  const fitObserver = new ResizeObserver(() => requestAnimationFrame(searchFit));
  fitObserver.observe($('#doc-nav'));
  fitObserver.observe($('#search-box'));
  for (const child of $('#doc-nav').children) if (child.id !== 'doc-search') fitObserver.observe(child);
  // The short band moves the status line into the bar (documents/view-status.ts); a new message changes its width.
  fitObserver.observe($('#status'));
}
// ... or not: while the field holds the status to a max-width its box keeps that width whatever it says, so a new
// message is watched as it is drawn too.
new MutationObserver(() => requestAnimationFrame(searchFit)).observe($('#status'), {
  childList: true,
  subtree: true,
  characterData: true,
  attributes: true,
  attributeFilter: ['hidden'],
});
document.fonts.addEventListener('loadingdone', searchFit);
function watchSearchDismissal() {
  // A press anywhere else folds an empty field away too: a tap on the page takes no focus, so on a touch screen the field
  // would stay up (and its keyboard with it).
  document.addEventListener(
    'pointerdown',
    (event) => {
      if (!SEARCH.open || SEARCH.q || $('#doc-search').contains(eventElement(event))) return;
      const focused = focusedElement();
      searchHide();
      if (focused && $('#doc-search').contains(focused)) focused.blur();
    },
    true,
  );
}

export {
  watchSearchDismissal,
  SEARCH,
  pageText,
  searchClear,
  searchClose,
  searchFit,
  searchGo,
  searchLeave,
  searchOffer,
  searchOpen,
};
