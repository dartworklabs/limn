// ------------------------------------------------ The rendered compare of a Markdown document ([그린 비교])
// The changes view's rendered compare (docs/handbook/viewer.md §변경 보기, ADR-0031). The document's own file on the
// two sides the source diff compares (GET /api/revision-source: the commit's first parent and the commit, or a range's
// old side and its commit) is parsed in a worker of its own and drawn by the Markdown surface's renderer (renderTokens)
// with a render context of its own per side (newRenderContext), pausing for the browser as the document view does; the
// two drawn documents are then compared block by block (a paragraph, a heading, a list item's own text, a table row, a
// code block, display math, the front matter, a rule, a raw HTML placeholder): a block the other side has as it is, one
// changed in place (its words marked), one added, one taken out, one moved. One column: the new side, with the
// taken-out blocks put back where they were. Nothing here picks, pins or follows an in-document link: the view reads.
// Images are the manuscript tree's files of now (GET /api/asset, as the Markdown surface draws them) on both sides -
// the old side's own image files are not read; a line above the compare says so whenever a side has one. A character
// that would hide or reorder text stays in its box (drawText) on both sides, and a changed one is a changed word.
import { LAYOUT, scrollMotion } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { markHiddenHtml, markHiddenPlain } from '../platform/hidden-chars.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { REVISION_VIEW, hunkRanges, revisionKey, drawPinGuide, revisionCurrent, revisionPinFor } from './flow.ts';
import {
  MARKDOWN_VIEW,
  MARKDOWN_LIMITS,
  OVER_ELEMENT_LIMIT,
  limitText,
  formatMebibytes,
  renderTokens,
  newRenderContext,
  keepRenderContext,
  waitLine,
  yieldToBrowser,
  markedCharactersText,
} from '../markdown/view.ts';
import { $ } from '../platform/dom.ts';
import { DIFF_FORMAT, LAYOUT_MODE, MARKDOWN_LIMIT, SCOPE_MODE, SCOPE_SOURCE } from '../app/rules-tables.ts';
import { isMarkdownDoc, isTextDoc, withDocQuery } from '../documents/state.ts';
// RENDERED_COMPARE: the compare on screen (key: revisionKey() it was drawn for), its parse worker and job, the change
// groups in order (stops, each the blocks of one change) and the one the navigator is at, the drawn column (root) and
// the observer that lays its gutter chips out again when its width changes (ro), the status line it said (line) and
// what it counted (said: the answer and the counts, so a range's line can take the source diff's commit and file counts
// once they come).
const RENDERED_COMPARE = {
  seq: 0,
  key: '',
  worker: null as Worker | null,
  job: null as { id: number; resolve: (answer: any) => void; t: ReturnType<typeof setTimeout> } | null,
  stops: [] as HTMLElement[][],
  at: -1,
  ro: null as ResizeObserver | null,
  root: null as HTMLElement | null,
  line: '',
  said: null as { r: any; c: { ins: number; del: number; mod: number; move: number } | null } | null,
};
// the most cells one block or word comparison fills; past it the blocks between the common ends are all changed
const MAX_DIFF_CELLS = 4e6;
// The most steps one compare spends matching (every subsequence's table cells) and pairing (the words of each pair of
// blocks it weighs): past it no more blocks are paired and no more words marked - what is left is added and taken out
// as it is, at once.
const COMPARE_WORK_STEPS = 8e6;
const UNIT_SELECTOR = 'p,h1,h2,h3,h4,h5,h6,pre,tr,hr,li,.md-html,.md-html-run,.md-front';
// The boxes markRegroups looks at, a split or a join of which the two kept blocks beside it show: a quote, a list, a
// list item.
const REGROUP_BOX_TAGS = /^(?:BLOCKQUOTE|UL|OL|LI)$/;
const CHIP_WORDS: Record<string, string> = { ins: '더함', del: '뺌', mod: '고침', move: '옮김' };
// Whether the document on screen is drawn from Markdown (the rendered compare's documents): a text document shows its
// lines as they are, and its source diff is that already.
function isDrawnFromMarkdown() {
  return isMarkdownDoc() && !isTextDoc();
}
// ---------------- Parsing both sides, apart from the Markdown surface's own worker
function parseSide(text: string): Promise<any> {
  stopSideParse(null);
  return new Promise((resolve) => {
    let worker = RENDERED_COMPARE.worker;
    try {
      if (!worker) {
        worker = new Worker('/md-parse.mjs', { type: 'module' });
        RENDERED_COMPARE.worker = worker;
        worker.onmessage = (message) => {
          const job = RENDERED_COMPARE.job;
          if (!job || !message.data || message.data.id !== job.id) return;
          clearTimeout(job.t);
          RENDERED_COMPARE.job = null;
          job.resolve(message.data);
        };
        worker.onerror = (event) => {
          event.preventDefault();
          stopSideParse({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
        };
      }
    } catch (error) {
      resolve({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
      return;
    }
    const id = ++MARKDOWN_VIEW.seq;
    RENDERED_COMPARE.job = {
      id,
      resolve,
      t: setTimeout(() => stopSideParse({ ok: false, limit: MARKDOWN_LIMIT.TIME }), MARKDOWN_LIMITS.ms),
    };
    worker.postMessage({
      id,
      text,
      limits: { nesting: MARKDOWN_LIMITS.nesting, blocks: MARKDOWN_LIMITS.blocks, inlines: MARKDOWN_LIMITS.inlines },
    });
  });
}
function stopSideParse(answer: any) {
  const job = RENDERED_COMPARE.job;
  if (!job) return;
  RENDERED_COMPARE.job = null;
  clearTimeout(job.t);
  if (RENDERED_COMPARE.worker) {
    RENDERED_COMPARE.worker.terminate();
    RENDERED_COMPARE.worker = null;
  }
  job.resolve(answer);
}
// One side drawn with the Markdown surface's renderer (renderTokens) into a root of its own, with a render context of
// its own (newRenderContext: its lines, its element count, its marked characters, its headings - the document view's
// MARKDOWN_VIEW is never touched), with a yield to the browser whenever renderTokens pauses (every
// MARKDOWN_LIMITS.chunk units of work, as the document view builds) and live() asked after each: null past
// MARKDOWN_LIMITS.elements, or once live() is false (a newer compare). Ids go (a heading's: the surface keeps them),
// and an in-document heading or another document is a word here, so the view never leaves for the manuscript.
async function buildSide(tokens: any[], lines: string[], live: () => boolean): Promise<HTMLElement | null> {
  const root = document.createElement('div'),
    context = newRenderContext(lines);
  root.className = 'md mdc-doc';
  root.setAttribute('translate', 'no');
  root.lang = '';
  try {
    for (const pause of renderTokens(root, tokens, context)) {
      void pause;
      await yieldToBrowser();
      if (!live()) return null;
    }
  } catch (error) {
    if (error === OVER_ELEMENT_LIMIT) return null;
    throw error;
  }
  keepRenderContext(root, context); // an image that fails later draws its alt text on this side's count (onImageError)
  root.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'));
  root.querySelectorAll('[data-act="md-anchor"],[data-act="md-doc"]').forEach((element) => {
    const link = element as HTMLElement;
    delete link.dataset.act;
    link.removeAttribute('role');
    link.removeAttribute('tabindex');
    link.dataset.tip = translate('비교 화면에서는 문서 안 링크를 따라가지 않습니다');
  });
  return root;
}
// ---------------- Blocks and their keys
type CompareUnit = {
  el: HTMLElement;
  tag: string;
  key: string;
  text: string;
  pics: string;
  shape: string;
  box: string;
  grp: unknown[];
  alts: string;
  lo: number;
  hi: number;
};
// Whether element is a block another unit stands for: a list, a nested paragraph or code, a quote, a table - a tight
// list item's own text leaves these out.
function isNestedBlock(element: Element) {
  return /^(UL|OL|P|PRE|BLOCKQUOTE|TABLE|DIV|H[1-6]|HR)$/.test(element.tagName);
}
// Whether element, inside unit, is part of the unit's own content: for a list item, nothing between them is a nested
// block (isNestedBlock) - its nested list, a quote or a table in it are units of their own, wherever they sit below it.
// The one boundary of a list item's text (unitText), its structure (inlineShape), its words (unitWords), its images,
// links and alt texts (unitReferences, compareUnits) and its marked links (markChangedLinks). Pure over the DOM.
function isOwnPart(unit: HTMLElement, element: Element) {
  if (unit.tagName !== 'LI') return true;
  for (let ancestor = element as Element | null; ancestor && ancestor !== unit; ancestor = ancestor.parentElement)
    if (isNestedBlock(ancestor)) return false;
  return true;
}
// Whether element (one UNIT_SELECTOR matches) is a unit: not a loose list item (its paragraphs are units of their own),
// not a raw HTML block inside a run (the run is one), not the code box of the front matter (the front matter is one).
function isCompareUnit(element: Element) {
  return (
    !(element.tagName === 'LI' && [...element.children].some((child) => child.tagName === 'P')) &&
    !(element.classList.contains('md-html') && element.closest('.md-html-run')) &&
    !(element.tagName === 'PRE' && element.closest('.md-front'))
  );
}
// A unit's kind as its tag: display math (MATH) and the front matter (FRONT) apart from a code block and a raw HTML
// block, so none of them pairs with another. Pure over the DOM.
function unitTag(unit: HTMLElement) {
  return unit.classList.contains('md-front')
    ? 'FRONT'
    : unit.classList.contains('md-math-block')
      ? 'MATH'
      : unit.tagName;
}
// Whether a unit of that tag is a block of lines (a code block, display math, the front matter): its lines, spaces and
// all, are its words. Pure.
function isLinedTag(tag: string) {
  return tag === 'PRE' || tag === 'MATH' || tag === 'FRONT';
}
// The lines of a block of lines, each as it is (without its line end). Pure over the DOM.
function blockLines(unit: HTMLElement) {
  return [...unit.querySelectorAll('.ln')].map((line) => String(line.textContent || '').replace(/\n$/, ''));
}
// The comparable blocks of a drawn side, in document order (pure over the DOM): every paragraph, heading, code block,
// display math, front matter, table row, rule and raw HTML placeholder, and a list item whose text is its own (a tight
// list's). A raw HTML run is one unit. Each has its tag, its key, its text, its source lines, the parts of its key that
// are not words and the very boxes it sits in (grp: its box elements, outermost first - which quote, which list,
// markRegroups). The key is everything the block shows: its text with its inline structure (shape: emphasis, code,
// links, images with their alt text, a hidden character's box with the character, a table cell's alignment), the boxes
// it sits in (box: a quote, a list - a numbered one with its first number), its images' tree paths and its links'
// targets. So the same words in bold, out of a quote, in a list renumbered or in a column aligned the other way are
// another block - changed in place, as are an image's new alt text, a link's new target and a hidden character put in
// or taken out. What the renderer adds that shows nothing is not in it (inlineShape): the line spans, the copies of an
// emphasis or a link it opens again after a line break inside it, an inline formula's code box per source line - a
// paragraph rewrapped, inside bold, a link or a formula too, is the same block. An alt text is compared with its white
// space folded, as it is drawn.
function compareUnits(root: HTMLElement): CompareUnit[] {
  const out = [] as CompareUnit[];
  for (const match of root.querySelectorAll(UNIT_SELECTOR)) {
    const unit = match as HTMLElement;
    if (!isCompareUnit(unit)) continue;
    const tag = unitTag(unit),
      text = unitText(unit, tag),
      reopened = new Set() as Set<Element>,
      shape = inlineShape(unit, tag, reopened);
    const groupBoxes = boxElements(unit, root),
      linkTargets = unitReferences(unit, 'a,[data-anchor],.md-rel', reopened),
      pics = unitReferences(unit, '.md-pic,.md-img'),
      box = boxKinds(groupBoxes),
      alts = [...unit.querySelectorAll('img')]
        .filter((image) => isOwnPart(unit, image))
        .map((image) => (image.getAttribute('alt') || '').replace(/\s+/g, ' ').trim())
        .join('\u0001');
    const firstLine = +(unit.dataset.lo || unit.dataset.rLo || 0),
      lastLine = +(unit.dataset.hi || unit.dataset.rHi || firstLine);
    out.push({
      el: unit,
      tag,
      key: [tag, box, shape, pics, linkTargets].join('\u0001'),
      text,
      pics,
      shape,
      box,
      grp: groupBoxes,
      alts,
      lo: firstLine,
      hi: lastLine,
    });
  }
  return out;
}
// The boxes a unit sits in below the drawn root, outermost first: the elements. Pure over the DOM.
function boxElements(unit: HTMLElement, root: HTMLElement): Element[] {
  const out: HTMLElement[] = [];
  for (let ancestor = unit.parentElement; ancestor && ancestor !== root; ancestor = ancestor.parentElement)
    out.unshift(ancestor);
  return out;
}
// Those boxes (boxElements) as one string: each box's tag, a numbered list's with the number it starts at (OL5). Pure
// over the DOM.
function boxKinds(boxes: Element[]) {
  return boxes.map((box) => (box.tagName === 'OL' ? 'OL' + (box.getAttribute('start') || '1') : box.tagName)).join('>');
}
// The name an inline element goes by in a block's structure (inlineShape) and a word's place (unitWords): its tag, and
// for code its kind too (inline math and an inline HTML tag are code boxes of their own). Pure over the DOM.
function inlineName(element: Element) {
  return (
    element.tagName.toLowerCase() + (element.tagName === 'CODE' && element.className ? '.' + element.className : '')
  );
}
// A unit's inline structure as one string: its text, whitespace folded, with every inline element around its part as a
// mark (<strong>…</strong>, <code.md-math>…</code.md-math>, an image as <img alt>, a hidden character's box as <cc
// char>, a table cell with its alignment as <td right>), a list item's nested blocks and the screen reader's words left
// out. What the renderer adds and nothing shows is no structure: the line spans it puts round each source line, the
// shallow copies of the emphasis and links open at a line break that it opens again on the next line's span
// (drawInline), and the code box it draws for each source line of an inline formula (math_inline, one per line) - an
// emphasis or a link that starts right where one of the same kind and target ends is one run (isReopenedRun), and so is
// a formula's piece after the last one's, white space alone between them. So a paragraph wrapped on other lines, inside
// bold, a link or a formula too, reads the same. A link's copy goes in reopened (when given), so it is not counted
// twice (unitReferences). A block of lines' shape is its language (a code block's fence's info word) and its lines
// exactly as they are (linedShape). Pure over the DOM but for reopened.
function inlineShape(unit: HTMLElement, tag: string, reopened?: Set<Element>) {
  if (isLinedTag(tag)) return linedShape(tag === 'PRE' ? unit.dataset.lang || '' : '', blockLines(unit));
  const out = [] as (string | { t: string; to: string })[];
  const walk = (node: Node) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) {
        if (child.nodeValue) out.push(child.nodeValue);
        continue;
      }
      if (child.nodeType !== 1) continue;
      const element = child as HTMLElement;
      if ((unit.tagName === 'LI' && isNestedBlock(element)) || element.classList.contains('sr-only')) continue;
      if (element.classList.contains('cc')) {
        out.push('\u0002cc ' + (element.textContent || '') + '\u0003');
        continue;
      }
      if (element.classList.contains('ln') && element.tagName === 'SPAN') {
        walk(element);
        continue;
      }
      const name = inlineName(element);
      if (name === 'img') {
        out.push('\u0002img ' + (element.getAttribute('alt') || '') + '\u0003');
        continue;
      }
      const to = isReopenedRun(element) ? '\u0001' + linkTarget(element) : name === 'code.md-math' ? '' : null;
      let lastAt = out.length - 1;
      if (name === 'code.md-math')
        // a formula's pieces: one line end apart
        while (lastAt >= 0 && typeof out[lastAt] === 'string' && !/\S/.test(out[lastAt] as string)) lastAt--;
      const last = out[lastAt];
      if (to !== null && typeof last === 'object' && last.t === name && last.to === to) {
        out.splice(lastAt, 1);
        if (reopened && to) reopened.add(element);
        walk(element);
        out.push(last);
        continue;
      } // the same run, on the next line
      const align = /^T[DH]$/.test(element.tagName)
        ? (/(?:^|\s)md-al-(left|right|center)(?:\s|$)/.exec(element.className) || [])[1]
        : '';
      out.push('\u0002' + name + (align ? ' ' + align : '') + '\u0003');
      walk(element);
      out.push({ t: name, to: to === null ? '\u0000' : to });
    }
  };
  walk(unit);
  return out
    .map((part) => (typeof part === 'string' ? part : '\u0002/' + part.t + '\u0003'))
    .join('')
    .replace(/\s+/g, ' ')
    .trim();
}
// Whether an inline element is one the renderer opens again after a line break inside it (drawInline's stack): an
// emphasis, a strikethrough, a link - an inert one (.md-rel) too. Pure over the DOM.
function isReopenedRun(element: HTMLElement) {
  return (
    /^(STRONG|EM|S|A)$/.test(element.tagName) || (element.tagName === 'SPAN' && element.classList.contains('md-rel'))
  );
}
// Where a link element points (its target, as unitReferences names it; '' for an emphasis). Pure over the DOM.
function linkTarget(element: HTMLElement) {
  return element.dataset.tipUrl || element.getAttribute('href') || element.dataset.anchor || '';
}
// A block of lines' inline structure: its language (a code block's fence's info word, '' for any other) and its lines,
// spaces and all, serialized without ambiguity (JSON after a marker no other shape starts with) - so a code block whose
// body or language changed is another block, an empty fence ([]) is not one holding a blank line (['']), and no
// character in a language or a line can make two different blocks read alike. Pure.
function linedShape(lang: string, lines: string[]) {
  return '\u0002pre\u0003' + JSON.stringify([lang, lines]);
}
// The language a code block's shape (linedShape) carries, '' for any other shape. Pure.
function shapeLanguage(shape: string) {
  if (!shape.startsWith('\u0002pre\u0003')) return '';
  try {
    return String(JSON.parse(shape.slice(5))[0]);
  } catch {
    return '';
  }
}
// What changed in a block changed in place, beyond the words marked in it: its own change (ownChangeReason), then the
// boxes split or joined at it (how, markRegroups's) - '' when only its words changed (the marked words say what). Pure.
function changeReason(oldUnit: CompareUnit, newUnit: CompareUnit, how?: string[]) {
  const box = (how || []).map((change) =>
    change === 'split' ? translate('인용·목록이 둘로 갈라짐') : translate('인용·목록이 하나로 합쳐짐'),
  );
  return [ownChangeReason(oldUnit, newUnit), ...box].filter(Boolean).join(' · ');
}
// What changed in a block changed in place whose text stayed: its inline structure, an image's alt text, a table cell's
// alignment, the list numbering, the boxes it sits in, a block of lines' language or spaces - '' when its words changed
// (the marked words say what). Pure.
function ownChangeReason(oldUnit: CompareUnit, newUnit: CompareUnit) {
  if (oldUnit.text !== newUnit.text) return '';
  if (oldUnit.alts !== newUnit.alts) return translate('그림 대체 글이 바뀜');
  if (oldUnit.tag === 'PRE' && oldUnit.shape !== newUnit.shape)
    return shapeLanguage(oldUnit.shape) !== shapeLanguage(newUnit.shape)
      ? translate('코드 언어가 바뀜')
      : translate('코드의 공백·들여쓰기가 바뀜');
  if (isLinedTag(oldUnit.tag) && oldUnit.shape !== newUnit.shape) return translate('줄의 공백·들여쓰기가 바뀜');
  if (oldUnit.shape !== newUnit.shape && unalignedShape(oldUnit.shape) === unalignedShape(newUnit.shape))
    return translate('표 칸 정렬이 바뀜');
  if (oldUnit.shape !== newUnit.shape) return translate('글자 모양(굵게·기울임·코드·링크)이 바뀜');
  if (oldUnit.box !== newUnit.box)
    return oldUnit.box.replace(/OL\d+/g, 'OL') === newUnit.box.replace(/OL\d+/g, 'OL')
      ? translate('목록 번호가 바뀜')
      : translate('인용·목록 안팎으로 자리가 바뀜');
  return '';
}
// A shape (inlineShape) without its table cells' alignment. Pure.
function unalignedShape(shape: string) {
  return shape.replace(/(\u0002t[dh]) (?:left|right|center)\u0003/g, '$1\u0003');
}
// A unit's own text: a table row's cells joined with ' | ', a list item's without its nested blocks, a block of lines'
// lines, whitespace folded; a hidden character is in it (its box keeps it for the screen reader).
function unitText(unit: HTMLElement, tag: string) {
  if (unit.tagName === 'TR')
    return [...unit.children].map((cell) => (cell.textContent || '').replace(/\s+/g, ' ').trim()).join(' | ');
  if (isLinedTag(tag)) return blockLines(unit).join('\n').replace(/\s+/g, ' ').trim();
  let text = '';
  const walk = (node: Node) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) text += child.nodeValue;
      else if (child.nodeType === 1 && !(unit.tagName === 'LI' && isNestedBlock(child as Element))) walk(child);
    }
  };
  walk(unit);
  return text.replace(/\s+/g, ' ').trim();
}
// What a unit's images (selector '.md-pic,.md-img': tree path or alt text) or links (their targets) point at, in order
// - its own (isOwnPart: not those of a quote, a table or a list nested in a list item, which are in those blocks'
// keys); a link the renderer opened again after a line break inside it (skip, from inlineShape) is the link before it,
// not counted again.
function unitReferences(unit: HTMLElement, selector: string, skip?: Set<Element>) {
  const out: string[] = [];
  for (const match of unit.querySelectorAll(selector)) {
    const element = match as HTMLElement;
    if (!isOwnPart(unit, element) || (skip && skip.has(element))) continue;
    out.push(
      element.dataset.path ||
        element.dataset.tipUrl ||
        element.getAttribute('href') ||
        element.dataset.anchor ||
        element.textContent ||
        '',
    );
  }
  return out.join(' ');
}
// ---------------- Comparing sequences
// A compare's work budget (COMPARE_WORK_STEPS steps), spent by commonSubsequence, blockOps and markChangedWords.
type CompareBudget = { left: number };
function newCompareBudget(): CompareBudget {
  return { left: COMPARE_WORK_STEPS };
}
// The longest common subsequence of left and right (same tests two items) as ops in order - {t:'eq',a,b}, {t:'del',a},
// {t:'ins',b} - its common ends taken first, and within each gap the deletions before the insertions. Its table's cells
// are spent from budget (when given); past MAX_DIFF_CELLS or what the budget has left the middle is all deleted and
// inserted (never a wrong match) and the budget is spent out, so the compare pairs nothing more. Pure but for the
// budget.
function commonSubsequence<Item>(
  left: Item[],
  right: Item[],
  same: (first: Item, second: Item) => boolean,
  budget?: CompareBudget,
): { t: string; a: number; b: number }[] {
  const ops: { t: string; a: number; b: number }[] = [];
  let start = 0;
  while (start < left.length && start < right.length && same(left[start], right[start])) start++;
  let leftEnd = left.length,
    rightEnd = right.length;
  while (leftEnd > start && rightEnd > start && same(left[leftEnd - 1], right[rightEnd - 1])) {
    leftEnd--;
    rightEnd--;
  }
  for (let i = 0; i < start; i++) ops.push({ t: 'eq', a: i, b: i });
  const leftGap = leftEnd - start,
    rightGap = rightEnd - start;
  if (budget) budget.left -= left.length + right.length; // the ends just walked
  if (leftGap * rightGap > MAX_DIFF_CELLS || (budget && leftGap * rightGap > budget.left)) {
    if (budget && leftGap * rightGap) budget.left = 0;
    for (let i = start; i < leftEnd; i++) ops.push({ t: 'del', a: i, b: -1 });
    for (let j = start; j < rightEnd; j++) ops.push({ t: 'ins', a: -1, b: j });
  } else {
    if (budget) budget.left -= leftGap * rightGap;
    const rowWidth = rightGap + 1,
      table = new Uint32Array((leftGap + 1) * rowWidth);
    for (let i = leftGap - 1; i >= 0; i--)
      for (let j = rightGap - 1; j >= 0; j--)
        table[i * rowWidth + j] = same(left[start + i], right[start + j])
          ? table[(i + 1) * rowWidth + j + 1] + 1
          : Math.max(table[(i + 1) * rowWidth + j], table[i * rowWidth + j + 1]);
    let leftAt = 0,
      rightAt = 0;
    while (leftAt < leftGap && rightAt < rightGap) {
      if (same(left[start + leftAt], right[start + rightAt])) {
        ops.push({ t: 'eq', a: start + leftAt, b: start + rightAt });
        leftAt++;
        rightAt++;
      } else if (table[(leftAt + 1) * rowWidth + rightAt] >= table[leftAt * rowWidth + rightAt + 1]) {
        ops.push({ t: 'del', a: start + leftAt, b: -1 });
        leftAt++;
      } else {
        ops.push({ t: 'ins', a: -1, b: start + rightAt });
        rightAt++;
      }
    }
    for (; leftAt < leftGap; leftAt++) ops.push({ t: 'del', a: start + leftAt, b: -1 });
    for (; rightAt < rightGap; rightAt++) ops.push({ t: 'ins', a: -1, b: start + rightAt });
  }
  for (let k = 0; k < left.length - leftEnd; k++) ops.push({ t: 'eq', a: leftEnd + k, b: rightEnd + k });
  return ops;
}
// The words and marks of a text (pure): letters and digits together, every other visible character alone.
function wordsOfText(text: string) {
  return String(text).match(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu) || [];
}
// How alike two texts are, from their words (wordsOfText, found once per block however many blocks it is weighed
// against): twice the words they share over all their words (1 for two empty texts). Pure.
function wordLikeness(left: string[], right: string[]) {
  if (!left.length && !right.length) return 1;
  const counts = new Map();
  let shared = 0;
  for (const word of left) counts.set(word, (counts.get(word) || 0) + 1);
  for (const word of right) {
    const count = counts.get(word) || 0;
    if (count) {
      shared++;
      counts.set(word, count - 1);
    }
  }
  return (2 * shared) / (left.length + right.length);
}
// the likeness above which a taken-out block and an added one of the same kind in one gap are one block changed in
// place
const PAIR_LIKENESS = 0.4;
// the fewest characters a block taken out and an identical one added elsewhere need to count as one moved block
const MOVE_MIN_CHARS = 6;
// The block ops of two sides (pure over the units, but for the budget): commonSubsequence over the keys, then in each
// gap between unchanged blocks a block taken out and a block added of the same tag, alike enough and in order, become
// one block changed in place ({t:'mod'}); then a block taken out and an identical one added anywhere else are one block
// moved ({t:'from'} where it was, {t:'to'} where it is now). A heading moves at any length, any other block from
// MOVE_MIN_CHARS characters. Weighing a pair spends its words from budget; once it is spent no more pairs are weighed -
// the rest stay taken out and added. Last, two kept blocks a quote or list split or joined between are changed in place
// too (markRegroups, their ops' how).
function blockOps(oldUnits: CompareUnit[], newUnits: CompareUnit[], budget?: CompareBudget) {
  budget = budget || newCompareBudget();
  const raw = commonSubsequence(oldUnits, newUnits, (left, right) => left.key === right.key, budget),
    out: { t: string; a: number; b: number }[] = [];
  let at = 0;
  const words = new Map(),
    wordsOf = (unit: CompareUnit) => {
      let cached = words.get(unit);
      if (!cached) {
        cached = wordsOfText(unit.text);
        words.set(unit, cached);
      }
      return cached;
    };
  while (at < raw.length) {
    if (raw[at].t === 'eq') {
      out.push(raw[at++]);
      continue;
    }
    const gap: { t: string; a: number; b: number }[] = [];
    while (at < raw.length && raw[at].t !== 'eq') gap.push(raw[at++]);
    const takenOutOps = gap.filter((operation) => operation.t === 'del'),
      addedOps = gap.filter((operation) => operation.t === 'ins'),
      pair = new Map();
    let from = 0;
    weigh: for (const taken of takenOutOps)
      for (let addedAt = from; addedAt < addedOps.length; addedAt++) {
        const added = addedOps[addedAt];
        if (budget.left <= 0) break weigh;
        if (newUnits[added.b].tag !== oldUnits[taken.a].tag || newUnits[added.b].pics !== oldUnits[taken.a].pics) {
          budget.left--;
          continue;
        }
        const oldWords = wordsOf(oldUnits[taken.a]),
          newWords = wordsOf(newUnits[added.b]);
        budget.left -= oldWords.length + newWords.length + 1;
        if (wordLikeness(oldWords, newWords) >= PAIR_LIKENESS) {
          pair.set(taken, added);
          from = addedAt + 1;
          break;
        }
      }
    let takenAt = 0,
      addedAt = 0;
    while (takenAt < takenOutOps.length || addedAt < addedOps.length) {
      const taken = takenOutOps[takenAt],
        added = addedOps[addedAt];
      if (taken && pair.has(taken)) {
        const partner = pair.get(taken);
        if (added && added !== partner) {
          out.push(added);
          addedAt++;
          continue;
        }
        out.push({ t: 'mod', a: taken.a, b: partner.b });
        takenAt++;
        addedAt++;
        continue;
      }
      if (taken) {
        out.push(taken);
        takenAt++;
        continue;
      }
      out.push(added);
      addedAt++;
    }
  }
  const added = new Map();
  out.forEach((operation, index) => {
    if (operation.t !== 'ins') return;
    const unit = newUnits[operation.b];
    if (!/^H/.test(unit.tag) && unit.text.length < MOVE_MIN_CHARS) return;
    const places = added.get(unit.key) || [];
    places.push(index);
    added.set(unit.key, places);
  });
  out.forEach((operation) => {
    if (operation.t !== 'del') return;
    const places = added.get(oldUnits[operation.a].key);
    if (!places || !places.length) return;
    const index = places.shift() as number,
      to = out[index];
    operation.t = 'from';
    operation.b = to.b;
    to.t = 'to';
    to.a = operation.a;
  });
  markRegroups(oldUnits, newUnits, out);
  return out;
}
// The boxes split or joined between blocks kept on both sides (eq, mod) that come one after the other among those kept:
// two that shared a box on one side and not on the other while each still sits in boxes of the same kinds - one quote
// become two (a blank line between its paragraphs), a list cut in two by another bullet (- then *), two quotes or lists
// joined into one. No key can say it: a key holds the kinds of a block's boxes, never where a box begins or ends, so an
// item added at a list's top changes no other item. A split that a block added or moved in between makes, standing in
// neither of their boxes (a paragraph put between two items), is that block's own change: nothing more is marked. Both
// blocks of a split or a join become blocks changed in place (an eq op a mod) whose op says how ('split', 'merge';
// changeReason). Only the quote and list boxes count (REGROUP_BOX_TAGS): the words name those, and they are the boxes
// that split or join with no block changing. A table cannot: the second of two tables starts with a header row of its
// own, so a split or a join adds, takes out or changes that row (th cells for td), and that row says it - two tables
// joined are not "quotes or lists". Pure over the units' boxes (grp: which boxes, by identity; box: their kinds, one
// for each) but for the ops it marks.
function markRegroups(
  oldUnits: CompareUnit[],
  newUnits: CompareUnit[],
  ops: { t: string; a: number; b: number; how?: string[] }[],
) {
  const kept = ops.filter((operation) => operation.t === 'eq' || operation.t === 'mod'),
    memo = new Map() as Map<CompareUnit, { g: unknown; t: string }[]>;
  // a unit's quote and list boxes, outermost first: each box (by identity) and its kind (a numbered list's start aside)
  const own = (unit: CompareUnit) => {
    let boxes = memo.get(unit);
    if (boxes) return boxes;
    const boxKinds = unit.box ? unit.box.split('>') : [];
    boxes = [];
    (unit.grp || []).forEach((box, index) => {
      const kind = String(boxKinds[index] || '').replace(/^OL\d+$/, 'OL');
      if (REGROUP_BOX_TAGS.test(kind)) boxes.push({ g: box, t: kind });
    });
    memo.set(unit, boxes);
    return boxes;
  };
  // how many of those boxes two units of one side share from the outside in
  const shared = (first: CompareUnit, second: CompareUnit) => {
    const firstBoxes = own(first),
      secondBoxes = own(second);
    let depth = 0;
    while (depth < firstBoxes.length && depth < secondBoxes.length && firstBoxes[depth].g === secondBoxes[depth].g)
      depth++;
    return depth;
  };
  // the kinds of a unit's depth outermost quote and list boxes, null when it sits in fewer
  const kinds = (unit: CompareUnit, depth: number) => {
    const boxes = own(unit);
    return boxes.length >= depth
      ? boxes
          .slice(0, depth)
          .map((box) => box.t)
          .join('>')
      : null;
  };
  const alike = (oldUnit: CompareUnit, newUnit: CompareUnit, depth: number) => {
    const oldKinds = kinds(oldUnit, depth);
    return oldKinds !== null && oldKinds === kinds(newUnit, depth);
  };
  const mark = (operation: { t: string; how?: string[] }, how: string) => {
    if (operation.t === 'eq') operation.t = 'mod';
    const hows = operation.how || (operation.how = []);
    if (!hows.includes(how)) hows.push(how);
  };
  for (let i = 1; i < kept.length; i++) {
    const before = kept[i - 1],
      after = kept[i],
      was = shared(oldUnits[before.a], oldUnits[after.a]),
      now = shared(newUnits[before.b], newUnits[after.b]),
      depth = Math.max(was, now);
    if (
      was === now ||
      !alike(oldUnits[before.a], newUnits[before.b], depth) ||
      !alike(oldUnits[after.a], newUnits[after.b], depth)
    )
      continue; // a block that left or entered a box: its own change (ownChangeReason)
    let cut = false;
    if (was > now)
      for (let j = before.b + 1; j < after.b && !cut; j++)
        cut = shared(newUnits[j], newUnits[before.b]) <= now && shared(newUnits[j], newUnits[after.b]) <= now;
    if (!cut) {
      const how = was > now ? 'split' : 'merge';
      mark(before, how);
      mark(after, how);
    }
  }
}
// ---------------- Marking words inside a block changed in place
// A word of a unit: a run of a text node (node, s..e: its start and end offsets), or a whole element (el) - a hidden
// character's box, or in a block of lines one line. w is what it reads (a box's character, a line's text), f the inline
// elements it sits in below the unit (so a word that only became bold is another word), sp whether white space came
// before it (so taken-out words put back keep it).
type CompareWord = {
  node: Text | null;
  el: HTMLElement | null;
  s: number;
  e: number;
  w: string;
  f: string;
  sp: boolean;
};
// The words of a unit as they sit in its DOM (a list item's own text only); a block of lines' lines are its words. Pure
// over the DOM.
function unitWords(unit: HTMLElement): CompareWord[] {
  const out = [] as CompareWord[];
  let spaced = false;
  if (isLinedTag(unitTag(unit))) {
    for (const line of unit.querySelectorAll('.ln')) {
      const lineElement = line as HTMLElement;
      out.push({
        node: null,
        el: lineElement,
        s: 0,
        e: 0,
        w: String(lineElement.textContent || '').replace(/\n$/, ''),
        f: '',
        sp: true,
      });
    }
    return out;
  }
  const walk = (node: Node, inside: string) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) {
        const text = String(child.nodeValue || '');
        let at = 0;
        for (const match of text.matchAll(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu)) {
          const start = match.index as number;
          if (/\s/.test(text.slice(at, start))) spaced = true;
          out.push({
            node: child as Text,
            el: null,
            s: start,
            e: start + match[0].length,
            w: match[0],
            f: inside,
            sp: spaced,
          });
          spaced = false;
          at = start + match[0].length;
        }
        if (/\s/.test(text.slice(at))) spaced = true;
        continue;
      }
      if (child.nodeType !== 1) continue;
      const element = child as HTMLElement;
      if ((unit.tagName === 'LI' && isNestedBlock(element)) || element.classList.contains('sr-only')) continue;
      if (element.classList.contains('cc')) {
        out.push({ node: null, el: element, s: 0, e: 0, w: element.textContent || '', f: inside, sp: spaced });
        spaced = false;
        continue;
      }
      walk(
        element,
        element.classList.contains('ln') && element.tagName === 'SPAN' ? inside : inside + '/' + inlineName(element),
      );
    }
  };
  walk(unit, '');
  return out;
}
// Marks the words of a block changed in place: the added words of the new block (ins), and the taken-out words of the
// old one put back into it where they were, struck through (del) - text with its hidden characters boxed again
// (wordMark). A word in a text node is wrapped where it is; a hidden character's box is wrapped whole; a line of a
// block of lines has its content wrapped, and a taken-out line comes back as a line of its own. Edits in a text node
// run from its end to its start, so the offsets still to come stay right. Past the compare's budget the block stays
// marked as changed with no words marked.
function markChangedWords(oldUnit: HTMLElement, newUnit: HTMLElement, budget?: CompareBudget) {
  if (budget && budget.left <= 0) return;
  const oldWords = unitWords(oldUnit),
    newWords = unitWords(newUnit),
    ops = commonSubsequence(oldWords, newWords, (left, right) => left.w === right.w && left.f === right.f, budget),
    lined = isLinedTag(unitTag(newUnit));
  const edits: { node: Text; s: number; e: number; kind: string; text?: string }[] = [];
  const wraps: { el: HTMLElement; kind: string }[] = [];
  const puts: { at: HTMLElement | null; after: boolean; text: string }[] = [];
  const mark = (words: CompareWord[], kind: string) => {
    let at = 0;
    while (at < words.length) {
      const word = words[at];
      if (!word.node) {
        if (word.el) wraps.push({ el: word.el, kind });
        at++;
        continue;
      }
      let end = at;
      while (end + 1 < words.length && words[end + 1].node === word.node) end++;
      edits.push({ node: word.node, s: word.s, e: words[end].e, kind });
      at = end + 1;
    }
  };
  let gone = [] as CompareWord[];
  // the taken-out words before new word newAt (or after the last one), as one struck-through run: a block of lines' as
  // lines of their own; other words with the white space they had between them, and a space after the run when the word
  // it goes before has one before it (before the run when it goes after the last word and had one before it)
  const flushGone = (newAt: number) => {
    if (!gone.length) return;
    const at = newWords[newAt],
      last = newWords[newWords.length - 1];
    const words = lined
      ? gone.map((word) => word.w).join('\n') + '\n'
      : gone.map((word, index) => (index && word.sp ? ' ' : '') + word.w).join('');
    const before = words + (!lined && at && at.sp ? ' ' : ''),
      after = (!lined && last && gone[0].sp ? ' ' : '') + words;
    if (at && at.node) edits.push({ node: at.node, s: at.s, e: at.s, kind: 'put', text: before });
    else if (at) puts.push({ at: at.el, after: false, text: before });
    else if (last && last.node) edits.push({ node: last.node, s: last.e, e: last.e, kind: 'put', text: after });
    else puts.push({ at: last ? last.el : null, after: true, text: after });
    gone = [];
  };
  let nextNewAt = 0;
  for (const operation of ops) {
    if (operation.t === 'eq') {
      flushGone(operation.b);
      nextNewAt = operation.b + 1;
      continue;
    }
    if (operation.t === 'del') {
      gone.push(oldWords[operation.a]);
      continue;
    }
    flushGone(operation.b);
    mark([newWords[operation.b]], 'ins');
    nextNewAt = operation.b + 1;
  }
  flushGone(nextNewAt);
  // one edit per run of adjacent added words in one text node
  const merged: { node: Text; s: number; e: number; kind: string; text?: string }[] = [];
  for (const edit of edits) {
    const previous = merged[merged.length - 1];
    if (
      previous &&
      edit.kind === 'ins' &&
      previous.kind === 'ins' &&
      previous.node === edit.node &&
      /^\s*$/.test(String(edit.node.nodeValue || '').slice(previous.e, edit.s))
    ) {
      previous.e = edit.e;
      continue;
    }
    merged.push(edit);
  }
  const byNode = new Map<Text, (typeof merged)[number][]>();
  for (const edit of merged) {
    const nodeEdits = byNode.get(edit.node) || [];
    nodeEdits.push(edit);
    byNode.set(edit.node, nodeEdits);
  }
  for (const [node, nodeEdits] of byNode) {
    nodeEdits.sort((left, right) => right.s - left.s || (left.kind === 'put' ? 1 : -1));
    for (const edit of nodeEdits) {
      if (edit.kind === 'put') {
        const rest = node.splitText(edit.s);
        (rest.parentNode as Node).insertBefore(wordMark('del', edit.text || ''), rest);
        continue;
      }
      const word = node.splitText(edit.s);
      word.splitText(edit.e - edit.s);
      const wrapper = wordMark(edit.kind === 'ins' ? 'ins' : 'del', '');
      (word.parentNode as Node).insertBefore(wrapper, word);
      wrapper.appendChild(word);
    }
  }
  // a block that had no word left (an emptied paragraph, an emptied code block) takes the put-back words at its end
  const tail = lined ? newUnit.querySelector('code') || newUnit : newUnit;
  for (const put of puts) {
    const struck = wordMark('del', put.text);
    if (!put.at) tail.appendChild(struck);
    else if (put.after) put.at.after(struck);
    else put.at.before(struck);
  }
  for (const wrap of wraps) {
    const wrapper = wordMark(wrap.kind === 'ins' ? 'ins' : 'del', '');
    if (!wrap.el.classList.contains('ln')) {
      wrap.el.before(wrapper);
      wrapper.appendChild(wrap.el);
      continue;
    }
    // a line: its content, up to its line end (the end stays outside, so the mark ends with the line's text)
    const end = wrap.el.lastChild,
      lineEnd =
        end && end.nodeType === 3 && /\n$/.test(String(end.nodeValue || ''))
          ? (end as Text).splitText(String(end.nodeValue).length - 1)
          : null;
    wrapper.append(...[...wrap.el.childNodes].filter((child) => child !== lineEnd));
    wrap.el.insertBefore(wrapper, lineEnd);
  }
}
// A link of a block changed in place whose target the other side's block does not have: marked like an added (new side)
// or a taken-out word (old side), its tip saying the target changed - a link's words can stay while where it goes
// changes. A list item's own links only (isOwnPart): a nested block's are that block's.
function markChangedLinks(oldUnit: HTMLElement, newUnit: HTMLElement) {
  const selector = 'a,.md-rel,[data-anchor]',
    to = (link: Element) => {
      const element = link as HTMLElement;
      return element.dataset.tipUrl || element.getAttribute('href') || element.dataset.anchor || '';
    };
  const oldLinks = [...oldUnit.querySelectorAll(selector)].filter((link) => isOwnPart(oldUnit, link)),
    newLinks = [...newUnit.querySelectorAll(selector)].filter((link) => isOwnPart(newUnit, link)),
    oldTargets = new Set(oldLinks.map(to)),
    newTargets = new Set(newLinks.map(to));
  for (const link of newLinks) {
    const target = to(link);
    if (target && !oldTargets.has(target)) {
      link.classList.add('mdc-wl');
      (link as HTMLElement).dataset.tip = translateTemplate('링크 대상이 바뀜 · {to}', { to: markHiddenPlain(target) });
    }
  }
  for (const link of oldLinks) {
    const target = to(link);
    if (target && !newTargets.has(target)) link.classList.add('mdc-wl-del');
  }
}
// A word mark (ins, del) holding text, each character that would hide or reorder it in its box (markHiddenHtml), as the
// drawn text has.
function wordMark(tag: string, text: string) {
  const mark = document.createElement(tag);
  mark.className = 'mdc-w';
  if (text) setHtml(mark, markHiddenHtml(text));
  return mark;
}
// ---------------- Laying the marks
// Marks a unit's element as a change of kind (ins, del, mod, move): its tint and, for a screen reader, the kind before
// its text. why, for a block changed in place whose words stayed, says what did change - read with the kind and shown
// as its tip.
function markUnit(unit: HTMLElement, kind: string, why?: string) {
  unit.classList.add('mdc-' + kind);
  unit.dataset.mdc = kind;
  if (why) {
    unit.dataset.mdcWhy = why;
    unit.dataset.tip = why;
  }
  const spoken = document.createElement('span');
  spoken.className = 'sr-only';
  spoken.textContent =
    translate({ ins: '더한 블록', del: '뺀 블록', mod: '고친 블록', move: '옮긴 블록' }[kind] || '') +
    (why ? ' (' + why + ')' : '') +
    ': ';
  if (unit.tagName === 'TR') {
    const cell = unit.firstElementChild;
    if (cell) cell.prepend(spoken);
  } else if (unit.tagName !== 'HR') unit.prepend(spoken);
}
// The element a taken-out list item leaves behind in one column: its own text, without the nested blocks (units of
// their own, put back into it when they are taken out too, placeTakenOut). Its own nodes are moved, never copied: an
// image keeps the load and error handlers the renderer gave it (drawImage), so it gets its size or falls back to its
// alt text as in the document view.
function ownElement(unit: CompareUnit) {
  if (unit.el.tagName !== 'LI') return unit.el;
  const copy = unit.el.cloneNode(false) as HTMLElement;
  for (const child of [...unit.el.childNodes])
    if (!(child.nodeType === 1 && isNestedBlock(child as Element))) copy.appendChild(child);
  return copy;
}
function parentBoxTag(element: Element, root: Element) {
  const parent = element.parentElement;
  return !parent || parent === root ? 'root' : parent.tagName;
}
// The boxes of the two sides that stand for each other: an old element -> the new side's elements that stand for it. A
// block kept as it was or changed in place stands for its old self, and so does each box it sits in for the old block's
// box at the same height while their tags agree (pairBoxes); a block taken out, a moved block's old place and the
// shallow copy of a box made for them stand for what they were put back for (placeTakenOut). A moved block's new place
// stands for nothing on the old side.
type StandIns = Map<Element, Element[]>;
function standFor(boxes: StandIns, oldBox: Element, newBox: Element) {
  const standIns = boxes.get(oldBox);
  if (!standIns) boxes.set(oldBox, [newBox]);
  else if (!standIns.includes(newBox)) standIns.push(newBox);
}
function pairBoxes(
  boxes: StandIns,
  oldUnit: HTMLElement,
  newUnit: HTMLElement,
  oldRoot: HTMLElement,
  newRoot: HTMLElement,
) {
  for (
    let oldBox = oldUnit as Element | null, newBox = newUnit as Element | null;
    oldBox && newBox && oldBox !== oldRoot && newBox !== newRoot && oldBox.tagName === newBox.tagName;
    oldBox = oldBox.parentElement, newBox = newBox.parentElement
  )
    standFor(boxes, oldBox, newBox);
}
// The child of box that holds element (element itself, or the box's child it sits in), or null when element is not
// inside box.
function childHolding(element: Element, box: Element) {
  let child = element as Element | null;
  while (child && child.parentElement !== box) child = child.parentElement;
  return child;
}
// Puts block - a block taken out of the old side (its old place: oldPlace, in oldRoot), or a moved block's old place -
// into the new side's root, inside the very boxes oldPlace sat in: the nearest of oldPlace's old boxes that something
// on the new side stands for (boxes; the column when none) - of those, the one previous (the last block laid) or else
// next (the next new block) is in - takes it, inside shallow copies of the boxes between (a deleted item's nested list,
// a deleted table's body), right after the part of it that holds previous, else before the part that holds next, else
// at its end. A box is judged by what it stands for, never by its tag alone: a nested list is not the list around it,
// and a list item's paragraph does not join the item before it. Returns block, the next block's previous.
function placeTakenOut(
  block: HTMLElement,
  oldPlace: HTMLElement,
  oldRoot: HTMLElement,
  previous: HTMLElement | null,
  next: HTMLElement | null,
  root: HTMLElement,
  boxes: StandIns,
) {
  standFor(boxes, oldPlace, block);
  let node = block as HTMLElement,
    oldBox = oldPlace.parentElement;
  for (; oldBox && oldBox !== oldRoot && !boxes.has(oldBox); oldBox = oldBox.parentElement) {
    const copy = oldBox.cloneNode(false) as HTMLElement;
    delete copy.dataset.lo;
    delete copy.dataset.hi;
    copy.appendChild(node);
    standFor(boxes, oldBox, copy);
    node = copy;
  }
  const holders = oldBox && oldBox !== oldRoot ? (boxes.get(oldBox) as Element[]) : [root],
    box =
      holders.find((holder) => !!previous && holder.contains(previous)) ||
      holders.find((holder) => !!next && holder.contains(next)) ||
      holders[0];
  const afterChild = previous && previous !== box ? childHolding(previous, box) : null,
    beforeChild = !afterChild && next ? childHolding(next, box) : null;
  if (afterChild) afterChild.after(node);
  else if (beforeChild) beforeChild.before(node);
  else box.appendChild(node);
  return block;
}
// A moved block's place on the side it left: a slim line that says where it went.
function movedPlaceLine(unit: CompareUnit, to: CompareUnit) {
  const parent = unit.el.parentElement,
    tag =
      parent && /^(UL|OL)$/.test(parent.tagName)
        ? 'li'
        : parent && /^(TBODY|THEAD)$/.test(parent.tagName)
          ? 'tr'
          : 'div',
    line = document.createElement(tag);
  line.className = 'mdc-ghost';
  line.dataset.toLo = String(to.lo);
  line.dataset.n = '1';
  const text = translateTemplate('여기 있던 블록을 L{line}로 옮김', { line: to.lo }),
    box = tag === 'tr' ? document.createElement('td') : line;
  if (tag === 'tr') {
    (box as HTMLTableCellElement).colSpan = Math.max(1, unit.el.children.length);
    line.appendChild(box);
  }
  box.textContent = text;
  return line;
}
// ---------------- The column
// The new side, with each block taken out put back where it was (struck through), each moved block's old place a slim
// line, the words of a block changed in place marked inside it. Returns the column.
function layColumn(
  oldRoot: HTMLElement,
  newRoot: HTMLElement,
  oldUnits: CompareUnit[],
  newUnits: CompareUnit[],
  ops: any[],
  budget?: CompareBudget,
) {
  let previous = null as HTMLElement | null;
  const next = (index: number) => {
    for (let later = index + 1; later < ops.length; later++) {
      const operation = ops[later];
      if (operation.t !== 'del' && operation.t !== 'from') return newUnits[operation.b].el;
    }
    return null;
  };
  const boxes = new Map() as StandIns;
  for (const operation of ops)
    if (operation.t === 'eq' || operation.t === 'mod')
      pairBoxes(boxes, oldUnits[operation.a].el, newUnits[operation.b].el, oldRoot, newRoot); // before any block moves
  ops.forEach((operation, index) => {
    if (operation.t === 'eq') {
      previous = newUnits[operation.b].el;
      return;
    }
    if (operation.t === 'ins' || operation.t === 'to' || operation.t === 'mod') {
      const block = newUnits[operation.b].el;
      markUnit(
        block,
        operation.t === 'ins' ? 'ins' : operation.t === 'to' ? 'move' : 'mod',
        operation.t === 'mod' ? changeReason(oldUnits[operation.a], newUnits[operation.b], operation.how) : '',
      );
      if (operation.t === 'to') block.dataset.mdcFrom = String(oldUnits[operation.a].lo);
      if (operation.t === 'mod') {
        markChangedWords(oldUnits[operation.a].el, block, budget);
        markChangedLinks(oldUnits[operation.a].el, block);
      }
      previous = block;
      return;
    }
    const unit = oldUnits[operation.a];
    if (operation.t === 'del') {
      const block = ownElement(unit);
      markUnit(block, 'del');
      previous = placeTakenOut(block, unit.el, oldRoot, previous, next(index), newRoot, boxes);
      return;
    }
    // blocks moved together (a section) leave one line: the first one's, widened to their lines
    const last = index > 0 ? ops[index - 1] : null;
    if (
      last &&
      last.t === 'from' &&
      previous &&
      previous.classList.contains('mdc-ghost') &&
      parentBoxTag(unit.el, oldRoot) === parentBoxTag(oldUnits[last.a].el, oldRoot)
    ) {
      const count = +(previous.dataset.n || 1) + 1,
        firstLine = +(previous.dataset.toLo || 0),
        lastLine = newUnits[operation.b].hi;
      previous.dataset.n = String(count);
      standFor(boxes, unit.el, previous);
      (previous.querySelector('td') || previous).textContent = translateTemplate(
        '여기 있던 블록 {n}개를 L{lo}–L{hi}로 옮김',
        {
          n: count,
          lo: firstLine,
          hi: lastLine,
        },
      );
      return;
    }
    previous = placeTakenOut(
      movedPlaceLine(unit, newUnits[operation.b]),
      unit.el,
      oldRoot,
      previous,
      next(index),
      newRoot,
      boxes,
    );
  });
  return newRoot;
}
// The gutter chips: each marked block's kind as a word at its first line, in the column's left gutter (a layer of the
// column, laid out again when its width changes). Not read aloud: the block itself carries its kind (markUnit).
function layGutterChips() {
  const root = RENDERED_COMPARE.root;
  if (!root) return;
  root.querySelectorAll(':scope>.mdc-chips').forEach((oldLayer) => oldLayer.remove());
  const layer = document.createElement('div');
  layer.className = 'mdc-chips';
  layer.setAttribute('aria-hidden', 'true');
  const top = root.getBoundingClientRect().top;
  const items = [] as { y: number; cls: string; text: string }[];
  for (const node of root.querySelectorAll('[data-mdc],.mdc-pin')) {
    const element = node as HTMLElement,
      rect = element.getBoundingClientRect();
    if (!rect.height) continue;
    if (element.classList.contains('mdc-pin'))
      items.push({ y: rect.top - top, cls: 'pin', text: element.dataset.mdcPin || '' });
    if (element.dataset.mdc)
      items.push({
        y: rect.top - top,
        cls: element.dataset.mdc,
        text: translate(CHIP_WORDS[element.dataset.mdc] || ''),
      });
  }
  items.sort((first, second) => first.y - second.y || (first.cls === 'pin' ? 1 : -1));
  let last = -1e9;
  for (const item of items) {
    const chip = document.createElement('span');
    chip.className = 'mdc-chip mdc-chip-' + item.cls;
    chip.textContent = item.text;
    const y = Math.max(item.y, last + 22);
    chip.style.top = y + 'px';
    last = y;
    layer.appendChild(chip);
  }
  root.appendChild(layer);
}
// The unit elements of a drawn side in document order, as compareUnits takes them (and a moved block's old place,
// ghosts).
function unitElements(root: HTMLElement, ghosts: boolean): HTMLElement[] {
  return [...root.querySelectorAll(UNIT_SELECTOR + (ghosts ? ',.mdc-ghost' : ''))]
    .map((node) => node as HTMLElement)
    .filter(isCompareUnit);
}
// ---------------- Showing a compare
// Git's lines [first, last] of a side (counted on LF alone, as a hunk counts them) as the screen's lines of that side
// (the side's lines, str.splitlines() - a form feed, a lone CR, U+2028 end a line there and not for git). map is the
// side's git_line_starts from GET /api/revision-source: [fromGit, fromScreen] pairs from which on git line gitLine
// starts on screen line fromScreen + (gitLine - fromGit), absent when the two agree - the last pair the line after the
// last git line, after the last screen line, when the last git line holds several; lineCount the side's line count.
// first's first screen line to the last before last + 1's. Pure.
function gitToScreenRange(map: number[][] | null | undefined, lineCount: number, range: number[]): number[] {
  const [first, last] = range;
  if (!map || !map.length) return [first, last];
  const at = (gitLine: number) => {
    let screenLine = gitLine;
    for (const [fromGit, fromScreen] of map) {
      if (fromGit > gitLine) break;
      screenLine = fromScreen + (gitLine - fromGit);
    }
    return screenLine;
  };
  const firstScreen = at(first);
  return [firstScreen, Math.max(firstScreen, lineCount ? Math.min(lineCount, at(last + 1) - 1) : at(last + 1) - 1)];
}
// The change groups in order: runs of marked blocks (a moved block's old place too) with nothing unchanged between
// them. The navigator steps through them.
function changeGroups(root: HTMLElement) {
  const stops = [] as HTMLElement[][];
  let group = null as HTMLElement[] | null;
  for (const element of unitElements(root, true)) {
    const marked = !!element.dataset.mdc || element.classList.contains('mdc-ghost');
    if (marked) {
      if (!group) {
        group = [];
        stops.push(group);
      }
      group.push(element);
    } else if (!/^(UL|OL|TABLE|TBODY|THEAD)$/.test(element.tagName)) group = null;
  }
  return stops;
}
// The navigator (#revision-nav): where it is among the change groups, and its buttons pressed only where there is a
// next one.
function drawCompareNavigator() {
  const count = RENDERED_COMPARE.stops.length,
    box = $('#revision-nav');
  box.hidden = REVISION_VIEW.format !== DIFF_FORMAT.RENDERED || !count;
  $('#mdc-at').textContent = !count
    ? ''
    : RENDERED_COMPARE.at < 0
      ? translateTemplate('바뀐 곳 {n}곳', { n: count })
      : translateTemplate('바뀐 곳 {at}/{n}', { at: RENDERED_COMPARE.at + 1, n: count });
  $('#mdc-prev').disabled = RENDERED_COMPARE.at <= 0;
  $('#mdc-next').disabled = RENDERED_COMPARE.at >= count - 1;
}
// Goes to change group index: brings its first block to a third of the pane's height and, with ring, rings the group
// for a moment.
function goToChangeGroup(index: number, ring?: boolean) {
  const group = RENDERED_COMPARE.stops[index];
  if (!group) return;
  RENDERED_COMPARE.at = index;
  drawCompareNavigator();
  document.querySelectorAll('#revision-rendered .mdc-cur').forEach((element) => element.classList.remove('mdc-cur'));
  if (ring) group.forEach((element) => element.classList.add('mdc-cur'));
  const pane = LAYOUT === LAYOUT_MODE.NARROW ? $('#revision-body') : $('#revision-rendered'),
    rect = group[0].getBoundingClientRect(),
    paneRect = pane.getBoundingClientRect();
  pane.scrollTo({
    top: pane.scrollTop + rect.top - paneRect.top - Math.round(pane.clientHeight / 3),
    behavior: scrollMotion(),
  });
}
function stepChangeGroup(step: number) {
  if (!RENDERED_COMPARE.stops.length) return;
  goToChangeGroup(Math.min(RENDERED_COMPARE.stops.length - 1, Math.max(0, RENDERED_COMPARE.at + step)), true);
}
// Forgets the compare on screen (another commit, another document, the manuscript view).
function clearRenderedCompare() {
  ++RENDERED_COMPARE.seq;
  RENDERED_COMPARE.key = '';
  RENDERED_COMPARE.line = '';
  RENDERED_COMPARE.said = null;
  RENDERED_COMPARE.stops = [];
  RENDERED_COMPARE.at = -1;
  RENDERED_COMPARE.root = null;
  stopSideParse(null);
  if (RENDERED_COMPARE.ro) {
    RENDERED_COMPARE.ro.disconnect();
    RENDERED_COMPARE.ro = null;
  }
  $('#revision-rendered').replaceChildren();
  $('#revision-nav').hidden = true;
}
// A notice in the compare's place (a side that cannot be drawn, a limit), with the way to the source diff.
function compareNotice(text: string) {
  const notice = document.createElement('div');
  notice.className = 'md-note mdc-note';
  notice.setAttribute('role', 'status');
  setHtml(
    notice,
    html`<span>${text}</span> <button class="btn-sm" data-act="revision-format" data-format="source">소스 diff 보기</button>`,
  );
  return notice;
}
// Why a side carries no lines (GET /api/revision-source's reason), in a line.
function sideFailureText(side: any, which: string) {
  switch (side && side.reason) {
    case 'source_too_large':
      return translateTemplate('{side}이 {size}라 그려 비교하지 않습니다(한도 {limit})', {
        side: which,
        size: formatMebibytes(side.bytes),
        limit: formatMebibytes(side.limit),
      });
    case 'source_not_utf8':
      return translateTemplate('{side}이 UTF-8이 아니라 그려 비교하지 않습니다', { side: which });
    case 'not_a_file':
      return translateTemplate('{side}에서 이 경로가 파일이 아니라 그려 비교하지 않습니다', { side: which });
    default:
      return translateTemplate('{side}을 읽지 못했습니다', { side: which });
  }
}
// Parses and draws one side's lines (null: the file is not on that side - an empty document), as the document view
// draws a document: a NUL in the source is not parsed (MARKDOWN_LIMIT.NUL). {root} or {why}; {root:null,why:''} once
// live() is false.
async function drawSide(
  lines: string[] | null | undefined,
  live: () => boolean,
): Promise<{ root: HTMLElement | null; why?: string }> {
  if (!lines) return { root: await buildSide([], [], live) };
  if (lines.some((line) => line.includes('\0'))) return { root: null, why: limitText(MARKDOWN_LIMIT.NUL) };
  const parsed = await parseSide(lines.join('\n'));
  if (!parsed || !live()) return { root: null, why: '' };
  if (!parsed.ok) return { root: null, why: limitText(String(parsed.limit || MARKDOWN_LIMIT.ERROR)) };
  const root = await buildSide(parsed.tokens, lines, live);
  return root ? { root } : { root: null, why: live() ? limitText(MARKDOWN_LIMIT.ELEMENTS) : '' };
}
// Shows the rendered compare of commit id (from base for a range) in #revision-rendered, for the visit seq of document
// docKey: reads both sides, draws and compares them, lays them out in one column, rings a pin's blocks when the view
// was opened for one ([변경 보기], then [그린 비교]), and says on the status line what changed.
async function showRenderedCompare(id: string, base: string, seq: number, docKey: string | null) {
  const pane = $('#revision-rendered'),
    key = revisionKey(),
    mine = ++RENDERED_COMPARE.seq,
    live = () => mine === RENDERED_COMPARE.seq && revisionCurrent(seq, docKey, id) && RENDERED_COMPARE.key === key;
  RENDERED_COMPARE.key = key;
  RENDERED_COMPARE.line = '';
  RENDERED_COMPARE.said = null;
  RENDERED_COMPARE.stops = [];
  RENDERED_COMPARE.at = -1;
  RENDERED_COMPARE.root = null;
  if (RENDERED_COMPARE.ro) {
    RENDERED_COMPARE.ro.disconnect();
    RENDERED_COMPARE.ro = null;
  }
  // the guide line says what this compare finds, once it has (ringPinBlocks)
  if (REVISION_VIEW.target) REVISION_VIEW.target.mdcMsg = '';
  pane.replaceChildren(waitLine(translate('두 판을 읽는 중입니다.')));
  drawCompareNavigator();
  const pinTarget = revisionPinFor(id);
  let answer,
    scope = null;
  try {
    const query = '?commit=' + encodeURIComponent(id) + (base ? '&base=' + encodeURIComponent(base) : '');
    const [sides, pinDiff] = await Promise.all([
      api('GET /api/revision-source', { query: withDocQuery(query, docKey), what: '두 판 읽기', silent: true }),
      pinTarget
        ? api('GET /api/revision-diff', {
            query: withDocQuery('?commit=' + encodeURIComponent(id) + '&pin=' + pinTarget.id, docKey),
            what: '변경 내용 읽기',
            silent: true,
          }).catch(() => null)
        : Promise.resolve(null),
    ]);
    answer = sides.data;
    scope = pinDiff && pinDiff.data ? { ...(pinDiff.data.scope || {}), whole: String(pinDiff.data.diff || '') } : null;
  } catch (error) {
    if (live()) {
      const why = error && (error as ApiError).data ? errText((error as ApiError).data) : '';
      pane.replaceChildren(
        compareNotice(
          why
            ? translateTemplate('두 판을 읽지 못했습니다: {error}', { error: why })
            : translate('두 판을 읽지 못했습니다.'),
        ),
      );
    }
    return;
  }
  if (!live()) return;
  const bad = (
    [
      [answer.old, translate('옛 판')],
      [answer.new, translate('새 판')],
    ] as const
  ).find(([side]) => side && !Array.isArray(side.lines));
  if (bad) {
    pane.replaceChildren(compareNotice(sideFailureText(bad[0], bad[1])));
    sayCompareStatus(answer, null);
    return;
  }
  pane.replaceChildren(waitLine(translate('두 판을 그려 견주는 중입니다.')));
  const oldSide = await drawSide(answer.old ? answer.old.lines : null, live);
  if (!live()) return;
  const newSide = oldSide.root ? await drawSide(answer.new ? answer.new.lines : null, live) : { root: null, why: '' };
  if (!live()) return;
  if (!oldSide.root || !newSide.root) {
    pane.replaceChildren(
      compareNotice(
        translateTemplate('그려 비교하지 못했습니다 — {why}', {
          why: oldSide.why || newSide.why || translate('파서를 쓸 수 없습니다'),
        }),
      ),
    );
    sayCompareStatus(answer, null);
    return;
  }
  const budget = newCompareBudget(),
    oldUnits = compareUnits(oldSide.root),
    newUnits = compareUnits(newSide.root),
    ops = blockOps(oldUnits, newUnits, budget),
    counts = { ins: 0, del: 0, mod: 0, move: 0 };
  for (const operation of ops) {
    if (operation.t === 'ins') counts.ins++;
    else if (operation.t === 'del') counts.del++;
    else if (operation.t === 'mod') counts.mod++;
    else if (operation.t === 'to') counts.move++;
  }
  // read before the layout moves the old side's blocks
  const pics = !!(oldSide.root.querySelector('.md-pic') || newSide.root.querySelector('.md-pic'));
  const view = layColumn(oldSide.root, newSide.root, oldUnits, newUnits, ops, budget);
  RENDERED_COMPARE.root = view;
  const head = document.createElement('div');
  head.className = 'mdc-legend';
  head.setAttribute('aria-hidden', 'true');
  setHtml(
    head,
    html`<span class="mdc-chip mdc-chip-ins">${translate('더함')}</span><span class="mdc-chip mdc-chip-del">${translate('뺌')}</span><span class="mdc-chip mdc-chip-mod">${translate('고침')}</span><span class="mdc-chip mdc-chip-move">${translate('옮김')}</span>`,
  );
  const frame = document.createElement('div');
  frame.className = 'mdc-frame';
  // read and seen: the old side's images are not its own (ADR-0031 D8) - a plain line, never the hidden legend's
  if (pics)
    frame.appendChild(
      compareInfoLine(
        translate('그림은 두 판 모두 지금 원고 트리의 파일입니다 — 옛 판의 그림 파일은 읽지 않습니다.'),
        false,
      ),
    );
  // the characters drawn in their boxes in the column (the new side and the blocks and words put back): the document
  // view's notice
  const boxes = view.querySelectorAll('.cc').length;
  if (boxes) frame.appendChild(compareInfoLine(markedCharactersText(boxes), false));
  if (budget.left <= 0)
    frame.appendChild(
      compareInfoLine(
        translate(
          '바뀐 곳이 많아 블록을 짝짓지 않고 더한 블록과 뺀 블록으로만 표시합니다. 낱말 단위는 [소스 diff]에 있습니다.',
        ),
      ),
    );
  if (!answer.old)
    frame.appendChild(compareInfoLine(translate('이 커밋에서 파일이 처음 생겼습니다 — 모든 블록이 더한 블록입니다.')));
  if (!answer.new)
    frame.appendChild(compareInfoLine(translate('이 커밋에서 파일을 지웠습니다 — 모든 블록이 뺀 블록입니다.')));
  frame.append(head, view);
  pane.replaceChildren(frame);
  RENDERED_COMPARE.stops = changeGroups(view);
  const at = ringPinBlocks(pinTarget, scope, newUnits, answer.new);
  sayCompareStatus(answer, counts);
  if (!RENDERED_COMPARE.stops.length)
    frame.insertBefore(
      compareInfoLine(
        translate(
          '두 판의 그린 문서가 같습니다 — 줄 끝·공백·HTML 주석처럼 그리지 않는 곳만 바뀌었습니다. 정확한 변경은 [소스 diff]에 있습니다.',
        ),
      ),
      head,
    );
  requestAnimationFrame(() => {
    if (!live()) return;
    layGutterChips();
    RENDERED_COMPARE.ro = window.ResizeObserver
      ? new ResizeObserver(() => {
          if (live()) requestAnimationFrame(layGutterChips);
        })
      : null;
    if (RENDERED_COMPARE.ro) RENDERED_COMPARE.ro.observe(view);
    if (at >= 0) goToChangeGroup(at);
    else {
      RENDERED_COMPARE.at = -1;
      drawCompareNavigator();
    }
  });
  if (REVISION_VIEW.target) drawPinGuide();
}
// A line above the compare: a status, read when it comes, unless status is false - then a standing note, read in its
// place.
function compareInfoLine(text: string, status?: boolean) {
  const line = document.createElement('div');
  line.className = 'mdc-info';
  if (status !== false) line.setAttribute('role', 'status');
  line.textContent = text;
  return line;
}
// The status line of a compare: its two sides - a range's with the commits and files its source diff counted
// (REVISION_VIEW.rangeN, once that answer is in) - and what changed. Kept (RENDERED_COMPARE.said) so the range's counts
// can join it when they come (restateCompareStatus).
function sayCompareStatus(answer: any, counts: { ins: number; del: number; mod: number; move: number } | null) {
  RENDERED_COMPARE.said = { r: answer, c: counts };
  const ends =
      (answer.base ? String(answer.base).slice(0, 8) : translate('없음')) + ' → ' + String(answer.id || '').slice(0, 8),
    rangeCounts = REVISION_VIEW.base ? REVISION_VIEW.rangeN : null;
  let line = rangeCounts
    ? translateTemplate('{base} → {head} · 커밋 {commits}개 · 파일 {files}개', {
        base: String(answer.base || '').slice(0, 8),
        head: String(answer.id || '').slice(0, 8),
        commits: rangeCounts.commits,
        files: rangeCounts.files,
      })
    : ends;
  if (answer.merge_base)
    line += ' · ' + translateTemplate('공통 조상 {mb}부터 비교', { mb: String(answer.merge_base).slice(0, 8) });
  if (counts) {
    const total = counts.ins + counts.del + counts.mod + counts.move;
    line +=
      ' · ' +
      (total
        ? translateTemplate('바뀐 블록 {n}곳 — 고침 {mod} · 더함 {ins} · 뺌 {del} · 옮김 {move}', {
            n: total,
            mod: counts.mod,
            ins: counts.ins,
            del: counts.del,
            move: counts.move,
          })
        : translate('바뀐 블록 없음'));
  }
  RENDERED_COMPARE.line = line;
  if (REVISION_VIEW.format === DIFF_FORMAT.RENDERED) $('#revision-status').textContent = line;
}
// The range's source diff has answered (loadRevisionSource): the compare's status line says its commits and files too.
function restateCompareStatus() {
  if (RENDERED_COMPARE.said && RENDERED_COMPARE.key === revisionKey())
    sayCompareStatus(RENDERED_COMPARE.said.r, RENDERED_COMPARE.said.c);
}
// The pin the view was opened for ([변경 보기], then [그린 비교]): its blocks on the new side - those whose lines meet
// the pin's own changes (the server's hunks of the pin, scope) or else its lines - ringed in the review colour, the
// changed ones first. The compare is the whole commit's (ADR-0031 D6: it has no pin-only side), so when the pin owns
// part of it the line says so and points at [소스 diff], which shows the pin's hunks alone. Returns the change group to
// open at (-1: none), and leaves on the pin the line the guide says (pinTarget.mdcMsg).
/** @param side the new side GET /api/revision-source gave */
function ringPinBlocks(pinTarget: RevTarget | null, scope: any, newUnits: CompareUnit[], side: any) {
  const target = REVISION_VIEW.target;
  if (target && !pinTarget)
    target.mdcMsg = translateTemplate('핀 #{id}의 커밋을 볼 때만 핀 자리를 표시합니다', { id: target.id });
  if (!pinTarget) return -1;
  // the pin's own hunks when it owns part of the commit; every hunk when it owns all of it; else its lines as they are
  // now. A hunk counts git's lines (LF only); the blocks count the screen's (the side's lines): gitToScreenRange turns
  // one into the other
  const firstLine = pinTarget.lo || 0,
    map = side && side.git_line_starts,
    lineCount = side && side.lines ? side.lines.length : 0,
    hunks = (diff: string) => hunkRanges(diff).map((range) => gitToScreenRange(map, lineCount, range));
  const part = !!scope && scope.mode === SCOPE_MODE.PIN,
    ranges = part
      ? hunks(scope.diff)
      : scope && scope.hunks > 0
        ? hunks(scope.whole)
        : [[firstLine, pinTarget.hi || firstLine]];
  const meets = newUnits.filter(
    (unit) => unit.lo && ranges.some(([first, last]) => unit.hi >= first && unit.lo <= last) && unit.el.isConnected,
  );
  const changed = meets.filter((unit) => unit.el.dataset.mdc);
  const shown = changed.length ? changed : meets;
  shown.forEach((unit) => {
    unit.el.classList.add('mdc-pin');
    unit.el.dataset.mdcPin = translateTemplate('핀 #{id}', { id: pinTarget.id });
  });
  pinTarget.mdcMsg =
    (changed.length
      ? translateTemplate('핀 #{id} 자리의 바뀐 블록 {n}곳을 보라 테두리로 표시했습니다', {
          id: pinTarget.id,
          n: changed.length,
        }) +
        (scope && scope.hunks > 0
          ? ' (' + translate(scope.source === SCOPE_SOURCE.CHANGES ? '에이전트가 기록한 줄' : '핀 자리로 추정') + ')'
          : '')
      : meets.length
        ? translate('핀 자리의 블록은 이 커밋에서 바뀌지 않았습니다 — 그 블록을 보라 테두리로 표시했습니다')
        : translate('새 판에서 핀 자리를 찾지 못했습니다 — 정확한 줄은 [소스 diff]')) +
    (part ? ' · ' + translate('그린 비교는 커밋 전체입니다 — 이 핀의 변경만은 [소스 diff]') : '');
  const first = shown[0];
  if (!first) return -1;
  const index = RENDERED_COMPARE.stops.findIndex((group) => group.includes(first.el));
  return index;
}
export {
  RENDERED_COMPARE,
  clearRenderedCompare,
  drawCompareNavigator,
  isDrawnFromMarkdown,
  restateCompareStatus,
  showRenderedCompare,
  stepChangeGroup,
};
