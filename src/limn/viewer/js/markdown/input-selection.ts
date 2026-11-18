/** Map browser selections and taps to source ranges and preserve the selected source text. */
import { $, findClosest } from '../platform/dom.ts';
import { linesAt, blockAt } from './view-levels.ts';
import { MARKDOWN_VIEW } from './state.ts';
import { pickLines } from './flow-pick.ts';
import { LAST_POINTER, showTip, TIP, hideTip } from '../platform/tooltip.ts';
import { lineElements } from './view-reading.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { COARSE_POINTER_QUERY } from '../app/state.ts';

// ---------------- Input on the document
// A mouse drag ends: the part of its text selection inside the document (documentPart) is the pick. A press without a
// selection (a click, a tap) picks the block under it - not on a link, a badge or another control.
function pickSelection(tapTarget: EventTarget | null) {
  const selection = window.getSelection(),
    column = $('#md');
  if (!column || !column.matches('article')) return false;
  if (selection && !selection.isCollapsed && selection.rangeCount) {
    const selected = selection.getRangeAt(0),
      range = documentPart(selected, column);
    if (!range) return false;
    let startLines = linesAt(range.startContainer),
      endLines = linesAt(range.endContainer);
    if (!startLines || !endLines) return false;
    // A selection that ends before any character of its last line (a triple click ends at the start of the next block)
    // does not take that line: nothing of it is selected. An end documentPart cut back to the document's last element
    // is no such end - the selection ran past that element, which may have no character of its own (a closing rule, an
    // empty code block).
    const cut = range !== selected && !column.contains(selected.endContainer);
    if (endLines.lo > startLines.hi && !cut && takesNothingOfEnd(range)) {
      const before = endLines.lo - 1;
      endLines = { lo: Math.max(startLines.lo, before), hi: Math.max(startLines.lo, before) };
    }
    let first = Math.min(startLines.lo, endLines.lo),
      last = Math.max(startLines.hi, endLines.hi);
    while (last > first && !String(MARKDOWN_VIEW.lines[last - 1] || '').trim()) last--;
    // A document that drew math reads its quote through rangeText, where each drawn formula gives back its source TeX;
    // one that drew none reads the selection's own text (ADR-0036 D4).
    pickLines(
      { lo: first, hi: last },
      blockAt(range.startContainer),
      blockAt(range.endContainer),
      range === selected && !MARKDOWN_VIEW.tex ? selection.toString() : rangeText(widenToFormulas(range)),
      false,
    );
    return true;
  }
  if (tapTarget instanceof Element) {
    const target = tapTarget;
    const inertLink = findClosest(target, '#md .md-rel', HTMLElement);
    if (inertLink && LAST_POINTER !== 'mouse') {
      showInertTip(inertLink);
      return true;
    } // a finger has no hover
    if (target.closest('a,button,[data-act],.md-badges,.md-limit')) return false;
    const carrier = findClosest(target, '#md [data-lo],#md [data-line]', HTMLElement);
    if (!carrier) return false;
    const head = MARKDOWN_VIEW.heads.find(
      (heading) => heading.el === target.closest('#md h1,#md h2,#md h3,#md h4,#md h5,#md h6'),
    );
    const lines = head
        ? { lo: head.lo, hi: head.lo }
        : linesAt(target) || { lo: +(carrier.dataset.lo || 0), hi: +(carrier.dataset.hi || 0) },
      block = blockAt(target);
    // the front matter's head line is the viewer's words, not the source's
    const said = block && block.dataset.kind === 'front' ? block.querySelector('pre') : null;
    pickLines(lines, block, block, elementText(said || block || carrier), true);
    return true;
  }
  return false;
}
// The part of a selection's range inside the document column: the range itself when it lies inside; else the range cut
// back to the document's first and last line elements where it runs past them - a triple click on the last paragraph
// ends after the article, there being no next block inside it to end at, and a drag may start above it. One end must be
// in the document: a selection with both ends outside it (select-all, one made in the side panel) is no pick - null, as
// for one that does not reach it or one that, cut back, takes nothing of it (from above the document to its very
// start).
function documentPart(range: Range, column: HTMLElement) {
  if (column.contains(range.commonAncestorContainer)) return range;
  if (!column.contains(range.startContainer) && !column.contains(range.endContainer)) return null;
  const elements = lineElements();
  if (!elements.length) return null;
  // The start goes to the first element that carries lines and holds none of its own (a paragraph's first line span,
  // not the paragraph: that would read as all its lines); the last element in document order is always such a leaf.
  const first = elements.find((element) => !element.querySelector('[data-line],[data-lo]')) || elements[0];
  const part = range.cloneRange();
  if (!column.contains(range.startContainer)) part.setStart(first, 0);
  if (!column.contains(range.endContainer)) {
    const last = elements[elements.length - 1];
    part.setEnd(last, last.childNodes.length);
  }
  return part.collapsed ? null : part;
}
// The text a range shows, as the selection's own toString gives it: its contents laid out once off screen, under the
// document's own .md rules (an HTML placeholder's label and code stack as on screen), and read as innerText. A range's
// toString runs blocks together ('First.Last.'), the renderer putting no whitespace between them; the selection itself
// is not touched, as changing it would set off the touch screen's resting-selection pick again. The pin badges standing
// between blocks (drawPinMarks) are the viewer's, not the document's text: they are left out. A marked character's box
// (hiddenBox) gives its character, where it stands. innerText does not: Chromium reads the box's hidden child, out of
// the line's flow, as a block of its own ('x\n\u202e\ny'), and Firefox drops a bidirectional control from innerText
// altogether. So each box stands in the copy as U+FFF0 - a character of the repertoire, which the document's own text
// therefore never holds raw - and gets its character back after. A drawn formula (data-tex, ADR-0036 D4) goes the same
// way, as U+FFF1, and gets its source TeX back: innerText would read the glyphs KaTeX drew (and the MathML copy beside
// them), and an agent looks for the TeX the manuscript holds. A formula stands in a block or an inline slot as it did
// on screen, so the blocks around it still read apart.
function rangeText(range: Range) {
  const box = document.createElement('div'),
    copy = document.createElement('div');
  box.className = 'sr-only';
  box.setAttribute('aria-hidden', 'true');
  copy.className = 'md';
  copy.append(range.cloneContents());
  copy.querySelectorAll('.md-badges').forEach((element) => element.remove());
  const tex: string[] = [];
  copy.querySelectorAll('[data-tex]').forEach((element) => {
    tex.push(element.getAttribute('data-tex') || '');
    const slot = document.createElement(element.classList.contains('md-math-block') ? 'div' : 'span');
    slot.textContent = '\ufff1';
    element.replaceWith(slot);
  });
  const kept: string[] = [];
  copy.querySelectorAll('.cc').forEach((element) => {
    kept.push(element.textContent || '');
    element.replaceWith('\ufff0');
  });
  box.append(copy);
  document.body.append(box);
  try {
    let boxAt = 0,
      texAt = 0;
    return copy.innerText.replace(/[\ufff0\ufff1]/g, (found) =>
      found === '\ufff0' ? kept[boxAt++] || '' : tex[texAt++] || '',
    );
  } finally {
    box.remove();
  }
}
// The range with either end inside a drawn formula moved out to that formula's edge - a clone, the selection itself is
// never touched - so a selection that cuts into drawn math reads that formula whole, by its source TeX. The range
// itself when neither end is in one.
function widenToFormulas(range: Range): Range {
  const formulaAt = (node: Node | null) => {
    const element = node && (node instanceof Element ? node : node.parentElement);
    return element ? element.closest('#md [data-tex]') : null;
  };
  const startFormula = formulaAt(range.startContainer),
    endFormula = formulaAt(range.endContainer);
  if (!startFormula && !endFormula) return range;
  const widened = range.cloneRange();
  if (startFormula) widened.setStartBefore(startFormula);
  if (endFormula) widened.setEndAfter(endFormula);
  return widened;
}
// The text an element shows, as rangeText reads a range: a tap's quote. A drawn formula tapped whole is its source TeX
// - selectNodeContents would leave the element itself, which carries data-tex, outside the range.
function elementText(element: Element) {
  const tex = element instanceof HTMLElement ? element.dataset.tex : undefined;
  if (tex !== undefined) return tex;
  const range = document.createRange();
  range.selectNodeContents(element);
  return rangeText(range);
}
// Shows a link's description that does not open (a tap on it), until 4s pass or the next press.
function showInertTip(element: HTMLElement) {
  showTip(element);
  const shown = TIP.textContent;
  setTimeout(() => {
    if (!TIP.hidden && TIP.textContent === shown) hideTip();
  }, 4000);
}
// Whether the range takes no visible character of the line (or block) its end is in.
function takesNothingOfEnd(range: Range) {
  const element = range.endContainer instanceof Element ? range.endContainer : range.endContainer.parentElement;
  if (!element) return false;
  const host = element.closest('[data-line]') || element.closest('[data-lo]');
  if (!host) return false;
  const head = document.createRange();
  head.setStart(host, 0);
  head.setEnd(range.endContainer, range.endOffset);
  return !head.toString().trim();
}
/** Register the mouse and touch handlers that turn picks in the document into source ranges. */
function listenToMarkdownSelection() {
  // A release's pick waits one task, for the selection its press made, and it is that press's alone: once the next press
  // is down (a double or triple click's next press, which a busy page takes ahead of the timer) it does nothing - that
  // press picks at its own release. Run then, it would take the new press's selection, the note field's focus would take
  // that selection away, and the click that follows would count as a tap and choose the block. pressCount counts the
  // document's primary presses.
  let pressCount = 0;
  $('#doc').addEventListener('mousedown', (event: MouseEvent) => {
    if (event.button === 0) pressCount++;
  });
  $('#doc').addEventListener('mouseup', (event: MouseEvent) => {
    if (!isMarkdownDoc() || event.button !== 0) return;
    const press = pressCount;
    setTimeout(() => {
      if (press === pressCount) pickSelection(null);
    }, 0);
  });
  $('#doc').addEventListener('click', (event: MouseEvent) => {
    if (!isMarkdownDoc()) return;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) return;
    pickSelection(event.target);
  });
  // A finger: the long-press handles make a selection with no mouseup; it is picked once it rests.
  let selectionTimer = 0;
  document.addEventListener('selectionchange', () => {
    if (!isMarkdownDoc() || !COARSE_POINTER_QUERY.matches) return;
    clearTimeout(selectionTimer);
    selectionTimer = setTimeout(() => {
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) pickSelection(null);
    }, 500);
  });
}

export { listenToMarkdownSelection };
