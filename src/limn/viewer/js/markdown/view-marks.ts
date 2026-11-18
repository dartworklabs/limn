/** Highlight selected and pinned source lines and locate pins in the rendered column. */
import { pdoc, isMarkdownDoc, isRegion } from '../documents/state.ts';
import { REPICK, COMPOSE, DOC, PINS, REVIEW_ALL, SWITCHSEQ } from '../app/state.ts';
import { levelOf } from '../documents/rules.ts';
import { $$, $ } from '../platform/dom.ts';
import { setSpotSelectionVisible, MARKDOWN_VIEW } from './state.ts';
import { lineLeaves, isColumnShown, isChosenSeen, readSpot } from './view-reading.ts';
import { pinState, lineRange } from '../app/rules-pins.ts';
import { PIN_STATE } from '../app/rules-tables.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';

let PENDING_PIN_JUMP: { id: number; doc: string | null; seq: number } | null = null;
// What the document marks as chosen: a re-place's candidate while there is one - the lines of the rung its banner names
// (bannerCompare), as the PDF surface draws its box - else the composer's selection (null: nothing).
function shownChoice(): { file?: string; lo?: number | null; hi?: number | null; kind?: string } | null {
  const candidate = REPICK && REPICK.cand;
  if (!candidate) return COMPOSE.current;
  const level = levelOf(candidate, candidate.default_level) || candidate;
  return { file: candidate.file, lo: level.lo, hi: level.hi, kind: candidate.kind };
}
// The chosen lines drawn on the document: their line spans and blocks get .md-sel (null clears), and the reading spot
// learns whether they are on screen (keepReadingSpot brings them back after a reflow only then).
function markChosenLines(
  chosen: { file?: string; lo?: number | null; hi?: number | null; kind?: string; pdf?: string } | null,
) {
  $$('#md .md-sel').forEach((element) => element.classList.remove('md-sel'));
  const low = chosen && chosen.lo,
    high = chosen && chosen.hi;
  if (chosen && isMarkdownDoc() && chosen.file === MARKDOWN_VIEW.file && !isRegion(chosen) && low && high)
    lineLeaves(low, high).forEach((element) => element.classList.add('md-sel'));
  if (MARKDOWN_VIEW.spot && MARKDOWN_VIEW.spot.doc === DOC && isColumnShown()) setSpotSelectionVisible(isChosenSeen());
} // hidden, nothing is on screen: what was stays
// ---------------- Pins on the document
// The marks of the pins on screen (marks()' branch): each pin's lines get .md-pin (review .rv, lost .st), and the first
// of them a number badge in the left gutter that jumps to the card (data-act mark-jump, as on a PDF page). The badges
// are drawn in line order, each layer just before the block of #md its line is in: Tab and a screen reader meet a badge
// where its line is - appended at the column's end they would come after the last link, in pin order (#1 L3, #2 L55, #4
// L9). The badge's name and description (its tip: '#1 · L3-L5 · <note>') are what marks the pinned lines for them,
// colour aside.
function drawPinMarks() {
  const column = $('#md');
  if (!column) return;
  column.querySelectorAll('.md-badges').forEach((element: Element) => element.remove());
  column.querySelectorAll('.md-pin').forEach((element: Element) => element.classList.remove('md-pin', 'rv', 'st'));
  const pins = PINS.concat(REVIEW_ALL.filter((pin) => pdoc(pin) === DOC))
    .filter(
      (pin): pin is Pin & { lo: number; hi: number } =>
        !isRegion(pin) && typeof pin.lo === 'number' && typeof pin.hi === 'number',
    )
    .sort((left, right) => left.lo - right.lo || left.id - right.id);
  const rows: Map<number, HTMLElement> = new Map(),
    top = column.getBoundingClientRect().top;
  for (const pin of pins) {
    const leaves = lineLeaves(pin.lo, pin.hi);
    if (!leaves.length) continue;
    const inReview = pinState(pin) === PIN_STATE.REVIEW,
      lost = !!pin.stale;
    leaves.forEach((element) => {
      element.classList.add('md-pin');
      if (inReview) element.classList.add('rv');
      if (lost) element.classList.add('st');
    });
    // The badge stands in the column's left gutter at the height of the pin's first line (a layer of #md, never inside
    // a paragraph, list or table, so it moves no text). Pins whose first lines share a height stack down.
    const y = Math.round(leaves[0].getBoundingClientRect().top - top);
    let box = rows.get(y);
    if (!box) {
      box = document.createElement('span');
      box.className = 'md-badges';
      box.setAttribute('translate', 'no');
      box.style.top = y + 'px';
      const at = topBlockOf(column, leaves[0]);
      ((at && at.parentElement) || column).insertBefore(box, at);
      rows.set(y, box);
    }
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = 'md-badge' + (inReview ? ' rv' : '') + (lost ? ' st' : '');
    badge.dataset.act = 'mark-jump';
    badge.dataset.id = String(pin.id);
    badge.dataset.pin = String(pin.id);
    badge.textContent = String(pin.id);
    badge.setAttribute('aria-label', translateTemplate('핀 #{id} 카드로 이동', { id: pin.id }));
    const note = String(pin.note || '')
      .replace(/\s+/g, ' ')
      .trim();
    badge.dataset.tip =
      '#' +
      pin.id +
      ' · ' +
      lineRange(pin.lo, pin.hi) +
      ' · ' +
      (note ? (note.length > 60 ? note.slice(0, 60) + '…' : note) : translate('(메모 없음)'));
    box.appendChild(badge);
  }
}
// The child of column (#md) that holds element (null: element is not inside it) - where a badge layer goes in the
// document's order, a child of #md still, so it stands in the gutter and no block's text (a quote, a tap's block) takes
// its number. A text document's lines are all one block (.tx-src, text/view.ts), so there the layer goes before
// element's line span itself, a
// sibling of the lines and in no line's text: before the whole text, every badge would be read before the first line.
function topBlockOf(column: HTMLElement, element: Element): Element | null {
  let child: Element | null = element;
  const isText = column.classList.contains('tx');
  while (
    child &&
    child.parentElement !== column &&
    !(isText && child.parentElement && child.parentElement.classList.contains('tx-src'))
  )
    child = child.parentElement;
  return child;
}
// Scrolls pin id's first line to the reading depth and flashes its lines (jumpPin's branch, showLines). A jump asked
// before this document is on screen - [보기] on a pin of another document: switchDoc settles before the source is read
// and drawn - waits for the draw (showDocumentNode) of this visit; another switch drops it.
function jumpToPinLines(id: number) {
  if (MARKDOWN_VIEW.shown !== DOC || !$('#md')) {
    PENDING_PIN_JUMP = { id, doc: DOC, seq: SWITCHSEQ };
    return;
  }
  const pin = PINS.find((candidate) => candidate.id === id) || REVIEW_ALL.find((candidate) => candidate.id === id);
  if (!pin || typeof pin.lo !== 'number' || typeof pin.hi !== 'number') return;
  const leaves = lineLeaves(pin.lo, pin.hi);
  if (leaves.length) showLines(leaves);
}
// Scrolls the first of the line elements to the reading depth (30% down the document area) and flashes them - a pin's
// [보기] (jumpToPinLines) and [바뀐 곳] (goToNextChange, documents/flow-updates.ts) - and reads the reading spot where
// that put the pane: the page's own jump is over at once, so its place is the spot before the scroll's frame reads it
// (as a heading jump's once it lands, endLandedJump). A width that changes before that frame puts back the jump's place
// (keepReadingSpot), not the one read before it.
function showLines(elements: HTMLElement[]) {
  const pane = $('#left'),
    paneRect = pane.getBoundingClientRect(),
    rect = elements[0].getBoundingClientRect();
  endJumpForScroll();
  pane.scrollTop += rect.top - (paneRect.top + paneRect.height * 0.3);
  readSpot(true);
  elements.forEach((element) => {
    element.classList.remove('md-flash');
    void element.offsetWidth;
    element.classList.add('md-flash');
  });
  setTimeout(() => elements.forEach((element) => element.classList.remove('md-flash')), 1200);
}

/** Consume the requested pin jump when this draw belongs to the visit that requested it. */
function finishPendingPinJump() {
  const jump = PENDING_PIN_JUMP;
  PENDING_PIN_JUMP = null;
  // a jump asked before the draw (jumpToPinLines)
  if (jump && jump.doc === DOC && jump.seq === SWITCHSEQ) jumpToPinLines(jump.id);
}

export { markChosenLines, shownChoice, jumpToPinLines, drawPinMarks, showLines, finishPendingPinJump };
