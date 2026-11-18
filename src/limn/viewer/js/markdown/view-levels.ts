/** Resolve source ranges into the line, block and section choices offered for a pin. */
import { $, findClosest, findAll } from '../platform/dom.ts';
import { MARKDOWN_VIEW } from './state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { isTextDoc, isMarkdownDoc } from '../documents/state.ts';
import { textSurface } from './state-seams.ts';
import { clipMarkedText } from '../platform/hidden-chars.ts';
import { DOC } from '../app/state.ts';
import { lineLeaves } from './view-reading.ts';

// ---------------- Picking: selection -> lines, and the ladder
// The lines a DOM point is on: its line span's, else its nearest block's range, else null (outside the document).
function linesAt(node: Node | null) {
  const element = node && (node instanceof Element ? node : node.parentElement);
  if (!element) return null;
  const column = $('#md');
  if (!column || !column.contains(element)) return null;
  // The nearest carrier wins. A drawn formula that was cut at a line end sits inside the span of the line it starts in
  // and carries the lines it covers itself (drawInline): those are the point's lines, not that one line's.
  const near = findClosest(element, '[data-line],[data-lo]', HTMLElement);
  if (near && column.contains(near)) {
    const line = +(near.dataset.line || 0);
    if (line) return { lo: line, hi: line };
    if (near.dataset.lo !== undefined) return { lo: +(near.dataset.lo || 0), hi: +(near.dataset.hi || 0) };
  }
  const block = findClosest(element, '[data-lo]', HTMLElement);
  return block && column.contains(block) ? { lo: +(block.dataset.lo || 0), hi: +(block.dataset.hi || 0) } : null;
}
// The block a point belongs to for the ladder's second rung: a table row's table, a list item's or a quote's
// paragraph's item or quote, else its nearest block (a run of text whose lines could not be told - kind 'lines',
// drawInline - stands for the block it is in).
function blockAt(node: Node | null) {
  const element = node && (node instanceof Element ? node : node.parentElement);
  if (!element) return null;
  let block = findClosest(element, '#md [data-lo]', HTMLElement);
  if (block && block.dataset.kind === 'lines' && block.parentElement)
    block = findClosest(block.parentElement, '#md [data-lo]', HTMLElement);
  if (!block) return null;
  if (block.dataset.kind === 'row') block = findClosest(block, 'table[data-lo]', HTMLElement) || block;
  else if (
    block.dataset.kind === 'paragraph' &&
    block.parentElement &&
    /^(item|quote)$/.test(block.parentElement.dataset.kind || '')
  )
    block = block.parentElement; // a list item's or a quote's own paragraph is that block
  // A heading or a rule is no block of its own (ADR-0025 D3's block kinds): the block it stands in, if any, is.
  while (block && !BLOCK_KINDS.includes(block.dataset.kind || ''))
    block = block.parentElement ? findClosest(block.parentElement, '#md [data-lo]', HTMLElement) : null;
  return block;
}
// The block kinds a block rung takes (its pin kind is md:<kind>, ADR-0025 D3; front, math: ADR-0032) and their names on
// the ladder.
const BLOCK_KINDS = ['paragraph', 'item', 'table', 'code', 'quote', 'html', 'front', 'math'];
const BLOCK_SELECTOR = BLOCK_KINDS.map((kind) => '[data-lo][data-kind="' + kind + '"]').join(',');
// The blocks lines first..last meet, outermost: each element of a block kind on screen whose lines meet first..last and
// that no other such element meeting them holds (a quote's paragraphs are the quote; a list's items are each a block).
function blocksMeeting(first: number, last: number) {
  const column = $('#md');
  if (!column) return [];
  const meets = (element: HTMLElement) => +(element.dataset.lo || 0) <= last && +(element.dataset.hi || 0) >= first;
  return findAll(column, BLOCK_SELECTOR, HTMLElement).filter((element) => {
    if (!meets(element)) return false;
    const up = element.parentElement && findClosest(element.parentElement, BLOCK_SELECTOR, HTMLElement);
    return !(up && column.contains(up) && meets(up));
  });
}
const BLOCK_LABEL: Record<string, string> = {
  paragraph: '문단',
  item: '목록 항목',
  table: '표',
  code: '코드 블록',
  quote: '인용',
  html: 'HTML 블록',
  front: '머리 정보',
  math: '수식',
};
function lineSnippet(first: number, last: number) {
  const out: string[] = [];
  for (let line = first; line <= Math.min(last, first + 79); line++)
    out.push(String(line).padStart(5, ' ') + '  ' + (MARKDOWN_VIEW.lines[line - 1] || ''));
  if (last - first + 1 > 80) out.push('      … ' + translateTemplate('{n}줄 더', { n: last - first + 1 - 80 }));
  return out.join('\n');
}
// The section around lines first..last: from the nearest heading at or above first to the line before the next heading
// of the same or a higher level (the file's end when none), its trailing blank lines left out. null above the first
// heading, or when last is past it.
function sectionAround(first: number, last: number) {
  let heading: { level: number; lo: number; title: string } | null = null;
  for (const head of MARKDOWN_VIEW.heads) {
    if (head.lo <= first) heading = head;
    else break;
  }
  if (!heading) return null;
  let end = MARKDOWN_VIEW.lines.length;
  for (const head of MARKDOWN_VIEW.heads) {
    if (head.lo > heading.lo && head.level <= heading.level) {
      end = head.lo - 1;
      break;
    }
  }
  while (end > heading.lo && !String(MARKDOWN_VIEW.lines[end - 1] || '').trim()) end--;
  if (end < last) return null;
  return { lo: heading.lo, hi: end, title: heading.title };
}
// The ladder for lines range (a drag or a tap) and the blocks its start and end are in (startBlock, endBlock: blockAt):
// the chosen lines, the block when both ends are in one - else, when they meet two or more blocks (blocksMeeting),
// those blocks whole ('블록 N개', level blocks: saved as lines, kindFor) - and the heading's section; a rung with the
// range of one before it merges into that one. A block rung carries its block kind as env (kindFor: md:<kind>). A tap
// (tapped) picks its block: when the block is no more than the tapped lines (an HTML block, a one-line paragraph) its
// rung stands first and the chosen lines merge into it, so the pin is md:<kind> as any other tapped block's - merged
// the other way, the tap's block would be saved as lines.
function markdownLevels(
  range: { lo: number; hi: number },
  startBlock: HTMLElement | null,
  endBlock: HTMLElement | null,
  tapped?: boolean,
) {
  if (isTextDoc()) return textSurface().levels(range); // a text document's rungs come from its lines alone
  const rungs: Rung[] = [];
  const add = (level: string, label: string, first: number, last: number, env: string | null) => {
    const same = rungs.find((rung) => rung.lo === first && rung.hi === last);
    if (same) {
      (same.merged = same.merged || []).push(level);
      return;
    }
    rungs.push({
      level,
      label,
      lo: first,
      hi: last,
      n: last - first + 1,
      snippet: lineSnippet(first, last),
      env: env || null,
    });
  };
  const kind = startBlock && startBlock === endBlock ? startBlock.dataset.kind || 'paragraph' : '',
    blockStart = startBlock ? Math.min(+(startBlock.dataset.lo || 0), range.lo) : 0,
    blockEnd = startBlock ? Math.max(+(startBlock.dataset.hi || 0), range.hi) : 0;
  const blockFirst = !!(tapped && kind && blockStart === range.lo && blockEnd === range.hi);
  if (blockFirst) add('block', BLOCK_LABEL[kind] || '블록', blockStart, blockEnd, kind);
  add('raw', '고른 줄', range.lo, range.hi, null);
  if (kind) {
    if (!blockFirst) add('block', BLOCK_LABEL[kind] || '블록', blockStart, blockEnd, kind);
  } else {
    const blocks = blocksMeeting(range.lo, range.hi);
    if (blocks.length > 1)
      add(
        'blocks',
        translateTemplate('블록 {n}개', { n: blocks.length }),
        Math.min(range.lo, ...blocks.map((block) => +(block.dataset.lo || 0))),
        Math.max(range.hi, ...blocks.map((block) => +(block.dataset.hi || 0))),
        null,
      );
  }
  const section = sectionAround(range.lo, range.hi);
  // the heading's hidden characters by name (clipMarkedText, ADR-0029 D5)
  if (section)
    add('section', translate('절') + ' · ' + clipMarkedText(section.title, 18), section.lo, section.hi, null);
  return rungs;
}
// The ladder of an edit card on a pin of this document: its lines' rungs from the drawn document (markdownLevels), or
// none when the document on screen is another or is not drawn (the line view, a notice) - the card then keeps the lines
// it has.
function editCardLevels(edit: { doc?: string | null; lo?: number | null; hi?: number | null }) {
  if (!isMarkdownDoc() || edit.doc !== DOC || typeof edit.lo !== 'number' || typeof edit.hi !== 'number') return null;
  const first = lineLeaves(edit.lo, edit.lo)[0],
    last = lineLeaves(edit.hi, edit.hi)[0];
  if (!first && !last) return null;
  const rungs = markdownLevels(
    { lo: edit.lo, hi: edit.hi },
    first ? blockAt(first) : null,
    last ? blockAt(last) : null,
  );
  return rungs.length > 1 ? rungs : null;
}

export { markdownLevels, lineSnippet, linesAt, blockAt, editCardLevels };
